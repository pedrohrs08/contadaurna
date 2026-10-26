#!/usr/bin/env python3
"""Salva os dados finais do TSE dentro do repositório, para o app funcionar como site estático.

Baixa os mesmos arquivos que o app usa (UFs e Brasil nos dois turnos, lista de municípios
e as grandes cidades) para tse/oficial/... e grava tse/congelado.json. Com esse arquivo
presente, o app lê só as cópias locais, sem consultar o TSE. Só usa a biblioteca padrão.

Uso:  python3 congelar.py
"""
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TSE = "https://resultados.tse.jus.br/oficial/"
CICLO = "ele2026"
ELE_1T, ELE_2T = "6257", "6258"
UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()


def grandes_do_index():
    """Lê a lista GRANDES do index.html, para as duas listas nunca ficarem diferentes."""
    html = open("index.html", encoding="utf-8").read()
    bloco = re.search(r"const GRANDES = \{(.*?)\n\};", html, re.S).group(1)
    return {uf: set(nomes.split("|")) for uf, nomes in re.findall(r'(\w\w): "([^"]*)"', bloco)}


def norm(t):
    t = unicodedata.normalize("NFD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).upper().strip()


def baixar(caminho):
    req = urllib.request.Request(TSE + caminho, headers={"User-Agent": "placar-2026"})
    with urllib.request.urlopen(req, timeout=30) as r:
        corpo = r.read()
    json.loads(corpo)  # garante que veio um JSON válido
    destino = os.path.join("tse", "oficial", *caminho.split("/"))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(corpo)
    return corpo


def tentar(caminho):
    try:
        baixar(caminho)
        return True
    except Exception as e:
        print(f"  falhou: {caminho} ({e})")
        return False


def uf_path(ele, uf):
    return f"{CICLO}/{ele}/dados/{uf}/{uf}-c0001-e{ele.zfill(6)}-u.json"


def mun_path(ele, uf, cd):
    return f"{CICLO}/{ele}/dados/{uf}/{uf}{cd}-c0001-e{ele.zfill(6)}-u.json"


def municipios(cfg, grandes):
    """Mesma busca do app: nós com lista "mu" e código da UF em "cd"."""
    out = []

    def walk(no):
        if isinstance(no, list):
            for x in no:
                walk(x)
        elif isinstance(no, dict):
            if isinstance(no.get("mu"), list) and no.get("cd"):
                uf = str(no["cd"]).lower()
                quer = grandes.get(uf, set())
                out.extend((uf, str(m["cd"])) for m in no["mu"] if norm(m.get("nm")) in quer)
                return
            for v in no.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(cfg)
    return out


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    grandes = grandes_do_index()
    caminhos = [uf_path(e, uf) for e in (ELE_1T, ELE_2T) for uf in UFS] + [uf_path(ELE_2T, "br")]
    print(f"Baixando {len(caminhos)} arquivos de UFs…")
    with ThreadPoolExecutor(8) as ex:
        ok_ufs = sum(ex.map(tentar, caminhos))
    if ok_ufs < 40:
        sys.exit(f"Só {ok_ufs} de {len(caminhos)} arquivos de UF vieram. Confira a internet e tente de novo.")

    cfg = None
    for ele in (ELE_2T, ELE_1T):
        try:
            cfg = json.loads(baixar(f"{CICLO}/{ele}/config/mun-e{ele.zfill(6)}-cm.json"))
            break
        except Exception as e:
            print(f"  lista de municípios da eleição {ele} indisponível ({e})")
    ok_mun, mus = 0, []
    if cfg:
        mus = municipios(cfg, grandes)
        caminhos_mun = [mun_path(e, uf, cd) for e in (ELE_1T, ELE_2T) for uf, cd in mus]
        print(f"Baixando {len(caminhos_mun)} arquivos de {len(mus)} grandes cidades…")
        with ThreadPoolExecutor(8) as ex:
            ok_mun = sum(ex.map(tentar, caminhos_mun))
    else:
        print("Sem lista de municípios: o app vai usar só o modelo por UF.")

    agora = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(os.path.join("tse", "congelado.json"), "w", encoding="utf-8") as f:
        json.dump({"salvo_em": agora, "ufs": ok_ufs, "municipios": ok_mun}, f, ensure_ascii=False)
    print(f"Pronto: {ok_ufs} arquivos de UF e {ok_mun} de cidades salvos em tse/. Salvo em {agora}.")


if __name__ == "__main__":
    main()
