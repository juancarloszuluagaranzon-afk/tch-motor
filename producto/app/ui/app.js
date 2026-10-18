"use strict";
// Estimador TCH — interfaz de la aplicación de escritorio. Habla con el servidor local (servidor.py).

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const TOKEN = (() => {
  const t = new URLSearchParams(location.search).get("t");
  if (t) { sessionStorage.setItem("t", t); history.replaceState(null, "", "/"); }
  return t || sessionStorage.getItem("t");
})();
const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString("es-CO", { maximumFractionDigits: d, minimumFractionDigits: d }));
const fechaCorta = (iso) => (iso ? iso.slice(8, 10) + "-" + iso.slice(5, 7) + "-" + iso.slice(0, 4) : "—");
const PLANTAS = { riopaila: "Riopaila", castilla: "Castilla" };
let ESTADO = null;

async function api(ruta, cuerpo) {
  const op = { headers: { "X-Token": TOKEN || "" } };
  if (cuerpo !== undefined) {
    op.method = "POST";
    op.headers["Content-Type"] = "application/json";
    op.body = JSON.stringify(cuerpo);
  }
  let r;
  try {
    r = await fetch(ruta, op);
  } catch (e) {
    throw new Error("El Estimador no responde: ciérralo y ábrelo de nuevo desde su acceso directo.");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Error ${r.status}`);
  return j;
}

function aviso(texto, error = false) {
  const t = $("#toast");
  t.textContent = texto;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(aviso._t);
  aviso._t = setTimeout(() => (t.hidden = true), error ? 7000 : 3500);
}

// ---------------------------------------------------------------- pestañas
function ir(p) {
  $$(".pestanas button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.p === p)));
  $$(".pagina").forEach((s) => (s.hidden = s.id !== "p-" + p));
  if (p === "resultados") $("#marco").src = "/tablero/?v=" + Date.now();
  if (p === "configuracion") cargarConfig();
}
$$(".pestanas button").forEach((b) => b.addEventListener("click", () => ir(b.dataset.p)));
$$("[data-ir]").forEach((b) => b.addEventListener("click", () => ir(b.dataset.ir)));

// ---------------------------------------------------------------- estado
async function cargarEstado() {
  try {
    ESTADO = await api("/api/estado");
  } catch (e) {
    aviso(e.message, true);
    return;
  }
  const s = ESTADO;
  $("#version").textContent = `Modelo Random Forest · versión ${s.version}`;
  $("#avisos").innerHTML = s.avisos.map((a) =>
    `<li class="${a.nivel}">${esc(a.texto)}${a.ir ? ` <a data-ir2="${a.ir}">Ir</a>` : ""}</li>`).join("");
  $$("[data-ir2]").forEach((a) => a.addEventListener("click", () => ir(a.dataset.ir2)));

  const c = s.corrida && !s.corrida.error ? s.corrida : null;
  const pub = s.publicado;
  let chip = '<span class="chip">sin conexión</span>';
  if (c && pub && pub.ok) chip = pub.fecha === c.fecha ? '<span class="chip ok">publicada</span>' : '<span class="chip atencion">sin publicar</span>';
  let html = `<div class="tarjeta"><div class="eti">Última corrida</div>
    <div class="grande">${c ? fechaCorta(c.fecha) : "—"}</div>
    <div class="det">${c ? `motor ${esc(c.version || "")} · satélite hasta ${esc(c.satelite || "—")}` : "Todavía no hay corrida"}</div>
    <div style="margin-top:6px">${chip}</div></div>`;
  for (const p of ["riopaila", "castilla"]) {
    const x = c && c.plantas[p];
    const f = c && c.factores[p];
    html += `<div class="tarjeta"><div class="eti">${PLANTAS[p]}</div>
      <div class="grande">${x ? fmt(x.toneladas) : "—"}<small>t en pie</small></div>
      <div class="det">${x ? `${fmt(x.suertes)} suertes · TCH ${fmt(x.tch, 1)}` : ""}${f ? ` · ajuste del año ${fmt(f, 3)}` : ""}</div></div>`;
  }
  $("#resumen").innerHTML = html;

  const cos = s.cosechas && !s.cosechas.error ? s.cosechas : null;
  $("#est-cosechas").textContent = cos
    ? `Cargadas hasta: Riopaila ${fechaCorta(cos.riopaila)} · Castilla ${fechaCorta(cos.castilla)} (${fmt(cos.filas)} cosechas en el archivo).`
    : "No encuentro el archivo de cosechas recientes.";
  $("#est-motor").textContent = c
    ? `Última corrida: ${fechaCorta(c.fecha)}. Satélite en la tabla: Riopaila ${s.satelite.riopaila || "—"}, Castilla ${s.satelite.castilla || "—"}; disponible hasta ${s.satelite_disponible}.`
    : "";
  $("#con-satelite").checked = !(s.satelite.riopaila && s.satelite.riopaila >= s.satelite_disponible && s.satelite.castilla >= s.satelite_disponible);
  $("#est-publicar").textContent = pub ? (pub.ok ? `El tablero publicado muestra la corrida del ${fechaCorta(pub.fecha)}.` : "No pude consultar el tablero publicado (¿sin internet?).") : "";

  const filas = s.insumos.map((i) => `<tr><td>${esc(i.nombre)}<div class="ruta">${esc(i.ruta)}</div></td>
    <td class="n">${i.modificado || "—"}</td>
    <td>${i.existe ? '<span class="chip ok">listo</span>' : '<span class="chip error">no está</span>'}</td></tr>`);
  filas.push(`<tr><td>Tabla del satélite<div class="ruta">${esc(s.trabajo)}\\Satelite</div></td>
    <td class="n">${s.satelite.riopaila || "—"} / ${s.satelite.castilla || "—"}</td>
    <td>${s.satelite.riopaila ? '<span class="chip ok">listo</span>' : '<span class="chip error">no está</span>'}</td></tr>`);
  $("#insumos").innerHTML = `<tr><th>Archivo</th><th>Modificado</th><th>Estado</th></tr>${filas.join("")}`;
  $("#trabajo-nota").innerHTML = `Carpeta de trabajo: <b>${esc(s.trabajo)}</b> · <a href="#" data-abrir="trabajo">abrir</a> · <a href="#" data-abrir="registros">registros</a>`;
  $$("[data-abrir]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); abrir(a.dataset.abrir); }));
  $("#programada").checked = !!s.programada;
  if (c && s.publicado !== undefined) $("#ver-publico").href = "https://" + (window.ALIAS || "estimador-tch.vercel.app");
  if (s.tarea && s.tarea.estado === "corriendo" && !TAREA) seguir(s.tarea);
}

function esc(t) {
  return String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function abrir(que, ruta) {
  try { await api("/api/abrir", { que, ruta }); } catch (e) { aviso(e.message, true); }
}

// ---------------------------------------------------------------- tareas
let TAREA = null;

async function lanzar(cuerpo) {
  try {
    const t = await api("/api/tarea", cuerpo);
    seguir(t);
  } catch (e) {
    aviso(e.message, true);
  }
}

function seguir(t) {
  TAREA = { id: t.id, desde: 0, log: t.log };
  $("#tarea-titulo").textContent = t.titulo;
  $("#tarea-log").textContent = "";
  ponerChip("corriendo");
  $("#tarea-detener").disabled = false;
  $("#tarea-cerrar").disabled = true;
  $("#tarea").hidden = false;
  sondear();
}

function ponerChip(e) {
  const txt = { corriendo: "corriendo…", ok: "terminó bien", error: "terminó con error" }[e];
  $("#tarea-chip").className = "chip " + e;
  $("#tarea-chip").textContent = txt;
}

async function sondear() {
  if (!TAREA) return;
  try {
    const r = await api(`/api/tarea?id=${TAREA.id}&desde=${TAREA.desde}`);
    if (r.texto) {
      const pre = $("#tarea-log");
      const abajo = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      pre.textContent += r.texto;
      if (abajo) pre.scrollTop = pre.scrollHeight;
    }
    TAREA.desde = r.desde;
    if (r.estado === "corriendo") {
      setTimeout(sondear, 900);
    } else {
      ponerChip(r.estado);
      $("#tarea-detener").disabled = true;
      $("#tarea-cerrar").disabled = false;
      cargarEstado();
    }
  } catch (e) {
    setTimeout(sondear, 2000);
  }
}

$("#tarea-cerrar").addEventListener("click", () => { $("#tarea").hidden = true; TAREA = null; });
$("#tarea-detener").addEventListener("click", async () => {
  if (!confirm("¿Detener la tarea? Lo que alcanzó a escribir queda como está.")) return;
  await api("/api/detener", {});
});
$("#tarea-registro").addEventListener("click", () => TAREA && abrir("log", TAREA.log));

const ACCIONES = {
  cosechas_app_sim: () => ({ tipo: "cosechas_app", mes: $("#mes-cosechas").value, simular: true }),
  cosechas_app: () => ({ tipo: "cosechas_app", mes: $("#mes-cosechas").value }),
  cosechas_lista_sim: () => lista(true),
  cosechas_lista: () => lista(false),
  motor: () => ({ tipo: "motor", satelite: $("#con-satelite").checked }),
  publicar: () => {
    const f = ESTADO && ESTADO.corrida && ESTADO.corrida.fecha;
    if (!confirm(`¿Publicar la corrida del ${fechaCorta(f)} en el tablero web? Todo el equipo la verá.`)) return null;
    return { tipo: "publicar" };
  },
  aforos_sim: () => ({ tipo: "aforos" }),
  aforos: () => (confirm("¿Escribir el estimado nuevo en los aforos de la app de Turnos?") ? { tipo: "aforos", aplicar: true } : null),
};
function lista(simular) {
  const texto = $("#lista-castilla").value.trim();
  if (!texto) { aviso("Pega primero la lista de cosechas.", true); return null; }
  return { tipo: "cosechas_lista", texto, simular };
}
$$("[data-accion]").forEach((b) => b.addEventListener("click", () => {
  const c = ACCIONES[b.dataset.accion]();
  if (c) lanzar(c);
}));

// ---------------------------------------------------------------- configuración
const CAMPOS = ["carpeta_insumos", "carpeta_trabajo", "gee_proyecto", "turnos_url", "vercel_equipo", "vercel_proyecto", "alias"];
async function cargarConfig() {
  try {
    const c = await api("/api/config");
    const f = $("#form-config");
    CAMPOS.forEach((k) => (f.elements[k].value = c[k] || ""));
    f.elements.turnos_key.value = "";
    f.elements.vercel_token.value = "";
    $("#llave-gee").textContent = c.cuenta_gee ? `Llave cargada: ${c.cuenta_gee}` : "Sin llave";
    $("#tiene-turnos").textContent = c.tiene.turnos_key ? "(hay una guardada)" : "(no hay ninguna guardada)";
    $("#tiene-vercel").textContent = c.tiene.vercel_token ? "(hay uno guardado)" : "(no hay ninguno guardado)";
    window.ALIAS = c.alias;
    $("#ver-publico").href = "https://" + c.alias;
  } catch (e) { aviso(e.message, true); }
}
$$("[data-elegir]").forEach((b) => b.addEventListener("click", async () => {
  try {
    const r = await api("/api/elegir", { tipo: "carpeta", titulo: "Elegir carpeta" });
    if (r.ruta) $("#form-config").elements[b.dataset.elegir].value = r.ruta;
  } catch (e) { aviso(e.message, true); }
}));
$("#cargar-llave").addEventListener("click", async () => {
  try {
    const r = await api("/api/elegir", { tipo: "archivo", titulo: "Llave de la cuenta de servicio de Earth Engine" });
    if (!r.ruta) return;
    const k = await api("/api/llave_gee", { ruta: r.ruta });
    $("#llave-gee").textContent = `Llave cargada: ${k.cuenta}`;
    aviso("Llave guardada y cifrada.");
  } catch (e) { aviso(e.message, true); }
});
$$("[data-probar]").forEach((b) => b.addEventListener("click", () => lanzar({ tipo: b.dataset.probar })));
$("#form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const cuerpo = {};
  CAMPOS.forEach((k) => (cuerpo[k] = f.elements[k].value.trim()));
  for (const k of ["turnos_key", "vercel_token"]) if (f.elements[k].value.trim()) cuerpo[k] = f.elements[k].value.trim();
  try {
    const r = await api("/api/config", cuerpo);
    $("#config-msg").textContent = r.copiado ? `Guardado. Se prepararon ${r.copiado} archivos iniciales en la carpeta de trabajo.` : "Guardado.";
    cargarConfig();
    cargarEstado();
  } catch (e) { aviso(e.message, true); }
});
$("#programada").addEventListener("change", async (ev) => {
  try {
    const r = await api("/api/programar", { activar: ev.target.checked });
    aviso(r.mensaje);
  } catch (e) { aviso(e.message, true); ev.target.checked = !ev.target.checked; }
});

// ---------------------------------------------------------------- arranque
(function () {
  const hoy = new Date();
  $("#mes-cosechas").value = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;
  if (!TOKEN) { aviso("Abre el Estimador desde su acceso directo.", true); return; }
  cargarEstado();
  cargarConfig();
  setInterval(() => api("/api/latido", {}).catch(() => {}), 10000);
  api("/api/latido", {}).catch(() => {});
  setInterval(() => { if (!TAREA && !document.hidden) cargarEstado(); }, 30000);
})();
