"""Serviço de envio de prints do contadaurna.com.br (roda no Render).

Recebe o print de um boato, devolve um código de protocolo e, se a pessoa quiser, guarda o
e-mail dela CRIPTOGRAFADO para avisar o resultado da checagem. O e-mail é apagado assim que o
aviso sai. Ninguém vê o e-mail pela página de administração: ela só mostra o protocolo.

Leia envios/README.md para o desenho de segurança e a configuração.

Rodar:  gunicorn -w 1 --threads 4 'app:criar_app()'
"""
import base64
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000  # recusa "bombas" de descompressão

AQUI = os.path.dirname(os.path.abspath(__file__))
TAMANHO_MAX = 10 * 1024 * 1024
FORMATOS = {"JPEG", "PNG", "WEBP"}
LADO_MAX = 4000
PROTOCOLO_RE = re.compile(r"^[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
RESULTADOS = {"publicado", "procede", "descartado"}
FILA_MAX = 500            # envios guardados; acima disso, novos envios são recusados
LIMITE_GB_PADRAO = 8      # espaço máximo no R2 (o plano grátis vai até 10 GB); muda com a variável LIMITE_GB
CACHE_USO_SEG = 60        # a consulta pública de capacidade relê o balde no máximo 1 vez por minuto
ENVIOS_POR_HORA_IP = 5
ENVIOS_POR_HORA_TOTAL = 120
FALHAS_ADMIN_POR_HORA = 10
CONSULTAS_POR_HORA_IP = 60       # consultas e pedidos de apagar por protocolo
CONSULTAS_POR_HORA_TOTAL = 1500  # teto geral: cada consulta é uma leitura paga no R2 acima da cota grátis

ASSUNTO = "Seu envio ao Conta da Urna ({p})"
TEXTOS = {
    "publicado": "O boato que você enviou foi checado e o parecer está publicado:\n{link}",
    "procede": "Checamos o que você enviou e, pelo que apuramos, a informação procede. Por isso não publicamos um parecer de fake news.{extra}",
    "descartado": "O que você enviou não entrou na checagem (fora do tema, sem como verificar com dados públicos ou repetido).{extra}",
}
RODAPE = ("\n\nProtocolo: {p}\n\nEste e-mail foi enviado automaticamente. Seu endereço foi apagado "
          "logo após o envio e não fica guardado em lugar nenhum do Conta da Urna.\n\nhttps://contadaurna.com.br/")

# Versão em HTML do mesmo aviso, com a marca do site. Só estilos inline e tabelas, que é o que os
# programas de e-mail entendem. A única imagem é o ícone servido pelo próprio site.
SITE = "https://contadaurna.com.br/"
HTML_RES = {
    "publicado": ("Publicado", "Seu envio virou parecer",
                  "O boato que você enviou foi checado e o parecer já está publicado no site.", "Ler o parecer"),
    "procede": ("Procede", "A informação procede",
                "Checamos o que você enviou e, pelo que apuramos, a informação procede. "
                "Por isso não publicamos um parecer de fake news.", "Ver no site"),
    "descartado": ("Não checado", "Seu envio não entrou na checagem",
                   "O que você enviou ficou fora da checagem: fora do tema, sem como verificar "
                   "com dados públicos ou repetido.", "Ver no site"),
}
FONTE = "Arial,Helvetica,sans-serif"
FONTE_MARCA = "'Archivo Narrow','Arial Narrow',Arial,sans-serif"


def aviso_html(res, link, p):
    selo, titulo, texto, botao = HTML_RES[res]
    e = html.escape
    alvo = e(link or SITE, quote=True)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{e(titulo)}</title></head>
<body style="margin:0;padding:0;background:#f3f6f4">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f6f4"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;border:1px solid #dfe7e2">
<tr><td style="padding:22px 28px;border-bottom:4px solid #11875b">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:12px"><img src="{SITE}icone.png" width="40" height="40" alt="" style="display:block;border:0;border-radius:50%"></td>
<td style="font-family:{FONTE_MARCA};font-size:20px;font-weight:700;letter-spacing:3px;color:#14211b">CONTA <span style="color:#11875b">DA</span> URNA</td>
</tr></table></td></tr>
<tr><td style="padding:28px 28px 8px;font-family:{FONTE}">
<span style="display:inline-block;background:#dcf3e8;color:#0b5e40;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:5px 10px;border-radius:999px">{e(selo)}</span>
<h1 style="margin:16px 0 10px;font-size:24px;line-height:1.25;color:#14211b">{e(titulo)}</h1>
<p style="margin:0 0 22px;font-size:16px;line-height:1.55;color:#33443b">{e(texto)}</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="background:#11875b;border-radius:8px">
<a href="{alvo}" style="display:inline-block;padding:12px 22px;font-family:{FONTE};font-size:16px;font-weight:700;color:#ffffff;text-decoration:none">{e(botao)}</a>
</td></tr></table>
</td></tr>
<tr><td style="padding:22px 28px 26px;font-family:{FONTE}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f6f4;border-radius:8px"><tr><td style="padding:12px 16px;font-size:14px;color:#33443b">
Protocolo: <strong style="font-family:Consolas,Menlo,monospace;letter-spacing:1px;color:#14211b">{e(p)}</strong></td></tr></table>
</td></tr>
<tr><td style="padding:18px 28px 24px;border-top:1px solid #dfe7e2;font-family:{FONTE};font-size:12px;line-height:1.5;color:#5f6f66">
Este e-mail foi enviado automaticamente. Seu endereço foi apagado logo após o envio e não fica guardado em lugar nenhum do Conta da Urna.<br>
<a href="{SITE}" style="color:#0b5e40">contadaurna.com.br</a>
</td></tr>
</table></td></tr></table>
</body></html>"""


# ---------- Armazenamento: Cloudflare R2 em produção, pasta local em testes ----------
class ArmazemR2:
    def __init__(self, conta, chave, segredo, balde):
        import boto3
        from botocore.config import Config
        self.balde = balde
        self.s3 = boto3.client("s3", endpoint_url=f"https://{conta}.r2.cloudflarestorage.com",
                               aws_access_key_id=chave, aws_secret_access_key=segredo,
                               region_name="auto", config=Config(retries={"max_attempts": 3}))

    def por(self, chave, dados, tipo):
        self.s3.put_object(Bucket=self.balde, Key=chave, Body=dados, ContentType=tipo)

    def pegar(self, chave):
        try:
            return self.s3.get_object(Bucket=self.balde, Key=chave)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def apagar(self, chave):
        self.s3.delete_object(Bucket=self.balde, Key=chave)

    def listar(self, prefixo):
        return [k for k, _ in self.listar_com_tamanho(prefixo)]

    def listar_com_tamanho(self, prefixo):
        itens, pag = [], self.s3.get_paginator("list_objects_v2")
        for p in pag.paginate(Bucket=self.balde, Prefix=prefixo):
            itens += [(o["Key"], o["Size"]) for o in p.get("Contents", [])]
        return itens


class ArmazemLocal:
    """Só para testes e desenvolvimento."""
    def __init__(self, pasta):
        self.pasta = pasta

    def _c(self, chave):
        return os.path.join(self.pasta, *chave.split("/"))

    def por(self, chave, dados, tipo):
        os.makedirs(os.path.dirname(self._c(chave)), exist_ok=True)
        with open(self._c(chave), "wb") as f:
            f.write(dados)

    def pegar(self, chave):
        try:
            with open(self._c(chave), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def apagar(self, chave):
        try:
            os.remove(self._c(chave))
        except FileNotFoundError:
            pass

    def listar(self, prefixo):
        return [k for k, _ in self.listar_com_tamanho(prefixo)]

    def listar_com_tamanho(self, prefixo):
        saida = []
        for raiz, _, arqs in os.walk(self.pasta):
            for a in arqs:
                c = os.path.join(raiz, a)
                k = os.path.relpath(c, self.pasta).replace(os.sep, "/")
                if k.startswith(prefixo):
                    saida.append((k, os.path.getsize(c)))
        return saida


# ---------- Serviços externos ----------
def _post(url, dados, cabecalhos):
    req = urllib.request.Request(url, data=dados, headers=cabecalhos, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def turnstile(segredo, hosts):
    """Confere o desafio anti-robô do Cloudflare Turnstile. Não repassa o IP da pessoa."""
    def verificar(token):
        if not token or len(token) > 4096:
            return False
        try:
            _, corpo = _post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                             urllib.parse.urlencode({"secret": segredo, "response": token}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded"})
            r = json.loads(corpo)
        except Exception:
            return False
        return bool(r.get("success")) and r.get("hostname") in hosts
    return verificar


def brevo(chave_api, remetente):
    """Manda o aviso pela API transacional do Brevo: texto puro e, se houver, a versão em HTML."""
    def enviar(para, assunto, texto, html_=None):
        msg = {"sender": {"email": remetente, "name": "Conta da Urna"},
               "to": [{"email": para}], "subject": assunto, "textContent": texto}
        if html_:
            msg["htmlContent"] = html_
        corpo = json.dumps(msg).encode()
        status, _ = _post("https://api.brevo.com/v3/smtp/email", corpo,
                          {"api-key": chave_api, "Content-Type": "application/json", "Accept": "application/json"})
        return 200 <= status < 300
    return enviar


# ---------- Utilidades ----------
def novo_protocolo():
    s = base64.b32encode(secrets.token_bytes(8)).decode()[:12]  # 60 bits aleatórios
    return f"{s[:4]}-{s[4:8]}-{s[8:]}"


def agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def limpar_texto(t, n):
    t = re.sub(r"[\x00-\x1f\x7f]", " ", t or "").strip()
    return t[:n]


def reprocessar_imagem(dados):
    """Abre, confere o formato e regrava como JPEG. Isso descarta metadados (EXIF, GPS, autor)
    e qualquer conteúdo escondido no arquivo original."""
    im = Image.open(io.BytesIO(dados))
    if im.format not in FORMATOS:
        raise ValueError("formato")
    im.load()
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((LADO_MAX, LADO_MAX))
    saida = io.BytesIO()
    im.save(saida, "JPEG", quality=88)
    return saida.getvalue()


class Limitador:
    """Limite de tentativas por hora, em memória. O IP é guardado só como hash, por no máximo 1 hora."""
    def __init__(self):
        self.reg, self.trava = {}, threading.Lock()

    def permite(self, chave, limite):
        t = time.time()
        with self.trava:
            lista = [x for x in self.reg.get(chave, []) if t - x < 3600]
            ok = len(lista) < limite
            if ok:
                lista.append(t)
            self.reg[chave] = lista
            if len(self.reg) > 50_000:
                self.reg = {k: v for k, v in self.reg.items() if v and t - v[-1] < 3600}
            return ok


# ---------- Aplicação ----------
def criar_app(armazem=None, verificar_captcha=None, enviar_email=None, env=None):
    env = os.environ if env is None else env
    exigidas = ["EMAIL_KEY", "ADMIN_TOKEN", "ORIGENS"]
    if armazem is None:
        exigidas += ["R2_CONTA", "R2_CHAVE", "R2_SEGREDO", "R2_BALDE"]
    if verificar_captcha is None:
        exigidas += ["TURNSTILE_SECRET"]
    if enviar_email is None:
        exigidas += ["BREVO_API_KEY", "EMAIL_REMETENTE"]
    faltam = [k for k in exigidas if not env.get(k)]
    if faltam:
        raise RuntimeError("Configuração faltando: " + ", ".join(faltam))  # falha fechada: não sobe sem tudo
    if len(env["ADMIN_TOKEN"]) < 32 or len(env["EMAIL_KEY"]) < 32:
        raise RuntimeError("ADMIN_TOKEN e EMAIL_KEY precisam ter pelo menos 32 caracteres")

    origens = [o.strip() for o in env["ORIGENS"].split(",") if o.strip()]
    hosts = {urllib.parse.urlparse(o).hostname for o in origens}
    armazem = armazem or ArmazemR2(env["R2_CONTA"], env["R2_CHAVE"], env["R2_SEGREDO"], env["R2_BALDE"])
    verificar_captcha = verificar_captcha or turnstile(env["TURNSTILE_SECRET"], hosts)
    enviar_email = enviar_email or brevo(env["BREVO_API_KEY"], env["EMAIL_REMETENTE"])
    # A chave do Fernet sai de um segredo longo (gerado pelo Render), para ninguém precisar copiá-la
    cofre = Fernet(base64.urlsafe_b64encode(hashlib.sha256(env["EMAIL_KEY"].encode()).digest()))
    token_admin = env["ADMIN_TOKEN"].encode()
    link_ok = tuple(o.rstrip("/") + "/" for o in origens)
    limitador = Limitador()
    try:
        limite_bytes = int(float(env.get("LIMITE_GB") or LIMITE_GB_PADRAO) * 1024 ** 3)
    except ValueError:
        raise RuntimeError("LIMITE_GB precisa ser um número (em GB)")
    cache_uso = {"t": 0.0, "uso": None}

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = TAMANHO_MAX + 64 * 1024

    def ip_hash():
        ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"
        return hashlib.sha256((ip + env["EMAIL_KEY"]).encode()).hexdigest()[:16]

    def erro(msg, status):
        return jsonify({"erro": msg}), status

    def meta(p):
        d = armazem.pegar(f"envios/{p}/meta.json")
        return json.loads(d) if d else None

    def salvar_meta(p, m):
        armazem.por(f"envios/{p}/meta.json", json.dumps(m).encode(), "application/json")

    def uso():
        """Quantos envios e quantos bytes estão guardados no balde (uma listagem só)."""
        itens = armazem.listar_com_tamanho("")
        r = {"envios": sum(1 for k, _ in itens if k.startswith("envios/") and k.endswith("/meta.json")),
             "bytes": sum(t for _, t in itens)}
        cache_uso.update(t=time.time(), uso=r)
        return r

    def tem_espaco(u, extra=0):
        return u["envios"] < FILA_MAX and u["bytes"] + extra <= limite_bytes

    def consulta_permitida():
        return (limitador.permite("consulta-ip:" + ip_hash(), CONSULTAS_POR_HORA_IP)
                and limitador.permite("consulta-total", CONSULTAS_POR_HORA_TOTAL))

    def admin_ok():
        h = request.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return False
        if not hmac.compare_digest(h[7:].encode(), token_admin):
            limitador.permite("falha-admin:" + ip_hash(), 10**9)
            return False
        return True

    def admin_bloqueado():
        return len([x for x in limitador.reg.get("falha-admin:" + ip_hash(), []) if time.time() - x < 3600]) >= FALHAS_ADMIN_POR_HORA

    @app.after_request
    def cabecalhos(r):
        o = request.headers.get("Origin")
        if o in origens and not request.path.startswith("/admin"):
            r.headers["Access-Control-Allow-Origin"] = o
            r.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE"
            r.headers["Vary"] = "Origin"
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Cache-Control"] = "no-store"
        r.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path == "/admin":
            r.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                                                    "img-src blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        else:
            r.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return r

    @app.errorhandler(413)
    def grande(_):
        return erro("A imagem passa de 10 MB.", 413)

    @app.get("/saude")
    def saude():
        return jsonify({"ok": True})

    # ----- Público -----
    @app.route("/envio", methods=["POST", "OPTIONS"])
    def envio():
        if request.method == "OPTIONS":
            return "", 204
        if not verificar_captcha(request.form.get("cf-turnstile-response", "")):
            return erro("Não foi possível confirmar que você não é um robô. Recarregue a página e tente de novo.", 400)
        if not limitador.permite("ip:" + ip_hash(), ENVIOS_POR_HORA_IP):
            return erro("Muitos envios seguidos. Tente de novo em uma hora.", 429)
        if not limitador.permite("total", ENVIOS_POR_HORA_TOTAL):
            return erro("Recebemos muitos envios agora. Tente de novo mais tarde.", 503)
        u = uso()
        if not tem_espaco(u):
            return erro("Atingimos o limite de envios guardados. Tente de novo em alguns dias.", 503)
        arq = request.files.get("imagem")
        if not arq:
            return erro("Escolha uma imagem.", 400)
        email = (request.form.get("email") or "").strip()
        if email and (len(email) > 254 or not EMAIL_RE.match(email)):
            return erro("O e-mail parece inválido. Corrija ou deixe em branco.", 400)
        try:
            jpeg = reprocessar_imagem(arq.read(TAMANHO_MAX + 1))
        except Exception:
            return erro("Não conseguimos abrir a imagem. Envie um JPG, PNG ou WEBP de até 10 MB.", 400)
        if not tem_espaco(u, len(jpeg) + 4096):
            return erro("Atingimos o limite de envios guardados. Tente de novo em alguns dias.", 503)
        p = novo_protocolo()
        armazem.por(f"envios/{p}/print.jpg", jpeg, "image/jpeg")
        if email:
            armazem.por(f"contatos/{p}.bin", cofre.encrypt(email.encode()), "application/octet-stream")
        salvar_meta(p, {"protocolo": p, "criado": agora(), "onde": limpar_texto(request.form.get("onde"), 300),
                        "status": "na_fila", "link": "", "concluido": "", "tem_email": bool(email)})
        return jsonify({"protocolo": p}), 201

    @app.get("/capacidade")
    def capacidade():
        """O site pergunta isto antes de mostrar o formulário, para ninguém enviar à toa."""
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        u = cache_uso["uso"] if time.time() - cache_uso["t"] < CACHE_USO_SEG else uso()
        return jsonify({"aceitando": tem_espaco(u)})

    @app.get("/status/<p>")
    def status(p):
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        p = p.upper()
        m = PROTOCOLO_RE.match(p) and meta(p)
        if not m:
            return erro("Protocolo não encontrado. Os envios são apagados em 30 dias.", 404)
        return jsonify({"status": m["status"], "link": m["link"]})

    @app.delete("/envio/<p>")
    def apagar_proprio(p):
        """Quem tem o protocolo pode apagar o próprio envio a qualquer momento (LGPD)."""
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        p = p.upper()
        if not (PROTOCOLO_RE.match(p) and meta(p)):
            return erro("Protocolo não encontrado.", 404)
        for k in (f"envios/{p}/print.jpg", f"envios/{p}/meta.json", f"contatos/{p}.bin"):
            armazem.apagar(k)
        return jsonify({"apagado": True})

    # ----- Administração (só com ADMIN_TOKEN) -----
    @app.get("/admin")
    def admin_pagina():
        return send_file(os.path.join(AQUI, "admin.html"), mimetype="text/html")

    @app.get("/admin.js")
    def admin_js():
        return send_file(os.path.join(AQUI, "admin.js"), mimetype="text/javascript")

    def exige_admin(f):
        def g(*a, **k):
            if admin_bloqueado():
                return erro("Muitas tentativas. Espere uma hora.", 429)
            if not admin_ok():
                return erro("Senha de administração incorreta.", 401)
            return f(*a, **k)
        g.__name__ = f.__name__
        return g

    @app.get("/admin/api/fila")
    @exige_admin
    def fila():
        itens = [meta(k.split("/")[1]) for k in armazem.listar("envios/") if k.endswith("/meta.json")]
        itens = sorted([m for m in itens if m], key=lambda m: (m["status"] != "na_fila", m["criado"]))
        return jsonify(itens)  # sem e-mails: só diz se a pessoa pediu aviso (tem_email)

    @app.get("/admin/api/uso")
    @exige_admin
    def uso_admin():
        u = uso()
        return jsonify({**u, "limite_bytes": limite_bytes, "limite_envios": FILA_MAX})

    @app.get("/admin/api/print/<p>")
    @exige_admin
    def print_(p):
        p = p.upper()
        d = PROTOCOLO_RE.match(p) and armazem.pegar(f"envios/{p}/print.jpg")
        if not d:
            return erro("Não encontrado.", 404)
        return send_file(io.BytesIO(d), mimetype="image/jpeg", download_name=f"{p}.jpg")

    @app.post("/admin/api/concluir")
    @exige_admin
    def concluir():
        d = request.get_json(silent=True) or {}
        p, res, link = str(d.get("protocolo", "")).upper(), d.get("resultado"), str(d.get("link") or "").strip()
        m = PROTOCOLO_RE.match(p) and meta(p)
        if not m:
            return erro("Protocolo não encontrado.", 404)
        if res not in RESULTADOS:
            return erro("Resultado inválido.", 400)
        if link and not link.startswith(link_ok):
            return erro("O link precisa ser de uma página do próprio site.", 400)
        if res == "publicado" and not link:
            return erro("Para 'publicado', informe o link do parecer.", 400)
        m.update(status=res, link=link, concluido=agora())
        salvar_meta(p, m)
        enviado = "sem_email"
        cifrado = armazem.pegar(f"contatos/{p}.bin")
        if cifrado:
            try:
                email = cofre.decrypt(cifrado).decode()
            except InvalidToken:
                return erro("Não foi possível abrir o contato (chave mudou?).", 500)
            extra = f"\n{link}" if link else ""
            texto = TEXTOS[res].format(link=link, extra=extra) + RODAPE.format(p=p)
            try:
                ok = enviar_email(email, ASSUNTO.format(p=p), texto, aviso_html(res, link, p))
            except Exception:
                ok = False
            del email
            if not ok:
                return jsonify({"status": res, "email": "falhou"}), 502  # o contato fica para tentar de novo
            armazem.apagar(f"contatos/{p}.bin")
            m["tem_email"] = False
            salvar_meta(p, m)
            enviado = "enviado"
        return jsonify({"status": res, "email": enviado})

    @app.post("/admin/api/apagar")
    @exige_admin
    def apagar_admin():
        p = str((request.get_json(silent=True) or {}).get("protocolo", "")).upper()
        if not PROTOCOLO_RE.match(p):
            return erro("Protocolo inválido.", 400)
        for k in (f"envios/{p}/print.jpg", f"envios/{p}/meta.json", f"contatos/{p}.bin"):
            armazem.apagar(k)
        return jsonify({"apagado": True})

    return app
