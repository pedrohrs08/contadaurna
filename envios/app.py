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
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

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
RESULTADOS = {"publicado", "ja_publicado", "procede", "descartado"}
PENDENTES = ("na_fila", "rascunho", "repetido")  # ainda esperam o responsável ou a rotina
FILA_MAX = 500            # envios com print guardado; acima disso, novos envios são recusados
LIMITE_GB_PADRAO = 8      # espaço máximo no R2 (o plano grátis vai até 10 GB); muda com a variável LIMITE_GB
LIMITE_BANCO_MB_PADRAO = 400  # tamanho máximo do banco D1 (o grátis vai até 500 MB); muda com LIMITE_BANCO_MB
CACHE_USO_SEG = 60        # o uso do balde e do banco é recalculado no máximo 1 vez por minuto
DIAS_GUARDA = 30          # depois disso, o print e o "onde viu" são apagados (o registro sem dados pessoais fica)
ENVIOS_POR_HORA_IP = 5
ENVIOS_POR_HORA_TOTAL = 120
FALHAS_ADMIN_POR_HORA = 10
CONSULTAS_POR_HORA_IP = 60       # consultas e pedidos de apagar por protocolo
CONSULTAS_POR_HORA_TOTAL = 1500  # teto geral: cada consulta é uma leitura paga no R2 acima da cota grátis

