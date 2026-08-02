# -*- coding: utf-8 -*-
"""
Agregador de notícias: lê os feeds RSS configurados em config.py, filtra por
tema, gera um resumo com IA (+nota de relevância) para cada matéria nova e
publica uma página HTML estática com duas visões (Geral / Curadoria) e
filtros por tema, veículo e período.

Pensado para rodar a cada 30 minutos via GitHub Actions (ver
.github/workflows/update-feed.yml), mas roda igual em qualquer máquina com
Python 3.10+ e a variável de ambiente ANTHROPIC_API_KEY definida.

Uso local:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
    python build_feed.py
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser

from config import (
    ANTHROPIC_MODEL,
    DIAS_RETENCAO,
    FEEDS,
    KEYWORDS,
    MAX_ITENS_PAGINA,
)

BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "data" / "items.json"
OUTPUT_HTML_PATH = BASE_DIR / "docs" / "index.html"

# O GitHub Actions roda em UTC. Sem isso, os horários mostrados na página
# ficam ~3h à frente do horário de Brasília.
FUSO_BR = ZoneInfo("America/Sao_Paulo")

# Rótulos "bonitos" (com acento) para exibição. As chaves precisam bater
# exatamente com as chaves de KEYWORDS em config.py.
ROTULO_TEMA = {
    "Economia": "Economia",
    "Politica": "Política",
    "Fundos Imobiliarios": "Fundos Imobiliários",
    "Mercado Financeiro": "Mercado Financeiro",
    "Asset": "Asset",
    "XP": "XP",
}


def normalizar(texto: str) -> str:
    """minúsculas e sem acento, para comparação de palavras-chave."""
    texto = texto or ""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Pré-compila um regex por tema (união das palavras-chave já sem acento).
_KEYWORD_PATTERNS = {
    tema: re.compile(
        "|".join(
            kw if kw.startswith("\\b") else r"\b" + re.escape(kw) + r"\b"
            for kw in palavras
        )
    )
    for tema, palavras in KEYWORDS.items()
}


def temas_correspondentes(titulo: str, descricao: str) -> list[str]:
    texto = normalizar(f"{titulo} {descricao}")
    encontrados = []
    for tema, padrao in _KEYWORD_PATTERNS.items():
        if padrao.search(texto):
            encontrados.append(tema)
    return encontrados


def carregar_itens_existentes() -> list[dict]:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("AVISO: data/items.json corrompido, recomeçando do zero.")
    return []


def salvar_itens(itens: list[dict]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def buscar_novas_materias(links_ja_vistos: set[str]) -> list[dict]:
    novas = []
    for feed_cfg in FEEDS:
        fonte = feed_cfg["source"]
        url = feed_cfg["url"]
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:  # feedparser raramente levanta, mas por via das dúvidas
            print(f"FEED FALHOU [{fonte}] ({url}): {exc}")
            continue

        if parsed.bozo and not parsed.entries:
            print(
                f"FEED COM ERRO [{fonte}] ({url}): {parsed.bozo_exception}. "
                "Verifique a URL em config.py."
            )
            continue

        if not parsed.entries:
            print(f"FEED SEM ITENS [{fonte}] ({url}). Verifique a URL em config.py.")
            continue

        for entry in parsed.entries:
            link = entry.get("link")
            if not link or link in links_ja_vistos:
                continue

            titulo = entry.get("title", "").strip()
            descricao = entry.get("summary", "") or entry.get("description", "")
            descricao_texto = re.sub("<[^<]+?>", "", descricao).strip()

            temas = temas_correspondentes(titulo, descricao_texto)
            if not temas:
                continue

            publicado = entry.get("published_parsed") or entry.get("updated_parsed")
            if publicado:
                dt = datetime(*publicado[:6], tzinfo=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

            novas.append(
                {
                    "source": fonte,
                    "title": titulo,
                    "link": link,
                    "description": descricao_texto,
                    "published": dt.isoformat(),
                    "themes": temas,
                }
            )
            links_ja_vistos.add(link)

    return novas


def _extrair_relevancia(texto: str, padrao: str) -> int | None:
    m = re.search(padrao, texto, re.IGNORECASE)
    if not m:
        return None
    try:
        nota = int(m.group(1))
    except (ValueError, IndexError):
        return None
    return max(1, min(10, nota))


def gerar_resumo_e_relevancia(cliente, item: dict) -> tuple[str, int]:
    """Gera o resumo da matéria e uma nota de relevância (1-10) numa única
    chamada à API, para não dobrar o custo."""
    prompt = (
        "Você ajuda a curar um feed pessoal de notícias sobre economia, "
        "política e mercado financeiro brasileiro.\n\n"
        "1) Resuma a matéria abaixo em português, em no máximo 2 frases "
        "curtas e diretas, focando no fato principal (sem opinião, sem "
        "'este artigo fala sobre'). Use só as informações fornecidas.\n"
        "2) Dê uma nota de RELEVÂNCIA de 1 a 10 para essa matéria, pensando "
        "no quanto ela pode importar para alguém que acompanha economia, "
        "política e investimentos no Brasil: 9-10 = fato de grande "
        "repercussão ou que pode mover mercado (ex: decisão do Copom, "
        "mudança relevante de política econômica, evento com impacto "
        "amplo); 5-6 = notícia relevante mas de impacto mais limitado ou "
        "regional; 1-3 = nota/release de rotina, pauta de nicho ou baixo "
        "impacto.\n\n"
        f"Fonte: {item['source']}\n"
        f"Título: {item['title']}\n"
        f"Descrição/trecho: {item['description'][:1500]}\n\n"
        "Responda EXATAMENTE neste formato, sem nada antes ou depois:\n"
        "RESUMO: <resumo aqui>\n"
        "RELEVANCIA: <número de 1 a 10>"
    )
    try:
        resposta = cliente.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = resposta.content[0].text.strip()
        m = re.search(
            r"RESUMO:\s*(.*?)\s*RELEVANCIA:\s*(\d+)", texto, re.DOTALL | re.IGNORECASE
        )
        if m:
            resumo = m.group(1).strip()
            nota = max(1, min(10, int(m.group(2))))
            return resumo, nota
        # Formato inesperado: usa o texto todo como resumo e nota neutra.
        return texto, 5
    except Exception as exc:
        print(f"AVISO: falha ao gerar resumo para '{item['title']}': {exc}")
        # fallback: usa a descrição crua (ou o título) se a API falhar
        return item["description"][:280] or item["title"], 5


def gerar_relevancia_backfill(cliente, item: dict) -> int:
    """Para itens antigos que já têm resumo mas não têm nota de relevância
    (gerados antes desse recurso existir). Chamada mais barata, só pede a
    nota, sem reescrever o resumo já salvo."""
    prompt = (
        "Dê uma nota de RELEVÂNCIA de 1 a 10 para a matéria abaixo, pensando "
        "no quanto ela importa para alguém que acompanha economia, política "
        "e investimentos no Brasil: 9-10 = fato de grande repercussão ou que "
        "pode mover mercado; 5-6 = relevante mas de impacto mais limitado; "
        "1-3 = rotina ou baixo impacto.\n\n"
        f"Fonte: {item['source']}\n"
        f"Título: {item['title']}\n"
        f"Resumo: {item.get('summary', '')[:500]}\n\n"
        "Responda só com o número, nada mais."
    )
    try:
        resposta = cliente.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = resposta.content[0].text.strip()
        nota = _extrair_relevancia(texto, r"(\d+)")
        return nota if nota is not None else 5
    except Exception as exc:
        print(f"AVISO: falha ao gerar relevância para '{item['title']}': {exc}")
        return 5


PAGINA_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Feed de Notícias</title>
<style>
  :root {
    --bg: #0f1115; --card: #171a21; --text: #e8e8e8; --muted: #9aa0a6;
    --accent: #4da3ff; --tag-bg: #22262f; --chip-off: #1b1e26;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  }
  .header { max-width: 720px; margin: 0 auto 16px; }
  .header h1 { margin: 0 0 4px; font-size: 1.5rem; }
  .header .sub { color: var(--muted); font-size: 0.85rem; }

  .controles { max-width: 720px; margin: 0 auto 20px; display: flex; flex-direction: column; gap: 12px; }
  .tabs { display: flex; gap: 8px; }
  .tab-btn {
    background: none; border: none; color: var(--muted); font-size: 0.95rem;
    font-weight: 600; padding: 8px 4px; cursor: pointer; border-bottom: 2px solid transparent;
  }
  .tab-btn.active { color: var(--text); border-bottom-color: var(--accent); }

  .filtros { display: flex; flex-direction: column; gap: 8px; }
  select#filtro-periodo {
    background: var(--chip-off); color: var(--text); border: 1px solid #23262e;
    border-radius: 8px; padding: 6px 10px; font-size: 0.82rem; align-self: flex-start;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    background: var(--chip-off); color: var(--muted); border: 1px solid #23262e;
    border-radius: 999px; padding: 4px 12px; font-size: 0.78rem; cursor: pointer;
  }
  .chip.active { background: var(--accent); color: #061421; border-color: var(--accent); font-weight: 600; }

  .feed { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  .card {
    background: var(--card); border-radius: 10px; padding: 16px 18px;
    border: 1px solid #23262e;
  }
  .meta { display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--muted); margin-bottom: 6px; }
  .fonte { font-weight: 600; color: var(--accent); }
  h2 { margin: 0 0 8px; font-size: 1.05rem; line-height: 1.35; }
  h2 a { color: var(--text); text-decoration: none; }
  h2 a:hover { text-decoration: underline; }
  .resumo { margin: 0 0 10px; color: #d3d3d3; font-size: 0.92rem; line-height: 1.5; }
  .tags { display: flex; gap: 6px; flex-wrap: wrap; }
  .tag {
    background: var(--tag-bg); color: var(--muted); font-size: 0.72rem;
    padding: 3px 8px; border-radius: 999px;
  }
  .sem-resultado { text-align: center; color: var(--muted); padding: 24px 0; display: none; }
</style>
</head>
<body>
  <div class="header">
    <h1>Feed de Notícias</h1>
    <div class="sub">Atualizado em __ATUALIZADO_EM__ · Economia, Política, Fundos Imobiliários, Mercado Financeiro, Asset, XP</div>
  </div>

  <div class="controles">
    <div class="tabs">
      <button type="button" class="tab-btn active" data-tab="geral">Geral</button>
      <button type="button" class="tab-btn" data-tab="curadoria">Curadoria</button>
    </div>
    <div class="filtros">
      <select id="filtro-periodo">
        <option value="todos">Todos os períodos</option>
        <option value="24h">Últimas 24h</option>
        <option value="3d">Últimos 3 dias</option>
        <option value="7d">Últimos 7 dias</option>
        <option value="30d">Últimos 30 dias</option>
      </select>
      <div class="chips" id="chips-tema">
        __CHIPS_TEMA__
      </div>
      <div class="chips" id="chips-fonte">
        __CHIPS_FONTE__
      </div>
    </div>
  </div>

  <div class="feed" id="feed">
    __CARDS__
  </div>
  <p class="sem-resultado" id="sem-resultado">Nenhuma matéria encontrada com esses filtros.</p>

<script>
(function () {
  var feed = document.getElementById('feed');
  var semResultado = document.getElementById('sem-resultado');
  var tabButtons = document.querySelectorAll('.tab-btn');
  var chipTemas = document.querySelectorAll('#chips-tema .chip');
  var chipFontes = document.querySelectorAll('#chips-fonte .chip');
  var selectPeriodo = document.getElementById('filtro-periodo');
  var abaAtual = 'geral';

  var PERIODO_MS = {
    '24h': 24 * 60 * 60 * 1000,
    '3d': 3 * 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000
  };

  function chipsAtivos(lista) {
    var valores = [];
    lista.forEach(function (chip) {
      if (chip.classList.contains('active')) valores.push(chip.dataset.value);
    });
    return valores;
  }

  function reordenar() {
    var cards = Array.prototype.slice.call(feed.querySelectorAll('.card'));
    cards.sort(function (a, b) {
      if (abaAtual === 'curadoria') {
        var relA = parseInt(a.dataset.relevancia, 10) || 0;
        var relB = parseInt(b.dataset.relevancia, 10) || 0;
        if (relB !== relA) return relB - relA;
      }
      var dataA = new Date(a.dataset.data).getTime();
      var dataB = new Date(b.dataset.data).getTime();
      return dataB - dataA;
    });
    cards.forEach(function (card) { feed.appendChild(card); });
  }

  function aplicarFiltros() {
    var temasSel = chipsAtivos(chipTemas);
    var fontesSel = chipsAtivos(chipFontes);
    var periodo = selectPeriodo.value;
    var agora = Date.now();
    var algumVisivel = false;

    feed.querySelectorAll('.card').forEach(function (card) {
      var temasCard = (card.dataset.temas || '').split(',');
      var fonteCard = card.dataset.fonte;
      var dataCard = new Date(card.dataset.data).getTime();

      var passaTema = temasSel.length === 0 || temasCard.some(function (t) {
        return temasSel.indexOf(t) !== -1;
      });
      var passaFonte = fontesSel.length === 0 || fontesSel.indexOf(fonteCard) !== -1;
      var passaPeriodo = periodo === 'todos' || (agora - dataCard) <= PERIODO_MS[periodo];

      var mostrar = passaTema && passaFonte && passaPeriodo;
      card.style.display = mostrar ? '' : 'none';
      if (mostrar) algumVisivel = true;
    });

    semResultado.style.display = algumVisivel ? 'none' : 'block';
  }

  tabButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      tabButtons.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      abaAtual = btn.dataset.tab;
      reordenar();
      aplicarFiltros();
    });
  });

  chipTemas.forEach(function (chip) {
    chip.addEventListener('click', function () {
      chip.classList.toggle('active');
      aplicarFiltros();
    });
  });
  chipFontes.forEach(function (chip) {
    chip.addEventListener('click', function () {
      chip.classList.toggle('active');
      aplicarFiltros();
    });
  });
  selectPeriodo.addEventListener('change', aplicarFiltros);

  reordenar();
  aplicarFiltros();
})();
</script>
</body>
</html>
"""


