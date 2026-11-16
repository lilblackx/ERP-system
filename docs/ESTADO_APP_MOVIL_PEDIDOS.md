# App móvil de pedidos — estado del feature

**Rama:** `feature/app-movil-pedidos` (creada desde `main` el 2026-11-15). **No está en `main` y no debe llegar
ahí hasta que se decida.** Última actualización: 2026-11-15.

Este documento resume dónde está el feature, qué se decidió y por qué, qué falta y cómo no mezclarlo con `main`.
El detalle técnico de lo ya implementado está en `docs/ESTADO_DEL_PROYECTO.md` (sección 4, "Pedidos con reserva
de stock").

## 1. Qué se quiere

Que los vendedores tomen pedidos desde un celular Android. Caja o admin los revisan en el escritorio, los aprueban
y los convierten en factura. Un pedido **no es una factura**: no mueve inventario, no abre cuentas por cobrar ni
genera comisiones; solo aparta stock hasta que se factura, rechaza, anula o vence.

```
[App Android]  --HTTPS/JSON-->  [API FastAPI]  -->  app/services/*  -->  SQL Server
 vendedores                     PC servidor          (reglas y permisos intactos)
```

El celular nunca habla con SQL Server directo (no existe `pyodbc` en Android y se expondría la base). La API será
una capa fina sobre los servicios que ya existen.

## 2. Avance por fase

| Fase | Qué | Estado |
|---|---|---|
| 1 | Backend de pedidos: migración, servicio, reserva de stock, integración con la factura | **Hecha y commiteada** (3 commits) |
| 2 | Módulo "Pedidos" del escritorio y factura desde un pedido | **Hecha, sin commitear** |
| 3 | API HTTPS (FastAPI) sobre los servicios | Pendiente |
| 4 | App Android (Flutter) | Pendiente |
| 5 | Acceso desde la calle, instalador, firewall, distribución de la app | Pendiente (decisión abierta, ver 5) |

Verificación al cierre de la Fase 2: suite completa **2 771 tests en verde** (`pytest -n 6 --dist loadfile`, 4 min 8 s),
`ruff check` y `ruff format --check` limpios.

### Fase 1 — commits

| Commit | Contenido |
|---|---|
| `f913970` | Migración 0100, modelos, cálculo de reserva y bases de prueba propias de la rama |
| `d4b09ec` | `emitir_factura` respeta lo apartado y cierra el pedido en el mismo commit; `confirmar_transaccion` en `db_utils` |
| `a4c9cda` | Servicio de pedidos, ciclo de vencidos del servicio de Windows, tests y documentación |

### Fase 2 — pendiente de commit

Archivos nuevos: `app/ui/pedidos_panel.py`, `app/ui/pedido_detalle_dialog.py`, `tests/ui/test_pedidos_panel.py`,
`tests/ui/test_factura_desde_pedido.py`. Modificados: `app/db/models.py` (`Pedido.total`),
`app/services/pedidos.py` (`detalle_pedido`, `datos_para_facturar`, listado con líneas),
`app/services/reservas_stock.py` (`anotar_reservado`), `app/ui/factura_form_dialog.py`, `app/ui/main_window.py`,
`app/ui/sidebar.py`, `app/ui/topbar.py`, `app/ui/styles.py`, `tests/services/test_pedidos.py` y la documentación.

## 3. Cómo funciona lo ya hecho

**Estados:** `ENVIADO → APROBADO → FACTURADO`, más `RECHAZADO`, `ANULADO` y `VENCIDO`.

**Reserva de stock.** Se calcula, no se guarda: no hay columna, trigger ni vista
(`reservas_stock.reservado_por_producto`, una sola consulta para todos los productos). Aparta stock un pedido
`APROBADO`, o `ENVIADO` mientras no hayan pasado 48 h (`VIGENCIA_RESERVA_HORAS`), con la hora de SQL Server. Disponible
= `cantidad_unidad` − reservado. Crear o aprobar un pedido bloquea primero todos los productos con `UPDLOCK` (en orden
de id, como `emitir_factura`) y recién después lee la reserva; dos pedidos simultáneos no pueden apartar las mismas
unidades. Un pedido por revisar que vence suelta su stock solo; el servicio de Windows solo pasa su estado visible
a `VENCIDO` (cada 5 min, `PEDIDOS_SERVICIO_INTERVALO_SEG`).

**Facturación.**
- `emitir_factura` ya no vende lo que otro pedido tiene apartado.
- Con `id_pedido=` factura un pedido `APROBADO` del mismo cliente **y del mismo vendedor** (la comisión es del que
  tomó el pedido) y lo cierra como `FACTURADO` en la misma transacción. Si la factura falla, el pedido sigue aprobado.
- Dos cajeros que convierten el mismo pedido a la vez no pueden emitir dos facturas (`UPDLOCK` sobre el pedido).

**Alcance del vendedor** (mismo criterio que `alcance_vendedor.py`, aplicado en el servicio, no en la pantalla):
crea pedidos solo a su nombre y para sus clientes; ve y anula solo los suyos, y solo mientras están `ENVIADOS` o
`VENCIDOS`.

**Permisos (`pedidos`).** VENDEDOR: `ver` y `crear`. CAJERO: `ver` y `editar`. ADMIN entra por el bypass. `editar` significa
"revisar" (aprobar, rechazar, anular, facturar), porque `CK_permisos_accion` solo admite `ver/crear/editar/eliminar`
(mismo mapeo que las migraciones 0021, 0029 y 0048). Facturar además exige `ventas:crear`.

**Entrada no confiable.** Cantidad y precio se validan finitos y dentro de lo que cabe en la columna (`NaN`,
`Infinity` y `1e400` se rechazan con `ValueError`). Un bulto exige que el producto tenga unidades por caja
configuradas (el trigger de `factura_detalle` descontaría 0). `id_cliente_local` permite que la app reenvíe un pedido
sin duplicarlo, incluso si los dos envíos llegan a la vez.

**Escritorio (Fase 2).** Módulo "Pedidos" en el menú de Operaciones: listado paginado con filtros de estado y vendedor,
refresco cada 30 s, y acciones sobre el pedido elegido.

| Acción | Permiso | Qué hace |
|---|---|---|
| Ver detalle | `pedidos:ver` | Cliente, vendedor, reserva hasta cuándo, líneas y total |
| Aprobar / Rechazar (con motivo) | `pedidos:editar` | Aprobar revisa el stock otra vez |
| Anular (con motivo) | `editar`, o el vendedor con `crear` sobre los suyos | Libera el stock |
| Facturar | `pedidos:editar` + `ventas:crear` | Abre el formulario de factura; un pedido de contado exige caja abierta en la estación |

`FacturaFormDialog(pedido=...)` sale con cliente, vendedor, condición y líneas **bloqueados**; caja solo agrega formas
de pago, descuento, vuelto y porcentaje BCV. El selector de productos muestra el stock disponible y cuánto está
apartado (`stock: 42.00 Und | 8 apartadas`) y "Agregar" valida contra eso.

## 4. Cómo se probó

- Todo contra SQL Server real. Tests nuevos: `tests/services/test_pedidos.py`, `tests/ui/test_pedidos_panel.py`,
  `tests/ui/test_factura_desde_pedido.py`, más casos en `tests/services/test_servicio_licencia.py`.
- Incluyen concurrencia real con dos sesiones: dos pedidos compitiendo por el mismo stock, productos bloqueados en
  orden opuesto y un reenvío simultáneo.
- Se rompieron a propósito 38 condiciones clave (mutaciones). La suite detectó 35 a la primera; las 3 que sobrevivieron
  (tipo de venta inválido, facturar un pedido no aprobado y vendedor del pedido ignorado) ya tienen su test y se
  detectan. Cada archivo se restauró idéntico después de cada prueba.
- Correr la suite completa **siempre** con `pytest -n 6 --dist loadfile` (~4 min). En serie tarda ~42 min y parece colgada.

## 5. Qué falta

**Fase 3 — API HTTPS.** FastAPI en el PC servidor, solo HTTPS (sin puerto HTTP ni redirección). Login con la lógica de
`auth.py` (incluido el bloqueo escalonado), token con expiración, endpoints mínimos: `login`, `clientes` (los suyos),
`productos` con precio y stock, `pedidos` (crear, listar, anular) y `tasa`. El proceso debe instalar la compuerta de
licencia (`instalar_gate`) y auditar lo que viene del móvil. **El servidor debe fijar o acotar el precio:** hoy
`crear_pedido` confía en el precio que manda el llamador; uno menor lo rechaza `emitir_factura`, pero uno mayor no lo
detiene nadie y la comisión es venta − lista.

**Fase 4 — App Android (Flutter).** Login, mis clientes, catálogo con stock disponible, carrito, enviar pedido y mis
pedidos con su estado. Borradores guardados en el teléfono para tomar pedidos sin señal y enviarlos después.

**Fase 5 — Acceso y distribución.** HTTPS vía **Tailscale Serve** (la API escucha en 127.0.0.1 y Tailscale la publica con
certificado válido; sin CA propia ni pinning). **Decisión abierta:** cómo llegan los vendedores desde la calle: VPN
(Tailscale o WireGuard), túnel con HTTPS gestionado o dominio propio. Mi recomendación sigue siendo la VPN. Falta
también el firewall del servidor, el instalador y cómo distribuir el APK.

**Mejoras menores sin hacer:**
- El panel de Inventario y los reportes de stock muestran el stock real, no el disponible.
- Al facturar desde Pedidos no se imprime sola la factura (Facturación sí); se imprime desde el detalle.
- Los bloques de commit con manejo de errores copiados en otros servicios (`tesoreria`, `pagos`, `compras`...) no usan aún
  `confirmar_transaccion`.
- Código sin uso a propósito: `ESTADOS_ABIERTOS` en `reservas_stock.py` (decisión del usuario: se deja).

## 6. Aislamiento de `main`

El trabajo se hace sin tocar nada de `main`, migraciones incluidas.

- **Bases de pruebas propias:** `tests/conftest.py` usa por defecto `distribuidora_dj_test_pedidos` (y
  `…_pedidos_gw0…gw5` en paralelo). Las bases de `main` (`distribuidora_dj_test*`) no deben recibir la 0100: `main` no
  vacía `pedidos` y una fila suelta rompe su `DELETE FROM clientes`.
- **No correr `python -m app.db.migrar` desde esta rama contra `distribuidora_dj`** (la de desarrollo). Si hace falta
  abrir la app aquí, usar otra base, por ejemplo `distribuidora_dj_pedidos`.
- **Numeración:** la migración se llama `0100_…` y `main` puede crear otra `0100_…`. El runner identifica por nombre de
  archivo completo, así que no falla, pero es ambiguo.
- **CI:** subir la rama no lo dispara (solo corre en `push` a `main`); **abrir un Pull Request sí**, porque el workflow
  tiene `pull_request:` sin filtro. En GitHub ya existe `origin/feature/app-movil-pedidos` (con lo commiteado hasta la Fase 1).

## 7. Checklist al mergear a `main`

1. Renumerar la migración al siguiente número libre (gratis: solo las bases de la rama la aplicaron).
2. Revertir en `tests/conftest.py` el nombre por defecto de la base de pruebas a `distribuidora_dj_test`.
3. Quitar el "solo en la rama" de `docs/ESTADO_DEL_PROYECTO.md` y de este archivo.
4. Commits en partes separadas (migración, modelos y reserva / servicio / integración con la factura / pantallas).
5. Correr la suite completa en paralelo y revisar que el CI de GitHub pase.
6. Fijar el precio en el servidor **antes** de exponer cualquier API.

## 8. Mapa de archivos

| Capa | Archivos |
|---|---|
| Base de datos | `migrations/0100_pedidos_con_reserva_de_stock.sql`, `app/db/models.py` (`Pedido`, `PedidoDetalle`) |
| Servicios | `app/services/pedidos.py`, `reservas_stock.py`, `pedido_facturacion.py`, `db_utils.py` (`confirmar_transaccion`), `ventas.py` (`id_pedido`), `app/servicio_licencia.py` (`ciclo_pedidos`) |
| Escritorio | `app/ui/pedidos_panel.py`, `pedido_detalle_dialog.py`, `factura_form_dialog.py` (`pedido=`), `main_window.py`, `sidebar.py`, `topbar.py`, `styles.py` |
| Tests | `tests/services/test_pedidos.py`, `tests/ui/test_pedidos_panel.py`, `tests/ui/test_factura_desde_pedido.py`, `tests/services/test_servicio_licencia.py`, `tests/conftest.py` |
