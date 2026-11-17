const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const fmt = (v) => (v == null ? "—" : brl.format(v));
const $ = (sel, el = document) => el.querySelector(sel);

let produtos = [];
let filtro = "pendentes";
let busca = "";

async function api(metodo, url, corpo) {
  const resp = await fetch(url, {
    method: metodo,
    headers: corpo ? { "Content-Type": "application/json" } : {},
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (resp.status === 204) return null;
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(dados.erro || `Erro ${resp.status}`);
  return dados;
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 4000);
}

function substituir(produto) {
  const i = produtos.findIndex((p) => p.id === produto.id);
  if (i >= 0) produtos[i] = produto; else produtos.unshift(produto);
  render();
}

async function carregar() {
  produtos = await api("GET", "/api/produtos");
  render();
}

function renderResumo() {
  const pend = produtos.filter((p) => !p.comprado);
  const total = pend.reduce((s, p) => s + (p.melhor_total || 0) * p.quantidade, 0);
  const economia = pend.reduce((s, p) => s + (p.economia || 0) * p.quantidade, 0);
  const gasto = produtos
    .filter((p) => p.comprado)
    .reduce((s, p) => s + (p.melhor_total || 0) * p.quantidade, 0);
  $("#resumo").innerHTML = `
    <div><small>A comprar</small><strong>${pend.length}</strong></div>
    <div><small>Total (menor preço + frete)</small><strong>${fmt(total)}</strong></div>
    <div><small>Economia comparando</small><strong>${fmt(economia)}</strong></div>
    <div><small>Já comprado</small><strong>${fmt(gasto)}</strong></div>`;
}

function render() {
  renderResumo();
  const lista = $("#lista");
  lista.innerHTML = "";
  const termo = busca.toLowerCase();
  const visiveis = produtos.filter(
    (p) =>
      (filtro === "todos" || (filtro === "comprados") === p.comprado) &&
      p.nome.toLowerCase().includes(termo)
  );
  if (!visiveis.length) {
    lista.innerHTML = `<p class="vazio">${
      produtos.length ? "Nenhum produto neste filtro." : "Sua lista está vazia. Adicione o primeiro produto acima."
    }</p>`;
    return;
  }
  for (const p of visiveis) lista.appendChild(cardProduto(p));
}

function cardProduto(p) {
  const el = $("#tpl-produto").content.firstElementChild.cloneNode(true);
  el.classList.toggle("feito", p.comprado);

  const foto = $(".foto", el);
  const img = $("img", foto);
  if (p.foto) {
    img.src = p.foto;
    img.alt = p.nome;
    img.referrerPolicy = "no-referrer";
    img.onerror = () => foto.classList.add("vazia");
  } else foto.classList.add("vazia");

  $(".nome", el).textContent = p.quantidade > 1 ? `${p.nome} (x${p.quantidade})` : p.nome;
  $(".obs", el).textContent = p.observacao || "";

  const chk = $(".comprado", el);
  chk.checked = p.comprado;
  chk.onchange = async () => substituir(await api("PATCH", `/api/produtos/${p.id}`, { comprado: chk.checked }));

  const destaque = $(".destaque", el);
  const comPreco = p.links.filter((l) => l.total != null);
  if (comPreco.length) {
    const m = comPreco[0];
    let txt = `✅ Menor valor: <strong>${fmt(m.total)}</strong> na <strong>${esc(m.loja)}</strong>`;
    txt += m.frete ? ` (produto ${fmt(m.preco)} + frete ${fmt(m.frete)})` : " (frete grátis/não informado)";
    if (comPreco.length > 1 && p.economia > 0) txt += ` — economia de ${fmt(p.economia)} vs. a opção mais cara`;
    destaque.innerHTML = txt;
  } else {
    destaque.classList.add("neutro");
    destaque.textContent = p.links.length
      ? "Informe o preço dos links para comparar."
      : "Adicione links de compra para comparar os preços.";
  }

  const tbody = $("tbody", el);
  if (!p.links.length) {
    $(".ofertas", el).replaceWith(Object.assign(document.createElement("p"), {
      className: "sem-ofertas", textContent: "Nenhum link ainda.",
    }));
  }
  for (const l of p.links) tbody.appendChild(linhaLink(l));

  const form = $(".form-link", el);
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const btn = $("button", form);
    btn.disabled = true; btn.textContent = "Buscando…";
    try {
      const dados = Object.fromEntries(new FormData(form));
      const r = await api("POST", `/api/produtos/${p.id}/links`, dados);
      if (r.aviso) toast(r.aviso);
      substituir(r.produto);
    } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "+ Link"; }
  };

  $(".editar", el).onclick = async () => {
    const nome = prompt("Nome do produto:", p.nome);
    if (nome == null) return;
    const quantidade = prompt("Quantidade:", p.quantidade);
    const foto_url = prompt("URL da foto (vazio = foto da loja):", p.foto_url || "");
    const observacao = prompt("Observação:", p.observacao || "");
    substituir(await api("PATCH", `/api/produtos/${p.id}`, {
      nome, quantidade: quantidade || 1, foto_url: foto_url ?? p.foto_url, observacao: observacao ?? p.observacao,
    }));
  };
  $(".excluir", el).onclick = async () => {
    if (!confirm(`Excluir "${p.nome}" e todos os links?`)) return;
    await api("DELETE", `/api/produtos/${p.id}`);
    produtos = produtos.filter((x) => x.id !== p.id);
    render();
  };
  return el;
}

