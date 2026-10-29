# Servidor de envios

Recebe os prints de boatos enviados pela aba **Fake news** de [contadaurna.com.br](https://contadaurna.com.br/#fake). O código é aberto para que qualquer pessoa confira como os dados são tratados.

## Como funciona

1. A pessoa escolhe o print, diz onde viu (opcional) e, **se quiser**, deixa um e-mail.
2. O servidor confere o anti-robô (Cloudflare Turnstile), regrava a imagem e devolve um **código de protocolo** (ex.: `ABCD-EFGH-2345`).
3. O responsável pelo site vê a fila na página `/admin`, só com protocolo, data, "onde viu", a imagem e se a pessoa pediu aviso. **O e-mail nunca aparece.**
4. **A checagem é feita por uma rotina de inteligência artificial (IA), não por uma pessoa.** Duas vezes por dia a rotina pega os envios da fila (veja [ROTINA.md](ROTINA.md)), que busca o assunto em várias fontes, de linhas editoriais diferentes (veículos vistos como à direita, à esquerda e de centro, além de dados oficiais), escreve o parecer e abre um PR neste repositório. O envio passa a constar como **rascunho**. **Todo parecer publicado lista as fontes consultadas, com link**, para que qualquer pessoa confira. **Nada vai ao ar sem o responsável revisar e aceitar (merge) o PR.**
5. Depois do merge, a própria rotina marca o envio como **publicado**. Se o boato já tem parecer no site, a rotina liga o envio a esse parecer e o responsável só dispara o aviso de **já publicado** (com o link). Nos outros casos, o responsável marca o resultado: **publicado** (com o link do parecer), **procede** (a informação é verdadeira, então não vira parecer de fake news) ou **descartado**.
6. Se havia e-mail, o servidor o decifra só naquele momento, manda o aviso e **apaga o e-mail**. Qualquer pessoa com o protocolo consulta o resultado no site.
7. Tudo é apagado automaticamente em 30 dias. A pessoa também pode apagar o próprio envio a qualquer momento usando o protocolo.

## Desenho de segurança

| Risco | O que o código faz |
|---|---|
| Robôs e spam | Turnstile obrigatório, limite de 5 envios por hora por IP e de 120 por hora no total, fila máxima de 500 envios. |
| Ataque para gerar conta alta (encher o armazenamento ou disparar operações pagas) | Antes de aceitar cada imagem, o servidor soma o espaço usado no balde e recusa o envio ao chegar em **8 GB** (o grátis vai até 10 GB; ajustável pela variável `LIMITE_GB`) ou 500 envios guardados. O site consulta `/capacidade` antes de mostrar o formulário. Consultas e pedidos de apagar têm limite de 60 por hora por IP e 1.500 por hora no total. Com todos os limites no máximo durante um mês inteiro, o uso fica dentro da cota grátis do R2 (cerca de 400 mil das 1 milhão de gravações e 1,1 milhão das 10 milhões de leituras): um ataque deixa o envio indisponível, mas não gera cobrança. |
| Arquivo malicioso | Só aceita JPEG, PNG ou WEBP de até 10 MB. A imagem é aberta e **regravada como JPEG novo**, o que descarta qualquer conteúdo escondido. Há proteção contra "bombas" de descompressão. |
| Metadados (local, aparelho, autor) | Saem na regravação. Há teste automático que confere isso. |
| E-mail exposto | É gravado **criptografado** (Fernet: AES-128 com HMAC-SHA256) num arquivo separado. A chave (`EMAIL_KEY`) é gerada pelo Render e não precisa ser copiada por ninguém. Nenhuma rota devolve o e-mail. Ele é apagado logo após o aviso. |
| IP | Não é gravado. É usado só embaralhado (hash), na memória e por até 1 hora, para o limite de envios. Não é repassado ao Turnstile. |
| Uso do servidor para mandar golpe por e-mail | O texto do aviso é fixo e só aceita links do próprio site. O e-mail tem versão em texto e em HTML com a marca do site, montada com tudo escapado; não carrega nada de terceiros além do ícone do próprio site. |
| Senha da rotina de IA | `ROTINA_TOKEN`, separado do `ADMIN_TOKEN` e também gerado pelo Render. Só lista a fila (sem saber quem pediu aviso), baixa o print, marca "rascunho" com o link do PR, marca "repetido" com o link de um parecer que já existe (sem mandar e-mail) e conclui como "publicado" um envio que já está em rascunho, com link de parecer do site. Não pode apagar envios, marcar "procede" ou "descartado", nem ver e-mails. Sem a variável, essas rotas ficam desligadas. |
| Senha de administração | `ADMIN_TOKEN` gerado pelo Render (256 bits), comparado em tempo constante. Após 10 erros em 1 hora, o IP fica bloqueado por 1 hora. |
| Páginas e respostas | CSP restritiva, `nosniff`, sem cache, sem iframe. A página `/admin` monta tudo com `textContent`, sem HTML vindo do servidor. CORS liberado só para o domínio do site. |
| Configuração incompleta | O servidor não sobe se faltar algum segredo (falha fechada). |
| Retenção | Regra de ciclo de vida no balde R2 apaga tudo com mais de 30 dias. |

### O que o responsável pelo site consegue e não consegue ver (dito com franqueza)

- No uso normal, **não vê o e-mail de ninguém**: a página de administração não mostra, e o armazenamento guarda só o texto cifrado.
- Como dono da conta no Render, ele *teria como* chegar a um e-mail se agisse de propósito (por exemplo, alterando o código para imprimi-lo). Toda mudança de código fica pública neste repositório. Proteção absoluta exigiria que o e-mail ficasse com um terceiro.
- O Brevo, serviço que envia o aviso, guarda por tempo limitado um registro técnico de cada e-mail enviado (destinatário e assunto). A regra deste projeto é não consultar esses registros.
- Em e-mails com HTML, o Brevo acrescenta por conta própria um pixel de abertura. Pela regra do Brevo, se a conta não tiver o consentimento da pessoa, a abertura é contada só no total, de forma anônima. Este projeto não coleta esse consentimento.

## Configuração (uma vez)

Todas as contas são gratuitas. Guarde cada segredo só no painel do Render, nunca no repositório.

### 1. Cloudflare (armazenamento e anti-robô)
1. Crie uma conta em dash.cloudflare.com.
2. **R2 › Criar balde**: nome `contadaurna-envios`, localização automática. O balde já nasce privado; não ative acesso público. (A Cloudflare pede um cartão para ativar o R2, mas o plano gratuito cobre 10 GB.)
3. No balde: **Configurações › Regras de ciclo de vida › Adicionar regra**: "apagar em 30 dias", aplicada ao balde todo, **excluir objetos 30 dias** após o envio.
4. **R2 › Gerenciar tokens de API › Criar token**: permissão **Leitura e gravação de objetos**, aplicada **só ao balde** `contadaurna-envios`. Anote o *Access Key ID*, o *Secret Access Key* e o *Account ID*.
5. **Turnstile › Adicionar widget**: nome "contadaurna", domínios `contadaurna.com.br` e `www.contadaurna.com.br`, modo **Gerenciado**. Anote a *Site Key* (pública) e a *Secret Key*.

### 2. Brevo (envio do aviso por e-mail)
1. Crie uma conta em brevo.com (plano gratuito: 300 e-mails por dia).
2. **Remetentes, domínios e IPs › Domínios › Adicionar domínio** `contadaurna.com.br` e autentique: o Brevo mostra registros DNS (TXT e DKIM) para criar no Registro.br.
3. **Remetentes › Adicionar**: `nao-responda@contadaurna.com.br`.
4. **SMTP e API › Chaves de API › Gerar**. Anote a chave. Não ative a restrição de IPs (o Render muda de IP).

### 3. Render (o servidor)
1. Depois do merge, abra o painel do Render. Se o repositório já está ligado como Blueprint, ele mostra o novo serviço `contadaurna-envios` para criar. Senão: **New › Blueprint** e escolha o repositório `contadaurna`.
2. Preencha as variáveis pedidas:

| Variável | Valor |
|---|---|
| `R2_CONTA` | Account ID da Cloudflare |
| `R2_CHAVE` | Access Key ID do token do R2 |
| `R2_SEGREDO` | Secret Access Key do token do R2 |
| `R2_BALDE` | `contadaurna-envios` |
| `TURNSTILE_SECRET` | Secret Key do Turnstile |
| `BREVO_API_KEY` | chave de API do Brevo |
| `EMAIL_REMETENTE` | `nao-responda@contadaurna.com.br` |

   `EMAIL_KEY` e `ADMIN_TOKEN` são gerados sozinhos. **Copie o `ADMIN_TOKEN`** (aba Environment) para o seu gerenciador de senhas: é a senha da página `/admin`. Não é preciso abrir o `EMAIL_KEY`. Se ele mudar, os e-mails ainda não avisados ficam ilegíveis.
3. Quando o serviço ficar verde, abra `https://<endereço>.onrender.com/saude`: deve mostrar `{"ok": true}`.
4. Coloque o endereço do serviço em `ENVIE_API` e a Site Key do Turnstile em `ENVIE_TURNSTILE`, no bloco "Envie seu print" do `index.html`. Os dois são públicos.

No plano gratuito, o Render "dorme" depois de 15 minutos sem uso. O primeiro envio depois disso pode levar até 1 minuto, e o site avisa isso.

## Uso no dia a dia
1. Abra `https://<endereço>.onrender.com/admin` e entre com o `ADMIN_TOKEN`.
2. Envios em **Rascunho pronto** têm o link do PR. Revise o parecer na versão de teste e dê merge se estiver certo. Na rodada seguinte, a rotina marca como publicado e o aviso sai.
3. Envios em **Já tem parecer: pronto para avisar** são boatos repetidos: a rotina já escolheu "Já publicado antes" e preencheu o link do parecer existente. Confira o link e toque em **Concluir**. Se a pessoa pediu aviso, ela recebe um e-mail agradecendo o envio e dizendo que o boato já tinha sido checado, com o link para o parecer.
4. Se o veredito for "procede" ou o envio não servir, feche o PR sem merge, escolha o resultado aqui e toque em **Concluir**. Se a pessoa pediu aviso, o e-mail sai na hora.
5. Conteúdo ofensivo ou ilegal: **Apagar envio**.

## Testes
```
pip install -r envios/requirements.txt pytest
pytest envios
```
Os testes rodam sozinhos no GitHub a cada PR que mexe nesta pasta (`.github/workflows/envios.yml`).
