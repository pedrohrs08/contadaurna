#!/usr/bin/env python3
"""Servidor local do Placar de Probabilidade 2026.

Serve o index.html desta pasta e repassa /tse/... para https://resultados.tse.jus.br/...
(evita bloqueios de CORS). Só usa a biblioteca padrão do Python 3.

Uso:  python3 servir.py          e abra http://localhost:8000
      python3 servir.py --rede   libera o acesso para outros aparelhos da rede local
"""
import http.server
import os
import socket
import socketserver
import sys
import urllib.request
import webbrowser

PORTA = int(os.environ.get("PORTA", "8000"))
TSE = "https://resultados.tse.jus.br/"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/tse/"):
            caminho = self.path[len("/tse/"):].split("?")[0]
            if not caminho.startswith("oficial/") or ".." in caminho:
                self.send_error(400, "caminho inválido")
                return
            try:
                req = urllib.request.Request(TSE + caminho, headers={"User-Agent": "placar-2026"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    corpo = r.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corpo)
            except urllib.error.HTTPError as e:
                self.send_error(e.code, str(e.reason))
            except Exception as e:  # rede fora do ar, timeout etc.
                self.send_error(502, str(e))
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        pass


def porta_em_uso(porta):
    """True se algum programa já atende nessa porta (em IPv4 ou IPv6).

    No Mac, outro programa ouvindo em ::1 ou 127.0.0.1 não impede o bind em 0.0.0.0,
    mas o navegador abriria o outro programa em "localhost". Por isso testamos conectando.
    """
    for familia, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(familia, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, porta)) == 0:
                    return True
        except OSError:
            pass
    return False


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    rede = "--rede" in sys.argv
    srv = None
    for PORTA in range(PORTA, PORTA + 20):  # pula portas já ocupadas por outros programas
        if porta_em_uso(PORTA):
            continue
        try:
            srv = socketserver.ThreadingTCPServer(("0.0.0.0" if rede else "127.0.0.1", PORTA), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit("Nenhuma porta livre encontrada. Tente: PORTA=9000 python3 servir.py")
    with srv:
        url = f"http://127.0.0.1:{PORTA}"
        print(f"Placar rodando em {url}  (Ctrl+C para sair)")
        if rede:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                print(f"Na rede local, abra nos outros aparelhos: http://{ip}:{PORTA}")
            except OSError:
                print("Na rede local, use o IP deste computador com a porta", PORTA)
        try:
            webbrowser.open(url)
        except Exception:
            pass
        srv.serve_forever()
