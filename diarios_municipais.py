"""Diários oficiais das associações de municípios (plataforma diariomunicipal.com.br).

Muitos municípios pequenos publicam só no diário da associação estadual (AMM-MG, AMP-PR,
FAMUP-PB, APRECE-CE, FEMURN-RN, FAMURS-RS etc.). Esses diários NÃO entram no Querido Diário.

Para cada associação e termo, lê a busca pública (sem login nem captcha), abre a matéria
(uma vez; fica em cache) e separa:
  - aviso de contratação/credenciamento  -> oportunidade (fonte "Diário Oficial");
  - extrato, empresa credenciada, homologação -> mapeamento de mercado (fonte "Mapeamento").
"""
import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta

import regras

BASE = "https://www.diariomunicipal.com.br"
REDE = "associacoes"
NOME_STATUS = "Diários Oficiais – associações de municípios"
# (endereço, sigla, UF) — testados em 08/11/2026; os demais endereços da plataforma deram 404.
ASSOCIACOES = [("amm-mg", "AMM-MG", "MG"), ("amp", "AMP-PR", "PR"), ("famup", "FAMUP", "PB"),
               ("aprece", "APRECE", "CE"), ("femurn", "FEMURN", "RN"), ("famurs", "FAMURS", "RS"),
               ("amupe", "AMUPE", "PE"), ("amm-mt", "AMM-MT", "MT"), ("ama", "AMA", "AL"),
               ("agm", "AGM", "GO"), ("aemerj", "AEMERJ", "RJ"), ("famep", "FAMEP", "PA")]
TERMOS = ["catarata", "facoemulsificação", "oftalmologia", "oftalmológicos", "oftalmológicas"]
MAX_PAGINAS = 3               # 10 matérias por página
MAX_MATERIAS_NOVAS = 300      # matérias abertas por rodada (as demais ficam para a próxima)

RE_CARD = re.compile(r'<li class="materia-card">(.*?)</li>', re.S)
RE_MAPA = re.compile(r'extrato.{0,40}(?:contrato|ata|credenciamento)|\bcredenciad[ao]s?\b|termo de credenciamento|'
                     r'homologa|adjudica|ratifica|resultado (?:final|do credenciamento|de julgamento)|aditivo')

RE_TITULO_MAPA = re.compile(r"\bresultado\b|julgamento|habilitac|desert|extrato|aditivo|ratificac|homologac|^\s*contrato n")
RE_TITULO_FORA = re.compile(r"sem efeito|revoga|anulac|cancelament|suspens")


