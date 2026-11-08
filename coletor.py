"""Radar de Licitações – Oftalmologia/Catarata.

Coleta editais abertos no PNCP, em plataformas privadas de pregão (Portal de Compras
Públicas, BLL, BNC) e novidades nos sites de OSS/AMEs, e gera
dados.json + radar.html (painel com filtros).

Uso: python3 coletor.py            (coleta tudo)
     python3 coletor.py --so-html  (só regenera o painel com o dados.json atual)
"""
import json, math, os, re, subprocess, sys, time, html, urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import unicodedata
import analise_editais
import estrutura_municipal
import plataformas
import regras

AQUI = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(AQUI, f)
BRT = timezone(timedelta(hours=-3))
AGORA = datetime.now(BRT)
HOJE = AGORA.strftime("%Y-%m-%d")

# Base para cálculo de distância: Monte Alto/SP
BASE = (-21.2655, -48.4971)

# Palavras pesquisadas (inclui grafias erradas comuns em editais, como "multirão")
TERMOS = ["catarata", "cirurgia de catarata", "cirurgias de catarata", "facoemulsificação",
          "facoemulsificacao", "cirurgia de facoemulsificação", "facectomia", "lente intraocular",
          "oftalmologia", "oftalmológico", "oftalmológicos", "oftalmologista", "oftalmo",
          "olho", "olhos", "cirurgia de olho", "cirurgia ocular", "cirurgias oftalmológicas",
          "pterígio", "mutirão de catarata", "mutirões de catarata", "mutirão de cirurgias",
          "multirão de catarata", "multirão", "multirões", "mutirão de facoemulsificação",
          "multirão de facoemulsificação"]
TERMOS_PNCP = TERMOS
# Diário Oficial (Querido Diário): termos mais específicos, para não trazer ruído
TERMOS_DIARIO = ['"catarata"', '"facoemulsificação"', '"facoemulsificacao"', '"oftalmologia"',
                 '"oftalmológicos"', '"oftalmologista"', '"mutirão de catarata"', '"multirão"', '"facectomia"']
RE_OFTALMO = re.compile(r"oftalm|catarat|facoem|faco |facectom|intraocular|pter[ií]gio|retina|glaucoma|yag|"
                        r"\bolhos?\b|ocular|mutir[aã]o|multir[aã]o|mutir[oõ]es|multir[oõ]es", re.I)
RE_CATARATA = re.compile(r"catarat|facoem|faco |facectomia|intraocular", re.I)
RE_COMPRA = re.compile(r"aquisi[cç][aã]o|fornecimento de (material|medicament|insumo|[oó]culos|lente)|"
                       r"registro de pre[cç]os? para (eventual |futura )?(aquisi|compra)|[oó]culos|arma[cç][oõ]es|"
                       r"material de consumo|equipamento|medicamento", re.I)
RE_SERVICO = re.compile(r"presta[cç][aã]o de servi|credenciamento|credenciar|cirurgia|procedimento|"
                        r"consulta|mutir[aã]o|servi[cç]os m[eé]dic|servi[cç]os? oftalm|chamamento", re.I)
RE_DOC_RESULT = re.compile(r"adjudica|homologa|resultado|contrato|convoca|extrato|ratifica", re.I)


def curl(url, timeout=40, tries=2):
    pncp = "pncp.gov.br" in url
    if pncp:
        # Desde 07/11/2026 o PNCP derruba cerca de metade das conexões ("connection reset");
        # novas tentativas curtas resolvem sem sobrecarregar o portal.
        tries = max(tries, 8)
    for tentativa in range(tries):
        r = subprocess.run(["curl", "-f", "-s", "-L", "-m", str(timeout), "-A",
                            "Mozilla/5.0 RadarLicitacoes/1.0", url],
                           capture_output=True, text=True, errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
        if tentativa + 1 < tries:
            time.sleep(1.5 + tentativa * 0.5 if pncp else 2 + tentativa * 2)
    raise RuntimeError("Fonte indisponível ou resposta vazia")


def cjson(url, default=None):
    try:
        resultado = json.loads(curl(url))
    except (ValueError, RuntimeError) as erro:
        raise RuntimeError("Fonte não retornou JSON válido") from erro
    if not isinstance(resultado, (dict, list)):
        raise RuntimeError("Formato inesperado na fonte")
    return resultado


def load(f, default):
    try:
        return json.load(open(P(f), encoding="utf-8"))
    except Exception:
        return default


MUN = load("municipios.json", {})


def dist_km(ibge):
    m = MUN.get(str(ibge or ""))
    if not m:
        return None
    la1, lo1 = map(math.radians, BASE)
    la2, lo2 = math.radians(m[1]), math.radians(m[2])
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(a)))


