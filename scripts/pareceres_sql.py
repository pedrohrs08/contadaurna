#!/usr/bin/env python3
"""Gera banco/migrations/0002_pareceres_iniciais.sql a partir de fakes.json.

Usado uma vez, na mudança dos pareceres do index.html para o banco: cada parecer entra já
publicado, na mesma ordem da aba (o primeiro do arquivo fica no topo).
"""
import json
import secrets

ENTRADA, SAIDA = "fakes.json", "banco/migrations/0002_pareceres_iniciais.sql"
QUANDO = "2026-10-31T00:00:00Z"


def q(t):
    return "'" + t.replace("'", "''") + "'"


def main():
    fakes = json.load(open(ENTRADA, encoding="utf-8"))
    linhas = ["-- Os pareceres que estavam no index.html até 31/10/2026, já publicados.",
              "-- Gerado por scripts/pareceres_sql.py a partir de fakes.json."]
    for i, f in enumerate(fakes):
        dados = json.dumps({k: v for k, v in f.items() if k != "id"}, ensure_ascii=False)
        posicao = len(fakes) - i
        linhas.append(f"INSERT INTO pareceres (id, publicado, posicao, chave, criado, atualizado, publicado_em) VALUES "
                      f"({q(f['id'])}, {q(dados)}, {posicao}, {q(secrets.token_hex(16))}, {q(QUANDO)}, {q(QUANDO)}, {q(QUANDO)});")
        linhas.append(f"INSERT INTO historico (quando, quem, tipo, ref, acao, dados) VALUES "
                      f"({q(QUANDO)}, 'sistema', 'parecer', {q(f['id'])}, 'importado do index.html', {q(dados)});")
    open(SAIDA, "w", encoding="utf-8").write("\n".join(linhas) + "\n")
    print(f"{len(fakes)} pareceres em {SAIDA}")


if __name__ == "__main__":
    main()
