"""Plataformas privadas de pregão/credenciamento (consulta pública, sem login e sem captcha).

- Portal de Compras Públicas: API pública de busca por palavra no objeto.
- BLL Compras e BNC Compras: a busca por filtros exige captcha, então NÃO é usada.
  Lemos só a lista pública dos 100 processos mais recentes e abrimos a página
  pública de cada processo novo para ler o objeto. Como o radar roda de hora em hora,
  a lista cobre o intervalo entre as rodadas.
- Licitanet (bloqueia robôs) e Licitações-e/BB (captcha) ficam de fora.

Itens que já aparecem no PNCP são descartados para não avisar duas vezes.
"""
import hashlib
import html
import json
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone

import regras

BRT = timezone(timedelta(hours=-3))
FONTE = "Plataforma privada"
PCP_API = "https://compras.api.portaldecompraspublicas.com.br/v2/licitacao/processos"
PCP_SITE = "https://www.portaldecompraspublicas.com.br/processos"
PCP_TERMOS = ["catarata", "facoemulsifica", "oftalmol"]
PCP_MAX_PAGINAS = 25          # 10 itens por página; resultados vêm dos mais recentes
PCP_IDADE_MAX_DIAS = 400      # para de paginar quando a página inteira é mais antiga que isso
PCP_FINAIS = re.compile(r"finalizad|desert|fracassad|revogad|anulad|cancelad|suspens|homologad|adjudicad", re.I)
LISTAS = [("BLL Compras", "https://bllcompras.com"), ("BNC Compras", "https://bnccompras.com")]
LISTA_FINAIS = {"DESERTO", "HOMOLOGADO", "ADJUDICADO", "CANCELADO", "FRACASSADO", "SUSPENSO",
                "REVOGADO", "ANULADO", "RESULTADO FINAL"}
MAX_PAGINAS_NOVAS = 120       # limite de páginas de processo abertas por plataforma em cada rodada
CACHE_DIAS = 90


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower().strip()


def _num(s):
    """'004/2026' -> ('4', '2026'); '66' + ano -> ('66', ano)."""
    m = re.search(r"0*(\d+)\s*/\s*(\d{4})", s or "")
    return (m.group(1), m.group(2)) if m else None


UF_COD = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22, "CE": 23,
          "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
          "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}


def indice_municipios(mun):
    idx = {}
    for ib, v in mun.items():
        idx[(ib[:2], _sem_acento(v[0]))] = ib
    return idx


def ibge7(cidade, uf, idx):
    cod = UF_COD.get((uf or "").upper())
    return idx.get((str(cod), _sem_acento(cidade))) if cod else None


def chaves_pncp(pncp_itens, cache_pncp):
    """Identificadores dos editais que já estão no PNCP: código do Portal de Compras e (UF, município, número, ano)."""
    codigos, numeros = set(), set()
    for i in pncp_itens:
        chave = i.get("id", "").split(":", 1)[-1]
        q = (cache_pncp.get(chave) or {}).get("consulta") or {}
        link = (q.get("linkSistemaOrigem") or i.get("plataforma") or "").strip()
        m = re.search(r"portaldecompraspublicas\.com\.br/processos/.*-(\d+)/?$", link, re.I)
        if m:
            codigos.add(m.group(1))
        n = str(q.get("numeroCompra") or "").lstrip("0")
        ano = str(q.get("anoCompra") or "")
        if n and ano:
            numeros.add(((i.get("uf") or "").upper(), _sem_acento(i.get("municipio")), n, ano))
    return codigos, numeros


def _iso_utc_para_brt(s):
    if not s:
        return ""
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(BRT).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return s[:16]


def _br_para_iso(s):
    m = re.match(r"(\d\d)/(\d\d)/(\d{4})(?:\s+(\d\d):(\d\d))?", s or "")
    if not m:
        return ""
    d, mo, a, h, mi = m.groups()
    return f"{a}-{mo}-{d}" + (f"T{h}:{mi}" if h else "")


def _categoria(texto):
    cat = regras.classificar(texto)
    return cat if cat in ("Catarata", "Oftalmologia") else None


def _item(iid, nome_plat, cat, uf, cidade, orgao, modalidade, objeto, valor, abertura, encerramento,
          publicado, link, ibge, dist_km, primeira, termos):
    return {"id": iid, "fonte": FONTE, "plataforma_nome": nome_plat, "categoria": cat, "uf": uf or "",
            "municipio": cidade or "", "orgao": orgao or "", "modalidade": modalidade or "",
            "objeto": re.sub(r"\s+", " ", objeto or "").strip()[:600], "valor_total": valor, "faco": None,
            "abertura": abertura or "", "encerramento": encerramento or "", "publicado": publicado or "",
            "vencedores": [], "docs_resultado": [], "plataforma": link, "link": link,
            "dist_km": dist_km(ibge) if ibge else None, "primeira_vez": primeira, "termos": termos}