# ---------------------------------------------------------------- PNCP
def buscar_pncp():
    achados = {}
    for termo in TERMOS_PNCP:
        for pag in range(1, 6):
            u = ("https://pncp.gov.br/api/search/?q=" + urllib.parse.quote(termo) +
                 f"&tipos_documento=edital&ordenacao=-data&pagina={pag}&tam_pagina=100&status=recebendo_proposta")
            d = cjson(u, {}) or {}
            itens = d.get("items", [])
            for it in itens:
                a = achados.setdefault(it["item_url"], it)
                a.setdefault("_termos", [])
                if termo not in a["_termos"]:
                    a["_termos"].append(termo)
            if len(itens) < 100:
                break
            time.sleep(0.5)
        print(f"  PNCP '{termo}': total acumulado {len(achados)}", flush=True)
    return list(achados.values())


def classificar(desc):
    return regras.classificar(desc)


def enriquecer(it, cache):
    cnpj, ano, seq = it["item_url"].split("/")[2:5]
    chave = f"{cnpj}/{ano}/{seq}"
    base = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}"
    c = cache.get(chave) or {}
    if not c.get("consulta") or c.get("consultado_em") != HOJE:
        c["consulta"] = cjson(f"https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}", {}) or {}
        c["itens"] = cjson(base + "/itens?pagina=1&tamanhoPagina=200", []) or []
        c.setdefault("primeira_vez", HOJE)
        c["consultado_em"] = HOJE
    # situação muda: sempre reconsulta arquivos e resultados
    arqs = cjson(base + "/arquivos", []) or []
    c["arquivos"] = [{"titulo": a.get("titulo"), "url": a.get("url")} for a in arqs if isinstance(a, dict)]
    vencedores = []
    if any(x.get("temResultado") for x in c["itens"] if isinstance(x, dict)):
        for x in c["itens"][:15]:
            if isinstance(x, dict) and x.get("temResultado"):
                for r in cjson(f"{base}/itens/{x['numeroItem']}/resultados", []) or []:
                    n = r.get("nomeRazaoSocialFornecedor")
                    if n and n not in vencedores:
                        vencedores.append(n)
    c["vencedores"] = vencedores
    cache[chave] = c
    return chave, c


