# Eleições 2026

Site para entender o 2º turno presidencial de 25 de outubro de 2026, entre Lula (13) e Flávio Bolsonaro (22), com números que qualquer pessoa pode conferir.

**No ar:** https://contadaurna.com.br/

## Propósito

Depois do 2º turno circularam muitas versões sobre o que aconteceu no dia: ônibus parados em Salvador, a prorrogação da votação até as 19h, pedidos de anulação e boatos de fraude. Este site junta, num lugar só:

- o **resultado oficial** do TSE;
- a **cronologia do dia**, separando fato, opinião e fake news, com links para veículos de linhas editoriais diferentes;
- o **impacto da extensão do horário**, medido com os registros públicos das urnas;
- a comparação entre as **pesquisas da véspera e as urnas**;
- a **checagem de boatos** que circularam depois da eleição.

É um projeto pessoal, sem fins lucrativos e sem vínculo com partidos ou com o TSE. Foi construído com ajuda de inteligência artificial (Claude), com uma regra definida nas instruções: registrar só fatos comprovados, avaliar os acontecimentos de forma imparcial e identificar como tal qualquer opinião, hipótese ou estimativa. Todas as informações vêm de dados públicos, com link para a fonte.

## As abas

| Aba | O que mostra | De onde vêm os dados |
|---|---|---|
| **Cronologia** | Do dia da eleição até hoje, agrupado por dia (o mais recente primeiro e aberto; os outros recolhidos). Cada item é marcado como fato, opinião ou fake news e diz qual candidatura foi prejudicada **no resultado** (em votos) e por quê. Quando os veículos divergem em horário ou número, o item mostra as versões. | Reportagens com link (Gazeta do Povo, Revista Oeste, Brasil Paralelo, Jovem Pan, Exame, Bloomberg Línea, Mix Vale, Poder360, Band, CartaCapital, Brasil 247, Agência Brasil, Agência Senado, TSE) |
| **Resultado** | Placar oficial: votos válidos, seções totalizadas, resultado por região, por UF e no mapa. Clicando num estado, aparecem as grandes cidades. | Arquivos públicos de resultados do TSE |
| **Impactos da Extensão** | Quanto a prorrogação até 19h poderia ter mudado o resultado: votos registrados depois das 17h, cenários de horário normal × estendido, o mínimo que o perdedor precisaria para virar e a hipótese contrária ("e se todas as seções ficassem abertas?"). Inclui uma explicação em linguagem simples. | Resultado do TSE e contagens dos registros (logs) das urnas feitas pelo G1 (35.521 votos) e pela Jovem Pan (34.319). As suposições por região são editáveis e marcadas como estimativa. |
| **Pesquisas × urnas** | A média das pesquisas da véspera (Lula 49,1% dos válidos) comparada com o resultado (51,8%), instituto por instituto, com exemplos de erro de pesquisa em 2022 e por que essa diferença não indica fraude. | Compilação da RED (24/10/2026) e reportagens de 2022 |
| **Fake news** | Boatos que circularam, com o texto original na íntegra e o parecer, feito com os números oficiais do 1º e do 2º turno. | Resultados do TSE |
| **Envie para checagem** | Formulário para enviar o print de um boato, com código de protocolo e e-mail opcional. Link direto: `contadaurna.com.br/#envie`. | Servidor próprio em `envios/` (veja `envios/README.md`) |

No fim da página há a seção **"Achou um erro?"**, com link para pedir uma correção (abre uma issue neste repositório) e o registro público das correções feitas.

## Como funciona tecnicamente

### Visão geral

O site é **um único arquivo `index.html`**, com HTML, CSS e JavaScript sem bibliotecas nem etapa de build. Tudo o que ele mostra vem de duas fontes:

1. **Dados do TSE**, lidos em JSON. O app busca os arquivos de cada UF no 1º turno (eleição `6257`) e no 2º turno (eleição `6258`), além dos arquivos de cerca de 140 capitais e grandes cidades.
2. **Conteúdo editorial**, escrito dentro do próprio `index.html` em listas JavaScript (veja "Onde editar o conteúdo").

