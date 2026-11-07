"""Consulta no CNES (dados abertos do Ministério da Saúde) quais estabelecimentos com centro cirúrgico
existem em cada município: hospitais públicos, filantrópicos (Santas Casas) e clínicas de olhos.

Resultado em cache_estrutura.json (renovado a cada 30 dias).
"""
import json, os, re, subprocess, time, unicodedata
from datetime import datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "cache_estrutura.json")
UF_COD = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22, "CE": 23,
          "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
          "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}
TIPOS = {5: "Hospital geral", 7: "Hospital especializado", 15: "Unidade mista", 62: "Hospital-dia",
         36: "Clínica especializada", 4: "Policlínica", 39: "Serviço de diagnóstico", 20: "Pronto-socorro",
         21: "Pronto-socorro especializado", 22: "Consultório", 73: "Pronto atendimento"}
RE_OLHO = re.compile(r"olho|oftalm|vis[aã]o|ocul|retina|catarat|optic|[oó]ptica|eye", re.I)


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower().strip()


def ibge_de(municipio, uf, municipios):
    """municipios = dict ibge7 -> [nome, lat, lon]. Retorna ibge6 (str) ou None."""
    cod = UF_COD.get((uf or "").upper())
    alvo = _sem_acento(municipio)
    if not cod or not alvo:
        return None
    for ib, v in municipios.items():
        if ib.startswith(str(cod)) and _sem_acento(v[0]) == alvo:
            return ib[:6]
    return None


def _natureza(cod):
    c = str(cod or "")
    if c.startswith("1"):
        return "público"
    if c.startswith("3"):
        return "filantrópico"
    if c.startswith("2"):
        return "privado"
    return ""


def _consulta(ibge6):
    est, off = [], 0
    while off < 200:
        u = (f"https://apidadosabertos.saude.gov.br/cnes/estabelecimentos?codigo_municipio={ibge6}"
             f"&estabelecimento_possui_centro_cirurgico=1&limit=20&offset={off}")
        d = None
        for i in range(3):
            r = subprocess.run(["curl", "-s", "-m", "40", u], capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
                break
            except Exception:
                time.sleep(2 + 2 * i)
        if d is None:
            return None
        lote = d.get("estabelecimentos", [])
        for e in lote:
            nome = e.get("nome_fantasia") or e.get("nome_razao_social") or ""
            tipo = e.get("codigo_tipo_unidade")
            est.append({
                "cnes": e.get("codigo_cnes"), "nome": nome.title(), "tipo": TIPOS.get(tipo, f"Tipo {tipo}"),
                "hosp": tipo in (5, 7, 15, 62) or bool(e.get("estabelecimento_possui_atendimento_hospitalar")),
                "nat": _natureza(e.get("descricao_natureza_juridica_estabelecimento")),
                "olho": bool(RE_OLHO.search(nome + " " + (e.get("nome_razao_social") or ""))),
                "sus": e.get("estabelecimento_faz_atendimento_ambulatorial_sus") == "SIM",
                "tel": e.get("numero_telefone_estabelecimento") or "",
            })
        if len(lote) < 20:
            break
        off += 20
    return est


def carregar():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def salvar(c):
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def estrutura(ibge6, cache, dias=30):
    if not ibge6:
        return None
    c = cache.get(ibge6)
    if c and c.get("data", "") >= (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d"):
        return c
    est = _consulta(ibge6)
    if est is None:
        return c
    # ordem: hospitais públicos, filantrópicos, clínicas de olhos, resto
    peso = lambda e: (0 if e["hosp"] and e["nat"] == "público" else 1 if e["hosp"] and e["nat"] == "filantrópico"
                      else 2 if e["olho"] else 3 if e["hosp"] else 4)
    est.sort(key=peso)
    c = {"data": datetime.now().strftime("%Y-%m-%d"), "est": est[:15], "total": len(est)}
    cache[ibge6] = c
    return c


def resumo(c):
    """Frase curta + contagens para o painel."""
    if not c:
        return None
    est = c.get("est", [])
    pub = [e for e in est if e["hosp"] and e["nat"] == "público"]
    fil = [e for e in est if e["hosp"] and e["nat"] == "filantrópico"]
    olho = [e for e in est if e["olho"]]
    priv = [e for e in est if e["hosp"] and e["nat"] == "privado"]
    return {"publico": len(pub), "filantropico": len(fil), "olho": len(olho), "privado": len(priv),
            "total": c.get("total", len(est)), "est": est, "data": c.get("data")}
