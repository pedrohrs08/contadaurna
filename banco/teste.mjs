// Testes do serviço dos pareceres, com um banco D1 local. Rodar: cd banco && npm ci && npm test
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { unstable_dev } from "wrangler";

const PERSIST = ".wrangler/teste";
let w;
const sql = (c) => execFileSync("npx", ["wrangler", "d1", "execute", "contadaurna", "--local", "--persist-to", PERSIST, "--command", c], { stdio: "pipe" });

before(async () => {
  rmSync(PERSIST, { recursive: true, force: true });
  execFileSync("npx", ["wrangler", "d1", "migrations", "apply", "contadaurna", "--local", "--persist-to", PERSIST], { stdio: "pipe" });
  sql(`INSERT INTO pareceres (id, pendente, chave, criado, atualizado) VALUES ('novo-boato', '{"titulo":"Novo"}', 'segredo123', 'x', 'x')`);
  w = await unstable_dev("worker.js", { persistTo: PERSIST, experimental: { disableExperimentalWarning: true }, logLevel: "error" });
});
after(async () => { await w?.stop(); });

test("lista os publicados na ordem da aba", async () => {
  const r = await w.fetch("/pareceres");
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("access-control-allow-origin"), "*");
  const lista = await r.json();
  const ids = [...readFileSync("migrations/0002_pareceres_iniciais.sql", "utf8").matchAll(/^INSERT INTO pareceres .*? VALUES \('([^']+)'/gm)].map((m) => m[1]);
  assert.deepEqual(lista.map((p) => p.id), ids);
  assert.ok(lista.every((p) => p.titulo && p.fontes.length));
  assert.ok(!lista.some((p) => p.id === "novo-boato"));
});

test("prévia só com a chave certa", async () => {
  assert.equal((await w.fetch("/previa/novo-boato?chave=errada")).status, 404);
  assert.equal((await w.fetch("/previa/novo-boato")).status, 404);
  const r = await w.fetch("/previa/novo-boato?chave=segredo123");
  assert.deepEqual(await r.json(), { id: "novo-boato", titulo: "Novo", previa: true });
});

test("só leitura", async () => {
  assert.equal((await w.fetch("/pareceres", { method: "POST" })).status, 405);
  assert.equal((await w.fetch("/qualquer")).status, 404);
});
