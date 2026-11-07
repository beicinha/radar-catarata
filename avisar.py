"""Avisa por e-mail e WhatsApp quando o Radar encontra licitações novas de catarata.

Lê o dados.json gerado pelo coletor.py, seleciona os itens relevantes que ainda
não foram avisados e guarda os avisados em avisados.json (para não repetir o
aviso entre a rodada das 7h e a das 17h).

Configuração por variáveis de ambiente (no GitHub ficam em "Secrets"):
  GMAIL_USER          conta Gmail que envia (ex.: rafaelmqbarbosa@gmail.com)
  GMAIL_APP_PASSWORD  "senha de app" do Google (16 letras), não a senha normal
  EMAIL_TO            quem recebe (se vazio, usa GMAIL_USER)
  CALLMEBOT_PHONE     celular com DDI, ex.: +5517991358557
  CALLMEBOT_APIKEY    chave que o robô CallMeBot mandou no WhatsApp
  PAINEL_URL          (opcional) link do painel para abrir no celular

Uso: python3 avisar.py            (envia, se houver novidade)
     python3 avisar.py --teste    (só mostra na tela o que enviaria; não grava nada)
"""
import json, os, re, smtplib, sys, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

AQUI = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(AQUI, f)
AGORA = datetime.now(timezone(timedelta(hours=-3)))
HOJE = AGORA.strftime("%Y-%m-%d")
DESDE = (AGORA - timedelta(days=2)).strftime("%Y-%m-%d")  # janela para itens "novos"

RE_CIRURGIA = re.compile(r"catarat|facoem|facectom|intraocular|cirurgi|mutir[aã]o|multir[aã]o|pter[ií]gio", re.I)
RE_FORA = re.compile(r"cataratas do igua|turis|passeio|ingresso|obra|constru|pavimenta|ve[ií]culo|"
                     r"aquisi[cç][aã]o|[oó]culos|lentes de contato|equipamento|medicamento|\bkits?\b|insumo|"
                     r"material (m[eé]dico|hospitalar|de consumo)|fornecimento de", re.I)


def relevante(i):
    texto = f'{i.get("objeto") or ""} {i.get("orgao") or ""}'
    if i.get("categoria") == "Material/compra" or RE_FORA.search(texto) or i.get("vencedores"):
        return False
    enc = (i.get("encerramento") or "")[:10]
    if enc and enc < HOJE:
        return False
    if i.get("categoria") == "Catarata":
        return True
    return i.get("categoria") in ("Oftalmologia", "Chamamento médico") and bool(RE_CIRURGIA.search(texto))


def ordem(i):
    return (i.get("categoria") != "Catarata", i.get("uf") not in ("SP", "MG", "GO"),
            i.get("dist_km") if i.get("dist_km") is not None else 99999)


def data_br(s):
    s = (s or "")[:10]
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if len(s) == 10 else "sem prazo informado"


def reais(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def linha(i):
    partes = [f'{i.get("municipio") or "?"}/{i.get("uf") or "?"}']
    faco = (i.get("faco") or {}).get("valor")
    if faco:
        partes.append(f"faco {reais(faco)}")
    partes.append(f'prazo {data_br(i.get("encerramento"))}' if i.get("encerramento") else "sem prazo informado")
    if i.get("dist_km") is not None:
        partes.append(f'{i["dist_km"]} km')
    return " · ".join(partes)


def enviar_email(novos, texto):
    user, senha = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and senha):
        print("e-mail não configurado (faltam GMAIL_USER/GMAIL_APP_PASSWORD)")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[Radar Catarata] {len(novos)} caso(s) novo(s) – {data_br(HOJE)}"
    msg["From"], msg["To"] = user, os.environ.get("EMAIL_TO") or user
    msg.set_content(texto)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, senha.replace(" ", ""))
        s.send_message(msg)
    print("e-mail enviado")
    return True


def enviar_whatsapp(texto):
    fone, chave = os.environ.get("CALLMEBOT_PHONE"), os.environ.get("CALLMEBOT_APIKEY")
    if not (fone and chave):
        print("whatsapp não configurado (faltam CALLMEBOT_PHONE/CALLMEBOT_APIKEY)")
        return False
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": fone, "text": texto, "apikey": chave})
    try:
        r = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
        ok = "queued" in r.lower() or "sent" in r.lower()
        print("whatsapp:", "enviado" if ok else re.sub(r"<[^>]+>", " ", r)[:200])
        return ok
    except Exception as e:
        print("whatsapp falhou:", e)
        return False


def main():
    teste = "--teste" in sys.argv
    dados = json.load(open(P("dados.json"), encoding="utf-8"))
    try:
        avisados = json.load(open(P("avisados.json"), encoding="utf-8"))
    except (OSError, ValueError):
        avisados = {}
    novos = sorted([i for i in dados.get("itens", [])
                    if (i.get("primeira_vez") or "") >= DESDE and i.get("id") not in avisados and relevante(i)],
                   key=ordem)
    print(f"{len(novos)} casos novos relevantes ({HOJE})")
    if not novos:
        return
    painel = os.environ.get("PAINEL_URL", "")

    corpo = [f"O Radar Catarata encontrou {len(novos)} caso(s) novo(s) ({data_br(HOJE)}):", ""]
    for n, i in enumerate(novos[:15], 1):
        corpo += [f"{n}. {linha(i)}", f'   {i.get("orgao") or ""}', f'   {(i.get("objeto") or "")[:300]}',
                  f'   Fonte: {i.get("fonte")} – {i.get("link")}', ""]
    if len(novos) > 15:
        corpo.append(f"... e mais {len(novos) - 15} no painel.")
    if painel:
        corpo += ["", f"Painel completo (abre no celular): {painel}"]
    texto = "\n".join(corpo)

    zap = [f"Radar Catarata: {len(novos)} novo(s)"] + [f"{n}. {linha(i)}" for n, i in enumerate(novos[:5], 1)]
    if len(novos) > 5:
        zap.append(f"+{len(novos) - 5} no e-mail")
    if painel:
        zap.append(painel)
    zap = "\n".join(zap)

    if teste:
        print("---- E-MAIL ----\n" + texto + "\n---- WHATSAPP ----\n" + zap)
        return

    email_ok = enviar_email(novos, texto)
    zap_ok = enviar_whatsapp(zap)
    if email_ok or zap_ok:
        for i in novos:
            avisados[i["id"]] = HOJE
        json.dump(avisados, open(P("avisados.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
