// Página de administração da fila. Todo dado vindo do servidor entra com textContent (nunca innerHTML).
const $ = (id) => document.getElementById(id);
let senha = "";
try { senha = sessionStorage.getItem("adm") || ""; } catch (e) {}

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, {...opcoes, headers: {...(opcoes.headers || {}), Authorization: "Bearer " + senha}});
  if (r.status === 401) { sair("Senha incorreta."); throw new Error("401"); }
  return r;
}

function sair(texto) {
  senha = "";
  try { sessionStorage.removeItem("adm"); } catch (e) {}
  $("painel").hidden = true; $("entrar").hidden = false; $("msg").textContent = texto || "";
}

const NOMES = {na_fila: "Na fila", rascunho: "Rascunho pronto", repetido: "Já tem parecer: pronto para avisar",
  publicado: "Publicado", ja_publicado: "Avisado: já publicado", procede: "Procede", descartado: "Descartado"};

const RESULTADOS = ["publicado", "ja_publicado", "procede", "descartado"];

async function carregar() {
  $("msg").textContent = "Carregando…";
  const r = await api("/admin/api/fila");
  if (!r.ok) { $("msg").textContent = (await r.json()).erro || "Erro."; return; }
  const itens = await r.json();
  api("/admin/api/uso").then((u) => u.ok && u.json()).then((u) => {
    if (u) $("uso").textContent = "Armazenamento: " + (u.bytes / 1024 ** 2).toFixed(1) + " MB de " + (u.limite_bytes / 1024 ** 3).toFixed(0) +
      " GB · " + u.envios + " de " + u.limite_envios + " envios guardados. Ao chegar no limite, o site para de aceitar envios.";
  }).catch(() => {});
  $("entrar").hidden = true; $("painel").hidden = false;
  $("msg").textContent = itens.length ? itens.filter((i) => i.status === "na_fila").length + " na fila, " +
    itens.filter((i) => i.status === "repetido").length + " repetidos para avisar, " + itens.length + " no total." : "Nenhum envio.";
  const lista = $("lista"); lista.replaceChildren();
  for (const it of itens) {
    const n = $("modelo").content.firstElementChild.cloneNode(true);
    n.querySelector(".prot").textContent = it.protocolo;
    n.querySelector(".meta").textContent = it.criado.replace("T", " ").replace("Z", " UTC") + " · " + NOMES[it.status] + (it.tem_email ? " · pediu aviso" : "");
    n.querySelector(".onde").textContent = it.onde ? "Onde viu: " + it.onde : "";
    n.querySelector(".link").value = it.link || "";
    if (RESULTADOS.includes(it.status)) n.querySelector(".res").value = it.status;
    if (it.status === "repetido") n.querySelector(".res").value = "ja_publicado";  // a rotina já pôs o link do parecer
    if (it.pr) { const a = n.querySelector(".pr"); a.href = it.pr; a.textContent = "Ver o PR com o parecer"; a.hidden = false; }
    else if (it.status === "repetido" && it.link) { const a = n.querySelector(".pr"); a.href = it.link; a.textContent = "Ver o parecer que já existe"; a.hidden = false; }
    n.querySelector(".ver").onclick = async () => {
      const img = n.querySelector("img");
      const resp = await api("/admin/api/print/" + encodeURIComponent(it.protocolo));
      if (!resp.ok) return;
      if (img.src) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(await resp.blob()); img.hidden = false;
    };
    n.querySelector(".concluir").onclick = async () => {
      const out = n.querySelector(".retorno"); out.textContent = "Enviando…";
      const resp = await api("/admin/api/concluir", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({protocolo: it.protocolo, resultado: n.querySelector(".res").value, link: n.querySelector(".link").value})});
      const d = await resp.json();
      out.className = "retorno aviso" + (resp.ok ? "" : " erro");
      out.textContent = d.erro || ("Marcado como " + NOMES[d.status] + ". " +
        ({enviado: "Aviso enviado por e-mail e endereço apagado.", sem_email: "A pessoa não pediu aviso.", falhou: "O e-mail falhou; tente concluir de novo."})[d.email]);
    };
    n.querySelector(".apagar").onclick = async () => {
      if (!confirm("Apagar o envio " + it.protocolo + "? Não dá para desfazer.")) return;
      const resp = await api("/admin/api/apagar", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({protocolo: it.protocolo})});
      if (resp.ok) n.remove();
    };
    lista.append(n);
  }
}

$("entrar").onsubmit = (e) => {
  e.preventDefault();
  senha = $("senha").value; $("senha").value = "";
  try { sessionStorage.setItem("adm", senha); } catch (e2) {}
  carregar().catch(() => {});
};
$("atualizar").onclick = () => carregar().catch(() => {});
$("sair").onclick = () => sair("");
if (senha) carregar().catch(() => {});
