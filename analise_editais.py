"""Lê os PDFs dos editais (PNCP) e resume o que o edital exige da empresa e o que o órgão oferece.

O resultado fica em cache_analise.json (cada edital é baixado e lido uma vez só).
"""
import io, json, os, re, subprocess, zipfile, hashlib
from datetime import datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "cache_analise.json")
MAX_BYTES = 30 * 1024 * 1024
MAX_PAGINAS = 90

try:
    import pypdf
except Exception:  # pragma: no cover
    pypdf = None

RE_DOC_BOM = re.compile(r"edital|termo de refer|\bTR\b|anexo|aviso|chamamento|credenciamento|projeto b[aá]sico", re.I)
RE_DOC_RUIM = re.compile(r"resultado|homologa|adjudica|ata d[ae] (sess|julg|abert)|contrato|extrato|convoca|impugna|esclarec|recurso|errata", re.I)

UFS = "AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO"

# (chave, rótulo curto, grupo, regex)
REGRAS = [
    # O que o órgão/município oferece
    ("cede_estrutura", "Órgão cede o centro cirúrgico/hospital", "oferece",
     r"(infraestrutura|estrutura f[ií]sica|centro cir[uú]rgico|depend[eê]ncias|instala[cç][oõ]es)[^.;]{0,140}(ser[aá]|ser[aã]o|fica|ficar[aã]o)\s+(disponibiliza|cedid|fornecid|colocad)"
     r"|(executad|realizad)[oa]s?\s+(nas depend[eê]ncias|no hospital municipal|na unidade hospitalar|no centro cir[uú]rgico|nas instala[cç][oõ]es)\s+d[oa]\s+(hospital|munic[ií]pio|contratante|secretaria|policl[ií]nica|consórcio)"
     r"|(contratante|munic[ií]pio|secretaria|cons[oó]rcio)[^.;]{0,60}(disponibilizar[aá]|ceder[aá])[^.;]{0,80}(espa[cç]o|estrutura|centro cir[uú]rgico|sala|instala[cç]|consult[oó]rio)"),
    ("orgao_insumos", "Órgão fornece insumos/lentes", "oferece",
     r"(contratante|munic[ií]pio|secretaria|cons[oó]rcio)[^.;]{0,80}(fornecer[aá]|disponibilizar[aá])[^.;]{0,80}(insumos|materiais|lentes?|medicamentos|\bLIO\b)"),
    ("orgao_transporte", "Órgão faz o transporte dos pacientes", "oferece",
     r"transporte\s+(dos|de)\s+pacientes[^.;]{0,100}(contratante|munic[ií]pio|secretaria|cons[oó]rcio)"
     r"|(contratante|munic[ií]pio|secretaria)[^.;]{0,60}(transporte|deslocamento)\s+dos\s+pacientes"),
    # O que a empresa precisa ter
    ("estrutura_propria", "Exige estrutura própria (clínica/centro cirúrgico)", "exige",
     r"(estabelecimento|instala[cç][oõ]es|cl[ií]nica|unidade|centro cir[uú]rgico)\s+(pr[oó]pri[oa]s?|d[ao] (contratad|credenciad)[oa])"
     r"|licen[cç]a sanit[aá]ria[^.;]{0,80}(endere[cç]o|estabelecimento|local) de (execu|realiza|atendimento)"
     r"|executad[oa]s?\s+em\s+estabelecimento[^.;]{0,40}(contratad|credenciad)"),
    ("no_municipio", "Atendimento no município/região", "exige",
     r"(sediad|localizad|situad|instalad|estabelecid)[oa]s?\s+(no|em)\s+(munic[ií]pio|territ[oó]rio|cidade)"
     r"|no\s+territ[oó]rio\s+d[oa]\s+munic[ií]pio"),
    ("raio_km", "Distância máxima exigida", "exige", r"(raio|dist[aâ]ncia)[^.;]{0,50}?(\d{2,4})\s?(km|quil[oô]metros)"),
    ("cnes", "CNES ativo", "exige", r"\bCNES\b"),
    ("licenca", "Licença sanitária/alvará", "exige", r"licen[cç]a (sanit[aá]ria|de funcionamento)|alvar[aá] (sanit[aá]rio|de funcionamento)"),
    ("atestado", "Atestado de capacidade técnica", "exige", r"atestados?\s+de\s+capacidade\s+t[eé]cnica|capacidade\s+t[eé]cnico[- ]operacional"),
    ("crm_local", "CRM do estado do órgão", "exige",
     r"(CRM|Conselho Regional de Medicina)[^.;]{0,60}(jurisdi[cç][aã]o|do estado d[eo]|com sede)"
     r"|CRM[\s/-]*(" + UFS + r")\b"),
    ("rqe", "RQE / título de especialista", "exige", r"\bRQE\b|registro de qualifica[cç][aã]o de especialista|t[ií]tulo de especialista"),
    ("balanco", "Balanço e índices financeiros", "exige", r"balan[cç]o patrimonial|[ií]ndices? de liquidez|liquidez geral"),
    ("capital", "Capital/patrimônio mínimo", "exige", r"(capital social|patrim[oô]nio l[ií]quido)\s+m[ií]nimo"),
    ("vistoria", "Vistoria", "exige", r"\bvistoria"),
    ("equip", "Equipamentos próprios (faco, microscópio)", "exige", r"(contratad|credenciad)[oa][^.;]{0,100}(fornec|disponibiliz|possuir|manter)[^.;]{0,100}(facoemulsificador|aparelho de facoemulsifica|microsc[oó]pio cir[uú]rgico)"),
    ("contratada_insumos", "Empresa fornece LIO/insumos", "exige",
     r"(contratad|credenciad)[oa][^.;]{0,140}(fornec|disponibiliz|respons[aá]vel)[^.;]{0,80}(lentes?|\bLIO\b|insumos|materiais|medicamentos)"
     r"|incluindo[^.;]{0,40}(lente|LIO|insumos|materiais)"),
    ("sem_consorcio", "Consórcio de empresas vedado", "exige",
     r"(vedad[ao]|n[aã]o (ser[aá]|ser[aã]o) (admitid|permitid))[^.;]{0,60}cons[oó]rcio"),
    ("consorcio_ok", "Aceita consórcio de empresas", "exige",
     r"(admitid|permitid)[ao][^.;]{0,40}participa[cç][aã]o[^.;]{0,40}cons[oó]rcio|empresas reunidas em cons[oó]rcio"),
]
REGRAS = [(k, r, g, re.compile(x, re.I)) for k, r, g, x in REGRAS]
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
RE_FORMA = re.compile(r"(inscri[cç][aã]o|protocol|envelope|requerimento|documenta[cç][aã]o)[^.;]{0,160}", re.I)


