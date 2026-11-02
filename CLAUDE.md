# CLAUDE.md: contadaurna

Site estático do 2º turno de 2026 (contadaurna.com.br). Detalhes no README.md; aqui ficam só as regras para trabalhar gastando poucos tokens.

## Economia de contexto (obrigatório)

- **Nunca leia o `index.html` inteiro** (~260 KB, ~70 mil tokens). Ache o trecho com `grep -n` e leia só as linhas necessárias (`sed -n 'A,Bp'`). As seções começam com `// ---------- Nome ----------`:
  - `// ---------- Aba Cronologia ----------`: `FONTES_CRON` e `CRONO` (itens da cronologia).
  - `// ---------- Data de atualização, correções ...`: `ATUALIZADO` e `CORRECOES`.
  - `// ---------- Aba Desmentindo fake news ----------`: `FAKES_API` e a aba Fake news.
  - `// ---------- Pesquisas da véspera × urnas ...`: `PESQ_VESPERA`.
- Para acrescentar um item, edite só o fim da lista certa (por exemplo, o último item de `CRONO`), sem reescrever o arquivo.
- **Não abra os JSON da pasta `tse/`** (3,4 MB). Para um número, use `jq` no arquivo exato (ex.: `jq '.carg[0].agr[].par[].cand[] | {n, vap}' tse/oficial/ele2026/6258/dados/ba/ba-c0001-e006258-u.json`).
- Não leia `fakes.json` nem `banco/migrations/*.sql` inteiros; use `jq` ou `grep`.
- Não use subagentes nem pesquisa profunda sem o Pedro pedir.

## Regras de conteúdo

- Só o que a fonte diz, com link aberto antes de citar. Fato, opinião e fake bem separados; versões divergentes mostradas.
- `prej` mede só o efeito no resultado (votos): "Nenhuma" ou "Não dá para dizer" quando for o caso.
- Nunca publique @, nome ou foto do autor de um post checado; escreva "autor do post".
- A cada mudança de conteúdo, atualize `ATUALIZADO` (horário de Brasília). Erro corrigido em item antigo vai também para `CORRECOES`.

## Fluxo

- Nunca faça push na `main` nem merge. Toda mudança vai por PR; o workflow `teste.yml` publica uma cópia em `contadaurna.com.br/teste/pr-N/` para o Pedro testar.
- Testar: `python3 servir.py` e abrir a aba alterada com Playwright (sem erro no console, sem overflow na largura de celular). Servidor de envios: `pytest -q envios`.
- Arquivo novo que o site precisa servir deve entrar na lista de cópia de `.github/workflows/pages.yml` e `teste.yml` (e em `PUBLICOS` do `servir.py`).
- Rotina de envios: siga `envios/ROTINA.md`.
