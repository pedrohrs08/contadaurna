// Entrega ao site os pareceres da aba Fake news, lidos do banco D1.
// Só leitura: quem escreve no banco é o servidor de envios (envios/app.py), pelo /admin e pela rotina.
//   GET /pareceres            pareceres publicados, do mais novo para o mais antigo
//   GET /previa/<id>?chave=…  versão pendente de um parecer, para o responsável revisar antes de publicar
//   GET /saude
const MEMORIA_SEG = 60;   // cada cópia do serviço relê o banco no máximo 1 vez por minuto (cota de leituras do D1)
const ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
let memoria = { t: 0, corpo: null };

function resposta(corpo, status = 200, cache = "no-store") {
  return new Response(typeof corpo === "string" ? corpo : JSON.stringify(corpo), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": cache,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    },
  });
}

async function publicados(env) {
  if (memoria.corpo && Date.now() - memoria.t < MEMORIA_SEG * 1000) return memoria.corpo;
  const { results } = await env.DB.prepare(
    "SELECT id, publicado FROM pareceres WHERE publicado IS NOT NULL ORDER BY posicao DESC").all();
  const corpo = JSON.stringify(results.map((r) => ({ id: r.id, ...JSON.parse(r.publicado) })));
  memoria = { t: Date.now(), corpo };
  return corpo;
}

async function previa(env, id, chave) {
  if (!ID_RE.test(id) || !chave) return null;
  const r = await env.DB.prepare("SELECT publicado, pendente, chave FROM pareceres WHERE id = ?").bind(id).first();
  if (!r || r.chave !== chave) return null;
  return { id, ...JSON.parse(r.pendente || r.publicado), previa: true };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: { "Access-Control-Allow-Origin": "*" } });
    if (req.method !== "GET") return resposta({ erro: "Método não aceito." }, 405);
    try {
      if (url.pathname === "/saude") return resposta({ ok: true });
      if (url.pathname === "/pareceres") return resposta(await publicados(env), 200, `public, max-age=${MEMORIA_SEG}`);
      const m = url.pathname.match(/^\/previa\/([^/]+)$/);
      if (m) {
        const p = await previa(env, decodeURIComponent(m[1]), url.searchParams.get("chave"));
        return p ? resposta(p) : resposta({ erro: "Prévia não encontrada." }, 404);
      }
      return resposta({ erro: "Não encontrado." }, 404);
    } catch (e) {
      return resposta({ erro: "O banco não respondeu." }, 503);
    }
  },
};
