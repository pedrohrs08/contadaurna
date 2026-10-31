"""Testes do serviço de envio. Rodar:  pip install -r requirements.txt pytest && pytest envios"""
import io
import json
import os

import pytest
from PIL import Image

from app import ArmazemLocal, BancoLocal, criar_app, validar_parecer

ENV = {"EMAIL_KEY": "k" * 40, "ADMIN_TOKEN": "a" * 40, "ORIGENS": "https://contadaurna.com.br,https://www.contadaurna.com.br"}
ADM = {"Authorization": "Bearer " + "a" * 40}


@pytest.fixture
def ctx(tmp_path):
    enviados = []
    arm = ArmazemLocal(str(tmp_path))
    app = criar_app(armazem=arm, banco=BancoLocal(), verificar_captcha=lambda t: t == "ok",
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
    c = criar_app(armazem=arm, banco=BancoLocal(), verificar_captcha=lambda t: True, enviar_email=lambda *a: False, env=ENV).test_client()
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
    arm, banco = ArmazemLocal(str(tmp_path)), BancoLocal()
    banco.consultar("INSERT INTO envios (protocolo, criado, print_chave, print_bytes) VALUES "
                    "('AAAA-BBBB-CCCC', '2099-01-01T00:00:00Z', 'envios/AAAA-BBBB-CCCC/print.jpg', 2000)")
    c = criar_app(armazem=arm, banco=banco, verificar_captcha=lambda t: True, enviar_email=lambda *a: True,
                  env={**ENV, "LIMITE_GB": str(1000 / 1024 ** 3)}).test_client()
    assert c.get("/capacidade").get_json() == {"aceitando": False}
    r = enviar(c)
    assert r.status_code == 503 and "limite" in r.get_json()["erro"]
    assert arm.listar("") == []


def test_limite_do_banco(tmp_path):
    c = criar_app(armazem=ArmazemLocal(str(tmp_path)), banco=BancoLocal(), verificar_captcha=lambda t: True,
                  enviar_email=lambda *a: True, env={**ENV, "LIMITE_BANCO_MB": "0.01"}).test_client()
    assert c.get("/capacidade").get_json() == {"aceitando": False}
    assert enviar(c).status_code == 503


def test_capacidade_e_uso(ctx):
    c, _, _ = ctx
    assert c.get("/capacidade").get_json() == {"aceitando": True}
    enviar(c)
    u = c.get("/admin/api/uso", headers=ADM).get_json()
    assert u["envios"] == 1 and u["bytes"] > 0 and u["limite_bytes"] == 8 * 1024 ** 3
    assert 0 < u["banco_bytes"] < u["limite_banco_bytes"] == 400 * 1024 ** 2
    assert c.get("/admin/api/uso").status_code == 401


def test_limite_gb_invalido():
    with pytest.raises(RuntimeError):
        criar_app(armazem=object(), banco=object(), verificar_captcha=lambda t: True, enviar_email=lambda *a: True, env={**ENV, "LIMITE_GB": "muito"})


def test_limite_de_consultas(ctx):
    c, _, _ = ctx
    codigos = [c.get("/status/AAAA-BBBB-CCCC").status_code for _ in range(61)]
    assert codigos[:60] == [404] * 60 and codigos[60] == 429


ENV_ROTINA = {**ENV, "ROTINA_TOKEN": "r" * 40}
ROT = {"Authorization": "Bearer " + "r" * 40}


@pytest.fixture
def rot(tmp_path):
    enviados = []
    app = criar_app(armazem=ArmazemLocal(str(tmp_path)), banco=BancoLocal(), verificar_captcha=lambda t: t == "ok",
                    enviar_email=lambda para, assunto, texto, html_: enviados.append(para) or True, env=ENV_ROTINA)
    return app.test_client(), enviados


def test_rotina_desligada_sem_token(ctx):
    c, _, _ = ctx
    assert c.get("/rotina/api/fila", headers=ADM).status_code == 401
    assert c.get("/rotina/api/fila", headers={"Authorization": "Bearer "}).status_code == 401


def test_rotina_token_igual_ao_admin():
    with pytest.raises(RuntimeError):
        criar_app(armazem=object(), banco=object(), verificar_captcha=lambda t: True, enviar_email=lambda *a: True,
                  env={**ENV, "ROTINA_TOKEN": ENV["ADMIN_TOKEN"]})


FAKES_JSON = json.load(open(os.path.join(os.path.dirname(__file__), "..", "fakes.json"), encoding="utf-8"))


def parecer(**k):
    return {"titulo": "\"Boato de teste\"", "data": "31/10/2026", "texto": "texto do post", "curto": "Não procede.",
            "parecer": "<p><b>Os dados:</b> <a href=\"https://www.tse.jus.br/\">TSE</a></p>", "fontes": [["TSE", "https://www.tse.jus.br/"]], **k}


def test_pareceres_importados_passam_na_conferencia(ctx):
    for f in FAKES_JSON:
        dados, erros = validar_parecer(f)
        assert erros == [], (f["id"], erros)
    c, _, _ = ctx
    lista = c.get("/admin/api/pareceres", headers=ADM).get_json()
    assert [p["id"] for p in lista] == [f["id"] for f in FAKES_JSON] and all(p["no_ar"] and not p["pendente"] for p in lista)


@pytest.mark.parametrize("ruim", [
    {"parecer": "<p>oi</p><script>alert(1)</script>"},
    {"parecer": "<p onclick=\"x()\">oi</p>"},
    {"parecer": "<a href=\"javascript:alert(1)\">x</a>"},
    {"frase": "<img src=x onerror=alert(1)>"},
    {"nums": [["<iframe>", "x"]]},
    {"fontes": [["TSE", "javascript:alert(1)"]]},
    {"fontes": [["<a href='https://x.com'>x</a>", "https://x.com"]]},
    {"data": "amanhã"},
    {"selo": "Mentira"},
    {"extra": "campo"},
])
def test_parecer_perigoso_ou_errado_e_recusado(rot, ruim):
    c, _ = rot
    r = c.put("/rotina/api/parecer/teste", json=parecer(**ruim), headers=ROT)
    assert r.status_code == 400 and r.get_json()["detalhes"]


def test_id_de_parecer_invalido(rot):
    c, _ = rot
    assert c.put("/rotina/api/parecer/Com%20Espaco", json=parecer(), headers=ROT).status_code == 400


def test_rotina_fluxo_completo(rot):
    c, enviados = rot
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    assert c.get("/rotina/api/fila", headers=ADM).status_code == 401  # admin não serve para a rotina
    fila = c.get("/rotina/api/fila", headers=ROT).get_json()
    assert len(fila) == 1 and set(fila[0]) == {"protocolo", "criado", "onde", "status", "publicavel", "motivo", "parecer", "tem_print"}
    assert (fila[0]["protocolo"], fila[0]["status"], fila[0]["publicavel"]) == (p, "na_fila", None)
    assert "email" not in json.dumps(fila)
    assert c.get("/rotina/api/print/" + p, headers=ROT).mimetype == "image/jpeg"
    # a rotina não pode concluir, apagar nem publicar
    assert c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "descartado"}, headers=ROT).status_code == 401
    assert c.post("/admin/api/apagar", json={"protocolo": p}, headers=ROT).status_code == 401
    # avaliar como publicável exige o parecer gravado antes
    assert c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": True, "parecer": "boato-teste"}, headers=ROT).status_code == 400
    r = c.put("/rotina/api/parecer/boato-teste", json=parecer(), headers=ROT).get_json()
    assert (r["no_ar"], r["pendente"]) == (False, True) and r["previa"].startswith("https://contadaurna.com.br/?previa=boato-teste.")
    assert c.post("/admin/api/parecer/boato-teste/publicar", headers=ROT).status_code == 401
    r = c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": True, "parecer": "boato-teste"}, headers=ROT).get_json()
    assert (r["status"], r["parecer"]) == ("rascunho", "boato-teste")
    assert c.get("/status/" + p).get_json() == {"status": "rascunho", "link": ""}
    item = c.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["publicavel"], item["parecer"], item["parecer_pendente"], item["link"]) == (
        True, "boato-teste", True, "https://contadaurna.com.br/#fake-boato-teste")
    assert enviados == []
    # o responsável publica: o parecer vai para o topo e o aviso sai sozinho
    r = c.post("/admin/api/parecer/boato-teste/publicar", headers=ADM).get_json()
    assert r["no_ar"] and r["avisos"] == [{"protocolo": p, "status": "publicado", "email": "enviado"}]
    assert enviados == ["pessoa@exemplo.com"]
    assert c.get("/admin/api/pareceres", headers=ADM).get_json()[0]["id"] == "boato-teste"
    assert c.get("/status/" + p).get_json() == {"status": "publicado", "link": "https://contadaurna.com.br/#fake-boato-teste"}
    assert c.get("/rotina/api/fila", headers=ROT).get_json() == []
    acoes = [h["acao"] for h in c.get(f"/admin/api/historico?tipo=envio&ref={p}", headers=ADM).get_json()]
    assert acoes[::-1] == ["recebido", "avaliado: publicável", "concluído: publicado", "aviso enviado por e-mail e endereço apagado"]
    assert "pessoa@exemplo.com" not in json.dumps(c.get("/admin/api/historico", headers=ADM).get_json())