def gerar_html(itens: list[dict]) -> str:
    linhas = []
    for item in itens:
        dt = datetime.fromisoformat(item["published"])
        dt_local = dt.astimezone(FUSO_BR)
        data_fmt = dt_local.strftime("%d/%m/%Y %H:%M")
        temas_html = " ".join(
            f'<span class="tag">{html.escape(ROTULO_TEMA.get(t, t))}</span>'
            for t in item["themes"]
        )
        linhas.append(
            f"""
            <article class="card" data-fonte="{html.escape(item['source'])}"
                      data-temas="{html.escape(','.join(item['themes']))}"
                      data-data="{html.escape(item['published'])}"
                      data-relevancia="{item.get('relevance', 5)}">
              <div class="meta">
                <span class="fonte">{html.escape(item['source'])}</span>
                <span class="data">{data_fmt}</span>
              </div>
              <h2><a href="{html.escape(item['link'])}" target="_blank" rel="noopener">
                {html.escape(item['title'])}
              </a></h2>
              <p class="resumo">{html.escape(item['summary'])}</p>
              <div class="tags">{temas_html}</div>
            </article>
            """
        )

    atualizado_em = datetime.now(timezone.utc).astimezone(FUSO_BR).strftime("%d/%m/%Y %H:%M")

    temas_presentes = list(ROTULO_TEMA.keys())
    fontes_presentes = sorted({item["source"] for item in itens})

    chips_tema = " ".join(
        f'<button type="button" class="chip active" data-value="{html.escape(t)}">'
        f'{html.escape(ROTULO_TEMA.get(t, t))}</button>'
        for t in temas_presentes
    )
    chips_fonte = " ".join(
        f'<button type="button" class="chip active" data-value="{html.escape(f)}">'
        f'{html.escape(f)}</button>'
        for f in fontes_presentes
    )

    cards_html = (
        "".join(linhas)
        if linhas
        else '<p style="text-align:center;color:var(--muted)">Nenhuma matéria ainda.</p>'
    )

    return (
        PAGINA_TEMPLATE.replace("__ATUALIZADO_EM__", atualizado_em)
        .replace("__CHIPS_TEMA__", chips_tema)
        .replace("__CHIPS_FONTE__", chips_fonte)
        .replace("__CARDS__", cards_html)
    )


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERRO: variável de ambiente ANTHROPIC_API_KEY não definida.")
        sys.exit(1)

    import anthropic

    cliente = anthropic.Anthropic(api_key=api_key)

    itens_existentes = carregar_itens_existentes()
    links_ja_vistos = {item["link"] for item in itens_existentes}

    # Itens antigos (de antes desse recurso existir) não têm nota de
    # relevância. Preenche uma vez, sem regerar o resumo já salvo.
    sem_relevancia = [i for i in itens_existentes if "relevance" not in i]
    if sem_relevancia:
        print(
            f"Preenchendo relevância de {len(sem_relevancia)} item(ns) "
            "antigo(s) sem essa informação..."
        )
        for item in sem_relevancia:
            item["relevance"] = gerar_relevancia_backfill(cliente, item)

    novas_materias = buscar_novas_materias(links_ja_vistos)
    print(f"{len(novas_materias)} matéria(s) nova(s) encontradas após filtro de tema.")

    for item in novas_materias:
        resumo, nota = gerar_resumo_e_relevancia(cliente, item)
        item["summary"] = resumo
        item["relevance"] = nota

    todos_itens = itens_existentes + novas_materias

    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_RETENCAO)
    todos_itens = [
        i for i in todos_itens if datetime.fromisoformat(i["published"]) >= limite
    ]
    todos_itens.sort(key=lambda i: i["published"], reverse=True)
    todos_itens = todos_itens[:MAX_ITENS_PAGINA]

    salvar_itens(todos_itens)

    OUTPUT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML_PATH.write_text(gerar_html(todos_itens), encoding="utf-8")
    print(f"Página gerada em {OUTPUT_HTML_PATH} com {len(todos_itens)} itens.")


if __name__ == "__main__":
    main()