ASSUNTO = "Seu envio ao Conta da Urna ({p})"
TEXTOS = {
    "publicado": "O boato que você enviou foi checado e o parecer está publicado:\n{link}",
    "ja_publicado": "Olá! Obrigado por enviar. Verificamos e esse boato já tinha sido checado: o parecer foi publicado anteriormente. Confere lá:\n{link}",
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
    "ja_publicado": ("Já checado", "Obrigado por enviar!",
                     "Olá! Verificamos e esse boato já tinha sido checado: o parecer foi publicado anteriormente no site. Confere lá.",
                     "Ler o parecer"),
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


# ---------- Banco: Cloudflare D1 em produção, SQLite local em testes ----------
# O D1 é SQLite, então as mesmas consultas valem nos dois. O esquema está em banco/migrations/.
class BancoD1:
    """Fala com o D1 pela API da Cloudflare. O token precisa só da permissão "D1: Edit"."""
    def __init__(self, conta, banco_id, token):
        self.base = f"https://api.cloudflare.com/client/v4/accounts/{conta}/d1/database/{banco_id}"
        self.cab = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    def _pedir(self, caminho="", corpo=None):
        req = urllib.request.Request(self.base + caminho, data=json.dumps(corpo).encode() if corpo is not None else None,
                                     headers=self.cab, method="POST" if corpo is not None else "GET")
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        if not d.get("success"):
            raise RuntimeError("D1: " + json.dumps(d.get("errors"))[:300])
        return d["result"]

    def consultar(self, sql, params=()):
        return self._pedir("/query", {"sql": sql, "params": list(params)})[0].get("results") or []

    def tamanho(self):
        return int(self._pedir().get("file_size") or 0)


class BancoLocal:
    """Só para testes e desenvolvimento: aplica as migrações em um SQLite na memória."""
    def __init__(self, pasta_migracoes=os.path.join(AQUI, "..", "banco", "migrations")):
        self.con = sqlite3.connect(":memory:", check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.trava = threading.Lock()
        for nome in sorted(os.listdir(pasta_migracoes)):
            if nome.endswith(".sql"):
                self.con.executescript(open(os.path.join(pasta_migracoes, nome), encoding="utf-8").read())

    def consultar(self, sql, params=()):
        with self.trava:
            cur = self.con.execute(sql, list(params))
            linhas = [dict(r) for r in cur.fetchall()]
            self.con.commit()
            return linhas

    def tamanho(self):
        return self.consultar("SELECT page_count * page_size AS t FROM pragma_page_count(), pragma_page_size()")[0]["t"]


# ---------- Pareceres: conferência do conteúdo antes de gravar ----------
# O site monta alguns campos como HTML. Para que nem um token vazado consiga pôr script na página,
# só passam as marcações que os pareceres usam.
ID_PARECER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATA_RE = re.compile(r"^[0-3][0-9]/[01][0-9]/20[0-9]{2}$")
URL_FONTE_RE = re.compile(r"^https?://[^\s\"'<>`]+$")
SELOS = {"Não procede", "Enganoso", "Procede"}
TAGS_OK = {"p", "b", "strong", "i", "em", "u", "ul", "ol", "li", "a", "br", "div", "span", "small", "sup", "sub",
           "table", "thead", "tbody", "tr", "th", "td"}
CLASSE_RE = re.compile(r"^[\w -]{1,60}$")


class _ConfereHTML(HTMLParser):
    def __init__(self, tags):
        super().__init__(convert_charrefs=True)
        self.tags, self.problemas = tags, []

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            self.problemas.append(f"<{tag}>")
            return
        for nome, valor in attrs:
            valor = valor or ""
            if nome == "class" and CLASSE_RE.match(valor):
                continue
            if tag == "a" and nome == "href" and (URL_FONTE_RE.match(valor) or re.match(r"^#fake-[a-z0-9-]+$", valor)):
                continue
            if tag == "a" and nome in ("target", "rel") and valor in ("_blank", "noopener", "noopener noreferrer"):
                continue
            self.problemas.append(f'{nome}="{valor[:40]}" em <{tag}>')

    def handle_comment(self, _):
        self.problemas.append("comentário HTML")


def html_seguro(t, tags=TAGS_OK):
    p = _ConfereHTML(tags)
    p.feed(t)
    p.close()
    return p.problemas


def validar_parecer(d):
    """Devolve (dados limpos, lista de erros). Os campos são os do item da aba Fake news."""
    erros, saida = [], {}
    if not isinstance(d, dict):
        return None, ["Mande um objeto JSON."]

    def texto(nome, n, obrigatorio=True, html=False):
        v = d.get(nome)
        if v in (None, "") and not obrigatorio:
            return
        if not isinstance(v, str) or not v.strip():
            erros.append(f"Falta o campo {nome}.")
            return
        if len(v) > n:
            erros.append(f"{nome} passa de {n} caracteres.")
        if html:
            erros.extend(f"{nome}: marcação não aceita {x}" for x in html_seguro(v))
        saida[nome] = v

    texto("titulo", 400)
    texto("data", 10)
    if "data" in saida and not DATA_RE.match(saida["data"]):
        erros.append("data precisa estar no formato dd/mm/aaaa.")
    if d.get("selo") not in (None, ""):
        if d["selo"] not in SELOS:
            erros.append("selo precisa ser " + ", ".join(sorted(SELOS)) + ".")
        else:
            saida["selo"] = d["selo"]
    texto("texto", 30000)
    texto("frase", 2000, obrigatorio=False, html=True)
    texto("curto", 5000, html=True)
    texto("parecer", 80000, html=True)
    nums = d.get("nums")
    if nums not in (None, []):
        if (not isinstance(nums, list) or len(nums) > 8 or
                not all(isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) and len(y) < 400 for y in x) for x in nums)):
            erros.append("nums precisa ser uma lista de pares [número, rótulo].")
        else:
            erros.extend(f"nums: marcação não aceita {x}" for par in nums for y in par for x in html_seguro(y))
            saida["nums"] = nums
    fontes = d.get("fontes")
    if (not isinstance(fontes, list) or not 1 <= len(fontes) <= 60 or
            not all(isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) for y in x) for x in fontes)):
        erros.append("fontes precisa ser uma lista (de 1 a 60) de pares [nome, link].")
    else:
        for nome, link in fontes:
            if not URL_FONTE_RE.match(link):
                erros.append(f"Link de fonte inválido: {link[:80]}")
            erros.extend(f"fontes: marcação não aceita {x}" for x in html_seguro(nome, {"b", "i", "em", "strong"}))
        saida["fontes"] = fontes
    outras = d.get("outras")
    if outras not in (None, []):
        if (not isinstance(outras, list) or len(outras) > 20 or
                not all(isinstance(o, dict) and isinstance(o.get("texto"), str) and DATA_RE.match(str(o.get("data", "")))
                        for o in outras)):
            erros.append("outras precisa ser uma lista de {\"data\": \"dd/mm/aaaa\", \"texto\": \"...\"}.")
        else:
            saida["outras"] = [{"data": o["data"], "texto": o["texto"]} for o in outras]
    sobra = set(d) - {"id", "titulo", "data", "selo", "texto", "frase", "curto", "parecer", "nums", "fontes", "outras", "previa"}
    if sobra:
        erros.append("Campos desconhecidos: " + ", ".join(sorted(sobra)))
    if len(json.dumps(saida, ensure_ascii=False)) > 150_000:
        erros.append("O parecer está grande demais.")
    return saida, erros


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
def criar_app(armazem=None, banco=None, verificar_captcha=None, enviar_email=None, env=None):
    env = os.environ if env is None else env
    exigidas = ["EMAIL_KEY", "ADMIN_TOKEN", "ORIGENS"]
    if armazem is None:
        exigidas += ["R2_CONTA", "R2_CHAVE", "R2_SEGREDO", "R2_BALDE"]
    if banco is None:
        exigidas += ["R2_CONTA", "D1_BANCO", "D1_TOKEN"]
    if verificar_captcha is None:
        exigidas += ["TURNSTILE_SECRET"]
    if enviar_email is None:
        exigidas += ["BREVO_API_KEY", "EMAIL_REMETENTE"]
    faltam = sorted({k for k in exigidas if not env.get(k)})
    if faltam:
        raise RuntimeError("Configuração faltando: " + ", ".join(faltam))  # falha fechada: não sobe sem tudo
    if len(env["ADMIN_TOKEN"]) < 32 or len(env["EMAIL_KEY"]) < 32:
        raise RuntimeError("ADMIN_TOKEN e EMAIL_KEY precisam ter pelo menos 32 caracteres")

    origens = [o.strip() for o in env["ORIGENS"].split(",") if o.strip()]
    hosts = {urllib.parse.urlparse(o).hostname for o in origens}
    armazem = armazem or ArmazemR2(env["R2_CONTA"], env["R2_CHAVE"], env["R2_SEGREDO"], env["R2_BALDE"])
    banco = banco or BancoD1(env["R2_CONTA"], env["D1_BANCO"], env["D1_TOKEN"])
    verificar_captcha = verificar_captcha or turnstile(env["TURNSTILE_SECRET"], hosts)
    enviar_email = enviar_email or brevo(env["BREVO_API_KEY"], env["EMAIL_REMETENTE"])
    # A chave do Fernet sai de um segredo longo (gerado pelo Render), para ninguém precisar copiá-la
    cofre = Fernet(base64.urlsafe_b64encode(hashlib.sha256(env["EMAIL_KEY"].encode()).digest()))
    token_admin = env["ADMIN_TOKEN"].encode()
    # Senha da rotina de IA: lê a fila e os prints, escreve pareceres pendentes e diz se cada envio é publicável.
    # Não publica, não apaga e não vê e-mails.
    token_rotina = (env.get("ROTINA_TOKEN") or "").encode()
    if token_rotina and (len(token_rotina) < 32 or hmac.compare_digest(token_rotina, token_admin)):
        raise RuntimeError("ROTINA_TOKEN precisa ter pelo menos 32 caracteres e ser diferente do ADMIN_TOKEN")
    link_ok = tuple(o.rstrip("/") + "/" for o in origens)
    site = origens[0].rstrip("/") + "/"
    limitador = Limitador()
    try:
        limite_bytes = int(float(env.get("LIMITE_GB") or LIMITE_GB_PADRAO) * 1024 ** 3)
        limite_banco = int(float(env.get("LIMITE_BANCO_MB") or LIMITE_BANCO_MB_PADRAO) * 1024 ** 2)
    except ValueError:
        raise RuntimeError("LIMITE_GB e LIMITE_BANCO_MB precisam ser números")
    cache_uso = {"t": 0.0, "uso": None}
    limpeza = {"t": 0.0}
    importacao = {"feita": False}

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = TAMANHO_MAX + 64 * 1024

    def ip_hash():
        ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"
        return hashlib.sha256((ip + env["EMAIL_KEY"]).encode()).hexdigest()[:16]

    def erro(msg, status):
        return jsonify({"erro": msg}), status

    # ----- Banco -----
    def um(sql, params=()):
        r = banco.consultar(sql, params)
        return r[0] if r else None

    def registrar(quem, tipo, ref, acao, dados=None):
        banco.consultar("INSERT INTO historico (quando, quem, tipo, ref, acao, dados) VALUES (?, ?, ?, ?, ?, ?)",
                        (agora(), quem, tipo, ref, acao, json.dumps(dados, ensure_ascii=False) if dados is not None else None))

    def envio_(p):
        return um("SELECT * FROM envios WHERE protocolo = ?", (p,)) if PROTOCOLO_RE.match(p) else None

    def mudar_envio(p, quem, acao, **campos):
        banco.consultar(f"UPDATE envios SET {', '.join(k + ' = ?' for k in campos)} WHERE protocolo = ?",
                        (*campos.values(), p))
        registrar(quem, "envio", p, acao, campos)

    def apagar_envio(p):
        for k in (f"envios/{p}/print.jpg", f"contatos/{p}.bin"):
            armazem.apagar(k)
        banco.consultar("DELETE FROM envios WHERE protocolo = ?", (p,))
        banco.consultar("DELETE FROM historico WHERE tipo = 'envio' AND ref = ?", (p,))

    def limpar_expirados():
        """Depois de 30 dias o balde apaga o print sozinho (regra de ciclo de vida); aqui o banco acompanha."""
        if time.time() - limpeza["t"] < 600:
            return
        limpeza["t"] = time.time()
        corte = (datetime.now(timezone.utc) - timedelta(days=DIAS_GUARDA)).strftime("%Y-%m-%dT%H:%M:%SZ")
        vencidos = banco.consultar("SELECT protocolo, status FROM envios WHERE expirado = '' AND criado < ?", (corte,))
        for v in vencidos:
            campos = {"print_chave": None, "print_bytes": 0, "onde": "", "tem_email": 0, "expirado": agora()}
            if v["status"] in PENDENTES:
                campos["status"] = "expirado"
            mudar_envio(v["protocolo"], "sistema", f"apagados print e dados após {DIAS_GUARDA} dias", **campos)
            armazem.apagar(f"contatos/{v['protocolo']}.bin")

    def uso(forcar=False):
        """Espaço usado no balde (somado pelo banco, sem listar o balde) e tamanho do banco."""
        if not forcar and cache_uso["uso"] and time.time() - cache_uso["t"] < CACHE_USO_SEG:
            return cache_uso["uso"]
        r = um("SELECT COUNT(*) AS envios, COALESCE(SUM(print_bytes), 0) AS bytes FROM envios WHERE print_chave IS NOT NULL")
        u = {"envios": int(r["envios"]), "bytes": int(r["bytes"]), "banco_bytes": int(banco.tamanho())}
        cache_uso.update(t=time.time(), uso=u)
        return u

    def tem_espaco(u, extra=0):
        return u["envios"] < FILA_MAX and u["bytes"] + extra <= limite_bytes and u["banco_bytes"] + 64 * 1024 <= limite_banco

    def importar_do_balde():
        """Até 31/10/2026 cada envio tinha um meta.json no balde. Passa esses envios para o banco, uma vez
        (no primeiro uso depois de o servidor subir, para não depender de o banco já estar pronto na hora do deploy)."""
        if importacao["feita"]:
            return
        tamanhos = dict(armazem.listar_com_tamanho("envios/"))
        for k in [k for k in tamanhos if k.endswith("/meta.json")]:
            m = json.loads(armazem.pegar(k) or b"null")
            if not m:
                continue
            p = m["protocolo"]
            chave = f"envios/{p}/print.jpg" if f"envios/{p}/print.jpg" in tamanhos else None
            banco.consultar("INSERT OR IGNORE INTO envios (protocolo, criado, onde, status, link, print_chave, print_bytes, "
                            "tem_email, concluido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (p, m["criado"], m.get("onde", ""), m.get("status", "na_fila"), m.get("link") or m.get("parecer") or "",
                             chave, tamanhos.get(chave, 0), int(bool(m.get("tem_email"))), m.get("concluido", "")))
            registrar("sistema", "envio", p, "importado do balde", {"status": m.get("status"), "pr": m.get("pr", "")})
            armazem.apagar(k)
        importacao["feita"] = True

    # ----- Pareceres -----
    def ler_parecer(i):
        r = um("SELECT * FROM pareceres WHERE id = ?", (i,)) if ID_PARECER_RE.match(i or "") else None
        if r:
            r["publicado"] = json.loads(r["publicado"]) if r["publicado"] else None
            r["pendente"] = json.loads(r["pendente"]) if r["pendente"] else None
        return r

    def link_previa(r):
        return f"{site}?previa={r['id']}.{r['chave']}#fake-{r['id']}"

    def link_parecer(i):
        return f"{site}#fake-{i}"

    def resumo_parecer(r):
        versao = r["pendente"] or r["publicado"] or {}
        return {"id": r["id"], "titulo": versao.get("titulo", ""), "frase": versao.get("frase", ""), "selo": versao.get("selo", ""),
                "no_ar": r["publicado"] is not None, "pendente": r["pendente"] is not None,
                "atualizado": r["atualizado"], "link": link_parecer(r["id"]), "previa": link_previa(r)}

    def todos_pareceres():
        linhas = banco.consultar("SELECT * FROM pareceres ORDER BY pendente IS NULL, posicao IS NULL DESC, posicao DESC, atualizado DESC")
        for r in linhas:
            r["publicado"] = json.loads(r["publicado"]) if r["publicado"] else None
            r["pendente"] = json.loads(r["pendente"]) if r["pendente"] else None
        return linhas

    def gravar_pendente(i, quem):
        if not ID_PARECER_RE.match(i) or len(i) > 80:
            return erro("O id do parecer usa só letras minúsculas, números e hífens (até 80).", 400)
        dados, erros = validar_parecer(request.get_json(silent=True))
        if erros:
            return jsonify({"erro": "O parecer tem problemas.", "detalhes": erros}), 400
        r = ler_parecer(i)
        corpo = json.dumps(dados, ensure_ascii=False)
        if r:
            banco.consultar("UPDATE pareceres SET pendente = ?, atualizado = ? WHERE id = ?", (corpo, agora(), i))
        else:
            banco.consultar("INSERT INTO pareceres (id, pendente, chave, criado, atualizado) VALUES (?, ?, ?, ?, ?)",
                            (i, corpo, secrets.token_hex(16), agora(), agora()))
        registrar(quem, "parecer", i, "versão pendente gravada" if r else "parecer criado", dados)
        r = ler_parecer(i)
        return jsonify(resumo_parecer(r))

    # ----- Cabeçalhos -----
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
    def consulta_permitida():
        return (limitador.permite("consulta-ip:" + ip_hash(), CONSULTAS_POR_HORA_IP)
                and limitador.permite("consulta-total", CONSULTAS_POR_HORA_TOTAL))

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
        importar_do_balde()
        limpar_expirados()
        u = uso(forcar=True)
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
        chave = f"envios/{p}/print.jpg"
        armazem.por(chave, jpeg, "image/jpeg")
        if email:
            armazem.por(f"contatos/{p}.bin", cofre.encrypt(email.encode()), "application/octet-stream")
        banco.consultar("INSERT INTO envios (protocolo, criado, onde, print_chave, print_bytes, tem_email) VALUES (?, ?, ?, ?, ?, ?)",
                        (p, agora(), limpar_texto(request.form.get("onde"), 300), chave, len(jpeg), int(bool(email))))
        registrar("pessoa", "envio", p, "recebido", {"pediu_aviso": bool(email)})
        cache_uso["uso"] = None
        return jsonify({"protocolo": p}), 201

    @app.get("/capacidade")
    def capacidade():
        """O site pergunta isto antes de mostrar o formulário, para ninguém enviar à toa."""
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        return jsonify({"aceitando": tem_espaco(uso())})

    @app.get("/status/<p>")
    def status(p):
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        m = envio_(p.upper())
        if not m:
            return erro("Protocolo não encontrado. Os envios são apagados em 30 dias.", 404)
        # O link só aparece depois de concluído: antes disso o parecer pode nem estar no ar
        return jsonify({"status": m["status"], "link": m["link"] if m["concluido"] else ""})

    @app.delete("/envio/<p>")
    def apagar_proprio(p):
        """Quem tem o protocolo pode apagar o próprio envio a qualquer momento (LGPD): some do balde e do banco."""
        if not consulta_permitida():
            return erro("Muitas consultas. Tente de novo mais tarde.", 429)
        p = p.upper()
        if not envio_(p):
            return erro("Protocolo não encontrado.", 404)
        apagar_envio(p)
        cache_uso["uso"] = None
        return jsonify({"apagado": True})

    # ----- Senhas -----
    def bloqueado():
        return len([x for x in limitador.reg.get("falha-admin:" + ip_hash(), []) if time.time() - x < 3600]) >= FALHAS_ADMIN_POR_HORA

    def exige(nome, token, msg):
        """Só deixa passar com "Authorization: Bearer <token>". Após 10 erros em 1 hora, o IP fica bloqueado por 1 hora."""
        def deco(f):
            def g(*a, **k):
                if bloqueado():
                    return erro("Muitas tentativas. Espere uma hora.", 429)
                h = request.headers.get("Authorization", "")
                if not (token and h.startswith("Bearer ") and hmac.compare_digest(h[7:].encode(), token)):
                    limitador.permite("falha-admin:" + ip_hash(), 10**9)
                    return erro(msg, 401)
                return f(*a, quem=nome, **k)
            g.__name__ = f.__name__
            return g
        return deco

    exige_admin = exige("admin", token_admin, "Senha de administração incorreta.")
    exige_rotina = exige("rotina", token_rotina, "Senha da rotina incorreta.")

    # ----- Administração (só com ADMIN_TOKEN) -----
    @app.get("/admin")
    def admin_pagina():
        return send_file(os.path.join(AQUI, "admin.html"), mimetype="text/html")

    @app.get("/admin.js")
    def admin_js():
        return send_file(os.path.join(AQUI, "admin.js"), mimetype="text/javascript")

    def lista_envios(onde="", params=()):
        itens = banco.consultar(
            "SELECT e.protocolo, e.criado, e.onde, e.status, e.publicavel, e.motivo, e.parecer, e.link, e.tem_email, e.concluido, "
            "e.print_chave IS NOT NULL AS tem_print, p.publicado IS NOT NULL AS parecer_no_ar, p.pendente IS NOT NULL AS parecer_pendente "
            f"FROM envios e LEFT JOIN pareceres p ON p.id = e.parecer {onde} ORDER BY e.criado", params)
        for it in itens:
            for k in ("tem_email", "tem_print", "parecer_no_ar", "parecer_pendente"):
                it[k] = bool(it[k])
            it["publicavel"] = None if it["publicavel"] is None else bool(it["publicavel"])
        return itens

    @app.get("/admin/api/fila")
    @exige_admin
    def fila(quem):
        importar_do_balde()
        limpar_expirados()
        itens = lista_envios()
        itens.sort(key=lambda m: (m["status"] not in PENDENTES, m["criado"] if m["status"] in PENDENTES else ""), reverse=False)
        return jsonify(itens)  # sem e-mails: só diz se a pessoa pediu aviso (tem_email)

    @app.get("/admin/api/uso")
    @exige_admin
    def uso_admin(quem):
        u = uso(forcar=True)
        return jsonify({**u, "limite_bytes": limite_bytes, "limite_envios": FILA_MAX, "limite_banco_bytes": limite_banco})

    def ler_print(p):
        m = envio_(p.upper())
        d = m and m["print_chave"] and armazem.pegar(m["print_chave"])
        if not d:
            return erro("Não encontrado.", 404)
        return send_file(io.BytesIO(d), mimetype="image/jpeg", download_name=f"{m['protocolo']}.jpg")

    @app.get("/admin/api/print/<p>")
    @exige_admin
    def print_(p, quem):
        return ler_print(p)

    def concluir_envio(p, res, link, quem):
        """Marca o resultado e, se a pessoa pediu aviso, manda o e-mail e apaga o endereço. Devolve (corpo, status)."""
        mudar_envio(p, quem, "concluído: " + res, status=res, link=link, concluido=agora())
        cifrado = armazem.pegar(f"contatos/{p}.bin")
        if not cifrado:
            return {"status": res, "email": "sem_email"}, 200
        try:
            email = cofre.decrypt(cifrado).decode()
        except InvalidToken:
            return {"status": res, "erro": "Não foi possível abrir o contato (chave mudou?)."}, 500
        extra = f"\n{link}" if link else ""
        texto = TEXTOS[res].format(link=link, extra=extra) + RODAPE.format(p=p)
        try:
            ok = enviar_email(email, ASSUNTO.format(p=p), texto, aviso_html(res, link, p))
        except Exception:
            ok = False
        del email
        if not ok:
            return {"status": res, "email": "falhou"}, 502  # o contato fica para tentar de novo
        armazem.apagar(f"contatos/{p}.bin")
        mudar_envio(p, "sistema", "aviso enviado por e-mail e endereço apagado", tem_email=0)
        return {"status": res, "email": "enviado"}, 200

    @app.post("/admin/api/concluir")
    @exige_admin
    def concluir(quem):
        d = request.get_json(silent=True) or {}
        p, res, link = str(d.get("protocolo", "")).upper(), d.get("resultado"), str(d.get("link") or "").strip()
        if not envio_(p):
            return erro("Protocolo não encontrado.", 404)
        if res not in RESULTADOS:
            return erro("Resultado inválido.", 400)
        if link and not link.startswith(link_ok):
            return erro("O link precisa ser de uma página do próprio site.", 400)
        if res in ("publicado", "ja_publicado") and not link:
            return erro("Informe o link do parecer.", 400)
        corpo, st = concluir_envio(p, res, link, quem)
        return jsonify(corpo), st

    @app.post("/admin/api/apagar")
    @exige_admin
    def apagar_admin(quem):
        p = str((request.get_json(silent=True) or {}).get("protocolo", "")).upper()
        if not PROTOCOLO_RE.match(p):
            return erro("Protocolo inválido.", 400)
        apagar_envio(p)
        cache_uso["uso"] = None
        return jsonify({"apagado": True})

    @app.get("/admin/api/pareceres")
    @exige_admin
    def pareceres_admin(quem):
        ligados = {}
        for e in banco.consultar("SELECT protocolo, parecer, status FROM envios WHERE parecer IS NOT NULL"):
            ligados.setdefault(e["parecer"], []).append({"protocolo": e["protocolo"], "status": e["status"]})
        return jsonify([{**resumo_parecer(r), "envios": ligados.get(r["id"], [])} for r in todos_pareceres()])

    @app.get("/admin/api/parecer/<i>")
    @exige_admin
    def parecer_admin(i, quem):
        r = ler_parecer(i)
        if not r:
            return erro("Parecer não encontrado.", 404)
        return jsonify({**resumo_parecer(r), "publicado": r["publicado"], "pendente": r["pendente"]})

    @app.put("/admin/api/parecer/<i>")
    @exige_admin
    def parecer_gravar_admin(i, quem):
        return gravar_pendente(i, quem)

    @app.post("/admin/api/parecer/<i>/publicar")
    @exige_admin
    def parecer_publicar(i, quem):
        """Põe no ar a versão pendente. Os envios ligados a este parecer viram "publicado" e o aviso sai na hora."""
        r = ler_parecer(i)
        if not r or not r["pendente"]:
            return erro("Não há versão pendente para publicar.", 404)
        primeira = r["posicao"] is None
        banco.consultar("UPDATE pareceres SET publicado = pendente, pendente = NULL, atualizado = ?, publicado_em = ?, "
                        "posicao = COALESCE(posicao, (SELECT COALESCE(MAX(posicao), 0) + 1 FROM pareceres)) WHERE id = ?",
                        (agora(), agora(), i))
        registrar(quem, "parecer", i, "publicado" if primeira else "nova versão publicada", r["pendente"])
        avisos = []
        for e in banco.consultar("SELECT protocolo FROM envios WHERE parecer = ? AND status IN ('na_fila', 'rascunho') "
                                 "AND publicavel = 1", (i,)):
            corpo, _ = concluir_envio(e["protocolo"], "publicado", link_parecer(i), quem)
            avisos.append({"protocolo": e["protocolo"], **corpo})
        return jsonify({**resumo_parecer(ler_parecer(i)), "avisos": avisos})

    @app.post("/admin/api/parecer/<i>/descartar")
    @exige_admin
    def parecer_descartar(i, quem):
        """Joga fora a versão pendente. Se o parecer nunca foi ao ar, ele some e os envios voltam para a fila."""
        r = ler_parecer(i)
        if not r or not r["pendente"]:
            return erro("Não há versão pendente.", 404)
        if r["publicado"]:
            banco.consultar("UPDATE pareceres SET pendente = NULL, atualizado = ? WHERE id = ?", (agora(), i))
            registrar(quem, "parecer", i, "versão pendente descartada", r["pendente"])
        else:
            banco.consultar("DELETE FROM pareceres WHERE id = ?", (i,))
            registrar(quem, "parecer", i, "rascunho descartado", r["pendente"])
            for e in banco.consultar("SELECT protocolo FROM envios WHERE parecer = ? AND concluido = ''", (i,)):
                mudar_envio(e["protocolo"], quem, "parecer descartado; volta para a fila", parecer=None, status="na_fila", link="")
        return jsonify({"descartado": True})

    @app.post("/admin/api/parecer/<i>/tirar")
    @exige_admin
    def parecer_tirar(i, quem):
        """Tira o parecer do ar. A versão que estava no ar vira pendente (se não houver outra), para não se perder."""
        r = ler_parecer(i)
        if not r or not r["publicado"]:
            return erro("Este parecer não está no ar.", 404)
        banco.consultar("UPDATE pareceres SET pendente = COALESCE(pendente, publicado), publicado = NULL, atualizado = ? WHERE id = ?",
                        (agora(), i))
        registrar(quem, "parecer", i, "tirado do ar", r["publicado"])
        return jsonify(resumo_parecer(ler_parecer(i)))

    @app.get("/admin/api/historico")
    @exige_admin
    def historico(quem):
        tipo, ref = request.args.get("tipo", ""), request.args.get("ref", "")
        if tipo and ref:
            linhas = banco.consultar("SELECT * FROM historico WHERE tipo = ? AND ref = ? ORDER BY n DESC LIMIT 200", (tipo, ref))
        else:
            linhas = banco.consultar("SELECT * FROM historico ORDER BY n DESC LIMIT 200")
        for h in linhas:
            h["dados"] = json.loads(h["dados"]) if h["dados"] else None
        return jsonify(linhas)

    # ----- Rotina de IA (só com ROTINA_TOKEN; desligada se ele não existir) -----
    # Ela escreve pareceres como versão pendente e diz se cada envio é publicável. Nada vai ao ar sem
    # o responsável tocar em Publicar no /admin. Não vê e-mails, não apaga e não conclui envios.
    @app.get("/rotina/api/fila")
    @exige_rotina
    def rotina_fila(quem):
        importar_do_balde()
        limpar_expirados()
        campos = ("protocolo", "criado", "onde", "status", "publicavel", "motivo", "parecer", "tem_print")
        return jsonify([{k: m[k] for k in campos} for m in lista_envios("WHERE e.status IN ('na_fila', 'rascunho')")])

    @app.get("/rotina/api/print/<p>")
    @exige_rotina
    def rotina_print(p, quem):
        return ler_print(p)

    @app.get("/rotina/api/pareceres")
    @exige_rotina
    def rotina_pareceres(quem):
        return jsonify([resumo_parecer(r) for r in todos_pareceres()])

    @app.get("/rotina/api/parecer/<i>")
    @exige_rotina
    def rotina_parecer(i, quem):
        r = ler_parecer(i)
        if not r:
            return erro("Parecer não encontrado.", 404)
        return jsonify({**resumo_parecer(r), "publicado": r["publicado"], "pendente": r["pendente"]})

    @app.put("/rotina/api/parecer/<i>")
    @exige_rotina
    def rotina_parecer_gravar(i, quem):
        return gravar_pendente(i, quem)

    @app.post("/rotina/api/avaliar")
    @exige_rotina
    def rotina_avaliar(quem):
        """Diz se o envio é publicável e qual parecer responde a ele.
        - publicavel false: fica na fila com o motivo, para o responsável marcar "procede" ou "descartado";
        - publicavel true + parecer pendente: vira "rascunho" e é avisado quando o responsável publicar;
        - publicavel true + parecer já no ar (boato repetido): vira "repetido", pronto para o aviso de "já publicado"."""
        d = request.get_json(silent=True) or {}
        p = str(d.get("protocolo", "")).upper()
        m = envio_(p)
        if not m:
            return erro("Protocolo não encontrado.", 404)
        if m["concluido"] or m["status"] not in ("na_fila", "rascunho", "repetido"):
            return erro("Este envio já foi concluído.", 409)
        if not isinstance(d.get("publicavel"), bool):
            return erro("Informe publicavel: true ou false.", 400)
        motivo = limpar_texto(str(d.get("motivo") or ""), 1000)
        if not d["publicavel"]:
            if not motivo:
                return erro("Diga o motivo de não ser publicável.", 400)
            mudar_envio(p, quem, "avaliado: não publicável", publicavel=0, motivo=motivo, parecer=None, status="na_fila", link="")
            return jsonify({"protocolo": p, "status": "na_fila", "publicavel": False})
        r = ler_parecer(str(d.get("parecer") or ""))
        if not r:
            return erro("Grave o parecer antes (PUT /rotina/api/parecer/<id>) e informe o id dele.", 400)
        st = "repetido" if r["publicado"] else "rascunho"
        mudar_envio(p, quem, "avaliado: publicável", publicavel=1, motivo=motivo, parecer=r["id"], status=st,
                    link=link_parecer(r["id"]))
        return jsonify({"protocolo": p, "status": st, "publicavel": True, "parecer": r["id"], "previa": link_previa(r)})

    return app