def _curl(url):
    r = subprocess.run(["curl", "-f", "-s", "-L", "-m", "120", "--max-filesize", str(MAX_BYTES), "-A",
                        "Mozilla/5.0 RadarLicitacoes/1.0", url], capture_output=True)
    return r.stdout or b""


def _texto_pdf(b):
    if not pypdf or not b.startswith(b"%PDF"):
        return ""
    try:
        rd = pypdf.PdfReader(io.BytesIO(b))
        partes = []
        for p in rd.pages[:MAX_PAGINAS]:
            try:
                partes.append(p.extract_text() or "")
            except Exception:
                pass
        return "\n".join(partes)
    except Exception:
        return ""


def _texto_arquivo(b):
    if b.startswith(b"%PDF"):
        return _texto_pdf(b)
    if b.startswith(b"PK"):
        out = []
        try:
            z = zipfile.ZipFile(io.BytesIO(b))
            nomes = sorted(z.namelist(), key=lambda n: (0 if RE_DOC_BOM.search(n) else 1, n))
            for n in nomes[:6]:
                if n.lower().endswith(".pdf"):
                    out.append(_texto_pdf(z.read(n)))
        except Exception:
            pass
        return "\n".join(out)
    return ""


def _trecho(t, m, larg=170):
    a, b = max(0, m.start() - larg // 2), min(len(t), m.end() + larg)
    return ("…" if a else "") + t[a:b].strip() + "…"


def negada(texto, match):
    inicio = max(texto.rfind(".", 0, match.start()), texto.rfind(";", 0, match.start())) + 1
    fins = [p for p in (texto.find(".", match.end()), texto.find(";", match.end())) if p >= 0]
    fim = min(fins) if fins else len(texto)
    frase = texto[inicio:fim]
    return bool(re.search(r"n[aã]o[^.;]{0,70}(exigid|obrigat)|dispensad|facultativ", frase, re.I))


def exigencia_valida(rotulo, trecho):
    regra = next((r for r in REGRAS if r[1] == rotulo), None)
    if not regra:
        return True
    return any(not negada(trecho, m) for m in regra[3].finditer(trecho))


def analisar_texto(t):
    t = re.sub(r"\s+", " ", t)
    res = {"oferece": [], "exige": [], "emails": [], "forma": "", "paginas_texto": len(t)}
    for k, rot, g, rx in REGRAS:
        m = next((m for m in rx.finditer(t) if g != "exige" or not negada(t, m)), None)
        if not m:
            continue
        item = {"k": k, "rotulo": rot, "trecho": _trecho(t, m)}
        if k == "raio_km":
            item["rotulo"] = f"Até {m.group(2)} km do município"
        if k == "crm_local":
            uf = re.search(r"CRM[\s/-]*(" + UFS + r")\b", t)
            if uf:
                item["rotulo"] = f"CRM-{uf.group(1).upper()}"
        res[g].append(item)
    # consórcio: se o edital veda, não mostrar "aceita"
    ks = {x["k"] for x in res["exige"]}
    if "sem_consorcio" in ks and "consorcio_ok" in ks:
        res["exige"] = [x for x in res["exige"] if x["k"] != "consorcio_ok"]
    emails = []
    for e in RE_EMAIL.findall(t):
        e = e.strip(".").lower()
        if e not in emails and not e.endswith((".png", ".jpg")):
            emails.append(e)
    res["emails"] = emails[:4]
    m = RE_FORMA.search(t)
    if m:
        res["forma"] = m.group(0)[:220]
    return res


def carregar_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def salvar_cache(c):
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def analisar(chave, arquivos, cache):
    """arquivos = [{'titulo','url'}] do PNCP. Retorna o resumo (do cache, se já lido)."""
    assinatura = hashlib.sha256(json.dumps(arquivos, sort_keys=True).encode()).hexdigest()
    anterior = cache.get(chave) or {}
    validade = 7 if anterior.get("status") == "ok" else 1
    desde = (datetime.now() - timedelta(days=validade)).isoformat()
    if (anterior.get("versao") == 2 and anterior.get("assinatura") == assinatura
            and anterior.get("analisado_em", "") >= desde):
        return anterior
    docs = [a for a in arquivos if a.get("url") and not RE_DOC_RUIM.search(a.get("titulo") or "")]
    docs.sort(key=lambda a: 0 if RE_DOC_BOM.search(a.get("titulo") or "") else 1)
    texto, lidos = "", []
    for a in docs[:3]:
        b = _curl(a["url"])
        tx = _texto_arquivo(b)
        if tx.strip():
            texto += "\n" + tx
            lidos.append(a.get("titulo") or "")
        if len(texto) > 400000:
            break
    if not docs:
        res = {"status": "sem_arquivo"}
    elif not texto.strip():
        res = {"status": "sem_texto", "lidos": [d.get("titulo") for d in docs[:3]]}
    else:
        res = analisar_texto(texto)
        res["status"] = "ok"
        res["lidos"] = lidos
    res.update(versao=2, assinatura=assinatura, analisado_em=datetime.now().isoformat())
    cache[chave] = res
    return res
