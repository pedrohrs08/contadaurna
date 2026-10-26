# Placar de Probabilidade 2026

App que estima a probabilidade de vitória de Lula e Flávio Bolsonaro no 2º turno presidencial de 25/10/2026.

## Como abrir

1. Baixe `index.html` e `servir.py` para a mesma pasta.
2. No terminal, dentro da pasta: `python3 servir.py`
3. O navegador abre em http://localhost:8000. Clique em **Atualizar** (ou marque "atualizar a cada 60 s").

Para amigos na mesma rede Wi-Fi acessarem: `python3 servir.py --rede` e abra nos outros aparelhos o endereço que aparece no terminal (ex.: http://192.168.0.10:8000).

Também dá para abrir o `index.html` direto no navegador: ele tenta buscar o TSE diretamente. Se o navegador bloquear, use o `servir.py`, que repassa as requisições ao TSE.

A aba "Simulação" mostra o app funcionando com números inventados, sem precisar do TSE. Cada toque em "Avançar apuração" apura mais um pedaço.

A aba "Prorrogação" compara o horário normal (até 17h) com o horário estendido (até 19h). Você informa, por região, quantas seções ficaram abertas depois das 17h e que fatia desses votos foi para Lula (Flávio fica com o resto), além do fluxo de eleitores por hora. O app estima quantos votos entraram na prorrogação, tira esses votos do resultado oficial e mostra se o vencedor mudaria, quanto Lula precisaria ter na prorrogação para virar e quantos votos seriam necessários. Os valores iniciais são suposições, porque o TSE não divulgou os votos depois das 17h.

Se a porta 8000 estiver ocupada por outro programa, o `servir.py` usa a próxima livre (8001, 8002…) e mostra qual no terminal.

## Colocar no ar (Render)

O repositório já tem o `render.yaml`. Para publicar:

1. Crie uma conta em https://render.com (dá para entrar com o GitHub).
2. Clique em **New > Blueprint**, autorize o Render a ver o repositório `probabilidade` e escolha-o.
3. Confirme em **Apply**. Em 1 a 2 minutos o app fica no ar num endereço como `https://placar-2026.onrender.com`.

No plano grátis, o serviço "dorme" depois de 15 minutos sem acesso, e o primeiro acesso depois disso demora cerca de 1 minuto. Cada novo push na branch `main` publica a versão nova sozinho.

No modo nuvem (`python3 servir.py --nuvem`), o servidor usa a porta da variável `PORT`, guarda cada arquivo do TSE por 30 segundos (para não sobrecarregar o TSE com muitos acessos) e só serve o `index.html`.



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