def test_rotina_nao_publicavel_fica_para_o_responsavel(rot):
    c, enviados = rot
    p = enviar(c).get_json()["protocolo"]
    assert c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": False}, headers=ROT).status_code == 400  # sem motivo
    r = c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": False, "motivo": "fora do tema eleição"}, headers=ROT)
    assert r.get_json()["status"] == "na_fila"
    item = c.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["publicavel"], item["motivo"]) == (False, "fora do tema eleição")
    assert c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "descartado"}, headers=ADM).get_json()["status"] == "descartado"
    assert c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": False, "motivo": "x"}, headers=ROT).status_code == 409


def test_rotina_marca_repetido_e_admin_avisa(rot):
    c, enviados = rot
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    link = "https://contadaurna.com.br/#fake-venezuela-prorrogacao"
    r = c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": True, "parecer": "venezuela-prorrogacao"}, headers=ROT)
    assert r.get_json()["status"] == "repetido"
    assert enviados == []  # a rotina não dispara o aviso
    assert c.get("/rotina/api/fila", headers=ROT).get_json() == []  # não volta para a rotina
    item = c.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["status"], item["link"], item["parecer_no_ar"]) == ("repetido", link, True)
    r = c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "ja_publicado", "link": link}, headers=ADM)
    assert r.get_json() == {"status": "ja_publicado", "email": "enviado"}
    assert enviados == ["pessoa@exemplo.com"]


