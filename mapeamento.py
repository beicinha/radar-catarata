"""Mapeamento de mercado: contratos e atas de catarata já assinados (PNCP).

Não são oportunidades abertas e não geram alerta. Servem para saber quem atende cada
órgão, por quanto e até quando — contratos perto do fim indicam nova contratação em breve.
"""
import time
import urllib.parse
from datetime import datetime, timedelta

import regras

FONTE = "Mapeamento"
NOME_STATUS = "PNCP – contratos e atas assinados (mapeamento)"
TERMOS = ["catarata", "facoemulsificação", "facectomia", "cirurgias oftalmológicas"]
TIPOS = [("contrato", "Contrato"), ("ata", "Ata de registro de preços")]
MAX_PAGINAS = 5               # 100 por página, do mais recente para o mais antigo
PUBLICADO_DESDE_DIAS = 540    # publicações no PNCP nos últimos ~18 meses
VIGENCIA_TOLERANCIA_DIAS = 60 # mantém contratos encerrados há até 60 dias (renovação em curso)
MAX_DETALHES = 120            # consultas de fornecedor por rodada (ficam em cache)


def _partes(item_url):
    p = item_url.strip("/").split("/")
    return p[1:]  # contratos: cnpj, ano, seq | atas: cnpj, ano, seqCompra, seqAta


def coletar(cjson, cache, hoje, dist_km, vistos, pausa=0.6):
    h = datetime.fromisoformat(hoje)
    desde = (h - timedelta(days=PUBLICADO_DESDE_DIAS)).strftime("%Y-%m-%d")
    vig_min = (h - timedelta(days=VIGENCIA_TOLERANCIA_DIAS)).strftime("%Y-%m-%d")
    brutos, falhas, consultas = {}, 0, 0
    for tipo, _ in TIPOS:
        for termo in TERMOS:
            for pag in range(1, MAX_PAGINAS + 1):
                u = ("https://pncp.gov.br/api/search/?q=" + urllib.parse.quote(termo) +
                     f"&tipos_documento={tipo}&ordenacao=-data&pagina={pag}&tam_pagina=100")
                consultas += 1
                try:
                    d = cjson(u, {}) or {}
                except Exception:
                    falhas += 1
                    break
                itens = d.get("items", [])
                for it in itens:
                    a = brutos.setdefault(it.get("item_url"), dict(it, _tipo=tipo, _termos=[]))
                    if termo not in a["_termos"]:
                        a["_termos"].append(termo)
                time.sleep(pausa)
                antigos = [it for it in itens if (it.get("data_publicacao_pncp") or "")[:10] < desde]
                if len(itens) < 100 or len(antigos) == len(itens):
                    break
    if consultas and falhas == consultas:
        raise RuntimeError("PNCP (contratos/atas) sem resposta")
    out, detalhes = [], 0
    for url, it in brutos.items():
        desc = it.get("description") or ""
        if (it.get("data_publicacao_pncp") or "")[:10] < desde or it.get("cancelado"):
            continue
        fim = (it.get("data_fim_vigencia") or "")[:10]
        if fim and fim < vig_min:
            continue
        cat = regras.classificar(desc)
        if cat not in ("Catarata", "Oftalmologia") or not regras.cirurgia_ofertada(desc):
            continue
        partes = _partes(url)
        chave = it["_tipo"] + ":" + "/".join(partes)
        c = cache.setdefault(chave, {})
        if it["_tipo"] == "contrato" and "fornecedor" not in c and detalhes < MAX_DETALHES and len(partes) == 3:
            try:
                det = cjson("https://pncp.gov.br/api/pncp/v1/orgaos/{}/contratos/{}/{}".format(*partes), {}) or {}
                c["fornecedor"] = det.get("nomeRazaoSocialFornecedor") or ""
                c["cnpj_fornecedor"] = det.get("niFornecedor") or ""
                c["valor"] = det.get("valorGlobal")
                c["fim"] = (det.get("dataVigenciaFim") or "")[:10]
            except Exception:
                pass
            detalhes += 1
            time.sleep(pausa)
        fim = c.get("fim") or fim
        if fim and fim < vig_min:
            continue
        iid = "map:" + chave
        primeira = vistos.get(iid) or hoje
        vistos[iid] = primeira
        rotulo = dict(TIPOS)[it["_tipo"]]
        link = "https://pncp.gov.br/app/" + ("contratos/" if it["_tipo"] == "contrato" else "atas/") + "/".join(partes)
        forn = c.get("fornecedor") or ""
        out.append({
            "id": iid, "fonte": FONTE, "categoria": cat, "tipo_mapa": rotulo,
            "uf": it.get("uf") or "", "municipio": it.get("municipio_nome") or "",
            "orgao": it.get("orgao_nome") or "", "modalidade": f"{rotulo} · {it.get('modalidade_licitacao_nome') or ''}".strip(" ·"),
            "objeto": " ".join(desc.split())[:600], "valor_total": c.get("valor") or it.get("valor_global"),
            "faco": None, "abertura": "", "encerramento": "",
            "assinatura": (it.get("data_assinatura") or "")[:10], "vigencia_fim": fim,
            "publicado": (it.get("data_publicacao_pncp") or "")[:10],
            "vencedores": [forn] if forn else [], "fornecedor_cnpj": c.get("cnpj_fornecedor") or "",
            "docs_resultado": [], "plataforma": "", "link": link,
            "dist_km": dist_km(it.get("codigo_ibge")), "primeira_vez": primeira, "termos": it["_termos"],
            "credenciamento_aberto": "credencia" in regras.normalizar(f"{desc} {it.get('modalidade_licitacao_nome')}"),
        })
    status = {"nome": NOME_STATUS, "ok": True, "itens": len(out)}
    if falhas:
        status["parcial"] = f"{falhas} de {consultas} consultas sem resposta"
    return out, status
