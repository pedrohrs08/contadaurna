# Banco de dados

Envios, pareceres da aba **Fake news** e o histórico de tudo ficam num banco **Cloudflare D1** (gratuito, é um SQLite). Os prints continuam no balde R2: o banco guarda só o endereço e o tamanho de cada um.

| Quem | O que faz no banco |
|---|---|
| Servidor de envios (`envios/`, no Render) | Grava os envios, a avaliação da rotina, os pareceres pendentes e a publicação. Fala com o D1 pela API da Cloudflare, com um token que só tem a permissão **D1: Edit**. |
| Serviço dos pareceres (`banco/worker.js`, Cloudflare Workers) | Só lê. Entrega ao site os pareceres publicados (`/pareceres`) e a prévia de um pendente (`/previa/<id>?chave=…`). Não dorme, ao contrário do Render grátis. |
| GitHub Actions | `banco.yml` cria o banco na primeira vez, aplica as migrações e publica o serviço. `copia-pareceres.yml` copia os publicados para `fakes.json` a cada 20 minutos. |

## Tabelas (`migrations/0001_inicial.sql`)

- **envios**: protocolo, data, "onde viu", situação, **publicável** (decisão da rotina: sim, não ou ainda não avaliado), **motivo**, **parecer** ligado, link do aviso, endereço e tamanho do print no balde e se a pessoa pediu aviso. O e-mail nunca entra aqui: fica cifrado no balde.
- **pareceres**: `publicado` (versão no ar) e `pendente` (versão esperando aprovação), ambos em JSON com os mesmos campos de antes (`titulo`, `data`, `selo`, `texto`, `frase`, `nums`, `curto`, `parecer`, `fontes`, `outras`), a posição na aba e a chave secreta da prévia. O `id` é o mesmo do link `contadaurna.com.br/#fake-<id>`.
- **historico**: cada mudança, com data, quem fez (`admin`, `rotina`, `pessoa` ou `sistema`), a ação e os dados. Nos pareceres, guarda a versão inteira, então nenhuma versão antiga se perde.

Os 19 pareceres que estavam no `index.html` entram já publicados pela migração `0002`, gerada por `scripts/pareceres_sql.py`. Migração nova = arquivo novo em `migrations/` (nunca edite uma que já rodou).

## Como um parecer vai ao ar

1. A rotina (ou o responsável, pelo `/admin`) grava a versão **pendente**. Nada muda no site.
2. No `/admin`, aba **Pareceres**, o responsável abre **Ver prévia**: é o site de verdade, com o parecer pendente no topo e uma faixa "Prévia". Só quem tem o link vê.
3. **Publicar** põe a versão no ar. O site atualiza em até 1 minuto. Os envios ligados àquele parecer viram "publicado" e o aviso por e-mail sai na mesma hora.
4. Correção num parecer que já está no ar segue o mesmo caminho: a versão nova fica pendente até o responsável publicar, e a antiga fica no histórico.

## Limites gratuitos e o que o código faz

| Recurso | Grátis | Proteção |
|---|---|---|
| D1, tamanho | 500 MB por banco | O servidor de envios recusa envios novos quando o banco passa de **400 MB** (`LIMITE_BANCO_MB`). Cada envio ocupa menos de 1 KB. |
| D1, leituras | 5 milhões de linhas por dia | O serviço dos pareceres guarda a lista na memória por 1 minuto, e o navegador também. O uso do balde é somado no banco (sem listar o balde) e recalculado no máximo 1 vez por minuto. |
| D1, gravações | 100 mil por dia | Os limites de envio (120 por hora) mantêm o uso abaixo de 10 mil por dia. |
| R2 | 10 GB | Limite de **8 GB** (`LIMITE_GB`) e 500 prints guardados, somados pelo banco. |
| Workers | 100 mil pedidos por dia | Se passar, o site usa `fakes.json`. |

O uso do balde e do banco aparece no topo do `/admin`.

## Configuração (uma vez, antes do merge)

1. **Cloudflare › Armazenamento e bancos de dados › D1 › Criar banco**: nome `contadaurna`. Copie o **id** do banco (não é segredo).
2. **Cloudflare › Workers e Pages**: abra uma vez para ativar o endereço `*.workers.dev` da conta (se pedir um subdomínio, aceite o sugerido).
3. **Cloudflare › Meu perfil › Tokens de API › Criar token › modelo "Editar Cloudflare Workers"**: acrescente a permissão **Conta › D1 › Editar** e restrinja à sua conta. Este é o `CLOUDFLARE_API_TOKEN`.
4. **Crie um segundo token**, "Token personalizado", só com **Conta › D1 › Editar**. Este é o `D1_TOKEN` (o servidor de envios não precisa publicar Workers).
5. **GitHub › Settings › Secrets and variables › Actions › New repository secret**: `CLOUDFLARE_API_TOKEN` (token do passo 3) e `CLOUDFLARE_ACCOUNT_ID` (o mesmo Account ID de `R2_CONTA`).
6. **Render › contadaurna-envios › Environment**: acrescente `D1_BANCO` (id do passo 1) e `D1_TOKEN` (token do passo 4).

Depois do merge, o GitHub cria as tabelas, põe os 19 pareceres no banco e publica o serviço (Actions › "Banco e serviço dos pareceres"; o resumo da execução mostra o endereço do serviço). O Render publica o servidor novo, que passa para o banco, no primeiro uso, os envios que estavam no balde. Por último, o endereço do serviço vai em `FAKES_API`, no `index.html`. Até lá, o site usa `fakes.json`.

## Testes

```
cd banco && npm ci && npm test
```