### Dois modos de funcionamento

| Modo | Quando acontece | Comportamento |
|---|---|---|
| **Estático (dados congelados)** | Existe o arquivo `tse/congelado.json` (é o caso do site publicado). | Lê só as cópias dos arquivos do TSE salvas em `tse/oficial/...`. Não consulta o TSE e esconde o botão Atualizar. |
| **Ao vivo** | Rodando com `python3 servir.py --ao-vivo` (ou sem o `tse/congelado.json`). | Busca o TSE a cada clique em Atualizar ou a cada 60 s. Foi usado durante a apuração. |

O navegador não consegue ler o site do TSE diretamente em todos os casos (bloqueio de CORS). Por isso o `servir.py` funciona como proxy: repassa `/tse/...` para `https://resultados.tse.jus.br/...`.

### Endereços do TSE usados

- Por UF: `https://resultados.tse.jus.br/oficial/ele2026/{eleição}/dados/{uf}/{uf}-c0001-e00{eleição}-u.json` (`br` = Brasil, `zz` = exterior)
- Lista de municípios: `ele2026/{eleição}/config/mun-e00{eleição}-cm.json`
- Por município: `ele2026/{eleição}/dados/{uf}/{uf}{código}-c0001-e00{eleição}-u.json`

Campos lidos: `carg[].agr[].par[].cand[]` (`n` = número, `vap` = votos), `s` (seções totalizadas), `e` (eleitorado), `v` (votos válidos, brancos e nulos).

### Modelo de projeção (usado durante a apuração)

Enquanto faltavam urnas, o app estimava a chance de cada candidato. Com a apuração encerrada, essa aba deu lugar a "Pesquisas × urnas", mas o modelo continua no código:

1. **Unidades:** em cada UF, as capitais e grandes cidades separadas e o "resto da UF". A base de cada unidade é a fatia de Lula no 1º turno.
2. **Pesquisas:** a média ponderada (pela raiz da amostra e pela recência) define um deslocamento nacional, aplicado em escala logística.
3. **Apuração:** a diferença entre a parcial e o esperado ganha peso conforme a fração apurada. O que falta é preenchido pela tendência da UF, puxada para a nacional. Separar cidade e interior corrige boa parte do viés da ordem de apuração.
4. **Incerteza:** Monte Carlo (20 mil simulações) com erro nacional (t de 4 graus de liberdade), erro por UF, por unidade, de ordem de apuração e de comparecimento.

Os parâmetros não foram calibrados com 2018 e 2022.

### Credibilidade das fontes

- Ao lado de cada link de fonte o site mostra um link **arquivo**, que abre a cópia da página no archive.org (`https://web.archive.org/web/2026/<endereço>`). Assim a fonte continua acessível se a notícia sair do ar ou mudar.
- O workflow `Arquivar fontes` pede ao archive.org uma cópia de cada página citada e grava o endereço de cada cópia em `arquivo-fontes.json`.
- A data da última atualização do conteúdo aparece no topo do site.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `index.html` | O site inteiro: layout, cálculos e conteúdo. |
| `privacidade.html` | Política de privacidade (LGPD) e termos de uso, em página própria. Ao mudar a coleta de dados, atualize-a junto. |
| `tse/` | Cópias dos arquivos do TSE (dados finais) e `congelado.json`, que liga o modo estático. |
| `congelar.py` | Baixa do TSE os arquivos que o app usa e grava em `tse/`. |
| `servir.py` | Servidor local e proxy do TSE para o modo ao vivo. |
| `scripts/arquivar.py` | Guarda no archive.org as páginas citadas como fonte. |
| `arquivo-fontes.json` | Registro gerado automaticamente com a cópia arquivada de cada fonte. |
| `.github/workflows/pages.yml` | A cada push na `main`, publica o site no GitHub Pages (branch `gh-pages`). |
| `.github/workflows/arquivar.yml` | A cada mudança no `index.html`, arquiva as fontes no archive.org. Também pode ser rodado à mão em Actions. |
| `envios/` | Servidor de envio de prints da aba Fake news (Render), com página de administração e testes. Desenho de segurança e configuração em [`envios/README.md`](envios/README.md). |
| `.github/workflows/envios.yml` | Roda os testes do servidor de envios a cada PR que mexe em `envios/`. |
| `render.yaml` | Configuração do Render: o site estático e o servidor de envios. |
| `CNAME` | Domínio próprio do GitHub Pages. |