def montar_pncp(brutos, cache):
    out = []
    for i, it in enumerate(brutos):
        desc = it.get("description") or ""
        cat = classificar(desc + " " + (it.get("title") or ""))
        if not cat:
            continue
        # "olho/olhos/multirão" sozinhos trazem muito ruído: exige contexto de saúde ocular
        if cat == "Oftalmologia" and not re.search(r"oftalm|catarat|facoem|ocular|olho|pter[ií]gio|retina|glaucoma|yag", desc, re.I):
            if re.search(r"(mutir|multir)\w*.{0,40}cirurg|cirurg\w*.{0,40}eletiv", desc, re.I):
                cat = "Mutirão cirúrgico"
            else:
                continue
        if i and i % 25 == 0:
            json.dump(cache, open(P("cache_pncp.json"), "w", encoding="utf-8"), ensure_ascii=False)
        if cat == "Material/compra":
            # compras de material não interessam ao radar; guarda só o básico, sem consultas extras
            fim = it.get("data_fim_vigencia") or ""
            if fim and fim[:10] < HOJE:
                continue
            chave = "/".join(it["item_url"].split("/")[2:5])
            out.append({"id": "pncp:" + chave, "fonte": "PNCP", "categoria": cat, "uf": it.get("uf") or "",
                        "municipio": it.get("municipio_nome") or "", "orgao": it.get("orgao_nome") or "",
                        "modalidade": it.get("modalidade_licitacao_nome") or "", "objeto": desc[:400],
                        "valor_total": it.get("valor_global"), "faco": None, "abertura": "", "encerramento": fim[:16],
                        "publicado": (it.get("data_publicacao_pncp") or "")[:10], "vencedores": [], "docs_resultado": [],
                        "plataforma": "", "link": "https://pncp.gov.br/app/editais/" + chave,
                        "dist_km": dist_km(it.get("codigo_ibge")),
                        "primeira_vez": (cache.setdefault(chave, {}).setdefault("primeira_vez", HOJE)), "termos": it.get("_termos", [])})
            continue
        chave, c = enriquecer(it, cache)
        q = c.get("consulta") or {}
        fim = q.get("dataEncerramentoProposta") or it.get("data_fim_vigencia")
        if fim and fim[:10] < HOJE:
            continue
        faco = None
        for x in c.get("itens") or []:
            if isinstance(x, dict) and regras.valor_cirurgia(x):
                v = x.get("valorUnitarioEstimado") or 0
                qt = x.get("quantidade") or 0
                if v and v > 0 and v < 20000 and qt > 1:
                    faco = {"valor": round(v, 2), "qtd": qt, "desc": (x.get("descricao") or "")[:140]}
                    break
                if v and not faco and v > 0 and v < 20000:
                    faco = {"valor": round(v, 2), "qtd": qt, "desc": (x.get("descricao") or "")[:140]}
        docs_res = [a["titulo"] for a in c.get("arquivos", []) if a.get("titulo") and RE_DOC_RESULT.search(a["titulo"])]
        ibge = it.get("codigo_ibge") or (q.get("unidadeOrgao") or {}).get("codigoIbge")
        out.append({
            "id": "pncp:" + chave,
            "fonte": "PNCP",
            "categoria": cat,
            "uf": it.get("uf") or "",
            "municipio": it.get("municipio_nome") or "",
            "orgao": it.get("orgao_nome") or "",
            "modalidade": it.get("modalidade_licitacao_nome") or q.get("modalidadeNome") or "",
            "objeto": re.sub(r"\s+", " ", q.get("objetoCompra") or desc).strip()[:600],
            "valor_total": q.get("valorTotalEstimado") or it.get("valor_global"),
            "faco": faco,
            "abertura": (q.get("dataAberturaProposta") or "")[:16],
            "encerramento": (fim or "")[:16],
            "publicado": (q.get("dataPublicacaoPncp") or it.get("data_publicacao_pncp") or "")[:10],
            "vencedores": c.get("vencedores", []),
            "docs_resultado": docs_res[:5],
            "plataforma": q.get("linkSistemaOrigem") or "",
            "link": "https://pncp.gov.br/app/editais/" + chave,
            "dist_km": dist_km(ibge),
            "primeira_vez": c.get("primeira_vez", HOJE),
            "termos": it.get("_termos", []),
        })
        if i % 20 == 0:
            print(f"  enriquecidos {i}/{len(brutos)}", flush=True)
    return out


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def aplicar_analise(pncp, cache):
    """Lê os editais (uma vez por edital) e anexa o que exigem e o que o órgão oferece."""
    ca = analise_editais.carregar_cache()
    alvo = [i for i in pncp if i["categoria"] in ("Catarata", "Oftalmologia", "Mutirão cirúrgico")]
    novos = 0
    for n, i in enumerate(alvo):
        chave = i["id"].split(":", 1)[1]
        arqs = (cache.get(chave) or {}).get("arquivos") or []
        ja = chave in ca
        try:
            res = analise_editais.analisar(chave, arqs, ca)
        except Exception as e:
            res = {"status": "erro", "erro": str(e)[:80]}
        if not ja:
            novos += 1
            if novos % 10 == 0:
                analise_editais.salvar_cache(ca)
                print(f"  editais lidos: {n + 1}/{len(alvo)}", flush=True)
        mun = _sem_acento(i.get("municipio")).replace(" ", "")
        emails = [e for e in res.get("emails", [])
                  if (mun and mun[:6] in e.replace(".", "").replace("-", "")) or re.search(r"licit|compra|cpl|credenc|saude|contrat|cis|consorc|fms|prefeitura", e)]
        i["req"] = {"status": res.get("status"),
                    "oferece": [{"r": x["rotulo"], "t": x["trecho"]} for x in res.get("oferece", [])],
                    "exige": [{"r": x["rotulo"], "t": x["trecho"]} for x in res.get("exige", [])],
                    "emails": emails[:2], "lidos": res.get("lidos", [])}
    analise_editais.salvar_cache(ca)
    print(f"  análise de editais: {novos} lidos agora, {len(alvo) - novos} do cache", flush=True)