# ------------------------------------------------------------- Portal de Compras Públicas
def coletar_pcp(cjson, cache, hoje, idx, dist_km, pausa=0.4):
    achados = {}
    limite = (datetime.now(BRT) - timedelta(days=PCP_IDADE_MAX_DIAS)).strftime("%Y-%m-%d")
    for termo in PCP_TERMOS:
        for pag in range(1, PCP_MAX_PAGINAS + 1):
            d = cjson(f"{PCP_API}?pagina={pag}&objeto={urllib.parse.quote(termo)}")
            res = (d or {}).get("result") or []
            for r in res:
                a = achados.setdefault(str(r.get("codigoLicitacao")), r)
                a.setdefault("_termos", set()).add(termo)
            if not res or pag >= ((d or {}).get("pageCount") or 0):
                break
            if all((r.get("dataHoraPublicacao") or "9")[:10] < limite for r in res):
                break
            time.sleep(pausa)
    out = []
    for cod, r in achados.items():
        status = ((r.get("statusProcessoPublico") or r.get("status") or {}).get("descricao") or "")
        if PCP_FINAIS.search(status):
            continue
        texto = r.get("resumo") or ""
        cat = _categoria(texto)
        if not cat:
            continue
        enc = _iso_utc_para_brt(r.get("dataHoraFinalPropostas") or r.get("dataHoraInicioLances"))
        if enc and enc[:10] < hoje:
            continue
        u = r.get("unidadeCompradora") or {}
        tipo = r.get("tipoLicitacao") or {}
        num = r.get("numero") or ""
        chave = "pcp:" + cod
        c = cache.setdefault(chave, {})
        c.setdefault("primeira_vez", hoje)
        c["visto"] = hoje
        c["num"] = _num(num)
        c["local"] = [(u.get("uf") or "").upper(), _sem_acento(u.get("cidade"))]
        out.append(_item("priv:" + chave, "Portal de Compras Públicas", cat, u.get("uf"), u.get("cidade"),
                         u.get("nomeUnidadeCompradora") or r.get("razaoSocial"),
                         f"{tipo.get('tipoLicitacao') or ''} {num}".strip() + (f" · {status}" if status else ""),
                         texto, None, _iso_utc_para_brt(r.get("dataHoraInicioPropostas")), enc,
                         (r.get("dataHoraPublicacao") or "")[:10], PCP_SITE + (r.get("urlReferencia") or ""),
                         ibge7(u.get("cidade"), u.get("uf"), idx), dist_km, c["primeira_vez"],
                         sorted(r.get("_termos") or [])))
    return out


# ------------------------------------------------------------- BLL / BNC (lista pública)
RE_LINHA = re.compile(r"<tr>\s*<td class=\"tablebutton\">([\s\S]*?)</tr>", re.I)


def ler_lista(pagina_html, base):
    corpo = re.search(r'id="tableProcessDataBody"[\s\S]*?</tbody>', pagina_html or "")
    if not corpo:
        raise RuntimeError("Lista pública sem tabela de processos")
    linhas = []
    for bloco in RE_LINHA.findall(corpo.group(0)):
        href = re.search(r'href="(/Process/ProcessView\?[^"]+)"', bloco)
        cels = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", bloco)]
        if not href or len(cels) < 7:
            continue
        orgao, numero, modalidade, local, status, publicado, disputa = cels[-7:]
        m = re.match(r"(.*)-([A-Z]{2})$", local)
        cidade, uf = (m.group(1).strip(), m.group(2)) if m else (local, "")
        linhas.append({"link": base + html.unescape(href.group(1)), "orgao": orgao, "numero": numero,
                       "modalidade": modalidade, "cidade": cidade, "uf": uf, "status": status.upper(),
                       "publicado": _br_para_iso(publicado)[:10], "disputa": _br_para_iso(disputa)})
    return linhas


def ler_processo(pagina_html):
    obj = re.search(r'id="ProductOrService"[^>]*>([\s\S]*?)</textarea>', pagina_html or "")
    if not obj:
        raise RuntimeError("Página do processo sem objeto")
    val = re.search(r'id="TotalBaseValue"[^>]*value="([^"]*)"', pagina_html)
    valor = None
    if val:
        v = re.sub(r"[^\d,]", "", val.group(1)).replace(",", ".")
        try:
            valor = round(float(v), 2) if v else None
        except ValueError:
            valor = None
    return html.unescape(obj.group(1)).strip(), valor