def _txt(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def ler_busca(pagina_html, slug):
    out = []
    for c in RE_CARD.findall(pagina_html):
        m = re.search(r'href="(/' + re.escape(slug) + r'/materia/([0-9A-F]+))"[^>]*>(.*?)</a>', c, re.S)
        if not m:
            continue
        g = lambda cls: _txt((re.search(r'class="' + cls + r'"[^>]*>(.*?)</', c, re.S) or [None, ""])[1])
        data = re.search(r"<dt>Circula[^<]*</dt>\s*<dd>(\d{2})/(\d{2})/(\d{4})</dd>", c)
        out.append({"codigo": m.group(2), "url": BASE + m.group(1), "titulo": _txt(m.group(3)),
                    "entidade": g("materia-card__entidade"), "orgao": g("materia-card__orgao"),
                    "trecho": g("materia-card__trecho"),
                    "data": f"{data.group(3)}-{data.group(2)}-{data.group(1)}" if data else ""})
    total = re.search(r"de <strong>(\d+)</strong>\s*mat", pagina_html)
    return out, int(total.group(1)) if total else len(out)


def ler_materia(pagina_html):
    m = re.search(r'class="documento__corpo[^"]*"[^>]*>(.*)', pagina_html, re.S)
    return _txt(m.group(1) if m else pagina_html)[:6000]


def municipio_de(entidade):
    """'Prefeitura de Guaxupé' / 'Prefeitura Municipal de X' / 'PEDRA LAVRADA' -> nome do município.
    Consórcios e associações devolvem ''."""
    e = (entidade or "").strip()
    if re.search(r"(?i)cons[oó]rcio|associa[cç][aã]o|\bcis|amvap|agência|ag[eê]ncia", e):
        return ""
    e = re.sub(r"(?i)^(prefeitura|c[aâ]mara|fundo|secretaria|servi[cç]o|instituto)(\s+\w+)*?\s+(de|do|da|dos|das)\s+", "", e)
    e = re.sub(r"(?i)^munic[ií]pio\s+(de|do|da|dos|das)\s+", "", e)
    return e.strip(" -/")


def classificar(m, texto):
    """Devolve 'oportunidade', 'mapa' ou None."""
    base = f"{m['titulo']}. {texto[:1500] or m['trecho']}"
    t = regras.normalizar(base)
    if regras.TURISMO.search(t) or regras.classificar(base) in (None, "Material/compra"):
        return None
    if re.match(r"\s*(portaria|decreto|lei\b|justificativa)", regras.normalizar(m["titulo"])) \
            or RE_TITULO_FORA.search(regras.normalizar(m["titulo"])):
        return None
    if RE_MAPA.search(regras.normalizar(m["titulo"])) or RE_TITULO_MAPA.search(regras.normalizar(m["titulo"])):
        return "mapa" if regras.cirurgia_ofertada(base) else None
    # Oportunidade: ato de contratação cuja finalidade é cirurgia ou serviço oftalmológico.
    # (Os alertas continuam exigindo cirurgia; ver avisar.relevante.)
    objeto_oftalmo = re.search(r"(?:credencia\w*|contratac\w*|objeto|objetivando|prestac\w*)[^.;]{0,250}"
                               r"(?:oftalm|catarat|facoem)", t)
    if regras.diario_contratacao(base) and (regras.cirurgia_ofertada(base) or objeto_oftalmo):
        return "oportunidade"
    if RE_MAPA.search(t) and regras.cirurgia_ofertada(base):
        return "mapa"
    return None


def coletar(curl, cache, hoje, mun_idx, ibge7, dist_km, vistos, dias=60, pausa=0.4):
    """Retorna (oportunidades, mapeamento, status). cache: {codigo: {...}}."""
    inicio = (datetime.fromisoformat(hoje) - timedelta(days=dias)).strftime("%Y-%m-%d")
    achados, falhas, abertas = {}, [], 0
    for slug, sigla, uf in ASSOCIACOES:
        ok_assoc = False
        for termo in TERMOS:
            for pag in range(1, MAX_PAGINAS + 1):
                q = urllib.parse.urlencode({"busca_avancada[texto]": termo, "busca_avancada[dataInicio]": inicio,
                                            "busca_avancada[dataFim]": hoje, "busca_avancada[ordenacao]": "recente",
                                            "busca_avancada[Enviar]": "", "busca_avancada[pagina]": pag})
                try:
                    pg = curl(f"{BASE}/{slug}/pesquisar?{q}", timeout=40, tries=2)
                except Exception:
                    break
                if "busca_avancada" not in pg:
                    break
                ok_assoc = True
                cards, total = ler_busca(pg, slug)
                for c in cards:
                    a = achados.setdefault(c["codigo"], dict(c, sigla=sigla, uf=uf, termos=[]))
                    if termo not in a["termos"]:
                        a["termos"].append(termo)
                time.sleep(pausa)
                if pag * 10 >= total or not cards:
                    break
        if not ok_assoc:
            falhas.append(sigla)
    for cod, a in achados.items():
        c = cache.get(cod)
        if c is None and abertas < MAX_MATERIAS_NOVAS:
            texto = ""
            try:
                texto = ler_materia(curl(a["url"], timeout=40, tries=2))
                abertas += 1
                time.sleep(pausa)
            except Exception:
                pass
            c = cache[cod] = {"texto": texto[:2500], "visto": hoje} if texto else None
        a["texto"] = (c or {}).get("texto", "")
    oportunidades, mapa = [], []
    for cod, a in achados.items():
        tipo = classificar(a, a["texto"])
        if not tipo:
            continue
        cidade = municipio_de(a["entidade"])
        ib = ibge7(cidade, a["uf"], mun_idx) if cidade else None
        corpo = a["texto"] or a["trecho"]
        objeto = (a["titulo"] + " — " + corpo)[:900]
        iid = ("dou:" if tipo == "oportunidade" else "map:dom:") + a["url"]
        primeira = vistos.get(iid) or hoje
        vistos[iid] = primeira
        item = {"id": iid, "fonte": "Diário Oficial" if tipo == "oportunidade" else "Mapeamento",
                "categoria": "Catarata" if regras.CATARATA.search(regras.normalizar(objeto)) else "Oftalmologia",
                "uf": a["uf"], "municipio": cidade or "", "orgao": a["entidade"] or a["orgao"],
                "modalidade": f"Diário {a['sigla']}", "objeto": objeto, "valor_total": None, "faco": None,
                "abertura": "", "encerramento": "", "publicado": a["data"], "vencedores": [],
                "docs_resultado": [], "plataforma": "", "link": a["url"], "dist_km": dist_km(ib),
                "primeira_vez": primeira, "termos": a["termos"], "diario_rede": REDE, "diario_nome": a["sigla"]}
        if tipo == "mapa":
            item["tipo_mapa"] = "Publicação em diário"
            item["credenciamento_aberto"] = "credencia" in regras.normalizar(objeto)
            mapa.append(item)
        else:
            oportunidades.append(item)
    if len(falhas) == len(ASSOCIACOES):
        raise RuntimeError("Diários das associações sem resposta")
    status = {"nome": NOME_STATUS, "ok": True, "associacoes": len(ASSOCIACOES) - len(falhas)}
    if falhas:
        status["sem_resposta"] = falhas
    return oportunidades, mapa, status


def podar(cache, hoje, dias=120):
    lim = (datetime.fromisoformat(hoje) - timedelta(days=dias)).strftime("%Y-%m-%d")
    for k in [k for k, v in cache.items() if not v or (v.get("visto") or "") < lim]:
        del cache[k]