def aplicar_estrutura(itens):
    """Para cada oportunidade, lista os estabelecimentos com centro cirúrgico no município (CNES)."""
    ce = estrutura_municipal.carregar()
    alvo = [i for i in itens if i.get("municipio") and i.get("uf")
            and i["categoria"] in ("Catarata", "Oftalmologia", "Mutirão cirúrgico")]
    feitos = 0
    for i in alvo:
        ib = estrutura_municipal.ibge_de(i["municipio"], i["uf"], MUN)
        ja = ib in ce
        c = estrutura_municipal.estrutura(ib, ce)
        i["estr"] = estrutura_municipal.resumo(c)
        if ib and not ja:
            feitos += 1
            if feitos % 20 == 0:
                estrutura_municipal.salvar(ce)
                print(f"  municípios consultados no CNES: {feitos}", flush=True)
    estrutura_municipal.salvar(ce)
    print(f"  estrutura municipal: {feitos} municípios consultados agora", flush=True)


# ---------------------------------------------------------------- Diários Oficiais (Querido Diário)
RE_DIARIO_ATO = re.compile(r"credenciamento|chamamento p[uú]blico|preg[aã]o|licita[cç][aã]o|dispensa|inexigibilidade|"
                           r"contrata[cç][aã]o de (empresa|pessoa|servi)|extrato d[eo] contrato|ata de registro|"
                           r"homologa|adjudica|termo de refer|presta[cç][aã]o de servi", re.I)
RE_DIARIO_TEMA = re.compile(r"catarat|facoem|\bfaco\b|facectom|oftalmol[oó]gic|oftalmologia|oftalmologista|intraocular", re.I)


def coletar_diarios(vistos, dias=45):
    desde = (AGORA - timedelta(days=dias)).strftime("%Y-%m-%d")
    achados = {}
    for termo in TERMOS_DIARIO:
        u = ("https://api.queridodiario.org.br/gazettes?querystring=" + urllib.parse.quote(termo) +
             f"&published_since={desde}&size=100&excerpt_size=500&number_of_excerpts=3&sort_by=descending_date")
        d = cjson(u, {}) or {}
        for g in d.get("gazettes", []):
            trechos = [re.sub(r"\s+", " ", e).strip() for e in (g.get("excerpts") or [])]
            # só interessa se o trecho tiver cara de ato de contratação
            uteis = [t for t in trechos if RE_DIARIO_ATO.search(t) and RE_DIARIO_TEMA.search(t)]
            uteis = [t for t in uteis if regras.diario_contratacao(t)]
            if not uteis:
                continue
            k = g.get("url")
            a = achados.setdefault(k, {"g": g, "trechos": [], "termos": []})
            for t in uteis:
                if t not in a["trechos"]:
                    a["trechos"].append(t)
            a["termos"].append(termo.strip('"'))
        print(f"  Diários '{termo}': {len(achados)} publicações", flush=True)
        time.sleep(1)
    out = []
    for k, a in achados.items():
        g = a["g"]
        texto = " … ".join(a["trechos"])[:900]
        iid = "dou:" + k
        primeira = vistos.get(iid) or HOJE
        vistos[iid] = primeira
        cat = "Catarata" if RE_CATARATA.search(texto) else "Oftalmologia"
        if RE_COMPRA.search(texto) and not RE_SERVICO.search(texto):
            cat = "Material/compra"
        out.append({
            "id": iid, "fonte": "Diário Oficial", "categoria": cat,
            "uf": g.get("state_code") or "", "municipio": g.get("territory_name") or "",
            "orgao": "Diário Oficial de " + (g.get("territory_name") or ""), "modalidade": "Publicação no diário",
            "objeto": texto, "valor_total": None, "faco": None, "abertura": "", "encerramento": "",
            "publicado": g.get("date") or "", "vencedores": [], "docs_resultado": [], "plataforma": "",
            "link": k, "dist_km": dist_km(g.get("territory_id")), "primeira_vez": primeira,
            "termos": sorted(set(a["termos"])),
        })
    return out


