"""Critérios comuns ao coletor, painel e avisos. Não determinam habilitação."""
import re
import unicodedata


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto or '')
                   if unicodedata.category(c) != 'Mn').lower()


TEMA = re.compile(r'oftalm|catarat|faco\s*em|\bfaco\b|facectom|intra[- ]?ocular|pterig|retina|glaucoma|\byag\b|\bocular\b')
CATARATA = re.compile(r'catarat|faco\s*em|\bfaco\b|facectom')
CIRURGIA = re.compile(r'cirurg|faco\s*em|facectom|pterig')
SERVICO = re.compile(r'prestacao de servic|credencia|chamamento|realizacao de (?:procedimentos|cirurgias)|servicos (?:medicos|oftalm)')
COMPRA = re.compile(r'aquisicao|compra de|locacao de (?:microscopio|equipament|aparelho)|fornecimento\s+(?:(?:parcelado|continuado)\s+)?de\s+(?:caixas|kits?|instrument|equipament|materia|medicament|lentes|oculos|insumos)|registro de precos.{0,45}(?:aquisicao|compra)')
MATERIAL = re.compile(r'\bkit\b|blefarostato|pin[cç]a|canula|caixas cirurgicas|instrumental|instrumentos|arma[cç]oes|oculos|lentes de contato')
TURISMO = re.compile(r'cataratas do iguacu|passeio turist|viagem.{0,70}cataratas|ingressos para cataratas')
ATO = re.compile(r'credenciamento de (?:pessoas|empresas|clinicas|prestadores)|chamamento publico|aviso de (?:licitacao|pregao|contratacao|credenciamento)|edital de credenciamento|(?:abertura|deflagraram).{0,60}credenciamento')
RESULTADO = re.compile(r'extrato.{0,35}contrato|\baditivo\b|termo de credenciamento|contrato com|extrato da ata de registro|adjudicacao|homologacao|resultado (?:final|de julgamento)')


def classificar(texto):
    t = normalizar(texto)
    if TURISMO.search(t) or not TEMA.search(t):
        return None
    # Um serviço pode incluir lentes e insumos; compra isolada não é cirurgia.
    if (COMPRA.search(t) or MATERIAL.search(t)) and not SERVICO.search(t):
        return 'Material/compra'
    if SERVICO.search(t) or CIRURGIA.search(t):
        return 'Catarata' if CATARATA.search(t) else 'Oftalmologia'
    return 'Material/compra'


def cirurgia_ofertada(texto):
    t = normalizar(texto)
    if classificar(texto) not in ('Catarata', 'Oftalmologia'):
        return False
    if CATARATA.search(t) and CIRURGIA.search(t):
        return True
    # Uma lista de consultas em cirurgia geral e oftalmologia não oferece cirurgia ocular.
    t = re.sub(r'cirurgia (?:geral|vascular|plastica|cardiaca|toracica)|medico cirurgiao geral', '', t)
    return bool(re.search(r'oftalm\w*[^.;]{0,200}(?:\bcirurgias?\b|\bcirurgic\w*)|'
                          r'(?:\bcirurgias?\b|\bcirurgic\w*)[^.;]{0,200}oftalm', t))


def diario_contratacao(texto):
    t = normalizar(texto)
    return bool(ATO.search(t) and TEMA.search(t)) and not RESULTADO.search(t) and classificar(texto) != 'Material/compra'


def credenciamento(item):
    return 'credencia' in normalizar(f"{item.get('modalidade', '')} {item.get('objeto', '')}")


def valor_cirurgia(item):
    t = normalizar(item.get('descricao') or '')
    return bool(CATARATA.search(t) and CIRURGIA.search(t) and not MATERIAL.search(t)
                and not COMPRA.search(t) and not TURISMO.search(t))


def revisar_item(item):
    """Remove ruído e valores de materiais também de bases já coletadas."""
    i = dict(item)
    cat = classificar(i.get('objeto') or '')
    if i.get('fonte') == 'Diário Oficial' and not diario_contratacao(i.get('objeto') or ''):
        return None
    if i.get('fonte') != 'Site OSS/AME':
        if not cat:
            return None
        i['categoria'] = cat
    if i.get('faco') and (cat == 'Material/compra' or not valor_cirurgia({'descricao': i['faco'].get('desc', '')})):
        i['faco'] = None
    return i
