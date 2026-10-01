// Servidor de licencias (Cloudflare Worker + KV). Ver licencias/README.md.
//
// Endpoints publicos (los usa la app):
//   POST /v1/activar  {clave, hw_id}  -> ata la clave a esa PC la primera vez
//   POST /v1/validar  {clave, hw_id}  -> renueva el token si sigue vigente
// El cuerpo puede traer `estaciones` [{hw, nombre, ultima}]: las PCs cliente (estaciones) que usan
// la instalacion. Solo las reporta el SERVIDOR (que es quien activa la licencia).
// Ambos responden {token} (firmado Ed25519) o {error, codigo} con 4xx.
//
// Endpoints de administracion (Authorization: Bearer <ADMIN_TOKEN>):
//   POST /admin/emitir    {cliente, plan, dias | expira | perpetua}
//   POST /admin/renovar   {clave|hash, dias | expira | perpetua}
//   POST /admin/revocar   {clave|hash}
//   POST /admin/restaurar {clave|hash}
//   POST /admin/liberar   {clave|hash}   (desata la PC: reinstalacion / cambio de equipo)
//   POST /admin/editar    {clave|hash, cliente?, plan?, notas?, max_estaciones?}
//   POST /admin/liberar_estacion {clave|hash, hw}  (libera el puesto de UNA estacion)
//   GET  /admin/listar
//   GET  /admin/panel     (pagina web de administracion, ver panel.js; pide el ADMIN_TOKEN)
//
// Secretos (wrangler secret put): PRIVATE_KEY_B64 (Ed25519 PKCS8 en base64), ADMIN_TOKEN.
// Variable: TTL_DIAS (gracia sin conexion, 7 por defecto). KV: LICENCIAS.
//
// KV gratis permite 1000 escrituras/dia: por eso /validar NO escribe en cada llamada,
// solo refresca `ultima_validacion` como maximo una vez por dia por licencia.

import { PANEL_HTML } from "./panel.js";

const DIA = 86400;
const ALFABETO = "ABCDEFGHJKMNPQRSTVWXYZ23456789"; // 30 simbolos, sin 0/O/1/I/L
const enc = new TextEncoder();

const json = (cuerpo, status = 200) =>
  new Response(JSON.stringify(cuerpo), { status, headers: { "content-type": "application/json" } });

const rechazo = (status, codigo, error) => json({ codigo, error }, status);