def test_correcao_de_parecer_no_ar(rot):
    c, _ = rot
    original = c.get("/rotina/api/parecer/venezuela-prorrogacao", headers=ROT).get_json()
    assert original["publicado"] and original["pendente"] is None
    novo = {**original["publicado"], "curto": "Versão corrigida."}
    posicao = [p["id"] for p in c.get("/admin/api/pareceres", headers=ADM).get_json() if p["no_ar"]]
    assert c.put("/rotina/api/parecer/venezuela-prorrogacao", json=novo, headers=ROT).status_code == 200
    r = c.get("/admin/api/parecer/venezuela-prorrogacao", headers=ADM).get_json()
    assert r["publicado"] == original["publicado"] and r["pendente"]["curto"] == "Versão corrigida."  # o site não muda ainda
    c.post("/admin/api/parecer/venezuela-prorrogacao/publicar", headers=ADM)
    r = c.get("/admin/api/parecer/venezuela-prorrogacao", headers=ADM).get_json()
    assert r["publicado"]["curto"] == "Versão corrigida." and r["pendente"] is None
    assert [p["id"] for p in c.get("/admin/api/pareceres", headers=ADM).get_json() if p["no_ar"]] == posicao  # não muda de lugar
    h = c.get("/admin/api/historico?tipo=parecer&ref=venezuela-prorrogacao", headers=ADM).get_json()
    assert [x["acao"] for x in h] == ["nova versão publicada", "versão pendente gravada", "importado do index.html"]
    assert h[-1]["dados"] == {k: v for k, v in original["publicado"].items()}  # a versão antiga fica guardada