# ---------------------------------------------------------------- Sites OSS
class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._txt = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._txt = []

    def handle_data(self, data):
        if self._href is not None:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._txt).split())))
            self._href = None


RE_LINK_EDITAL = re.compile(r"edital|editais|credenciamento|chamamento|processo seletivo|sele[cç][aã]o|"
                            r"contrata[cç][aã]o|cota[cç][aã]o|compras|licita|fornecedor|presta[cç][aã]o de servi", re.I)
RE_LINK_SAUDE = re.compile(r"m[eé]dic|oftalm|catarat|cirurg|especialidad|credenciamento|pessoa jur[ií]dica|pj\b", re.I)
RE_OUTRA_ESPEC = re.compile(r"cardiolog|ginecolog|obstetr|ortoped|psiqui|nefrolog|dermatolog|pediatr|vascular|dentista|"
                            r"biom[eé]dic|enfermeir|fisioterap|psic[oó]log|nutricion|farmac|neurolog|urolog|anestesi|"
                            r"radiolog|endocrin|pneumolog|gastro|reumatolog|oncolog|hematolog|infectolog|geriatr|"
                            r"cl[ií]nic[oa] geral|sa[uú]de da fam[ií]lia|t[eé]cnico|assistente|auxiliar|motorista|"
                            r"manuten[cç][aã]o|limpeza|vigil[aâ]ncia|aliment|lavanderia|resultado|errata|homologa", re.I)
RE_GENERICO_PJ = re.compile(r"credenciamento|chamamento|servi[cç]os m[eé]dicos|pessoa jur[ií]dica|\bpj\b|edital m[eé]dico", re.I)
RE_ANO = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")


def oss_relevante(texto, url):
    alvo = texto + " " + urllib.parse.unquote(url)
    if RE_OFTALMO.search(alvo):
        return True
    return bool(RE_GENERICO_PJ.search(alvo)) and not RE_OUTRA_ESPEC.search(alvo)


RE_NAVEGAR = re.compile(r"edita|licita|compra|chamamento|credenciamento|fornecedor|transpar|processo", re.I)


def links_de(url):
    t = curl(url, timeout=30, tries=2)
    p = Links()
    try:
        p.feed(t)
    except Exception:
        pass
    res = []
    for h, txt in p.links:
        if not h or h.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        res.append((urllib.parse.urljoin(url, h), html.unescape(txt)))
    return res