Só usa a biblioteca padrão do Python 3; não há dependências para instalar.

## Rodar no computador

```
python3 servir.py          # abre http://localhost:8000 com os dados finais salvos
python3 servir.py --ao-vivo  # busca tudo no TSE, como durante a apuração
python3 servir.py --rede   # libera para outros aparelhos da mesma rede Wi-Fi
```

Se a porta 8000 estiver ocupada, o servidor usa a próxima livre e mostra qual no terminal.

## Publicar

**GitHub Pages (atual):** cada push na `main` dispara o workflow `pages.yml`, que copia `index.html`, `privacidade.html`, `tse/` e `CNAME` para a branch `gh-pages`. Em Settings → Pages, a origem é a branch `gh-pages`, pasta raiz.

**Versão de teste (antes de publicar):** todo PR aberto neste repositório ganha uma cópia em `https://contadaurna.com.br/teste/pr-N/` (workflow `teste.yml`, que usa `scripts/marcar_teste.py`). A cópia tem uma faixa laranja avisando que é teste, não é indexada pelo Google e não conta visitas no GoatCounter. O link aparece num comentário do próprio PR e é atualizado a cada novo commit. Testou e está certo: dê o merge, e o site oficial é publicado. Ao fechar o PR (com ou sem merge), a cópia de teste é apagada. O `pages.yml` preserva a pasta `teste/` dos PRs ainda abertos quando republica o site.

**Render (alternativa):** em render.com, *New → Blueprint*, escolha este repositório. O `render.yaml` publica o mesmo conteúdo como site estático.

**Atualizar os dados do TSE:** `python3 congelar.py`, depois commit e push da pasta `tse/`.

## Onde editar o conteúdo

Tudo fica no `index.html`:

| O que | Onde |
|---|---|
| Itens da cronologia | lista `CRONO` (campos `hora` (depois de 25/10, comece com o dia, como "Quinta, 29/10, manhã": é daí que sai o agrupamento por dia), `tipo` = fato/opiniao/fake, `titulo`, `texto`, `fontes`, `prej` = [candidatura prejudicada, motivo], e `atualizado` = ["dd/mm", "o que mudou"] quando um item já publicado é completado ou confirmado: vira um selo "Atualizado em dd/mm" no item e no título recolhido do dia) e mapa de fontes `FONTES_CRON` |
| Boatos checados | lista `FAKES` (o mais recente primeiro). Aparecem primeiro o `selo`, a `frase` (o veredito em uma linha) e os `nums` (três pares [número, o que é]); o `curto` + `parecer` e o texto do boato (`texto`, `outras`) ficam em "ver mais". Sem `frase`, o cartão mostra o `curto` |
| Frase-resposta de cada aba | blocos `<div class="so-…">` dentro de `.sobre`, no HTML (a da aba Fake news é calculada a partir de `FAKES`) |
| Pesquisas da véspera | lista `PESQ_VESPERA` |
| Data da última atualização | constante `ATUALIZADO` (atualizar a cada mudança de conteúdo) |
| Registro de correções | lista `CORRECOES` (`data`, `texto`) |
| Cidades com dados municipais | objeto `GRANDES` (o `congelar.py` lê a mesma lista) |

## Limitações

- As contagens de votos depois das 17h são levantamentos de imprensa sobre os registros das urnas, não números oficiais do TSE, e não dizem em quem foram os votos.
- Na Cronologia, a classificação fato/opinião e a "candidatura prejudicada" são análise, não dado. Cada item explica o motivo e cita a fonte.
- Parte das fontes pode não ter cópia no archive.org; o registro está em `arquivo-fontes.json`.

Encontrou um erro? [Abra uma correção](https://github.com/pedrohrs08/contadaurna/issues/new) com o link da fonte que mostra o dado certo.
