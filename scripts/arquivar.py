#!/usr/bin/env python3
"""Guarda no archive.org uma cópia de cada página citada como fonte no index.html.

Roda no GitHub Actions (ver .github/workflows/arquivar.yml). Pula as páginas que já têm
cópia de 2026 e pede uma nova cópia das outras, com pausa entre os pedidos para respeitar
o limite do archive.org. Só usa a biblioteca padrão.
"""
import json
import re
import time
import urllib.parse
import urllib.request

PULAR = re.compile(r"^https?://(localhost|www\.w3\.org|fonts\.googleapis\.com|fonts\.gstatic\.com|web\.archive\.org|github\.com|resultados\.tse\.jus\.br)[/:]?")


def links():
    html = open("index.html", encoding="utf-8").read()
    achados = re.findall(r'https?://[^\s"\'<>`)]+', html)
    return sorted({u.rstrip(".,;") for u in achados if not PULAR.match(u) and "." in urllib.parse.urlparse(u).netloc})


def tem_copia(url):
    q = urllib.parse.urlencode({"url": url, "timestamp": "20261026"})
    with urllib.request.urlopen(f"https://archive.org/wayback/available?{q}", timeout=60) as r:
        snap = json.load(r).get("archived_snapshots", {}).get("closest") or {}
    return snap.get("available") and str(snap.get("timestamp", "")).startswith("2026")


def salvar(url):
    req = urllib.request.Request("https://web.archive.org/save/" + url, headers={"User-Agent": "eleicoes2026-arquivo"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status


def main():
    lista = links()
    print(f"{len(lista)} links de fonte")
    falhas = 0
    for url in lista:
        try:
            if tem_copia(url):
                print(f"já arquivado: {url}")
                continue
            print(f"arquivando ({salvar(url)}): {url}")
        except Exception as e:
            falhas += 1
            print(f"falhou: {url} ({e})")
        time.sleep(20)
    print(f"Pronto. {falhas} falha(s).")


if __name__ == "__main__":
    main()