def coletar_oss(vistos):
    fontes = load("fontes_oss.json", [])
    out, status = [], []
    for f in fontes:
        achados = []
        try:
            if f.get("tipo") == "wp":
                for post in cjson(f["url"], []) or []:
                    tit = html.unescape(re.sub("<[^>]+>", "", (post.get("title") or {}).get("rendered", "")))
                    if (RE_LINK_EDITAL.search(tit) or RE_LINK_SAUDE.search(tit)) and oss_relevante(tit, post.get("link") or ""):
                        achados.append((post.get("link"), tit, (post.get("date") or "")[:10]))
            else:
                nivel1 = links_de(f["url"])
                paginas = [f["url"]] + [h for h, t in nivel1 if RE_NAVEGAR.search(t + " " + h)
                                        and urllib.parse.urlparse(h).netloc == urllib.parse.urlparse(f["url"]).netloc][:6]
                todos = list(nivel1)
                for pg in paginas[1:]:
                    todos += links_de(pg)
                for h, t in todos:
                    alvo = t + " " + urllib.parse.unquote(h)
                    if len(t) >= 8 and RE_LINK_EDITAL.search(alvo) and RE_LINK_SAUDE.search(alvo) and oss_relevante(t, h):
                        achados.append((h, t, ""))
            status.append({"nome": f["nome"], "ok": True, "itens": len(achados)})
        except Exception as e:
            status.append({"nome": f["nome"], "ok": False, "erro": "Fonte indisponível; dados anteriores preservados"})
            out += [i for i in load("dados.json", {}).get("itens", [])
                    if i.get("fonte") == "Site OSS/AME" and i.get("orgao") == f["nome"]]
        vistos_fonte = set()
        for h, t, data in achados:
            if h in vistos_fonte:
                continue
            vistos_fonte.add(h)
            iid = "oss:" + h
            primeira = vistos.get(iid) or HOJE
            vistos[iid] = primeira
            out.append({
                "id": iid, "fonte": "Site OSS/AME", "categoria":
                    "Catarata" if RE_CATARATA.search(t + h) else ("Oftalmologia" if RE_OFTALMO.search(t) else "Chamamento médico"),
                "uf": f.get("uf", ""), "municipio": "", "orgao": f["nome"], "modalidade": "Chamamento/edital da OSS",
                "objeto": t[:400], "valor_total": None, "faco": None, "abertura": "", "encerramento": "",
                "publicado": data, "vencedores": [], "docs_resultado": [], "plataforma": "",
                "link": h, "dist_km": None, "primeira_vez": primeira, "termos": [],
            })
        print(f"  {f['nome']}: {len(vistos_fonte)} links", flush=True)
    return out, status


# ---------------------------------------------------------------- Saída
def gerar_html(dados):
    dados = dict(dados, avisos_status=load("status_avisos.json", {}))
    tpl = open(P("painel_template.html"), encoding="utf-8").read()
    js = json.dumps(dados, ensure_ascii=True).replace("</", "<\\/")
    open(P("radar.html"), "w", encoding="utf-8").write(tpl.replace("/*__DADOS__*/null", js))
    # A cópia para servidor local é opcional e exige --copiar-local.
    if "--copiar-local" not in sys.argv:
        return
    try:
        pasta = os.path.expanduser("~/RadarCatarata")
        os.makedirs(pasta, exist_ok=True)
        open(os.path.join(pasta, "index.html"), "w", encoding="utf-8").write(tpl.replace("/*__DADOS__*/null", js))
    except Exception as e:
        print("  aviso: não consegui copiar para ~/RadarCatarata:", e)


PLATAFORMAS_NOMES = {"Portal de Compras Públicas"} | {n for n, _ in plataformas.LISTAS}


def revisar_dados(dados):
    revisados, ids = [], set()
    for item in dados.get("itens", []):
        i = regras.revisar_item(item)
        if not i or i.get("id") in ids:
            continue
        if i.get("encerramento") and i["encerramento"][:10] < HOJE:
            continue
        if i.get("req"):
            # As regras antigas não comprovam obrigação ou dispensa.
            i["req"] = dict(i["req"])
            i["req"]["conferencia_necessaria"] = True
            i["req"]["exige"] = [e for e in i["req"].get("exige", [])
                                   if analise_editais.exigencia_valida(e.get("r"), e.get("t", ""))]
        ids.add(i["id"])
        revisados.append(i)
    dados["itens"] = revisados
    for status in dados.get("fontes_status", []):
        nome = status.get("nome", "")
        if nome in PLATAFORMAS_NOMES:
            status["itens"] = sum(i.get("fonte") == plataformas.FONTE and i.get("plataforma_nome") == nome
                                  for i in revisados)
            continue
        fonte = "PNCP" if nome.startswith("PNCP") else "Diário Oficial" if nome.startswith("Diários Oficiais") else "Site OSS/AME"
        status["itens"] = sum(i.get("fonte") == fonte and (fonte != "Site OSS/AME" or i.get("orgao") == nome)
                              for i in revisados)
    return dados


