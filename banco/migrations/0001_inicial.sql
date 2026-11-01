-- Banco do Conta da Urna (Cloudflare D1, que é SQLite).
-- Os prints ficam no balde R2; aqui só fica o endereço deles. E-mails nunca entram aqui.

-- Um envio da aba "Envie para checagem"
CREATE TABLE envios (
  protocolo   TEXT PRIMARY KEY,
  criado      TEXT NOT NULL,                 -- data e hora UTC (2026-10-31T12:00:00Z)
  onde        TEXT NOT NULL DEFAULT '',      -- "onde viu", escrito pela pessoa; some em 30 dias
  status      TEXT NOT NULL DEFAULT 'na_fila',
  publicavel  INTEGER,                       -- decisão da rotina: NULL = ainda não olhou, 1 = sim, 0 = não
  motivo      TEXT NOT NULL DEFAULT '',      -- por que não é publicável (ou outra observação da rotina)
  parecer     TEXT,                          -- id do parecer ligado a este envio (tabela pareceres)
  link        TEXT NOT NULL DEFAULT '',      -- link enviado no aviso (#fake-...)
  print_chave TEXT,                          -- endereço do print no balde R2 (NULL depois de apagado)
  print_bytes INTEGER NOT NULL DEFAULT 0,    -- tamanho do print, para somar o uso do balde sem listá-lo
  tem_email   INTEGER NOT NULL DEFAULT 0,    -- só diz se a pessoa pediu aviso; o e-mail fica cifrado no R2
  concluido   TEXT NOT NULL DEFAULT '',
  expirado    TEXT NOT NULL DEFAULT ''       -- quando o print e o "onde viu" foram apagados (30 dias)
);
CREATE INDEX envios_status ON envios (status, criado);
CREATE INDEX envios_parecer ON envios (parecer);

-- Um parecer da aba Fake news. "publicado" é a versão no ar; "pendente", a que espera aprovação.
-- As duas são JSON com os campos titulo, data, selo, texto, frase, nums, curto, parecer, fontes, outras.
CREATE TABLE pareceres (
  id           TEXT PRIMARY KEY,             -- o mesmo do link contadaurna.com.br/#fake-<id>
  publicado    TEXT,                         -- NULL = fora do ar
  pendente     TEXT,                         -- NULL = nada esperando aprovação
  posicao      INTEGER,                      -- ordem na aba (maior fica mais acima), dada na 1ª publicação
  chave        TEXT NOT NULL,                -- segredo do link de prévia
  criado       TEXT NOT NULL,
  atualizado   TEXT NOT NULL,
  publicado_em TEXT
);

-- Tudo o que muda em envios e pareceres fica registrado aqui (nunca com e-mail).
CREATE TABLE historico (
  n      INTEGER PRIMARY KEY AUTOINCREMENT,
  quando TEXT NOT NULL,
  quem   TEXT NOT NULL,                      -- admin, rotina, pessoa (quem enviou) ou sistema
  tipo   TEXT NOT NULL,                      -- envio ou parecer
  ref    TEXT NOT NULL,                      -- protocolo ou id do parecer
  acao   TEXT NOT NULL,
  dados  TEXT                                -- JSON com o que mudou (em pareceres, a versão inteira)
);
CREATE INDEX historico_ref ON historico (tipo, ref, n);
