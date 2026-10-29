"""Testes do serviço de envio. Rodar:  pip install -r requirements.txt pytest && pytest envios"""
import io
import json

import pytest
from PIL import Image

from app import ArmazemLocal, criar_app

ENV = {"EMAIL_KEY": "k" * 40, "ADMIN_TOKEN": "a" * 40, "ORIGENS": "https://contadaurna.com.br,https://www.contadaurna.com.br"}
ADM = {"Authorization": "Bearer " + "a" * 40}


@pytest.fixture
def ctx(tmp_path):
    enviados = []
    arm = ArmazemLocal(str(tmp_path))
    app = criar_app(armazem=arm, verificar_captcha=lambda t: t == "ok",
                    enviar_email=lambda para, assunto, texto, html_: enviados.append((para, assunto, texto, html_)) or True, env=ENV)
    return app.test_client(), arm, enviados


def imagem(fmt="PNG", exif=False):
    b = io.BytesIO()
    im = Image.new("RGB", (50, 40), "red")
    if exif:
        e = Image.Exif(); e[0x013B] = "Autor Secreto"
        im.save(b, "JPEG", exif=e)
    else:
        im.save(b, fmt)
    return b.getvalue()


def enviar(c, email="", captcha="ok", dados=None, origem="https://contadaurna.com.br"):
    return c.post("/envio", data={"imagem": (io.BytesIO(dados or imagem()), "x.png"), "email": email,
                                  "onde": "grupo\x00 de zap", "cf-turnstile-response": captcha},
                  headers={"Origin": origem}, content_type="multipart/form-data")


def test_falta_configuracao():
    with pytest.raises(RuntimeError):
        criar_app(env={})


def test_envio_anonimo_e_status(ctx):
    c, arm, _ = ctx
    r = enviar(c)
    assert r.status_code == 201
    p = r.get_json()["protocolo"]
    assert r.headers["Access-Control-Allow-Origin"] == "https://contadaurna.com.br"
    assert c.get("/status/" + p).get_json() == {"status": "na_fila", "link": ""}
    assert arm.pegar(f"contatos/{p}.bin") is None


def test_origem_estranha_sem_cors(ctx):
    c, _, _ = ctx
    assert "Access-Control-Allow-Origin" not in enviar(c, origem="https://malicioso.example").headers


def test_captcha_obrigatorio(ctx):
    assert enviar(ctx[0], captcha="").status_code == 400


def test_arquivo_que_nao_e_imagem(ctx):
    assert enviar(ctx[0], dados=b"<script>alert(1)</script>").status_code == 400


def test_metadados_removidos(ctx):
    c, arm, _ = ctx
    p = enviar(c, dados=imagem(exif=True)).get_json()["protocolo"]
    salvo = arm.pegar(f"envios/{p}/print.jpg")
    assert b"Autor Secreto" not in salvo and not Image.open(io.BytesIO(salvo)).getexif()


def test_email_criptografado_e_invisivel_ao_admin(ctx):
    c, arm, enviados = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    assert b"pessoa@exemplo.com" not in arm.pegar(f"contatos/{p}.bin")
    for k in arm.listar(""):
        assert b"pessoa@exemplo.com" not in arm.pegar(k)
    fila = c.get("/admin/api/fila", headers=ADM)
    assert b"pessoa@exemplo.com" not in fila.data and fila.get_json()[0]["tem_email"] is True


def test_concluir_avisa_e_apaga_email(ctx):
    c, arm, enviados = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    r = c.post("/admin/api/concluir", headers=ADM, json={"protocolo": p, "resultado": "publicado",
                                                         "link": "https://contadaurna.com.br/#fake-x"})
    assert r.get_json() == {"status": "publicado", "email": "enviado"}
    assert enviados[0][0] == "pessoa@exemplo.com" and "#fake-x" in enviados[0][2]
    assert 'href="https://contadaurna.com.br/#fake-x"' in enviados[0][3] and p in enviados[0][3]
    assert arm.pegar(f"contatos/{p}.bin") is None
    assert c.get("/status/" + p).get_json()["status"] == "publicado"


