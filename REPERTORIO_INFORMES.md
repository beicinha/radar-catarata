# Informes do Radar

Configurado em 07/11/2026, a pedido do usuário. Depois de cada execução iniciada no GitHub, enviar um informe por e-mail e WhatsApp, mesmo sem novas oportunidades.

## Conteúdo de todos os informes

- Data e horário do informe em Brasília.
- Resultado real da procura: concluída, parcial, falhou, não executada ou sem confirmação.
- Horários de início e término, quando pertencem àquela execução.
- Quantidade de fontes com resposta e indicação de falhas.
- Data da base disponível e link do painel.
- Oportunidades novas ou pendentes, quando existirem. Lembretes antigos não são novos alertas.

## Repertório alternado

| Tema | Informação usada |
| --- | --- |
| Resumo | Quantidade de possíveis serviços cirúrgicos e de registros de catarata na base |
| Prazo próximo | Registro com menor prazo futuro, acompanhado de fonte e data da base |
| Mais perto | Registro de catarata com menor distância estimada de Monte Alto |
| SP, MG e GO | Quantidades na base por esses estados |
| Estrutura | Registro cujo texto sugere cessão de centro cirúrgico pelo órgão, sujeito a conferência |
| Leitura dos editais | Quantos registros têm texto analisado e quantos têm leitura incompleta |
| Lembrete anterior | Uma oportunidade anterior, identificada como lembrete e acompanhada da fonte |
| Distâncias | Explicação de que a distância é em linha reta e não comprova atendimento ao edital |

As mensagens são montadas com dados reais. Não afirmam habilitação nem ausência de novidades em fontes que falharam. Trechos repetidos usam a indicação “Lembrete da base de [data]; não é novidade”.

## Operação

- `python3 avisar.py --informe --teste`: simula sem rede, envio ou gravação.
- `python3 avisar.py --informe`: envia. Exige autorização do usuário e credenciais em variáveis de ambiente.
- `informes.json`: guarda tema e resultado por canal e por execução do GitHub. Evita repetir um informe aceito ao retentar a mesma execução. Uma execução nova gera um novo informe.
- O fluxo horário executa a coleta e depois o informe, inclusive para informar uma falha da etapa de coleta.
- Agendamento solicitado: a cada hora, no minuto 27. O horário foi alterado para renovar a programação após ausência de disparos no minuto 17.
- Se o GitHub não iniciar a execução, nenhum código roda e o próprio fluxo não consegue avisar dessa ausência. Não confundir publicação ou teste manual com validação do agendamento automático. GitHub Actions pode sofrer atrasos.