function linhaLink(l) {
  const tr = document.createElement("tr");
  if (l.melhor) tr.className = "melhor";
  tr.innerHTML = `
    <td class="loja"><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.loja || "Loja")} ↗</a>${
      l.melhor ? '<span class="selo">MENOR PREÇO</span>' : ""}</td>
    <td data-r="Preço"><input class="preco" inputmode="decimal" value="${l.preco != null ? l.preco.toFixed(2).replace(".", ",") : ""}" placeholder="informar"></td>
    <td data-r="Frete"><input class="frete" inputmode="decimal" value="${l.frete ? l.frete.toFixed(2).replace(".", ",") : ""}" placeholder="0,00"></td>
    <td data-r="Total" class="total">${fmt(l.total)}</td>
    <td class="acoes-link">
      <button class="link-btn atualizar" title="Buscar preço novamente na loja">↻ preço</button>
      <button class="link-btn perigo remover" title="Remover link">✕</button>
    </td>`;

  const salvar = async () => {
    const r = await api("PATCH", `/api/links/${l.id}`, {
      preco: $(".preco", tr).value, frete: $(".frete", tr).value,
    });
    substituir(r.produto);
  };
  for (const inp of tr.querySelectorAll("input")) {
    inp.onchange = salvar;
    inp.onkeydown = (e) => e.key === "Enter" && inp.blur();
  }
  $(".atualizar", tr).onclick = async (e) => {
    e.target.textContent = "…";
    const r = await api("POST", `/api/links/${l.id}/atualizar`);
    toast(r.aviso || "Preço atualizado.");
    substituir(r.produto);
  };
  $(".remover", tr).onclick = async () => {
    if (!confirm("Remover este link?")) return;
    substituir((await api("DELETE", `/api/links/${l.id}`)).produto);
  };
  return tr;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

$("#form-produto").onsubmit = async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const btn = $("button", form);
  const dados = Object.fromEntries(new FormData(form));
  if (!dados.nome.trim() && !dados.url.trim()) {
    toast("Cole um link de compra ou digite o nome do produto.");
    return;
  }
  btn.disabled = true; btn.textContent = dados.url ? "Buscando dados da loja…" : "Salvando…";
  try {
    const r = await api("POST", "/api/produtos", dados);
    if (r.aviso) toast(r.aviso);
    form.reset();
    if (filtro === "comprados") setFiltro("pendentes");
    substituir(r.produto);
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = "Adicionar";
};

function setFiltro(f) {
  filtro = f;
  for (const b of document.querySelectorAll("#abas button")) b.classList.toggle("ativa", b.dataset.filtro === f);
  render();
}
for (const b of document.querySelectorAll("#abas button")) b.onclick = () => setFiltro(b.dataset.filtro);
$("#busca").oninput = (e) => { busca = e.target.value; render(); };

// ---- tema claro/escuro (padrão: escuro; a escolha fica salva no navegador)
function aplicarTema(tema) {
  document.documentElement.dataset.theme = tema;
  const btn = $("#tema");
  btn.textContent = tema === "dark" ? "☀️ Modo claro" : "🌙 Modo escuro";
  try { localStorage.setItem("tema", tema); } catch {}
}
$("#tema").onclick = () =>
  aplicarTema(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
aplicarTema(document.documentElement.dataset.theme || "dark");

carregar().catch((e) => toast(e.message));