const normalizar = (clave) => String(clave || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

function b64u(buffer) {
  let s = "";
  for (const b of new Uint8Array(buffer)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64Bytes(texto) {
  const bin = atob(texto);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function sha256hex(texto) {
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(texto));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function generarClave() {
  // Muestreo por rechazo (240 = 8 * 30) para que los 30 simbolos sean equiprobables.
  let clave = "";
  while (clave.length < 20) {
    for (const b of crypto.getRandomValues(new Uint8Array(32))) {
      if (b < 240 && clave.length < 20) clave += ALFABETO[b % 30];
    }
  }
  return clave.match(/.{5}/g).join("-");
}

let clavePrivadaPromesa = null;
function clavePrivada(env) {
  if (!clavePrivadaPromesa) {
    clavePrivadaPromesa = crypto.subtle.importKey("pkcs8", b64Bytes(env.PRIVATE_KEY_B64), { name: "Ed25519" }, false, [
      "sign",
    ]);
  }
  return clavePrivadaPromesa;
}

const VENTANA_ESTACIONES = 30 * DIA; // una estacion sin verse en 30 dias libera su puesto

// Puestos autorizados: las `max_estaciones` mas antiguas (por `primera`, fijada aqui por el
// servidor al verlas por primera vez, no por el cliente) entre las vistas en los ultimos 30 dias.
function estacionesAutorizadas(lic, ahora) {
  const max = lic.max_estaciones || 1;
  return Object.entries(lic.estaciones || {})
    .filter(([, e]) => e.ultima > ahora - VENTANA_ESTACIONES)
    .sort((a, b) => a[1].primera - b[1].primera)
    .slice(0, max)
    .map(([hw]) => hw);
}

function fusionarEstaciones(lic, reportadas, ahora) {
  if (!Array.isArray(reportadas)) return false;
  lic.estaciones ||= {};
  let cambio = false;
  for (const e of reportadas.slice(0, 200)) {
    const hw = String(e?.hw || "");
    if (!/^[0-9a-f]{64}$/.test(hw)) continue;
    const nombre = String(e.nombre || "").slice(0, 60);
    const ultima = Math.min(Number(e.ultima) || ahora, ahora);
    // Una estacion liberada por el administrador no vuelve a ocupar puesto hasta que se USE de nuevo
    // (su ultimo uso posterior a la liberacion); si solo sigue figurando en la base del servidor, se ignora.
    const liberada = lic.liberadas?.[hw];
    if (liberada) {
      if (ultima <= liberada) continue;
      delete lic.liberadas[hw];
      cambio = true;
    }
    const previa = lic.estaciones[hw];
    if (!previa) {
      lic.estaciones[hw] = { nombre, primera: ahora, ultima };
      cambio = true;
    } else if (ultima > previa.ultima + DIA) {
      previa.ultima = ultima;
      previa.nombre = nombre;
      cambio = true;
    }
  }
  for (const [hw, e] of Object.entries(lic.estaciones)) {
    if (e.ultima < ahora - 90 * DIA) {
      delete lic.estaciones[hw];
      cambio = true;
    }
  }
  for (const [hw, t] of Object.entries(lic.liberadas || {})) {
    if (t < ahora - 90 * DIA) {
      delete lic.liberadas[hw];
      cambio = true;
    }
  }
  return cambio;
}

async function emitirToken(env, lic, hw) {
  const ahora = Math.floor(Date.now() / 1000);
  const ttl = (parseInt(env.TTL_DIAS, 10) || 7) * DIA;
  const expira = lic.expira ?? null;
  const payload = {
    v: 1,
    hw,
    plan: lic.plan,
    cliente: lic.cliente,
    expira,
    max_estaciones: lic.max_estaciones || 1,
    estaciones: estacionesAutorizadas(lic, ahora),
    emitido: ahora,
    valido_hasta: expira ? Math.min(expira, ahora + ttl) : ahora + ttl,
  };
  const cuerpo = b64u(enc.encode(JSON.stringify(payload)));
  // Se firma el texto base64url del payload (no el JSON), igual que verifica la app.
  const firma = await crypto.subtle.sign("Ed25519", await clavePrivada(env), enc.encode(cuerpo));
  return `${cuerpo}.${b64u(firma)}`;
}

async function leerJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

// ── Endpoints de la app ─────────────────────────────────────────────────────

async function procesarLicencia(env, request, modo) {
  const body = await leerJson(request);
  const clave = normalizar(body?.clave);
  const hw = String(body?.hw_id || "");
  if (clave.length < 16 || !/^[0-9a-f]{64}$/.test(hw)) {
    return rechazo(400, "SOLICITUD", "Solicitud invalida.");
  }

  const llave = `lic:${await sha256hex(clave)}`;
  const crudo = await env.LICENCIAS.get(llave);
  if (!crudo) return rechazo(404, "NO_ENCONTRADA", "La clave de licencia no es valida.");
  const lic = JSON.parse(crudo);
  const ahora = Math.floor(Date.now() / 1000);

  if (lic.revocada) return rechazo(403, "REVOCADA", "Esta licencia fue revocada. Contacte a su proveedor.");
  if (lic.expira && ahora > lic.expira) {
    return rechazo(403, "VENCIDA", "Esta licencia esta vencida. Contacte a su proveedor para renovarla.");
  }

  let cambio = false;
  if (!lic.hw_id) {
    if (modo !== "activar") return rechazo(409, "NO_ACTIVADA", "La licencia no esta activada en esta computadora.");
    lic.hw_id = hw;
    lic.activada_en = ahora;
    cambio = true;
  } else if (lic.hw_id !== hw) {
    return rechazo(409, "OTRA_PC", "Esta licencia ya esta activada en otra computadora.");
  }

  if (fusionarEstaciones(lic, body?.estaciones, ahora)) cambio = true;
  if (!lic.ultima_validacion || ahora - lic.ultima_validacion > DIA) {
    lic.ultima_validacion = ahora;
    cambio = true;
  }
  if (cambio) await env.LICENCIAS.put(llave, JSON.stringify(lic));

  return json({ token: await emitirToken(env, lic, hw) });
}

// ── Administracion ──────────────────────────────────────────────────────────

async function esAdmin(env, request) {
  const dado = request.headers.get("authorization") || "";
  const esperado = `Bearer ${env.ADMIN_TOKEN || ""}`;
  if (!env.ADMIN_TOKEN) return false;
  // Se comparan digests (largo fijo) en tiempo constante, no los textos.
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(dado)),
    crypto.subtle.digest("SHA-256", enc.encode(esperado)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

function maxEstaciones(valor) {
  const n = Math.floor(Number(valor));
  if (valor === undefined || valor === null || valor === "") return 1;
  if (!Number.isFinite(n) || n < 1 || n > 1000) throw new Error("'max_estaciones' debe estar entre 1 y 1000.");
  return n;
}

function calcularExpira(body) {
  if (body.perpetua) return null;
  if (body.expira) {
    const t = Date.parse(`${body.expira}T23:59:59Z`);
    if (Number.isNaN(t)) throw new Error("Fecha 'expira' invalida, use AAAA-MM-DD.");
    return Math.floor(t / 1000);
  }
  const dias = Number(body.dias);
  if (!Number.isFinite(dias) || dias <= 0) throw new Error("Indique 'dias', 'expira' o 'perpetua'.");
  return Math.floor(Date.now() / 1000) + Math.floor(dias) * DIA;
}

async function llaveDe(body) {
  if (body.hash && /^[0-9a-f]{64}$/.test(body.hash)) return `lic:${body.hash}`;
  const clave = normalizar(body.clave);
  if (clave.length < 16) throw new Error("Indique 'clave' o 'hash'.");
  return `lic:${await sha256hex(clave)}`;
}

async function modificar(env, body, cambiar) {
  const llave = await llaveDe(body);
  const crudo = await env.LICENCIAS.get(llave);
  if (!crudo) return rechazo(404, "NO_ENCONTRADA", "Licencia no encontrada.");
  const lic = cambiar(JSON.parse(crudo));
  await env.LICENCIAS.put(llave, JSON.stringify(lic));
  return json({ ok: true, hash: llave.slice(4), licencia: lic });
}

async function admin(env, request, ruta) {
  if (!(await esAdmin(env, request))) return rechazo(401, "NO_AUTORIZADO", "No autorizado.");

  if (request.method === "GET" && ruta === "/admin/listar") {
    const licencias = [];
    let cursor;
    do {
      const pagina = await env.LICENCIAS.list({ prefix: "lic:", cursor });
      for (const { name } of pagina.keys) {
        const lic = JSON.parse(await env.LICENCIAS.get(name));
        licencias.push({ hash: name.slice(4), ...lic, autorizadas: estacionesAutorizadas(lic, Math.floor(Date.now() / 1000)) });
      }
      cursor = pagina.list_complete ? undefined : pagina.cursor;
    } while (cursor);
    return json({ licencias });
  }

  if (request.method !== "POST") return rechazo(405, "METODO", "Metodo no permitido.");
  const body = (await leerJson(request)) || {};

  try {
    switch (ruta) {
      case "/admin/emitir": {
        const clave = generarClave();
        const hash = await sha256hex(normalizar(clave));
        const lic = {
          cliente: String(body.cliente || "").slice(0, 120),
          plan: String(body.plan || "estandar").slice(0, 40),
          expira: calcularExpira(body),
          hw_id: null,
          revocada: false,
          creada_en: Math.floor(Date.now() / 1000),
          sufijo: normalizar(clave).slice(-4),
          notas: String(body.notas || "").slice(0, 200),
          max_estaciones: maxEstaciones(body.max_estaciones),
          estaciones: {},
        };
        await env.LICENCIAS.put(`lic:${hash}`, JSON.stringify(lic));
        // La clave en claro solo se muestra ahora: en KV queda unicamente su hash.
        return json({ clave, hash, licencia: lic });
      }
      case "/admin/renovar":
        return await modificar(env, body, (lic) => ({ ...lic, expira: calcularExpira(body) }));
      case "/admin/revocar":
        return await modificar(env, body, (lic) => ({ ...lic, revocada: true }));
      case "/admin/restaurar":
        return await modificar(env, body, (lic) => ({ ...lic, revocada: false }));
      case "/admin/editar":
        return await modificar(env, body, (lic) => ({
          ...lic,
          ...(body.cliente !== undefined && { cliente: String(body.cliente).slice(0, 120) }),
          ...(body.plan !== undefined && { plan: String(body.plan).slice(0, 40) }),
          ...(body.notas !== undefined && { notas: String(body.notas).slice(0, 200) }),
          ...(body.max_estaciones !== undefined && { max_estaciones: maxEstaciones(body.max_estaciones) }),
        }));
      case "/admin/liberar_estacion": {
        const hw = String(body.hw || "");
        if (!/^[0-9a-f]{64}$/.test(hw)) throw new Error("Indique 'hw' (id de la estacion, 64 caracteres hex).");
        return await modificar(env, body, (lic) => {
          if (!lic.estaciones?.[hw]) throw new Error("Esa estacion no esta registrada en la licencia.");
          const estaciones = { ...lic.estaciones };
          delete estaciones[hw];
          return { ...lic, estaciones, liberadas: { ...(lic.liberadas || {}), [hw]: Math.floor(Date.now() / 1000) } };
        });
      }
      case "/admin/liberar":
        return await modificar(env, body, (lic) => ({ ...lic, hw_id: null, activada_en: null }));
      default:
        return rechazo(404, "RUTA", "Ruta no encontrada.");
    }
  } catch (error) {
    return rechazo(400, "SOLICITUD", error.message);
  }
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    try {
      if (request.method === "GET" && pathname === "/admin/panel") {
        return new Response(PANEL_HTML, {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "content-security-policy":
              "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; " +
              "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
          },
        });
      }
      if (pathname.startsWith("/admin/")) return await admin(env, request, pathname);
      if (request.method === "POST" && pathname === "/v1/activar") return await procesarLicencia(env, request, "activar");
      if (request.method === "POST" && pathname === "/v1/validar") return await procesarLicencia(env, request, "validar");
      return rechazo(404, "RUTA", "Ruta no encontrada.");
    } catch (error) {
      console.error(error);
      return rechazo(500, "INTERNO", "Error interno del servidor de licencias.");
    }
  },
};
