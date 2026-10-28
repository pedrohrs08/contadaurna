#!/usr/bin/env python3
"""Transforma uma página (index.html, privacidade.html) de um PR na versão de teste publicada em /teste/pr-N/.

Uso: python3 scripts/marcar_teste.py <página.html> <número do PR>

- tira o GoatCounter (as visitas de teste não entram na estatística do site);
- pede aos buscadores para não indexar a página;
- põe uma faixa no topo avisando que é uma versão de teste.
"""
import re
import sys

caminho, pr = sys.argv[1], sys.argv[2]
html = open(caminho, encoding="utf-8").read()

html = re.sub(r'<script data-goatcounter=[^>]*></script>\n?', "", html)
html = html.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
faixa = (f'<div style="background:#a86400;color:#fff;font:600 14px/1.4 Arial,sans-serif;'
         f'text-align:center;padding:8px 12px">VERSÃO DE TESTE do PR #{pr}, ainda não publicada. '
         f'<a style="color:#fff" href="https://contadaurna.com.br/">Ir para o site oficial</a></div>')
html, n = re.subn(r'(<body[^>]*>)', r'\1\n' + faixa.replace("\\", "\\\\"), html, count=1)
if n != 1 or "gc.zgo.at" in html:
    sys.exit("marcar_teste.py: estrutura da página mudou; confira o script")
open(caminho, "w", encoding="utf-8").write(html)
