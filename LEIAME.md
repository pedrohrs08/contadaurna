# Placar de Probabilidade 2026

App que estima a probabilidade de vitória de Lula e Flávio Bolsonaro no 2º turno presidencial de 25/10/2026.

## Como abrir

1. Baixe `index.html` e `servir.py` para a mesma pasta.
2. No terminal, dentro da pasta: `python3 servir.py`
3. O navegador abre em http://localhost:8000. Clique em **Atualizar** (ou marque "atualizar a cada 60 s").

Para amigos na mesma rede Wi-Fi acessarem: `python3 servir.py --rede` e abra nos outros aparelhos o endereço que aparece no terminal (ex.: http://192.168.0.10:8000).

Também dá para abrir o `index.html` direto no navegador: ele tenta buscar o TSE diretamente. Se o navegador bloquear, use o `servir.py`, que repassa as requisições ao TSE.

A aba "Simulação" mostra o app funcionando com números inventados, sem precisar do TSE. Cada toque em "Avançar apuração" apura mais um pedaço.

Se a porta 8000 estiver ocupada por outro programa, o `servir.py` usa a próxima livre (8001, 8002…) e mostra qual no terminal.

## Fontes de dados

- 2º turno (parcial): `https://resultados.tse.jus.br/oficial/ele2026/6258/dados/{uf}/{uf}-c0001-e006258-u.json`
- 1º turno (perfil de cada UF): mesma estrutura com a eleição `6257`
- Municípios: lista em `ele2026/{eleição}/config/mun-e00{eleição}-cm.json` e um arquivo por município em `dados/{uf}/{uf}{código}-c0001-e00{eleição}-u.json`. O app baixa só capitais e grandes cidades (cerca de 140).
- Pesquisas da véspera (24/10/2026, votos válidos): AtlasIntel, CNT/MDA, Datafolha, Futura, Gerp, Nexus/BTG e Quaest. A tabela é editável no app.

## Modelo

1. Unidades: em cada UF, as capitais e grandes cidades separadas e o "resto da UF" (interior). Sem dados municipais, a UF inteira vira uma unidade. A base de cada unidade é a fatia de Lula entre Lula e Flávio no 1º turno de 2026.
2. Deslocamento nacional uniforme (escala logística) para que a média das pesquisas seja reproduzida: "esperado pré-apuração".
3. A diferença entre a parcial de cada unidade e o esperado ganha peso conforme a fração apurada (as primeiras seções não são amostra aleatória). O que falta numa unidade recebe a tendência da própria UF, que por sua vez é puxada para a tendência nacional e para as pesquisas. Como as cidades grandes são apuradas antes, separar cidade e interior corrige boa parte do viés da ordem de apuração.
4. Monte Carlo (20 mil simulações) com erro nacional (t de 4 g.l.), erro por UF, erro por unidade, viés de ordem de apuração e erro de comparecimento.
5. Confiabilidade: Baixa, Moderada, Alta ou Muito alta, pela fração apurada e pela largura do intervalo.

Limitação: os parâmetros de erro não foram calibrados com a ordem de apuração de 2018 e 2022, porque essas séries históricas não estão disponíveis de forma aberta.

Os parâmetros ficam em "Parâmetros do modelo" no fim da página. É um modelo estatístico e não substitui o resultado oficial.
