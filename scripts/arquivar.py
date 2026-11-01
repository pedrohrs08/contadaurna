#!/usr/bin/env python3
"""Guarda no archive.org uma cópia de cada página citada como fonte no index.html e nos pareceres (fakes.json).

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
    html = open("index.html", encoding="utf-8").read() + open("fakes.json", encoding="utf-8").read()
    achados = re.findall(r'https?://[^\s"\'<>`)]+', html)
    return sorted({u.rstrip(".,;") for u in achados if not PULAR.match(u) and "." in urllib.parse.urlparse(u).netloc})


def copia(url):
    """Endereço da cópia de 2026 mais próxima de 26/10, ou None."""
    q = urllib.parse.urlencode({"url": url, "timestamp": "20261026"})
    with urllib.request.urlopen(f"https://archive.org/wayback/available?{q}", timeout=60) as r:
        snap = json.load(r).get("archived_snapshots", {}).get("closest") or {}
    if snap.get("available") and str(snap.get("timestamp", "")).startswith("2026"):
        return snap["url"]
    return None


def salvar(url):
    req = urllib.request.Request("https://web.archive.org/save/" + url, headers={"User-Agent": "eleicoes2026-arquivo"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.geturl() if "/web/" in r.geturl() else None


def main():
    lista = links()
    print(f"{len(lista)} links de fonte")
    registro = {}
    for url in lista:
        try:
            achado = copia(url)
            if not achado:
                achado = salvar(url)
                time.sleep(20)
            registro[url] = achado
            print(f"{'ok' if achado else 'sem cópia'}: {url} -> {achado}")
        except Exception as e:
            registro[url] = None
            print(f"falhou: {url} ({e})")
            time.sleep(20)
    with open("arquivo-fontes.json", "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"Pronto. {sum(1 for v in registro.values() if v)} de {len(registro)} com cópia.")


if __name__ == "__main__":
    main()
