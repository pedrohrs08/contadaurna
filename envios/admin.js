// Página de administração: fila de envios e pareceres. Todo dado vindo do servidor entra com textContent
// ou value (nunca innerHTML).
const $ = (id) => document.getElementById(id);
let senha = "";
try { senha = sessionStorage.getItem("adm") || ""; } catch (e) {}

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, {...opcoes, headers: {...(opcoes.headers || {}), Authorization: "Bearer " + senha}});
  if (r.status === 401) { sair("Senha incorreta."); throw new Error("401"); }
  return r;
}
const json = (corpo) => ({headers: {"Content-Type": "application/json"}, body: JSON.stringify(corpo)});

function sair(texto) {
  senha = "";
  try { sessionStorage.removeItem("adm"); } catch (e) {}
  $("painel").hidden = true; $("entrar").hidden = false; $("msg").textContent = texto || "";
}

const NOMES = {na_fila: "Na fila", rascunho: "Parecer pendente: espera você publicar", repetido: "Já tem parecer: pronto para avisar",
  publicado: "Publicado", ja_publicado: "Avisado: já publicado", procede: "Procede", descartado: "Descartado",
  expirado: "Expirado (30 dias sem conclusão)"};

const RESULTADOS = ["publicado", "ja_publicado", "procede", "descartado"];
const mb = (b) => (b / 1024 ** 2).toFixed(1) + " MB";

async function historico(alvo, tipo, ref) {
  if (!alvo.hidden) { alvo.hidden = true; return; }
  const r = await api("/admin/api/historico?" + new URLSearchParams({tipo, ref}));
  const linhas = r.ok ? await r.json() : [];
  alvo.textContent = linhas.length ? linhas.map((h) => h.quando.replace("T", " ").replace("Z", " UTC") + " · " + h.quem + " · " + h.acao).join("\n") : "Sem registros.";
  alvo.hidden = false;
}

async function carregarUso() {
  const r = await api("/admin/api/uso");
  if (!r.ok) return;
  const u = await r.json();
  $("uso").textContent = "Balde: " + mb(u.bytes) + " de " + (u.limite_bytes / 1024 ** 3).toFixed(0) + " GB · " + u.envios + " de " +
    u.limite_envios + " prints guardados · Banco: " + mb(u.banco_bytes) + " de " + mb(u.limite_banco_bytes) +
    ". Ao chegar em qualquer limite, o site para de aceitar envios.";
}

async function carregarEnvios() {
  const r = await api("/admin/api/fila");
  if (!r.ok) { $("msg").textContent = (await r.json()).erro || "Erro."; return; }
  const itens = await r.json();
  $("msg").textContent = itens.length ? itens.filter((i) => i.status === "na_fila").length + " na fila, " +
    itens.filter((i) => i.status === "rascunho").length + " com parecer pendente, " +
    itens.filter((i) => i.status === "repetido").length + " repetidos para avisar, " + itens.length + " no total." : "Nenhum envio.";
  const lista = $("lista"); lista.replaceChildren();
  for (const it of itens) {
    const n = $("modelo").content.firstElementChild.cloneNode(true);
    n.querySelector(".prot").textContent = it.protocolo;
    n.querySelector(".meta").textContent = it.criado.replace("T", " ").replace("Z", " UTC") + " · " + (NOMES[it.status] || it.status) + (it.tem_email ? " · pediu aviso" : "");
    n.querySelector(".onde").textContent = it.onde ? "Onde viu: " + it.onde : "";
    n.querySelector(".avaliacao").textContent = it.publicavel === null ? "" :
      (it.publicavel ? "Rotina: publicável" + (it.parecer ? ", parecer " + it.parecer + (it.parecer_no_ar ? " (no ar)" : " (pendente, veja a aba Pareceres)") : "")
        : "Rotina: não publicável. " + it.motivo);
    n.querySelector(".link").value = it.link || "";
    if (RESULTADOS.includes(it.status)) n.querySelector(".res").value = it.status;
    if (it.status === "repetido") n.querySelector(".res").value = "ja_publicado";  // a rotina já pôs o link do parecer
    if (it.parecer && it.parecer_no_ar) { const a = n.querySelector(".pr"); a.href = it.link; a.textContent = "Ver o parecer no site"; a.hidden = false; }
    n.querySelector(".ver").hidden = !it.tem_print;
    n.querySelector(".ver").onclick = async () => {
      const img = n.querySelector("img");
      const resp = await api("/admin/api/print/" + encodeURIComponent(it.protocolo));
      if (!resp.ok) return;
      if (img.src) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(await resp.blob()); img.hidden = false;
    };
    n.querySelector(".hist-bt").onclick = () => historico(n.querySelector(".hist"), "envio", it.protocolo);
    n.querySelector(".concluir").onclick = async () => {
      const out = n.querySelector(".retorno"); out.textContent = "Enviando…";
      const resp = await api("/admin/api/concluir", {method: "POST", ...json({protocolo: it.protocolo, resultado: n.querySelector(".res").value, link: n.querySelector(".link").value})});
      const d = await resp.json();
      out.className = "retorno aviso" + (resp.ok ? "" : " erro");
      out.textContent = d.erro || ("Marcado como " + NOMES[d.status] + ". " +
        ({enviado: "Aviso enviado por e-mail e endereço apagado.", sem_email: "A pessoa não pediu aviso.", falhou: "O e-mail falhou; tente concluir de novo."})[d.email]);
    };
    n.querySelector(".apagar").onclick = async () => {
      if (!confirm("Apagar o envio " + it.protocolo + "? Não dá para desfazer.")) return;
      const resp = await api("/admin/api/apagar", {method: "POST", ...json({protocolo: it.protocolo})});
      if (resp.ok) n.remove();
    };
    lista.append(n);
  }
}

