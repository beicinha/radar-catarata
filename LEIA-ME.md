# Radar Catarata

Painel que junta, num só lugar, as oportunidades de catarata e oftalmologia.

## De onde vêm os dados
1. **PNCP**: editais com propostas abertas que citam catarata, facoemulsificação, oftalmologia, lente intraocular, pterígio ou mutirão. Para cada edital, o coletor busca:
   - o valor por catarata e a quantidade, pelos itens do edital;
   - o prazo de encerramento;
   - a plataforma do órgão;
   - os vencedores ou credenciados já publicados;
   - os documentos de resultado (adjudicação, homologação, convocação).
2. **Sites de OSS e AMEs**: a lista está em `fontes_oss.json`. O coletor procura links de edital, chamamento ou credenciamento ligados a médico ou oftalmologia, e marca como "Novo" o que aparece pela primeira vez.

## Arquivos
- `coletor.py`: faz a coleta e gera o painel. Para rodar: `/usr/bin/python3 coletor.py`
- `radar.html`: o painel, que abre no navegador. É também a página publicada.
- `dados.json`: os dados da última coleta.
- `fontes_oss.json`: os sites monitorados. Para incluir um site, acrescente `{"nome": "...", "uf": "SP", "url": "..."}`.
- `cache_pncp.json` e `vistos_oss.json`: memória entre as coletas, para saber o que é novo.
- `municipios.json`: coordenadas dos municípios, usadas no cálculo da distância até Monte Alto.

## Limites
- Municípios com até 20 mil habitantes podem publicar só no Diário Oficial até abril de 2027. Esses editais não aparecem.
- Nos sites de OSS, o radar mostra links para conferir; ele não lê o conteúdo dos editais.
- O valor por catarata vem do item do edital. Confira sempre no edital.
- As marcações "Acompanhar" e "Descartar" ficam salvas só no navegador em que foram feitas.

## Servidor local
- Endereço: **http://localhost:8765** (só neste Mac).
- Arquivo servido: `~/RadarCatarata/index.html`. O coletor atualiza esse arquivo a cada coleta.
- O servidor liga sozinho quando o Mac inicia. Ele é configurado em `~/Library/LaunchAgents/br.radarcatarata.servidor.plist`.
- Para desligar de vez:
  `launchctl unload ~/Library/LaunchAgents/br.radarcatarata.servidor.plist` e depois apague o arquivo `.plist`.
