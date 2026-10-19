# Licenciamiento

Cómo funciona, cómo se despliega el servidor y qué protege (y qué no).

## Cómo funciona: una licencia por empresa (servidor + estaciones)

```
 SERVIDOR (activa y renueva)                    Cloudflare Worker + KV
 ───────────────────────────                    ──────────────────────
 clave + hw_id + estaciones ─ POST /v1/activar ─► ata la clave a ESTE servidor
                           ◄── token firmado ───  (Ed25519, válido como máximo 7 días,
 servicio de Windows,                              con max_estaciones y los puestos)
 cada 10 min ───────────── POST /v1/validar ───► renueva, o rechaza (revocada/vencida/otra PC)
        │
        ▼ guarda el token en SQL Server (tabla licencia_sistema)
 ESTACIONES (solo leen) ◄── lo leen por su conexión normal a SQL Server
```

- **Una clave por empresa.** Se activa una sola vez, en el **servidor**, y queda atada a su
  hardware. Las estaciones **no activan nada**: leen el token de SQL Server, verifican la firma
  con la clave pública embebida y su `valido_hasta`, y trabajan.
- **Servicio de Windows en el servidor** (`app/servicio_licencia.py`): renueva el token cada
  10 minutos aunque nadie tenga la app abierta. Si se detiene, se revoca la licencia o el
  servidor pierde internet más de **7 días**, el token vence y **todas las PCs quedan en solo
  lectura**. Una revocación llega a las estaciones en ≤ 10 min.
- **Límite de estaciones.** Cada licencia trae `max_estaciones`. Cada PC que abre la app se
  registra en `licencia_estaciones`; el servicio manda la lista a Cloudflare, que concede los
  puestos a las **más antiguas primero** (el orden lo fija el servidor, no el cliente) entre las
  vistas en los últimos 30 días. Una estación sin puesto queda en solo lectura. Cuenta **toda PC
  que abre la app, incluido el servidor** si alguien la usa ahí: para "1 servidor + 3 estaciones"
  emite la licencia con 4 estaciones. Un puesto libre se concede de inmediato, sin esperar a la
  siguiente renovación.
- Si alguien copia la base de datos a otro servidor: su token no se puede renovar (Cloudflare solo
  renueva al servidor activado) y vence en ≤ 7 días.
- El token y la clave viven en `licencia_sistema`; el anti-retroceso de reloj en
  `%PROGRAMDATA%\DistribuidoraDJ\reloj.dat`, cifrado con DPAPI de máquina.
- Si la licencia vence, se revoca o no se puede validar, la app queda en **solo lectura**:
  consulta todo, pero no registra ventas/compras/pagos. Login y recuperación de clave siguen
  funcionando (ver `TABLAS_EXENTAS` en `app/services/licencia.py`).
- Retroceder el reloj de Windows invalida la licencia hasta validar en línea.

### Protección contra la manipulación de fecha y hora

- **Estaciones:** calculan "ahora" con la hora del **SQL Server** (`SYSUTCDATETIME()`) avanzada con un
  reloj monotónico, no con el reloj de su PC. Cambiar la fecha de Windows en una estación no tiene efecto.
- **Servidor:** guarda tres marcas de tiempo en **tres sitios** (`reloj.dat` cifrado con DPAPI, el registro
  `HKLM\SOFTWARE\DistribuidoraDJ` y la fila de `licencia_sistema`); manda siempre la más reciente, así que
  borrar una sola no reinicia nada:
  - `ultimo_visto`: la hora más alta vista. Un reloj por debajo (más de 15 min) invalida la licencia.
  - `ancla_servidor` + `ancla_tick`: la hora del servidor de licencias en la última validación y el
    contador de arranque de Windows (`GetTickCount64`, independiente de la fecha del sistema). Con eso se
    calcula una **cota inferior de la hora real**: `ancla + tiempo de arranque transcurrido`. Un reloj por
    debajo de ella se considera manipulado y, dentro de la tolerancia, el vencimiento se evalúa con la cota.
    Tras un reinicio la cota solo baja (nunca sube), así que no genera falsos positivos.
- Una **validación en línea** exitosa reemplaza las marcas con la hora del servidor de licencias: un reloj
  adelantado por error se corrige solo al volver a validar.
- Con internet en el servidor, el vencimiento lo decide Cloudflare con su propia hora cada 10 minutos.
- **Límite que queda:** alguien con permisos de administrador que a la vez bloquee el acceso a internet del
  servidor, atrase el reloj y borre las tres marcas (archivo, registro y fila de la base) sigue pudiendo
  extender la licencia. Eso exige conocer y coordinar todo lo anterior.

### Rol de cada instalación

