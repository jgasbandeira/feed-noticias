# -*- coding: utf-8 -*-
"""
Configuração do agregador de notícias.

IMPORTANTE sobre as URLs de RSS abaixo:
Não consegui testar diretamente o acesso aos domínios da Globo (g1.globo.com,
oglobo.globo.com, valor.globo.com) porque a ferramenta que uso para isso tem
esses domínios bloqueados. As URLs marcadas como "verified": False são o meu
melhor palpite com base em pesquisa, mas PRECISAM ser conferidas na primeira
execução real (rodando em GitHub Actions, que não tem essa restrição).

Como conferir/corrigir uma URL de feed:
1. Abra o site da fonte no navegador.
2. Procure por um ícone de RSS, ou veja o código-fonte da página (Ctrl+U) e
   procure por uma tag como:
   <link rel="alternate" type="application/rss+xml" href="...">
3. Cole a URL encontrada aqui.
O script também registra no log (visível na aba Actions do GitHub) quando um
feed falha ou retorna zero itens, então dá para ir ajustando aos poucos.
"""

FEEDS = [
    {"source": "Brazil Journal", "url": "https://braziljournal.com/feed/", "verified": True},
    {"source": "Metro Quadrado", "url": "https://braziljournal.com/metroquadrado/feed/", "verified": False},
    {"source": "G1 - Economia", "url": "https://g1.globo.com/rss/g1/economia/", "verified": False},
    {"source": "G1 - Política", "url": "https://g1.globo.com/rss/g1/politica/", "verified": False},
    {"source": "O Globo - Economia", "url": "https://oglobo.globo.com/rss/plantaoeconomia.xml", "verified": False},
    {"source": "Valor Econômico", "url": "https://valor.globo.com/rss/", "verified": False},
]

# Palavras-chave por tema (comparadas sem acento e em minúsculas, com \b de
# fronteira de palavra). Adicione/ajuste livremente.
KEYWORDS = {
    "Economia": [
        "economia", "economico", "pib", "inflacao", "ipca", "igpm", "juros",
        "selic", "banco central", "bacen", "copom", "fiscal", "deficit",
        "superavit", "dolar", "cambio", "arcabouco fiscal", "reforma tributaria",
    ],
    "Politica": [
        "politica", "governo federal", "congresso nacional", "camara dos deputados",
        "senado federal", "eleicao", "eleicoes", "ministerio", "ministro",
        "supremo tribunal federal", "\\bstf\\b", "planalto", "presidente da republica",
        "reforma administrativa",
    ],
    "Fundos Imobiliarios": [
        "fundo imobiliario", "fundos imobiliarios", "\\bfii\\b", "\\bfiis\\b", "\\bifix\\b",
    ],
    "Mercado Financeiro": [
        "mercado financeiro", "bolsa de valores", "ibovespa", "\\bb3\\b",
        "acoes", "renda fixa", "renda variavel", "investidor", "investidores",
        "\\bcvm\\b", "tesouro direto", "debentures",
    ],
    "Asset": [
        "asset management", "gestora de recursos", "gestora de fundos",
        "\\basset\\b",
    ],
    "XP": [
        "xp investimentos", "xp asset", "\\bxp inc\\b",
    ],
}

# Modelo usado para gerar os resumos (rápido e barato).
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Quantos dias de histórico manter na página (itens mais antigos são descartados).
DIAS_RETENCAO = 21

# Máximo de itens mostrados na página final.
MAX_ITENS_PAGINA = 300
