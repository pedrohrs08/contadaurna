# Rotina de IA que prepara os pareceres

Roda duas vezes por dia como tarefa agendada do Claude, num ambiente que tem acesso ao servidor de envios e a variável `ROTINA_TOKEN` (copiada do Render). A rotina **nunca publica**: ela grava o parecer como **pendente** e diz se cada envio é publicável. Quem põe no ar é o responsável, pelo botão **Publicar** do `/admin`.

Todas as chamadas levam `Authorization: Bearer $ROTINA_TOKEN`.

## O que a rotina faz em cada rodada

1. `GET /rotina/api/fila`. Vêm os envios `na_fila` e `rascunho`, com `publicavel` (`null` = ainda não avaliado), `motivo` e `parecer`.
2. Pula os envios que já têm `publicavel` preenchido (já avaliados; esperam o responsável).
3. `GET /rotina/api/pareceres` traz todos os pareceres (id, título, frase, se está no ar, se tem versão pendente). Use para achar boatos repetidos.
4. Para cada envio ainda não avaliado (no máximo 5 por rodada, os mais antigos primeiro):
   1. Baixa o print em `GET /rotina/api/print/<protocolo>` e transcreve o texto na íntegra.
   2. **Repete um parecer que já existe** (mesmo boato, ainda que com outra imagem ou outro autor): `POST /rotina/api/avaliar` com `{"protocolo", "publicavel": true, "parecer": "<id existente>"}`. Se o parecer está no ar, o envio vira "Já tem parecer" e o responsável só toca em **Concluir** para mandar o aviso de "já publicado".
   3. **Não é publicável** (fora do tema eleição, ofensivo, ilegível ou a informação procede): `POST /rotina/api/avaliar` com `{"protocolo", "publicavel": false, "motivo": "<uma frase>"}`. O envio fica na fila para o responsável marcar "procede" ou "descartado".
   4. **Senão**, segue a skill de checagem (fontes de linhas editoriais diferentes, dados oficiais) e grava o parecer com `PUT /rotina/api/parecer/<id>`, mandando o JSON com `titulo`, `data` (dd/mm/aaaa), `selo` (opcional: "Enganoso" ou "Procede"; sem selo = "Não procede"), `texto` (o boato na íntegra), `frase`, `nums`, `curto`, `parecer` (HTML simples: `<p>`, `<ul>`, `<li>`, `<b>`, `<a href>`, tabelas) e `fontes` (lista de `[nome, link]`). A resposta traz o link da **prévia**. Depois chama `POST /rotina/api/avaliar` com `{"protocolo", "publicavel": true, "parecer": "<id>"}`. **Nunca põe nome, @ ou foto do autor do post**: escreva "autor do post".
5. Para corrigir um parecer que já está no ar: `GET /rotina/api/parecer/<id>`, altere a versão `publicado` e grave com `PUT /rotina/api/parecer/<id>`. Ela fica pendente até o responsável publicar.
6. Termina com um resumo curto: pareceres gravados (com o link da prévia), envios repetidos ligados a um parecer existente e envios não publicáveis, com o motivo.

O servidor recusa parecer com HTML fora da lista acima (script, imagem, eventos, links que não sejam `http(s)` ou `#fake-…`) e explica o problema em `detalhes`.

## Limites

- A senha da rotina não publica, não apaga envios, não conclui envios e não vê e-mails (veja a tabela de segurança no [README](README.md)).
- Se o servidor estiver dormindo (plano grátis do Render), a primeira chamada pode levar até 1 minuto.
