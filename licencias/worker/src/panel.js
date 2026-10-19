// Panel web de administracion de licencias (una sola pagina, sin dependencias).
// Se sirve en GET /admin/panel. La pagina es publica pero inofensiva: no trae datos ni
// secretos; todo lo que muestra o cambia lo pide a /admin/* con el ADMIN_TOKEN que el
// administrador escribe (se guarda solo en sessionStorage: se borra al cerrar la pestaña).
// Los textos de las licencias se escriben con textContent, nunca como HTML.

export const PANEL_HTML = `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Licencias</title>
<style>
  :root { --azul:#0D47A1; --borde:#CBD5E1; --fondo:#F8FAFC; --texto:#1E293B; --suave:#64748B;
          --verde:#16A34A; --ambar:#D97706; --rojo:#DC2626; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif; background:var(--fondo); color:var(--texto); }
  header { background:var(--azul); color:#fff; padding:14px 24px; display:flex; align-items:center; gap:16px; }
  header h1 { font-size:18px; margin:0; flex:1; }
  main { max-width:1200px; margin:24px auto; padding:0 16px; }
  .tarjeta { background:#fff; border:1px solid var(--borde); border-radius:12px; padding:20px; margin-bottom:20px; }
  h2 { margin:0 0 14px; font-size:16px; }
  label { display:block; font-weight:600; font-size:12px; margin-bottom:4px; }
  input, select { width:100%; padding:9px 10px; border:1px solid var(--borde); border-radius:6px; font:inherit; }
  input:focus, select:focus { outline:2px solid #BFDBFE; border-color:var(--azul); }
  .rejilla { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; align-items:end; }
  button { padding:9px 14px; border-radius:6px; border:1px solid var(--borde); background:#fff; font:inherit; cursor:pointer; }
  button:hover { background:#F1F5F9; }
  button.primario { background:var(--azul); border-color:var(--azul); color:#fff; font-weight:600; }
  button.primario:hover { background:#0A3A83; }
  button.chico { padding:4px 9px; font-size:12px; }
  button.peligro { color:var(--rojo); border-color:#FCA5A5; }
  button:disabled { opacity:.5; cursor:default; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:12px; color:var(--suave); padding:8px; border-bottom:2px solid var(--borde); }
  td { padding:9px 8px; border-bottom:1px solid #E2E8F0; vertical-align:middle; }
  tr:hover td { background:#F8FAFC; }
  .envoltorio { overflow-x:auto; }
  .etiqueta { display:inline-block; padding:2px 9px; border-radius:99px; font-size:12px; font-weight:600; color:#fff; }
  .acciones { display:flex; gap:6px; flex-wrap:wrap; }
  .aviso { padding:10px 14px; border-radius:8px; margin-bottom:14px; }
  .aviso.error { background:#FEE2E2; color:#991B1B; }
  .aviso.ok { background:#DCFCE7; color:#166534; }
  .clave { font:600 20px ui-monospace,Consolas,monospace; letter-spacing:1px; background:#EFF6FF; border:1px dashed var(--azul);
           padding:12px 16px; border-radius:8px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .suave { color:var(--suave); font-size:12px; }
  #login { max-width:420px; margin:80px auto; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<header>
  <h1>Panel de licencias</h1>
  <button id="salir" hidden>Cerrar sesión</button>
</header>

<main>
  <section id="login" class="tarjeta">
    <h2>Acceso de administrador</h2>
    <label for="token">ADMIN_TOKEN</label>
    <input id="token" type="password" autocomplete="off" placeholder="El token que cargaste en Cloudflare">
    <p class="suave">Se guarda solo en esta pestaña y se borra al cerrarla.</p>
    <div id="login-error" class="aviso error" hidden></div>
    <button id="entrar" class="primario">Entrar</button>
  </section>

  <div id="app" hidden>
    <div id="mensaje" class="aviso" hidden></div>

    <section class="tarjeta">
      <h2>Nueva licencia</h2>
      <div class="rejilla">
        <div><label for="cliente">Cliente</label><input id="cliente" maxlength="120" placeholder="Distribuidora X"></div>
        <div><label for="plan">Plan</label><input id="plan" maxlength="40" value="estandar"></div>
        <div><label for="maxest">Estaciones (PCs)</label><input id="maxest" type="number" min="1" max="1000" value="1"></div>
        <div><label for="vigencia">Vigencia</label>
          <select id="vigencia">
            <option value="dias">Días desde hoy</option>
            <option value="expira">Hasta una fecha</option>
            <option value="perpetua">Sin vencimiento</option>
          </select></div>
        <div id="campo-dias"><label for="dias">Días</label><input id="dias" type="number" min="1" value="365"></div>
        <div id="campo-fecha" hidden><label for="fecha">Vence el</label><input id="fecha" type="date"></div>
        <div><label for="notas">Notas (opcional)</label><input id="notas" maxlength="200" placeholder="Contacto, factura, etc."></div>
        <div><button id="emitir" class="primario">Generar licencia</button></div>
      </div>
      <div id="resultado" hidden style="margin-top:16px">
        <p><b>Clave generada.</b> Cópiala ahora: no se vuelve a mostrar, el servidor solo guarda su huella.</p>
        <div class="clave"><span id="clave-nueva"></span><button id="copiar">Copiar</button></div>
      </div>
    </section>

    <section class="tarjeta">
      <div style="display:flex; gap:12px; align-items:center; margin-bottom:14px; flex-wrap:wrap">
        <h2 style="margin:0; flex:1">Licencias</h2>
        <input id="buscar" placeholder="Buscar cliente, plan o notas…" style="max-width:280px">
        <button id="recargar">Actualizar</button>
      </div>
      <div class="envoltorio">
        <table>
          <thead><tr><th>Cliente</th><th>Plan</th><th>Clave</th><th>Vence</th><th>Estaciones</th><th>Estado</th><th>Notas</th><th>Acciones</th></tr></thead>
          <tbody id="filas"></tbody>
        </table>
      </div>
      <p id="vacio" class="suave" hidden>No hay licencias que mostrar.</p>
    </section>
  </div>
</main>

<script>
(() => {
  const $ = (id) => document.getElementById(id);
  const DIA = 86400;
  let token = sessionStorage.getItem("admin_token") || "";
  let licencias = [];

  async function api(metodo, ruta, cuerpo) {
    const r = await fetch(ruta, {
      method: metodo,
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
    const datos = await r.json().catch(() => ({}));
    if (r.status === 401) { cerrarSesion(); throw new Error("Token incorrecto."); }
    if (!r.ok) throw new Error(datos.error || "Error " + r.status);
    return datos;
  }

  function aviso(texto, tipo) {
    const m = $("mensaje");
    m.textContent = texto; m.className = "aviso " + tipo; m.hidden = false;
    clearTimeout(aviso.t); aviso.t = setTimeout(() => (m.hidden = true), 6000);
  }

  const fecha = (e) => (e ? new Date(e * 1000).toLocaleDateString("es-VE") : "Sin vencimiento");

  function estado(l) {
    const ahora = Date.now() / 1000;
    if (l.revocada) return ["Revocada", "var(--rojo)"];
    if (l.expira && l.expira < ahora) return ["Vencida", "var(--rojo)"];
    if (l.expira && l.expira - ahora < 15 * DIA) return ["Por vencer", "var(--ambar)"];
    return l.hw_id ? ["Activa", "var(--verde)"] : ["Sin activar", "var(--suave)"];
  }

  function boton(texto, clase, accion) {
    const b = document.createElement("button");
    b.textContent = texto; b.className = "chico " + clase; b.addEventListener("click", accion);
    return b;
  }

  async function accionar(ruta, cuerpo, okTexto) {
    try { await api("POST", ruta, cuerpo); aviso(okTexto, "ok"); await cargar(); }
    catch (e) { aviso(e.message, "error"); }
  }

  const abiertas = new Set(); // licencias con el detalle de estaciones desplegado
  const fechaHora = (e) => (e ? new Date(e * 1000).toLocaleString("es-VE", { dateStyle: "short", timeStyle: "short" }) : "—");

  function etiqueta(texto, color) {
    const et = document.createElement("span");
    et.className = "etiqueta"; et.textContent = texto; et.style.background = color;
    return et;
  }

  function detalleEstaciones(l) {
    const cont = document.createElement("div");
    const max = l.max_estaciones || 1;
    const ahora = Date.now() / 1000;
    const autorizadas = new Set(l.autorizadas || []);
    const lista = Object.entries(l.estaciones || {}).sort((a, b) => a[1].primera - b[1].primera);
    const resumen = document.createElement("p");
    resumen.textContent = "Puestos en uso: " + autorizadas.size + " de " + max + ". " +
      (l.hw_id ? "Servidor activado: PC " + l.hw_id.slice(0, 8) + "… el " + fechaHora(l.activada_en)
               : "Aún no está activada en ningún servidor.");
    cont.append(resumen);
    if (!lista.length) {
      const vacio = document.createElement("p");
      vacio.className = "suave";
      vacio.textContent = "Aún no hay estaciones registradas: aparecen cuando el servidor renueva la licencia.";
      cont.append(vacio);
      return cont;
    }
    const tabla = document.createElement("table");
    const cab = document.createElement("tr");
    for (const t of ["Equipo", "ID", "Primera vez", "Último uso", "Puesto", ""]) {
      const th = document.createElement("th"); th.textContent = t; cab.append(th);
    }
    tabla.append(cab);
    for (const [hw, e] of lista) {
      const tr = document.createElement("tr");
      const celda = (txt) => { const td = document.createElement("td"); td.textContent = txt; tr.append(td); return td; };
      const tdNombre = celda(e.nombre || "(sin nombre)");
      if (hw === l.hw_id) { const b = etiqueta("Servidor", "var(--azul)"); b.style.marginLeft = "8px"; tdNombre.append(b); }
      celda(hw.slice(0, 8) + "…"); celda(fechaHora(e.primera)); celda(fechaHora(e.ultima));
      const inactiva = e.ultima < ahora - 30 * DIA;
      const [txt, color] = autorizadas.has(hw) ? ["Con puesto", "var(--verde)"]
        : inactiva ? ["Inactiva (30+ días)", "var(--suave)"] : ["Sin puesto", "var(--rojo)"];
      const tdPuesto = document.createElement("td"); tdPuesto.append(etiqueta(txt, color)); tr.append(tdPuesto);
      const tdAccion = document.createElement("td");
      tdAccion.append(boton("Liberar puesto", "peligro", () => {
        if (confirm("Liberar el puesto de " + (e.nombre || "esta estación") + "? Deja de contar hasta que vuelva a abrir la app."))
          accionar("/admin/liberar_estacion", { hash: l.hash, hw }, "Puesto liberado.");
      }));
      tr.append(tdAccion); tabla.append(tr);
    }
    cont.append(tabla);
    return cont;
  }

  function dibujar() {
    const q = $("buscar").value.trim().toLowerCase();
    const filas = $("filas"); filas.replaceChildren();
    const vistas = licencias
      .filter((l) => !q || [l.cliente, l.plan, l.notas].some((v) => (v || "").toLowerCase().includes(q)))
      .sort((a, b) => (b.creada_en || 0) - (a.creada_en || 0));
    $("vacio").hidden = vistas.length > 0;
    for (const l of vistas) {
      const tr = document.createElement("tr");
      const celda = (txt) => { const td = document.createElement("td"); td.textContent = txt; tr.append(td); return td; };
      celda(l.cliente || "—"); celda(l.plan || "—");
      celda("…" + (l.sufijo || "????")).title = "Solo se guardan los últimos 4 caracteres; la clave completa no es recuperable.";
      celda(fecha(l.expira));
      const max = l.max_estaciones || 1;
      const vigentes = Object.values(l.estaciones || {}).filter((e) => e.ultima > Date.now() / 1000 - 30 * DIA);
      const conPuesto = (l.autorizadas || []).length;
      const exceso = vigentes.length - conPuesto;
      const tdEst = celda(conPuesto + " / " + max + (exceso > 0 ? "  (+" + exceso + " sin puesto)" : ""));
      tdEst.title = "Estaciones con puesto / límite de la licencia. Pulsa 'Detalle' para ver cada equipo.";
      if (exceso > 0) tdEst.style.color = "var(--rojo)";
      const [txt, color] = estado(l);
      const tdEstado = document.createElement("td");
      tdEstado.append(etiqueta(txt, color));
      if (l.hw_id) { const sub = document.createElement("div"); sub.className = "suave"; sub.textContent = "Servidor " + l.hw_id.slice(0, 8) + "…"; tdEstado.append(sub); }
      tr.append(tdEstado);
      celda(l.notas || "");
      const tdAcc = document.createElement("td"); const acc = document.createElement("div"); acc.className = "acciones";
      const ref = { hash: l.hash };
      acc.append(boton(abiertas.has(l.hash) ? "Ocultar" : "Detalle", "", () => {
        if (abiertas.has(l.hash)) abiertas.delete(l.hash); else abiertas.add(l.hash);
        dibujar();
      }));
      acc.append(boton("Límite", "", () => {
        const d = prompt("Cuántas estaciones (PCs) permite esta licencia? Cuenta todo equipo que abre la app, servidor incluido.", String(max));
        if (d === null) return;
        const n = Number(d);
        if (!Number.isInteger(n) || n < 1 || n > 1000) return aviso("Número de estaciones inválido (1 a 1000).", "error");
        accionar("/admin/editar", { ...ref, max_estaciones: n }, "Límite de estaciones actualizado.");
      }));
      acc.append(boton("Renovar", "", () => {
        const d = prompt("Renovar por cuántos días desde hoy? (0 = sin vencimiento)", "365");
        if (d === null) return;
        const n = Number(d);
        if (!Number.isFinite(n) || n < 0) return aviso("Número de días inválido.", "error");
        accionar("/admin/renovar", { ...ref, ...(n === 0 ? { perpetua: true } : { dias: n }) }, "Licencia renovada.");
      }));
      if (l.hw_id) acc.append(boton("Liberar servidor", "", () => {
        if (confirm("Liberar el servidor de " + (l.cliente || "esta licencia") + "? Podrá activarse en otra computadora."))
          accionar("/admin/liberar", ref, "Servidor liberado.");
      }));
      if (l.revocada) acc.append(boton("Restaurar", "", () => accionar("/admin/restaurar", ref, "Licencia restaurada.")));
      else acc.append(boton("Revocar", "peligro", () => {
        if (confirm("Revocar la licencia de " + (l.cliente || "este cliente") + "? La app quedará en solo lectura en su próxima validación."))
          accionar("/admin/revocar", ref, "Licencia revocada.");
      }));
      tdAcc.append(acc); tr.append(tdAcc);
      filas.append(tr);
      if (abiertas.has(l.hash)) {
        const trDetalle = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 8; td.style.background = "#F8FAFC";
        td.append(detalleEstaciones(l));
        trDetalle.append(td); filas.append(trDetalle);
      }
    }
  }

  async function cargar() {
    const r = await api("GET", "/admin/listar");
    licencias = r.licencias; dibujar();
  }

  function mostrarApp(si) { $("login").hidden = si; $("app").hidden = !si; $("salir").hidden = !si; }
  function cerrarSesion() { token = ""; sessionStorage.removeItem("admin_token"); mostrarApp(false); }

  async function entrar() {
    token = $("token").value.trim();
    $("login-error").hidden = true;
    try { await cargar(); sessionStorage.setItem("admin_token", token); $("token").value = ""; mostrarApp(true); }
    catch (e) { $("login-error").textContent = e.message; $("login-error").hidden = false; token = ""; }
  }

  $("entrar").addEventListener("click", entrar);
  $("token").addEventListener("keydown", (e) => e.key === "Enter" && entrar());
  $("salir").addEventListener("click", cerrarSesion);
  $("recargar").addEventListener("click", () => cargar().catch((e) => aviso(e.message, "error")));
  $("buscar").addEventListener("input", dibujar);
  $("vigencia").addEventListener("change", () => {
    $("campo-dias").hidden = $("vigencia").value !== "dias";
    $("campo-fecha").hidden = $("vigencia").value !== "expira";
  });

  $("emitir").addEventListener("click", async () => {
    const cliente = $("cliente").value.trim();
    if (!cliente) return aviso("Escribe el nombre del cliente.", "error");
    const v = $("vigencia").value;
    const cuerpo = { cliente, plan: $("plan").value.trim() || "estandar", notas: $("notas").value.trim(),
                     max_estaciones: Number($("maxest").value) };
    if (v === "perpetua") cuerpo.perpetua = true;
    else if (v === "expira") { if (!$("fecha").value) return aviso("Elige la fecha de vencimiento.", "error"); cuerpo.expira = $("fecha").value; }
    else cuerpo.dias = Number($("dias").value);
    $("emitir").disabled = true;
    try {
      const r = await api("POST", "/admin/emitir", cuerpo);
      $("clave-nueva").textContent = r.clave; $("resultado").hidden = false;
      $("cliente").value = ""; $("notas").value = "";
      await cargar();
    } catch (e) { aviso(e.message, "error"); }
    $("emitir").disabled = false;
  });

  $("copiar").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("clave-nueva").textContent); $("copiar").textContent = "¡Copiada!"; }
    catch { aviso("No se pudo copiar; selecciona el texto a mano.", "error"); }
    setTimeout(() => ($("copiar").textContent = "Copiar"), 2000);
  });

  if (token) cargar().then(() => mostrarApp(true)).catch(() => cerrarSesion());
})();
</script>
</body>
</html>`;