def test_descartar_e_tirar_do_ar(rot):
    c, _ = rot
    p = enviar(c).get_json()["protocolo"]
    c.put("/rotina/api/parecer/boato-teste", json=parecer(), headers=ROT)
    c.post("/rotina/api/avaliar", json={"protocolo": p, "publicavel": True, "parecer": "boato-teste"}, headers=ROT)
    assert c.post("/admin/api/parecer/boato-teste/descartar", headers=ADM).status_code == 200
    assert c.get("/admin/api/parecer/boato-teste", headers=ADM).status_code == 404
    item = c.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["status"], item["parecer"]) == ("na_fila", None)  # volta para a fila
    assert c.post("/admin/api/parecer/venezuela-prorrogacao/tirar", headers=ADM).status_code == 200
    r = c.get("/admin/api/parecer/venezuela-prorrogacao", headers=ADM).get_json()
    assert r["publicado"] is None and r["pendente"]  # nada se perde
    c.post("/admin/api/parecer/venezuela-prorrogacao/publicar", headers=ADM)
    assert c.get("/admin/api/parecer/venezuela-prorrogacao", headers=ADM).get_json()["no_ar"]


def test_importa_envios_antigos_do_balde(tmp_path):
    arm, banco = ArmazemLocal(str(tmp_path)), BancoLocal()
    arm.por("envios/BERZ-4MUI-WMT3/print.jpg", b"x" * 300, "image/jpeg")
    arm.por("envios/BERZ-4MUI-WMT3/meta.json", json.dumps({"protocolo": "BERZ-4MUI-WMT3", "criado": "2099-10-29T20:00:00Z",
            "onde": "zap", "status": "repetido", "link": "https://contadaurna.com.br/#fake-x", "concluido": "", "tem_email": True}).encode(), "application/json")
    c = criar_app(armazem=arm, banco=banco, verificar_captcha=lambda t: True, enviar_email=lambda *a: True, env=ENV).test_client()
    item = c.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["protocolo"], item["status"], item["tem_email"], item["tem_print"]) == ("BERZ-4MUI-WMT3", "repetido", True, True)
    assert arm.pegar("envios/BERZ-4MUI-WMT3/meta.json") is None
    assert c.get("/admin/api/uso", headers=ADM).get_json()["bytes"] == 300


def test_apaga_dados_depois_de_30_dias(tmp_path):
    arm, banco = ArmazemLocal(str(tmp_path)), BancoLocal()
    c = criar_app(armazem=arm, banco=banco, verificar_captcha=lambda t: True, enviar_email=lambda *a: True, env=ENV).test_client()
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    banco.consultar("UPDATE envios SET criado = '2026-01-01T00:00:00Z' WHERE protocolo = ?", (p,))
    # a limpeza roda no máximo a cada 10 minutos; uma aplicação nova roda na hora
    c2 = criar_app(armazem=arm, banco=banco, verificar_captcha=lambda t: True, enviar_email=lambda *a: True, env=ENV).test_client()
    item = c2.get("/admin/api/fila", headers=ADM).get_json()[0]
    assert (item["status"], item["onde"], item["tem_print"], item["tem_email"]) == ("expirado", "", False, False)
    assert arm.pegar(f"contatos/{p}.bin") is None
    assert c2.get("/admin/api/uso", headers=ADM).get_json()["envios"] == 0


def test_texto_do_aviso_ja_publicado(ctx):
    c, _, enviados = ctx
    p = enviar(c, email="pessoa@exemplo.com").get_json()["protocolo"]
    link = "https://contadaurna.com.br/#fake-x"
    c.post("/admin/api/concluir", json={"protocolo": p, "resultado": "ja_publicado", "link": link}, headers=ADM)
    _, _, texto, html_ = enviados[0]
    assert "Obrigado por enviar" in texto and "publicado anteriormente" in texto and link in texto
    assert "Já checado" in html_ and link in html_
