# Rotina de IA que prepara os pareceres

Roda duas vezes por dia como tarefa agendada do Claude, num ambiente que tem acesso ao servidor de envios e a variável `ROTINA_TOKEN` (copiada do Render). A rotina **nunca publica sozinha**: ela abre um PR e espera o merge do responsável.

## O que a rotina faz em cada rodada

1. `GET /rotina/api/fila` com `Authorization: Bearer $ROTINA_TOKEN`. Vêm só os envios `na_fila` e `rascunho`.
2. Para cada envio em **rascunho**, abre o PR guardado em `pr`:
   - **mergeado:** pega o id do item novo em `FAKES` no `index.html` e chama `POST /rotina/api/publicado` com `{"protocolo", "link": "https://contadaurna.com.br/#fake-<id>"}`. Se a pessoa pediu aviso, o e-mail sai nesse momento.
   - **fechado sem merge:** não faz nada. O responsável conclui pelo `/admin`.
   - **aberto:** espera.
3. Para cada envio **na fila** (no máximo 5 por rodada, os mais antigos primeiro):
   1. Baixa o print em `GET /rotina/api/print/<protocolo>` e transcreve o texto na íntegra.
   2. Se **repete um parecer que já existe** em `FAKES` (mesmo boato, mesmo que com outra imagem ou outro autor), não abre PR: chama `POST /rotina/api/repetido` com `{"protocolo", "link": "https://contadaurna.com.br/#fake-<id do parecer existente>"}`. O envio passa a constar no `/admin` como "Já tem parecer", com o link preenchido; o responsável só toca em **Concluir** para mandar o aviso de agradecimento com o link. A rotina não dispara esse e-mail.
   3. Se não tem a ver com a eleição, é ofensivo ou ilegível, não abre PR: deixa na fila e lista no resumo para o responsável descartar.
   4. Senão, segue a skill de checagem (fontes de linhas editoriais diferentes, dados oficiais, links arquivados), cria o item no topo de `FAKES` e abre o PR `fake-<id>`, com o protocolo e o veredito na descrição. **Nunca põe nome, @ ou foto do autor do post.**
   5. Chama `POST /rotina/api/rascunho` com `{"protocolo", "pr": "<link do PR>"}`.
4. Termina com um resumo curto: quantos PRs abriu, quais envios repetidos foram ligados a um parecer existente, quais ficaram para o responsável decidir e quais foram marcados como publicados.

## Limites

- A senha da rotina não apaga envios, não marca "procede" nem "descartado" e não vê e-mails (veja a tabela de segurança no [README](README.md)).
- Se o servidor estiver dormindo (plano grátis do Render), a primeira chamada pode levar até 1 minuto.