def main():
    if "--so-html" in sys.argv or "--revisar-dados" in sys.argv:
        dados = revisar_dados(load("dados.json", {}))
        if "--revisar-dados" in sys.argv:
            json.dump(dados, open(P("dados.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        gerar_html(dados)
        print("painel revisado; sem coleta ou envio")
        return
    anteriores = load("dados.json", {})
    preservar = lambda fonte: [i for i in anteriores.get("itens", []) if i.get("fonte") == fonte]
    cache = load("cache_pncp.json", {})
    vistos = load("vistos_oss.json", {})
    status = []
    try:
        if "--sem-pncp" in sys.argv:
            pncp = preservar("PNCP")
        else:
            print("1/4 Buscando no PNCP...", flush=True)
            pncp = montar_pncp(buscar_pncp(), cache)
            if not pncp and preservar("PNCP"):
                raise RuntimeError("PNCP sem resultados; verificar fonte")
        aplicar_analise(pncp, cache)
        status.append({"nome": "PNCP (Portal Nacional de Contratações Públicas)", "ok": True})
    except Exception:
        pncp = preservar("PNCP")
        status.append({"nome": "PNCP (Portal Nacional de Contratações Públicas)", "ok": False,
                       "erro": "Coleta incompleta; dados anteriores preservados"})
        print("::warning::Falha no PNCP; preservados registros anteriores.", flush=True)
    print("3/4 Lendo Diários Oficiais...", flush=True)
    try:
        diarios = coletar_diarios(vistos)
        status.append({"nome": "Diários Oficiais municipais (Querido Diário)", "ok": True})
    except Exception:
        diarios = preservar("Diário Oficial")
        status.append({"nome": "Diários Oficiais municipais (Querido Diário)", "ok": False,
                       "erro": "Fonte indisponível; dados anteriores preservados"})
    print("3b/4 Plataformas privadas (Portal de Compras Públicas, BLL, BNC)...", flush=True)
    cache_plat = load("cache_plataformas.json", {})
    try:
        privadas, status_plat = plataformas.coletar(curl, cjson, cache_plat, HOJE, MUN, dist_km, pncp, cache,
                                                    preservar(plataformas.FONTE))
    except Exception:
        privadas = preservar(plataformas.FONTE)
        status_plat = [{"nome": n, "ok": False, "erro": "Fonte indisponível; dados anteriores preservados"}
                       for n in sorted(PLATAFORMAS_NOMES)]
    status += status_plat
    try:
        aplicar_estrutura(pncp + diarios + privadas)
    except Exception:
        print("::warning::Falha na consulta de estrutura municipal; não concluir ausência de estrutura.")
    print("4/4 Varrendo sites de OSS/AMEs...", flush=True)
    oss, status_oss = coletar_oss(vistos)
    dados = revisar_dados({"atualizado": AGORA.strftime("%Y-%m-%d %H:%M"), "base": "Monte Alto/SP",
                           "itens": pncp + diarios + privadas + oss, "fontes_status": status + status_oss,
                           "rodada": os.environ.get("GITHUB_RUN_ID"),
                           "concluido": datetime.now(BRT).strftime("%Y-%m-%d %H:%M")})
    json.dump(cache, open(P("cache_pncp.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(vistos, open(P("vistos_oss.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(cache_plat, open(P("cache_plataformas.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(dados, open(P("dados.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    gerar_html(dados)
    print(f"OK: {len(dados['itens'])} registros revisados. Painel: radar.html", flush=True)


if __name__ == "__main__":
    main()
