# -*- coding: utf-8 -*-
"""
Agregador de notícias: lê os feeds RSS configurados em config.py, filtra por
tema, gera um resumo com IA para cada matéria nova e publica uma página HTML
estática ordenada cronologicamente.

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


def gerar_resumo(cliente, item: dict) -> str:
    prompt = (
        "Resuma a matéria abaixo em português, em no máximo 2 frases curtas e "
        "diretas, focando no fato principal (sem opinião, sem 'este artigo fala "
        "sobre'). Use só as informações fornecidas.\n\n"
        f"Fonte: {item['source']}\n"
        f"Título: {item['title']}\n"
        f"Descrição/trecho: {item['description'][:1500]}\n"
    )
    try:
        resposta = cliente.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return resposta.content[0].text.strip()
    except Exception as exc:
        print(f"AVISO: falha ao gerar resumo para '{item['title']}': {exc}")
        # fallback: usa a descrição crua (ou o título) se a API falhar
        return item["description"][:280] or item["title"]


def gerar_html(itens: list[dict]) -> str:
    linhas = []
    for item in itens:
        dt = datetime.fromisoformat(item["published"])
        dt_local = dt.astimezone(FUSO_BR)
        data_fmt = dt_local.strftime("%d/%m/%Y %H:%M")
        temas_html = " ".join(
            f'<span class="tag">{html.escape(t)}</span>' for t in item["themes"]
        )
        linhas.append(
            f"""
            <article class="card">
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

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Feed de Notícias</title>
<style>
  :root {{
    --bg: #0f1115; --card: #171a21; --text: #e8e8e8; --muted: #9aa0a6;
    --accent: #4da3ff; --tag-bg: #22262f;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  }}
  .header {{ max-width: 720px; margin: 0 auto 24px; }}
  .header h1 {{ margin: 0 0 4px; font-size: 1.5rem; }}
  .header .sub {{ color: var(--muted); font-size: 0.85rem; }}
  .feed {{ max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }}
  .card {{
    background: var(--card); border-radius: 10px; padding: 16px 18px;
    border: 1px solid #23262e;
  }}
  .meta {{ display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--muted); margin-bottom: 6px; }}
  .fonte {{ font-weight: 600; color: var(--accent); }}
  h2 {{ margin: 0 0 8px; font-size: 1.05rem; line-height: 1.35; }}
  h2 a {{ color: var(--text); text-decoration: none; }}
  h2 a:hover {{ text-decoration: underline; }}
  .resumo {{ margin: 0 0 10px; color: #d3d3d3; font-size: 0.92rem; line-height: 1.5; }}
  .tags {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .tag {{
    background: var(--tag-bg); color: var(--muted); font-size: 0.72rem;
    padding: 3px 8px; border-radius: 999px;
  }}
</style>
</head>
<body>
  <div class="header">
    <h1>Feed de Notícias</h1>
    <div class="sub">Atualizado em {atualizado_em} · Economia, Política, Fundos Imobiliários, Mercado Financeiro, Asset, XP</div>
  </div>
  <div class="feed">
    {''.join(linhas) if linhas else '<p style="text-align:center;color:var(--muted)">Nenhuma matéria ainda.</p>'}
  </div>
</body>
</html>
"""


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERRO: variável de ambiente ANTHROPIC_API_KEY não definida.")
        sys.exit(1)

    import anthropic

    cliente = anthropic.Anthropic(api_key=api_key)

    itens_existentes = carregar_itens_existentes()
    links_ja_vistos = {item["link"] for item in itens_existentes}

    novas_materias = buscar_novas_materias(links_ja_vistos)
    print(f"{len(novas_materias)} matéria(s) nova(s) encontradas após filtro de tema.")

    for item in novas_materias:
        item["summary"] = gerar_resumo(cliente, item)

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