// ----- Pareceres -----
// "a | b" por linha. Nas fontes o link é o último pedaço; nos números, o número é o primeiro.
const pares = (t, ultimo) => t.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
  const i = ultimo ? l.lastIndexOf("|") : l.indexOf("|");
  return i < 0 ? [l, ""] : [l.slice(0, i).trim(), l.slice(i + 1).trim()];
});
let editando = null;

function abrirEditor(id, dados, estado) {
  editando = id;
  const d = dados || {};
  $("edId").textContent = id; $("edEstado").textContent = estado || "novo";
  $("edTitulo").value = d.titulo || ""; $("edData").value = d.data || new Date().toLocaleDateString("pt-BR");
  $("edSelo").value = d.selo || ""; $("edFrase").value = d.frase || ""; $("edCurto").value = d.curto || "";
  $("edNums").value = (d.nums || []).map((p) => p.join(" | ")).join("\n");
  $("edParecer").value = d.parecer || ""; $("edTexto").value = d.texto || "";
  $("edFontes").value = (d.fontes || []).map((p) => p.join(" | ")).join("\n");
  $("edOutras").value = d.outras ? JSON.stringify(d.outras, null, 1) : "";
  $("edRetorno").textContent = ""; $("editor").hidden = false;
  $("editor").scrollIntoView({block: "start"});
}

$("edSalvar").onclick = async () => {
  const out = $("edRetorno");
  let outras;
  try { outras = $("edOutras").value.trim() ? JSON.parse($("edOutras").value) : undefined; }
  catch (e) { out.className = "aviso erro"; out.textContent = "Outras versões: o JSON não está certo."; return; }
  const corpo = {titulo: $("edTitulo").value, data: $("edData").value.trim(), selo: $("edSelo").value || undefined,
    frase: $("edFrase").value || undefined, nums: pares($("edNums").value), curto: $("edCurto").value, parecer: $("edParecer").value,
    fontes: pares($("edFontes").value, true), texto: $("edTexto").value, outras};
  out.className = "aviso"; out.textContent = "Salvando…";
  const r = await api("/admin/api/parecer/" + encodeURIComponent(editando), {method: "PUT", ...json(corpo)});
  const d = await r.json();
  out.className = "aviso" + (r.ok ? "" : " erro");
  out.textContent = r.ok ? "Salvo como pendente. Confira a prévia e toque em Publicar." : d.erro + " " + (d.detalhes || []).join(" ");
  if (r.ok) carregarPareceres();
};
$("edFechar").onclick = () => { $("editor").hidden = true; editando = null; };
$("novo").onclick = () => {
  const id = $("novoId").value.trim().toLowerCase();
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(id)) { $("novoId").setCustomValidity("Use letras minúsculas, números e hífens."); $("novoId").reportValidity(); return; }
  $("novoId").setCustomValidity(""); abrirEditor(id, null, "novo");
};

