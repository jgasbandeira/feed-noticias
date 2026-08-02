# Feed de notícias (Economia, Política, FIIs, Mercado Financeiro, Asset, XP)

Lê os RSS de O Globo, G1/Globo.com, Valor Econômico, Brazil Journal e Metro
Quadrado a cada 30 minutos, filtra por tema, gera um resumo com IA (Claude
Haiku) para cada matéria nova e publica uma página estática ordenada
cronologicamente via GitHub Pages.

## Passo a passo para colocar no ar

### 1. Criar o repositório no GitHub
1. Crie um repositório novo (pode ser público — o conteúdo é só um feed de
   notícias, sem dado sensível). Ex: `meu-feed-noticias`.
2. Suba esta pasta (`news-feed/`) inteira para o repositório. Pode ser pelo
   site do GitHub (arrastar os arquivos) ou por linha de comando:
   ```
   git init
   git add .
   git commit -m "primeira versão"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/meu-feed-noticias.git
   git push -u origin main
   ```

### 2. Criar a chave de API da Anthropic
1. Acesse **platform.claude.com** e faça login (é uma conta separada do
   claude.ai, específica para uso via API).
2. Vá em **API Keys** (ou "Chaves de API") e crie uma nova chave.
3. Em **Billing/Faturamento**, adicione um cartão e coloque um crédito inicial
   pequeno (ex: US$ 5 já cobre bastante tempo de uso, dado o volume estimado
   de poucos dólares por mês).
4. Copie a chave gerada (começa com `sk-ant-...`) — ela só aparece uma vez.

### 3. Guardar a chave como "secret" no GitHub
1. No repositório, vá em **Settings → Secrets and variables → Actions**.
2. Clique em **New repository secret**.
3. Nome: `ANTHROPIC_API_KEY`. Valor: cole a chave copiada no passo anterior.

### 4. Ativar o GitHub Pages
1. No repositório, vá em **Settings → Pages**.
2. Em **Source**, escolha **Deploy from a branch**.
3. Branch: `main`, pasta: `/docs`.
4. Salve. O GitHub vai te dar uma URL tipo
   `https://SEU_USUARIO.github.io/meu-feed-noticias/`.

### 5. Rodar pela primeira vez
1. Vá na aba **Actions** do repositório.
2. Escolha o workflow **"Atualizar feed de notícias"**.
3. Clique em **Run workflow** para rodar manualmente (não precisa esperar os
   30 minutos na primeira vez).
4. Depois de terminar, olhe o log de cada passo — principalmente o passo
   "Rodar agregador". Ele avisa no log quando algum feed falhou ou voltou
   vazio, algo como:
   ```
   FEED SEM ITENS [O Globo - Economia] (...): Verifique a URL em config.py.
   ```
5. A partir daí, o workflow roda sozinho a cada 30 minutos.

## Sobre as URLs de RSS

Não consegui testar diretamente o acesso a g1.globo.com, oglobo.globo.com e
valor.globo.com (minhas ferramentas têm esses domínios bloqueados), então as
URLs em `config.py` para essas três fontes são meu melhor palpite e **muito
provavelmente vão precisar de ajuste** na primeira execução. O Brazil Journal
eu testei e confirmei que funciona.

Para achar a URL certa de um site:
1. Abra o site e veja o código-fonte da página (Ctrl+U / Cmd+Option+U).
2. Procure por `type="application/rss+xml"` — o `href` ao lado é a URL do
   feed.
3. Se não achar nada, o site pode não ter um RSS público facilmente
   descobrível; nesse caso me avise que ajustamos a estratégia para essa
   fonte específica (ex: usando busca ao invés de RSS).

Assim que confirmar as URLs certas, é só editar `config.py`, commitar e
empurrar (`git push`) — o próximo run já usa a versão corrigida.

## Ajustando o filtro de temas

As palavras-chave de cada tema estão em `config.py`, no dicionário `KEYWORDS`.
Pode adicionar, remover ou reorganizar livremente — não precisa saber
programar, é só editar a lista de palavras entre aspas.

## Ajustando quantidade de histórico

Em `config.py`:
- `DIAS_RETENCAO`: quantos dias de notícias manter na página (padrão: 21).
- `MAX_ITENS_PAGINA`: número máximo de itens exibidos (padrão: 300).

## Rodando localmente (para testar antes de subir)

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python build_feed.py
```
Abra `docs/index.html` no navegador para ver o resultado.

## Custo estimado por mês
- **GitHub Actions + Pages**: gratuito com repositório público.
- **API da Anthropic (resumos)**: poucos dólares por mês no volume esperado
  (o modelo usado, Haiku, custa US$1/milhão de tokens de entrada e US$5/milhão
  de saída — cada resumo consome uma fração de centavo).
