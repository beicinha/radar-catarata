"""Avisa por e-mail e WhatsApp quando o Radar encontra licitações novas de catarata.

Lê o dados.json gerado pelo coletor.py, seleciona os itens relevantes que ainda
têm pendências por canal e guarda as tentativas em avisados.json. A aceitação
pelo CallMeBot não comprova entrega. Há até três tentativas aceitas, espaçadas
por 24 horas, enquanto não existir confirmação. --teste não envia nem grava.

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
import json, os, re, smtplib, sys, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

AQUI = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(AQUI, f)
AGORA = datetime.now(timezone(timedelta(hours=-3)))
HOJE = AGORA.strftime("%Y-%m-%d")

from regras import cirurgia_ofertada, credenciamento, diario_contratacao


def relevante(i):
    texto = i.get("objeto") or ""
    if i.get("categoria") == "Material/compra" or not cirurgia_ofertada(texto):
        return False
    if i.get("vencedores") and not credenciamento(i):
        return False
    enc = i.get("encerramento") or ""
    if enc and enc[:10] < HOJE:
        return False
    if len(enc) > 10:
        try:
            prazo = datetime.fromisoformat(enc)
            if prazo.tzinfo is None:
                prazo = prazo.replace(tzinfo=AGORA.tzinfo)
            if prazo < AGORA:
                return False
        except ValueError:
            return False
    if i.get("fonte") == "Diário Oficial" and not diario_contratacao(texto):
        return False
    return True


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
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as s:
        s.login(user, senha.replace(" ", ""))
        s.send_message(msg)
    print("e-mail enviado")
    return True


def interpretar_whatsapp(resposta):
    # Nunca registrar resposta bruta: pode conter telefone, chave e URL.
    t = re.sub(r"<[^>]+>", " ", resposta).lower()
    if re.search(r"error|failed|not sent|not activated|invalid|unauthorized|not allowed|not authorized", t):
        if re.search(r"apikey|api key|key.*invalid|invalid.*key|not activated|not authorized|not allowed", t):
            return "erro_configuracao"
        if re.search(r"limit|too many|quota", t):
            return "limite_servico"
        return "erro_servico"
    if re.search(r"\bqueued\b|message.{0,50}\bsent\b|successfully sent", t):
        return "aceito_sem_confirmacao"
    return "resposta_desconhecida"


def enviar_whatsapp(texto):
    fone = re.sub(r"\D", "", os.environ.get("CALLMEBOT_PHONE", ""))
    chave = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if not (fone and chave):
        return "nao_configurado"
    if not 10 <= len(fone) <= 15:
        return "erro_configuracao"
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": "+" + fone, "text": texto, "apikey": chave})
    try:
        with urllib.request.urlopen(url, timeout=45) as resposta:
            return interpretar_whatsapp(resposta.read(65536).decode("utf-8", "replace"))
    except urllib.error.HTTPError as erro:
        # A exceção pode incluir a URL com a chave. Mostrar só o código HTTP.
        return f"http_{erro.code}"
    except Exception:
        return "falha_conexao"


def salvar_json(nome, dados):
    temporario = P(nome + ".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, P(nome))


def migrar_historico(historico):
    for iid, valor in list(historico.items()):
        if isinstance(valor, str):
            # O controle antigo não prova entrega no WhatsApp. Não repetir e-mail.
            historico[iid] = {"email": {"status": "enviado", "data": valor},
                              "whatsapp": {"status": "pendente", "tentativas": 0}}
    return historico


def pendente(registro, canal):
    estado = registro.get(canal) or {}
    if canal == "email":
        return estado.get("status") != "enviado"
    if estado.get("status") == "confirmado_pelo_usuario":
        return False
    if estado.get("status") == "aceito_sem_confirmacao":
        if estado.get("aceitas", 0) >= 3:
            return False
        try:
            ultima = datetime.fromisoformat(estado["ultima_tentativa"])
            return AGORA - ultima >= timedelta(hours=24)
        except (KeyError, ValueError, TypeError):
            return True
    return True


def textos(itens, painel):
    corpo = [f"Radar Catarata: {len(itens)} oportunidade(s) para conferir ({data_br(HOJE)}).", ""]
    for n, i in enumerate(itens, 1):
        corpo += [f"{n}. {linha(i)}", i.get("orgao") or "", (i.get("objeto") or "")[:600],
                  f'Fonte: {i.get("fonte")} – {i.get("link")}', ""]
    if painel:
        corpo += [f"Painel: {painel}"]
    corpo += ["", "Confira o edital antes de concluir sobre habilitação.",
              "WhatsApp: a aceitação pelo serviço não confirma a entrega ao celular."]
    zap = [f"Radar Catarata: {len(itens)} oportunidade(s)"]
    zap += [f"{n}. {linha(i)}" for n, i in enumerate(itens, 1)]
    if painel:
        zap.append(painel)
    return "\n".join(corpo), "\n".join(zap)


def main():
    teste = "--teste" in sys.argv
    if "--teste-whatsapp" in sys.argv:
        mensagem = "Radar Catarata: teste de funcionamento do WhatsApp."
        if teste:
            print(mensagem)
            return
        status = enviar_whatsapp(mensagem)
        print(f"WhatsApp: {status}. A entrega precisa ser confirmada no celular.")
        if status != "aceito_sem_confirmacao":
            raise SystemExit(1)
        return
    with open(P("dados.json"), encoding="utf-8") as arquivo:
        dados = json.load(arquivo)
    try:
        with open(P("avisados.json"), encoding="utf-8") as arquivo:
            avisados = json.load(arquivo)
        if not isinstance(avisados, dict):
            raise ValueError("Formato inválido de avisados.json")
    except FileNotFoundError:
        avisados = {}
    # Histórico ilegível precisa de correção; não apagar para depois reenviar tudo.
    avisados = migrar_historico(avisados)
    candidatos = sorted([i for i in dados.get("itens", []) if relevante(i)], key=ordem)
    painel = os.environ.get("PAINEL_URL", "https://beicinha.github.io/radar-catarata/")
    saude = {"atualizado": AGORA.isoformat(), "canais": {}}
    for canal, limite in (("email", 15), ("whatsapp", 5)):
        pendencias = [i for i in candidatos if pendente(avisados.get(i["id"], {}), canal)]
        lote = pendencias[:limite]
        print(f"{canal}: {len(pendencias)} pendente(s); lote de {len(lote)}")
        if not lote:
            anteriores = [v.get(canal, {}) for v in avisados.values()]
            estado = "aceito_sem_confirmacao" if canal == "whatsapp" and any(
                v.get("status") == "aceito_sem_confirmacao" for v in anteriores) else "sem_pendencias"
            saude["canais"][canal] = {"status": estado, "pendentes": 0}
            continue
        email, zap = textos(lote, painel)
        if teste:
            print(email if canal == "email" else zap)
            continue
        try:
            status = ("enviado" if enviar_email(lote, email) else "nao_configurado") if canal == "email" else enviar_whatsapp(zap)
        except Exception:
            # A falha de um canal não interrompe o outro nem expõe credenciais.
            status = "falha_envio"
        print(f"{canal}: {status}")
        if canal == "whatsapp" and status == "aceito_sem_confirmacao":
            print("::warning::WhatsApp aceito pelo serviço; entrega ao celular não confirmada.")
        elif status != "enviado":
            print(f"::warning::{canal}: {status}; será tentado novamente.")
        for i in lote:
            registro = avisados.setdefault(i["id"], {})
            anterior = registro.get(canal) or {}
            registro[canal] = {"status": status, "ultima_tentativa": AGORA.isoformat(),
                               "tentativas": anterior.get("tentativas", 0) + 1,
                               "aceitas": anterior.get("aceitas", 0) + int(status == "aceito_sem_confirmacao")}
        # Guardar cada canal imediatamente, inclusive quando o outro falhar.
        salvar_json("avisados.json", avisados)
        saude["canais"][canal] = {"status": status, "pendentes": len(pendencias), "lote": len(lote)}
    if not teste:
        salvar_json("status_avisos.json", saude)
        erros = [e for e in saude["canais"].values()
                 if e["status"] not in ("enviado", "aceito_sem_confirmacao", "sem_pendencias")]
        if erros:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