def test_email_html_escapa_link(ctx):
    c, arm, enviados = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    c.post("/admin/api/concluir", headers=ADM, json={"protocolo": p, "resultado": "publicado",
                                                     "link": 'https://contadaurna.com.br/"><script>x</script>'})
    assert "<script>" not in enviados[0][3] and "&quot;&gt;&lt;script&gt;" in enviados[0][3]


def test_email_falha_mantem_contato(tmp_path):
    arm = ArmazemLocal(str(tmp_path))
    c = criar_app(armazem=arm, verificar_captcha=lambda t: True, enviar_email=lambda *a: False, env=ENV).test_client()
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    r = c.post("/admin/api/concluir", headers=ADM, json={"protocolo": p, "resultado": "procede"})
    assert r.status_code == 502 and arm.pegar(f"contatos/{p}.bin") is not None


def test_link_externo_recusado(ctx):
    c, _, enviados = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    r = c.post("/admin/api/concluir", headers=ADM, json={"protocolo": p, "resultado": "publicado", "link": "https://golpe.example/"})
    assert r.status_code == 400 and not enviados


def test_admin_exige_senha_e_bloqueia_tentativas(ctx):
    c, _, _ = ctx
    for _ in range(10):
        assert c.get("/admin/api/fila", headers={"Authorization": "Bearer errada"}).status_code == 401
    assert c.get("/admin/api/fila", headers=ADM).status_code == 429


def test_protocolo_invalido_nao_vira_caminho(ctx):
    c, _, _ = ctx
    assert c.get("/status/..%2F..%2Fetc").status_code == 404
    assert c.get("/admin/api/print/../x", headers=ADM).status_code == 404


def test_pessoa_apaga_o_proprio_envio(ctx):
    c, arm, _ = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    assert c.delete("/envio/" + p).status_code == 200
    assert arm.listar("") == [] and c.get("/status/" + p).status_code == 404


def test_limite_por_ip(ctx):
    c, _, _ = ctx
    codigos = [enviar(c).status_code for _ in range(6)]
    assert codigos[:5] == [201] * 5 and codigos[5] == 429


def test_email_invalido(ctx):
    assert enviar(ctx[0], email="nao é email").status_code == 400


def test_limite_de_espaco(tmp_path):
    arm = ArmazemLocal(str(tmp_path))
    arm.por("envios/AAAA-BBBB-CCCC/print.jpg", b"x" * 2000, "image/jpeg")
    c = criar_app(armazem=arm, verificar_captcha=lambda t: True, enviar_email=lambda *a: True,
                  env={**ENV, "LIMITE_GB": str(1000 / 1024 ** 3)}).test_client()
    assert c.get("/capacidade").get_json() == {"aceitando": False}
    r = enviar(c)
    assert r.status_code == 503 and "limite" in r.get_json()["erro"]
    assert arm.listar("") == ["envios/AAAA-BBBB-CCCC/print.jpg"]


def test_capacidade_e_uso(ctx):
    c, _, _ = ctx
    assert c.get("/capacidade").get_json() == {"aceitando": True}
    enviar(c)
    u = c.get("/admin/api/uso", headers=ADM).get_json()
    assert u["envios"] == 1 and u["bytes"] > 0 and u["limite_bytes"] == 8 * 1024 ** 3
    assert c.get("/admin/api/uso").status_code == 401


def test_limite_gb_invalido():
    with pytest.raises(RuntimeError):
        criar_app(armazem=object(), verificar_captcha=lambda t: True, enviar_email=lambda *a: True, env={**ENV, "LIMITE_GB": "muito"})