async function acao(n, caminho, pergunta) {
  if (pergunta && !confirm(pergunta)) return;
  const out = n.querySelector(".retorno"); out.className = "retorno aviso"; out.textContent = "Enviando…";
  const r = await api(caminho, {method: "POST"});
  const d = await r.json();
  if (!r.ok) { out.className = "retorno aviso erro"; out.textContent = d.erro; return; }
  const avisos = (d.avisos || []).map((a) => a.protocolo + ": " + ({enviado: "aviso enviado", sem_email: "sem pedido de aviso", falhou: "e-mail falhou, conclua de novo na aba Envios"})[a.email]);
  await carregarPareceres();
  $("msg").textContent = "Feito." + (avisos.length ? " Envios ligados: " + avisos.join("; ") + "." : "");
}

async function carregarPareceres() {
  const r = await api("/admin/api/pareceres");
  if (!r.ok) return;
  const itens = await r.json();
  const lista = $("pareceres"); lista.replaceChildren();
  for (const p of itens) {
    const n = $("modeloParecer").content.firstElementChild.cloneNode(true);
    const e = n.querySelector(".estado");
    e.textContent = p.pendente ? (p.no_ar ? "No ar · com alteração pendente" : "Pendente") : (p.no_ar ? "No ar" : "Fora do ar");
    e.classList.add(p.pendente ? "pend" : "no-ar");
    n.querySelector(".titulo").textContent = p.titulo;
    n.querySelector(".meta").textContent = p.id + " · atualizado em " + p.atualizado.replace("T", " ").replace("Z", " UTC") + (p.selo ? " · " + p.selo : "");
    n.querySelector(".envios").textContent = p.envios.length ? "Envios ligados: " + p.envios.map((x) => x.protocolo + " (" + (NOMES[x.status] || x.status) + ")").join(", ") : "";
    n.querySelector(".previa").href = p.previa; n.querySelector(".previa").hidden = !p.pendente;
    n.querySelector(".site").href = p.link; n.querySelector(".site").hidden = !p.no_ar;
    n.querySelector(".publicar").hidden = n.querySelector(".descartar").hidden = !p.pendente;
    n.querySelector(".tirar").hidden = !p.no_ar;
    n.querySelector(".publicar").onclick = () => acao(n, `/admin/api/parecer/${encodeURIComponent(p.id)}/publicar`,
      "Publicar este parecer no site?" + (p.envios.length ? " Quem enviou o boato e pediu aviso recebe o e-mail agora." : ""));
    n.querySelector(".descartar").onclick = () => acao(n, `/admin/api/parecer/${encodeURIComponent(p.id)}/descartar`,
      p.no_ar ? "Descartar a alteração pendente? A versão no ar continua." : "Descartar este rascunho? Os envios ligados voltam para a fila.");
    n.querySelector(".tirar").onclick = () => acao(n, `/admin/api/parecer/${encodeURIComponent(p.id)}/tirar`,
      "Tirar este parecer do site? O link #fake-" + p.id + " para de abrir. Dá para publicar de novo depois.");
    n.querySelector(".editar").onclick = async () => {
      const d = await (await api("/admin/api/parecer/" + encodeURIComponent(p.id))).json();
      abrirEditor(p.id, d.pendente || d.publicado, e.textContent);
    };
    n.querySelector(".hist-bt").onclick = () => historico(n.querySelector(".hist"), "parecer", p.id);
    lista.append(n);
  }
}

function mostrar(aba) {
  $("secEnvios").hidden = aba !== "envios"; $("secPareceres").hidden = aba !== "pareceres";
  $("abaEnvios").setAttribute("aria-pressed", aba === "envios"); $("abaPareceres").setAttribute("aria-pressed", aba === "pareceres");
}

async function carregar() {
  $("msg").textContent = "Carregando…";
  await carregarEnvios();
  if (!senha) return;
  $("entrar").hidden = true; $("painel").hidden = false;
  carregarUso().catch(() => {});
  carregarPareceres().catch(() => {});
}

$("entrar").onsubmit = (e) => {
  e.preventDefault();
  senha = $("senha").value; $("senha").value = "";
  try { sessionStorage.setItem("adm", senha); } catch (e2) {}
  carregar().catch(() => {});
};
$("abaEnvios").onclick = () => mostrar("envios");
$("abaPareceres").onclick = () => mostrar("pareceres");
$("atualizar").onclick = () => carregar().catch(() => {});
$("sair").onclick = () => sair("");
if (senha) carregar().catch(() => {});
