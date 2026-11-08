# AGENTS.md – Radar Catarata

Radar de licitações de catarata/oftalmologia. Responda em português, de forma simples: o dono não é programador.
O contexto do negócio (regras, contatos e andamento) está em `../AGENTS.md`, na pasta "Licitações Catarata" do Mac. **Este repositório é público: não coloque dados pessoais, senhas ou chaves aqui.**

## Como funciona
- `coletor.py`: coleta o PNCP (editais abertos), o Querido Diário (diários oficiais) e os sites de OSS/AMEs (`fontes_oss.json`). Gera `dados.json` e `radar.html` (a partir de `painel_template.html`). Usa `analise_editais.py` (lê os PDFs dos editais) e `estrutura_municipal.py` (CNES do município).
  - Caches: `cache_pncp.json`, `cache_analise.json`, `cache_estrutura.json`, `vistos_oss.json`.
  - O campo `primeira_vez` de cada item marca quando ele apareceu pela primeira vez.
- `plataformas.py` (08/11/2026): Portal de Compras Públicas (API pública por palavra), BLL e BNC (lista pública dos 100 processos mais recentes + página pública de cada processo novo; **não contornar o captcha da busca**). Remove o que já está no PNCP (código do Portal ou UF+município+número/ano). Itens com `fonte: "Plataforma privada"` e `plataforma_nome`. Cache: `cache_plataformas.json`. Licitanet (403) e Licitações-e/BB (captcha) ficam de fora. Testes em `tests/test_plataformas.py`.
- `avisar.py`: seleciona os itens relevantes (catarata ou cirurgia oftalmológica, sem compras nem prazo vencido) que não estão em `avisados.json` e manda e-mail (Gmail SMTP) e WhatsApp (CallMeBot).
  - `python3 avisar.py --teste` só mostra o que enviaria.
- `.github/workflows/radar.yml`: roda a cada hora, no minuto 27 (24 horas por dia); coleta, envia informe mesmo sem novidades, faz commit dos caches e publica no GitHub Pages.
- `.github/workflows/painel.yml`: só republica o `radar.html`.
- Painel: https://beicinha.github.io/radar-catarata/
- Secrets usados (configurados no GitHub, nunca no código): `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY`, opcional `EMAIL_TO`.

## Cuidados
- Dependências: só Python 3, `curl` e `pypdf`.
- Antes de mexer nos filtros de relevância, teste com `python3 avisar.py --teste`.
- Rodar manualmente: aba Actions → "Radar Catarata" → "Run workflow" (ou `gh workflow run radar.yml -R beicinha/radar-catarata`).

## Correções e validação em 07/11/2026
- A segunda execução na nuvem concluiu coleta, histórico e publicação; e-mail recebido. Inicialmente o usuário informou que não recebeu o WhatsApp, mas **depois confirmou o recebimento**. O envio inicial chegou com atraso; a ativação já estava concluída. A confirmação foi registrada para os quatro itens do envio inicial, evitando repetição.
- CallMeBot aceitar/enfileirar uma solicitação **não comprova entrega**. Nunca registrar como entregue sem confirmação. Não expor resposta bruta, telefone, chave ou URL autenticada nos logs públicos.
- `regras.py` compartilha a triagem entre coleta e avisos. Compras de caixas/instrumentos, turismo e trechos administrativos não devem ser tratados como contratação de cirurgia. Serviços que incluem insumos não devem ser excluídos só por isso.
- `avisados.json` guarda estado por canal. Registros antigos preservam o e-mail já enviado e deixam o WhatsApp pendente. Falhas são independentes; pendências abertas não expiram só por terem aparecido há mais de dois dias. São processados até 15 itens por e-mail e 5 por WhatsApp a cada rodada.
- Solicitações WhatsApp aceitas pelo serviço não são repetidas automaticamente, mesmo sem confirmação de entrega. Erros de conexão/configuração continuam pendentes. A API gratuita não fornece aqui confirmação de entrega.
- Em 07/11, o usuário confirmou também o recebimento dos cinco itens da rodada das 15h19 e pediu monitoramento horário com avisos somente de novidades. `inicio_monitoramento.json` registra os IDs existentes no momento da configuração: continuam no painel, mas não geram alertas históricos. Novos IDs relevantes entram na fila por canal; falhas de envio são retomadas. Não apagar esse arquivo nem marcar itens antigos como enviados sem terem sido enviados.
- `status_avisos.json` informa a situação geral no painel, sem dados pessoais ou credenciais.
- O usuário pediu informes após cada procura, mesmo sem novidades, e autorizou repetir informações anteriores como lembretes. Usar `python avisar.py --informe` no fluxo do GitHub. Simulação: `python3 avisar.py --informe --teste`.
- `repertorio_informes.json` contém oito temas; a descrição está em `REPERTORIO_INFORMES.md`. `informes.py` monta as mensagens e `informes.json` guarda a rotação e evita duplicação na mesma execução.
- Não afirmar procura concluída se o arquivo de dados não tiver o identificador daquela execução e a etapa de coleta não tiver terminado. Informar falhas de fontes, data da base e rótulo explícito nos lembretes. O próprio fluxo não avisa se o GitHub não chegar a iniciá-lo.
- Para revisar os dados existentes e regenerar o painel **sem rede ou envio**: `python3 coletor.py --revisar-dados`. A cópia para `~/RadarCatarata` agora exige `--copiar-local`; não usar sem autorização para escrever fora do repositório.
- Testes de regressão sem envio: `python3 -m unittest discover -s tests -v`.
- O painel apresenta exigências como indícios para conferência, usa a data atual para prazos e avisa sobre coleta antiga. Falhas de fontes preservam os dados anteriores e devem aparecer como falha.
- Há um fluxo separado **“Testar WhatsApp (envia uma mensagem)”**. Só executá-lo quando o usuário autorizar o envio. Texto exato: “Radar Catarata: teste de funcionamento do WhatsApp.” Não envia e-mail nem altera o histórico de oportunidades.
- Recebimento inicial no celular confirmado pelo usuário; não é necessário disparar outra mensagem de teste. Falta validar a próxima coleta automática completa. PDFs sem texto ainda exigem OCR ou revisão manual; a cobertura de cada fonte OSS precisa de acompanhamento. Não prometer triagem infalível nem habilitação automática.

## Fontes ampliadas em 08/11/2026
- `coletor.py`: `TERMOS_GENERICOS` (eletivas, filas, OCI, Agora Tem Especialistas, SIGTAP etc.). Editais genéricos sem tema no objeto passam por `itens_oftalmo()` (itens do PNCP; cache diário em `cache_pncp.json`).
- `diarios_municipais.py`: diários das associações de municípios (12 redes; ver `ASSOCIACOES`). Cache das matérias em `cache_diarios.json`. Itens com `diario_rede: "associacoes"`. Oportunidade exige ato de contratação com objeto oftalmológico; alerta continua exigindo cirurgia (`avisar.relevante`).
- `mapeamento.py`: contratos e atas do PNCP (fonte `Mapeamento`), 1x por dia (`cache_mapeamento.json`, chave `_dia`). **Nunca geram alerta.** Painel: grupo "Mercado" (Mapa de contratos / Contratos vencendo). Informe tem tema `vencendo`.
- Testes: `tests/test_fontes_novas.py`.