def test_limite_de_consultas(ctx):
    c, _, _ = ctx
    codigos = [c.get("/status/AAAA-BBBB-CCCC").status_code for _ in range(61)]
    assert codigos[:60] == [404] * 60 and codigos[60] == 429


ENV_ROTINA = {**ENV, "ROTINA_TOKEN": "r" * 40}
ROT = {"Authorization": "Bearer " + "r" * 40}
PR = "https://github.com/pedrohrs08/contadaurna/pull/40"


@pytest.fixture
def rot(tmp_path):
    enviados = []
    app = criar_app(armazem=ArmazemLocal(str(tmp_path)), verificar_captcha=lambda t: t == "ok",
                    enviar_email=lambda para, assunto, texto, html_: enviados.append(para) or True, env=ENV_ROTINA)
    return app.test_client(), enviados


def test_rotina_desligada_sem_token(ctx):
    c, _, _ = ctx
    assert c.get("/rotina/api/fila", headers=ADM).status_code == 401
    assert c.get("/rotina/api/fila", headers={"Authorization": "Bearer "}).status_code == 401


def test_rotina_token_igual_ao_admin():
    with pytest.raises(RuntimeError):
        criar_app(armazem=object(), verificar_captcha=lambda t: True, enviar_email=lambda *a: True,
                  env={**ENV, "ROTINA_TOKEN": ENV["ADMIN_TOKEN"]})


def test_rotina_fluxo_completo(rot):
    c, enviados = rot
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    assert c.get("/rotina/api/fila", headers=ADM).status_code == 401  # admin não serve para a rotina
    fila = c.get("/rotina/api/fila", headers=ROT).get_json()
    assert len(fila) == 1 and set(fila[0]) == {"protocolo", "criado", "onde", "status", "pr"}
    assert (fila[0]["protocolo"], fila[0]["status"]) == (p, "na_fila")
    assert "email" not in json.dumps(fila) and "tem_email" not in fila[0]
    assert c.get("/rotina/api/print/" + p, headers=ROT).mimetype == "image/jpeg"
    # a rotina não pode concluir nem apagar pelas rotas de admin
    assert c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "descartado"}, headers=ROT).status_code == 401
    assert c.post("/admin/api/apagar", json={"protocolo": p}, headers=ROT).status_code == 401
    # publicar antes do rascunho é recusado
    assert c.post("/rotina/api/publicado", json={"protocolo": p, "link": "https://contadaurna.com.br/#fake-x"}, headers=ROT).status_code == 409
    assert c.post("/rotina/api/rascunho", json={"protocolo": p, "pr": "https://github.com/outro/repo/pull/1"}, headers=ROT).status_code == 400
    assert c.post("/rotina/api/rascunho", json={"protocolo": p, "pr": PR}, headers=ROT).status_code == 200
    assert c.post("/rotina/api/rascunho", json={"protocolo": p, "pr": PR}, headers=ROT).status_code == 409
    assert c.get("/status/" + p).get_json() == {"status": "rascunho", "link": ""}
    assert c.get("/admin/api/fila", headers=ADM).get_json()[0]["pr"] == PR
    assert c.post("/rotina/api/publicado", json={"protocolo": p, "link": "https://malicioso.example/#fake-x"}, headers=ROT).status_code == 400
    r = c.post("/rotina/api/publicado", json={"protocolo": p, "link": "https://contadaurna.com.br/#fake-x"}, headers=ROT)
    assert r.get_json() == {"status": "publicado", "email": "enviado"}
    assert enviados == ["pessoa@exemplo.com"]
    assert c.get("/rotina/api/fila", headers=ROT).get_json() == []


def test_admin_conclui_rascunho(rot):
    c, _ = rot
    p = enviar(c).get_json()["protocolo"]
    c.post("/rotina/api/rascunho", json={"protocolo": p, "pr": PR}, headers=ROT)
    r = c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "procede"}, headers=ADM)
    assert r.get_json()["status"] == "procede"
