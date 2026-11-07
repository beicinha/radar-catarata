# AGENTS.md – Radar Catarata

Radar de licitações de catarata/oftalmologia. Responda em português, de forma simples: o dono não é programador.
O contexto do negócio (regras, contatos e andamento) está em `../AGENTS.md`, na pasta "Licitações Catarata" do Mac. **Este repositório é público: não coloque dados pessoais, senhas ou chaves aqui.**

## Como funciona
- `coletor.py`: coleta o PNCP (editais abertos), o Querido Diário (diários oficiais) e os sites de OSS/AMEs (`fontes_oss.json`). Gera `dados.json` e `radar.html` (a partir de `painel_template.html`). Usa `analise_editais.py` (lê os PDFs dos editais) e `estrutura_municipal.py` (CNES do município).
  - Caches: `cache_pncp.json`, `cache_analise.json`, `cache_estrutura.json`, `vistos_oss.json`.
  - O campo `primeira_vez` de cada item marca quando ele apareceu pela primeira vez.
- `avisar.py`: seleciona os itens relevantes (catarata ou cirurgia oftalmológica, sem compras nem prazo vencido) que não estão em `avisados.json` e manda e-mail (Gmail SMTP) e WhatsApp (CallMeBot).
  - `python3 avisar.py --teste` só mostra o que enviaria.
- `.github/workflows/radar.yml`: roda às 7h e às 17h (Brasília); coleta, avisa, faz commit dos caches e publica no GitHub Pages.
- `.github/workflows/painel.yml`: só republica o `radar.html`.
- Painel: https://beicinha.github.io/radar-catarata/
- Secrets usados (configurados no GitHub, nunca no código): `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY`, opcional `EMAIL_TO`.

## Cuidados
- Dependências: só Python 3, `curl` e `pypdf`.
- Antes de mexer nos filtros de relevância, teste com `python3 avisar.py --teste`.
- Rodar manualmente: aba Actions → "Radar Catarata" → "Run workflow" (ou `gh workflow run radar.yml -R beicinha/radar-catarata`).
