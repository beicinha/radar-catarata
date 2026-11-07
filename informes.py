"""Informes de execução e lembretes baseados nos dados, sem inventar novidades."""
from collections import Counter


def detalhe(tipo, dados, itens, indice):
    base = dados.get('atualizado') or 'data não informada'
    lembrar = f'Lembrete da base de {base}; não é novidade.'
    if tipo == 'resumo':
        catarata = sum(i.get('categoria') == 'Catarata' for i in itens)
        return f'Base disponível: {len(itens)} registros de possíveis serviços cirúrgicos, sendo {catarata} classificados como catarata. Exigem conferência do edital.'
    if tipo == 'regiao':
        ufs = Counter(i.get('uf') for i in itens)
        return 'Na base disponível: ' + ', '.join(f'{uf}: {ufs[uf]}' for uf in ('SP', 'MG', 'GO')) + '. São registros para análise, sem confirmação de habilitação.'
    if tipo == 'documentos':
        reqs = [i['req'] for i in itens if i.get('req')]
        ok = sum(r.get('status') == 'ok' for r in reqs)
        sem = sum(r.get('status') in ('sem_texto', 'sem_arquivo', 'erro') for r in reqs)
        return f'Leitura automática na base: {ok} editais com texto analisado; {sem} sem leitura completa. Conferir os documentos originais.'
    if tipo == 'distancia':
        return 'As distâncias do Radar são em linha reta, a partir de Monte Alto/SP. Não são quilometragem de estrada nem prova de atendimento ao raio exigido no edital.'
    candidatos = list(itens)
    if tipo == 'prazo':
        candidatos = sorted((i for i in itens if i.get('encerramento')), key=lambda i: i['encerramento'])
    elif tipo == 'perto':
        candidatos = sorted((i for i in itens if i.get('categoria') == 'Catarata' and i.get('dist_km') is not None), key=lambda i: i['dist_km'])
    elif tipo == 'estrutura':
        candidatos = [i for i in itens if any('centro cirúrgico' in r.get('r', '') for r in (i.get('req') or {}).get('oferece', []))]
    if not candidatos:
        return 'Não há registro suficiente na base para este destaque. Confira o painel e os editais originais.'
    # Prazos e proximidade priorizam o primeiro; lembrança alterna os registros.
    i = candidatos[indice % len(candidatos)] if tipo == 'retomar' else candidatos[0]
    partes = [lembrar, f"{i.get('municipio') or 'Município não informado'}/{i.get('uf') or '?'}."]
    if i.get('encerramento'):
        partes.append('Prazo registrado: ' + i['encerramento'][:16].replace('T', ' ') + '.')
    if tipo == 'perto':
        partes.append(f"Distância estimada: {i['dist_km']} km em linha reta.")
    if tipo == 'estrutura':
        partes.append('O texto sugere cessão de estrutura; confirmar condições e responsabilidades no edital.')
    partes.append(f"Fonte: {i.get('fonte') or 'não informada'} — {i.get('link') or 'ver painel'}")
    return ' '.join(partes)


def criar(dados, itens, repertorio, indice, resultado, rodada, agora, painel):
    atual = bool(rodada and dados.get('rodada') == rodada and resultado == 'success')
    fontes = dados.get('fontes_status') or []
    falhas = [f.get('nome') or 'Fonte sem nome' for f in fontes if not f.get('ok')]
    if resultado == 'failure':
        titulo = 'A procura desta rodada falhou.'
    elif resultado == 'skipped':
        titulo = 'A procura desta rodada não foi executada.'
    elif not atual:
        titulo = 'Sem confirmação de nova procura nesta execução.'
    elif not fontes:
        titulo = 'Procura encerrada, sem confirmação das fontes consultadas.'
    elif falhas:
        titulo = 'Procura parcial concluída.'
    else:
        titulo = 'Procura concluída nas fontes configuradas.'
    linhas = [f'Radar Catarata — informe de {agora.strftime("%d/%m/%Y %H:%M")} (Brasília)', titulo]
    if atual:
        linhas.append(f"Início: {dados.get('atualizado', '?')}. Término: {dados.get('concluido', '?')}.")
        linhas.append(f'Fontes com resposta: {sum(bool(f.get("ok")) for f in fontes)}/{len(fontes)}.')
    linhas.append(f"Data da base disponível: {dados.get('atualizado') or 'não informada'}.")
    if falhas:
        linhas.append('Falhas registradas na base: ' + '; '.join(falhas[:3]) + (f'; e mais {len(falhas)-3}.' if len(falhas)>3 else '.'))
        linhas.append('Não é possível concluir ausência de novidades nas fontes que falharam.')
    registro = repertorio[indice % len(repertorio)]
    linhas += ['', registro['titulo'] + ':', detalhe(registro['tipo'], dados, itens, indice), '', f'Painel: {painel}']
    return '\n'.join(linhas), registro['tipo']