Se define con `MODO_INSTALACION` (`SERVIDOR` o `ESTACION`; el instalador lo escribe). Un valor
desconocido cae a `ESTACION`. Las estaciones apuntan al SQL Server del servidor con
`DB_SERVER` y no necesitan `LICENCIA_URL` para nada más que saber que el control está activo.

### Servicio de Windows (solo en el servidor)

En una consola de PowerShell **como Administrador**, desde la carpeta del proyecto:

```
python -m pywin32_postinstall -install      # una vez por entorno virtual
python -m app.servicio_licencia instalar    # inicio automático + reinicio si se cae; lo arranca
python -m app.servicio_licencia estado
python -m app.servicio_licencia ciclo       # una pasada en consola, para diagnosticar
python -m app.servicio_licencia detener | iniciar | desinstalar
```

Registra su actividad en `logs/app.log`. Intervalo: `LICENCIA_SERVICIO_INTERVALO_SEG` (600 por defecto,
mínimo 60).

## Puesta en marcha (una sola vez)

Requiere cuenta gratuita de Cloudflare y Node.js (para `wrangler`). No pide tarjeta.

1. `npm install -g wrangler` y `wrangler login`.
2. Generar el par de claves (la privada se imprime una vez, guárdala en un gestor de
   contraseñas; **no la pongas en el repo**):
   ```
   python scripts/licencias_admin.py generar-claves
   ```
3. Desde `licencias/worker/`:
   ```
   wrangler kv namespace create LICENCIAS      # pega el id en wrangler.toml
   wrangler secret put PRIVATE_KEY_B64          # la clave privada del paso 2
   wrangler secret put ADMIN_TOKEN              # una contraseña larga inventada por ti
   wrangler deploy                              # imprime la URL del Worker
   ```
4. En el `.env` del equipo desde el que administras:
   ```
   LICENCIAS_URL=https://distribuidora-licencias.<tu-subdominio>.workers.dev
   LICENCIAS_ADMIN_TOKEN=<el ADMIN_TOKEN del paso 3>
   ```
5. En el `.env` de desarrollo de la app (para probar el flujo completo):
   ```
   LICENCIA_URL=<la misma URL>
   LICENCIA_PUBLIC_KEY=<la clave pública del paso 2>
   ```

## Panel web de administración

Después de `wrangler deploy`, abre `https://<tu-worker>.workers.dev/admin/panel` e
ingresa el `ADMIN_TOKEN`. En cada licencia, **Detalle** muestra las estaciones (equipo, primera vez, último uso, si tiene puesto y cuál es el servidor); **Liberar puesto** saca una estación de la cuenta hasta que vuelva a usarse, y **Límite** cambia cuántas PCs permite. Desde ahí se emiten licencias (con notas), se buscan, y se
renuevan, revocan, restauran o liberan con un clic. El token queda solo en la pestaña del
navegador (`sessionStorage`) y se borra al cerrarla. La clave nueva se muestra una sola vez.

## Operación diaria (por línea de comandos)

Hace lo mismo que el panel; útil para automatizar.

```
python scripts/licencias_admin.py emitir --cliente "Distribuidora X" --plan pro --dias 365 --estaciones 4
python scripts/licencias_admin.py listar
python scripts/licencias_admin.py renovar --clave XXXXX-XXXXX-XXXXX-XXXXX --dias 365
python scripts/licencias_admin.py revocar --clave XXXXX-XXXXX-XXXXX-XXXXX
python scripts/licencias_admin.py liberar --clave XXXXX-XXXXX-XXXXX-XXXXX   # cliente cambia de PC
```

La clave en claro solo se muestra al emitirla; el servidor guarda únicamente su hash. Si el
cliente la pierde, emite otra. Para los demás comandos sin la clave usa `--hash` (lo da
`listar`).

## Límites del plan gratuito de Cloudflare

KV gratis permite 1000 escrituras/día y 100 000 lecturas/día. `/validar` solo escribe como
máximo una vez al día por licencia, así que alcanza para cientos de clientes. Si algún día
se supera, el plan de pago de Workers cuesta unos USD 5/mes.

## Qué protege y qué no

Protege contra: copiar la carpeta de la app a otra PC, compartir una clave entre clientes,
seguir usando la app después de vencida o revocada, atrasar el reloj para alargar el plazo.

**No** protege contra alguien con conocimientos que modifique el código de la app. Por
eso el siguiente paso es distribuir un ejecutable compilado (Nuitka) en vez de los `.py`
y hornear `LICENCIA_URL`/`LICENCIA_PUBLIC_KEY` en él (`app/licencia_embebida.py`; en un
ejecutable empaquetado el `.env` se ignora, ver `app/config.py`). La base de datos corre en
la PC del cliente con su propia contraseña: sus datos son suyos, y eso no se puede
esconder. La protección de fondo es contractual y comercial (contrato de licencia,
actualizaciones solo para clientes al día).