def coletar_lista(nome, base, curl, cache, hoje, idx, dist_km, pausa=0.5):
    linhas = ler_lista(curl(base + "/Process/ProcessSearchPublic?param1=0"), base)
    abertas = 0
    for ln in linhas:
        chave = "lista:" + hashlib.sha1(f"{base}|{ln['orgao']}|{ln['numero']}|{ln['modalidade']}".encode()).hexdigest()[:16]
        c = cache.get(chave)
        if c is None:
            if abertas >= MAX_PAGINAS_NOVAS:
                continue
            abertas += 1
            try:
                objeto, valor = ler_processo(curl(ln["link"]))
            except RuntimeError:
                continue          # tenta de novo na próxima rodada
            time.sleep(pausa)
            c = cache[chave] = {"primeira_vez": hoje, "plataforma": nome, "objeto": objeto[:800], "valor": valor}
        c.update({"visto": hoje, "link": ln["link"], "orgao": ln["orgao"], "numero": ln["numero"],
                  "modalidade": ln["modalidade"], "cidade": ln["cidade"], "uf": ln["uf"], "status": ln["status"],
                  "publicado": ln["publicado"], "disputa": ln["disputa"], "plataforma": nome,
                  "num": _num(ln["numero"]), "local": [ln["uf"], _sem_acento(ln["cidade"])]})
    return len(linhas), abertas


def itens_lista(cache, hoje, idx, dist_km):
    """Monta os itens relevantes a partir do cache (inclusive os que já saíram da lista dos 100 mais recentes)."""
    out = []
    for chave, c in cache.items():
        if not chave.startswith("lista:") or c.get("status") in LISTA_FINAIS:
            continue
        cat = _categoria(c.get("objeto") or "")
        if not cat:
            continue
        enc = c.get("disputa") or ""
        if enc and enc[:10] < hoje:
            continue
        out.append(_item("priv:" + chave, c.get("plataforma"), cat, c.get("uf"), (c.get("cidade") or "").title(),
                         c.get("orgao"), f"{(c.get('modalidade') or '').capitalize()} {c.get('numero') or ''}".strip()
                         + (f" · {c['status'].capitalize()}" if c.get("status") else ""),
                         c.get("objeto"), c.get("valor"), "", enc, c.get("publicado"), c.get("link"),
                         ibge7(c.get("cidade"), c.get("uf"), idx), dist_km, c.get("primeira_vez", hoje), []))
    return out


def podar(cache, hoje):
    limite = (datetime.fromisoformat(hoje) - timedelta(days=CACHE_DIAS)).strftime("%Y-%m-%d")
    for k in [k for k, c in cache.items() if (c.get("visto") or c.get("primeira_vez") or "") < limite
              and (c.get("disputa") or "")[:10] < hoje]:
        del cache[k]


def sem_duplicar(itens, cache, codigos_pncp, numeros_pncp):
    out = []
    for i in itens:
        chave = i["id"].split(":", 1)[1]
        c = cache.get(chave) or {}
        if chave.startswith("pcp:") and chave[4:] in codigos_pncp:
            continue
        num, local = c.get("num"), c.get("local") or ["", ""]
        if num and (local[0], local[1], num[0], num[1]) in numeros_pncp:
            continue
        out.append(i)
    return out


def coletar(curl, cjson, cache, hoje, mun, dist_km, pncp_itens, cache_pncp, anteriores):
    """Retorna (itens, status). Fonte com falha preserva os itens anteriores dessa plataforma."""
    idx = indice_municipios(mun)
    itens, status = [], []
    nome_pcp = "Portal de Compras Públicas"
    try:
        itens += coletar_pcp(cjson, cache, hoje, idx, dist_km)
        status.append({"nome": nome_pcp, "ok": True})
    except Exception:
        itens += [i for i in anteriores if i.get("plataforma_nome") == nome_pcp]
        status.append({"nome": nome_pcp, "ok": False, "erro": "Fonte indisponível; dados anteriores preservados"})
    for nome, base in LISTAS:
        try:
            n, abertas = coletar_lista(nome, base, curl, cache, hoje, idx, dist_km)
            status.append({"nome": nome, "ok": True})
            print(f"  {nome}: {n} processos na lista pública, {abertas} páginas novas lidas", flush=True)
        except Exception:
            status.append({"nome": nome, "ok": False, "erro": "Fonte indisponível; dados anteriores preservados"})
    itens += itens_lista(cache, hoje, idx, dist_km)
    podar(cache, hoje)
    codigos, numeros = chaves_pncp(pncp_itens, cache_pncp)
    itens = sem_duplicar(itens, cache, codigos, numeros)
    vistos = set()
    unicos = [i for i in itens if not (i["id"] in vistos or vistos.add(i["id"]))]
    for s in status:
        s["itens"] = sum(i.get("plataforma_nome") == s["nome"] for i in unicos)
    return unicos, status
