# Distribuidora DJ — Estado del Proyecto

Este documento resume el estado actual del backend del sistema de gestión: qué capas
están implementadas, qué decisiones de diseño se tomaron y qué queda pendiente.

## 1. Arquitectura general

- **Base de datos**: SQL Server (`schema_sqlserver.sql`), migrado desde un esquema MySQL
  original. Usa `IDENTITY` para autoincrementales, `CHECK` constraints en lugar de `ENUM`,
  y un conjunto de triggers que resuelven en la base de datos parte de la lógica de
  negocio (ver sección 3).
- **ORM**: SQLAlchemy 2.0 (estilo `Mapped` / `mapped_column`) en `app/db/models.py`.
- **Capa de servicios**: `app/services/`, un módulo por dominio de negocio. Cada
  servicio expone funciones o clases con métodos estáticos que reciben una `Session` de
  SQLAlchemy como primer parámetro y hacen su propio `commit()`.
- **UI**: PySide6, arranque en `app/main.py`. Pantalla de login (`login_window.py`),
  ventana principal con sidebar/topbar (`main_window.py`, `sidebar.py`, `topbar.py`) y
  paneles por módulo (`clientes_panel.py` + `cliente_form_dialog.py` como referencia de
  patrón de UI; el resto vía `placeholder_view.py` hasta que se implementen).
- **Configuración**: `app/config.py` arma la cadena de conexión ODBC desde variables de
  entorno (`.env`, ver `.env.example`). Nunca se versiona `.env` real.

## 2. Módulos de servicio implementados

| Servicio | Archivo | Responsabilidad |
|---|---|---|
| Autenticación | `auth.py` | Hash/verify de contraseñas (bcrypt), `authenticate()` |
| Clientes | `clientes.py` | CRUD, unicidad de código/identificación |
| Proveedores | `proveedores.py` | CRUD, unicidad de código/RIF, límite y días de crédito |
| Vendedores | `vendedores.py` | CRUD, desempeño mensual (ventas, facturas, clientes asignados). `id_ruta` obligatorio al crear (2026-09-01, mismo criterio que código/identificación — ver sección 8) |
| Rutas | `rutas.py` | CRUD de rutas de reparto/cobranza (1 ruta : N vendedores), punto de referencia opcional (`latitud`/`longitud`) para el mapa |
| Categorías | `categorias.py` | CRUD, conteo de productos asociados |
| Inventario y precios | `inventario.py` | CRUD de productos, alertas de stock/vencimiento, un precio de lista por producto (`obtener_precio`/`establecer_precio`, C14 2026-08-23 — antes hasta 3 tipos DETAL/MAYOR/ESPECIAL) con cálculo de margen |
| Ventas | `ventas.py` | Emisión de factura (con validación de stock y de crédito), anulación de factura, listado con filtros |
| Compras | `compras.py` | Registro de compra (con validación de crédito del proveedor), anulación de compra, listado con filtros |
| Tesorería | `tesoreria.py` | Bancos y cuentas bancarias (CRUD, resumen con número enmascarado), apertura/cierre de caja, movimientos manuales de caja |
| Pagos | `pagos.py` | Aplica pagos de clientes/proveedores contra `cuentas_por_cobrar`/`cuentas_por_pagar` (ver nota técnica de la sección 3) |
| Tasas de cambio | `tasas.py` | Registro de tasa, tasa actual con % vs. día anterior, histórico con brecha cambiaria |
| Usuarios | `usuarios.py` | CRUD de usuarios (hash de clave, vínculo opcional con vendedor), verificación de permisos vía matriz `rol_permisos` |
| Roles y permisos | `permisos.py` | CRUD de roles, y escritura de la matriz `rol_permisos` (asignar/revocar/reemplazar conjunto completo). El catálogo de permisos (`recurso`+`accion`) se mantiene fijo vía schema/seed, no se crea desde aquí. También expone `require_permiso()`, el punto de entrada de autorización que usan los otros 17 servicios (ver sección 7) |
| Cuentas por cobrar/pagar "otros" | `otros_movimientos.py` | Préstamos/anticipos a cobrar, y conciliación de transferencias bancarias sin identificar (ver sección 4) |
| Notas de crédito | `notas_credito.py` | Saldo a favor de cliente/proveedor generado automáticamente al anular una factura/compra con pagos ya aplicados (ver sección 3, "Notas de credito automaticas") |
| Comisiones de vendedor | `comisiones.py` | Cálculo automático al emitir factura (diferencia entre precio de venta y precio de lista) y pago real por caja/banco (C14 2026-08-23, ver sección 3, "Comisiones de vendedor") |
| Configuración de empresa | `empresa.py` | Datos fiscales y logotipo (registro singleton) |
| Auditoría | `auditoria.py` | Bitácora transversal de eventos críticos (ver sección 5) |
| Panel general | `dashboard.py` | KPIs consolidados para el panel principal (ver sección 6) |

## 3. Lógica resuelta por triggers en la base de datos

El schema delega en triggers varias operaciones que en otros sistemas viven en el
backend:

- **Stock**: `trg_factura_detalle_stock_*` y `trg_compra_detalle_stock_*` descuentan o
  reponen `inventario.cantidad_unidad` al insertar/actualizar/eliminar líneas de factura
  o compra.
- **Totales**: `trg_factura_total_*` y `trg_compra_total_*` recalculan
  `total_venta`/`total_compra` a partir de la suma de las líneas.
- **Apertura de cuentas por cobrar/pagar**: `trg_factura_venta_cxc` y `trg_compras_cxp`
  son triggers `AFTER UPDATE` sobre la cabecera: abren la cuenta por cobrar/pagar cuando
  el total cambia. Esto tiene una implicación importante para el código de aplicación:
  **la cabecera debe insertarse con el total en 0 (o el valor por defecto) y dejar que el
  trigger de recálculo, disparado al insertar las líneas, sea el que efectivamente cambie
  el valor** — si se inserta ya con el total correcto, el trigger no detecta cambio y la
  cuenta por cobrar/pagar nunca se abre. Los servicios de `ventas.py` y `compras.py` ya
  están escritos respetando esto. Del lado de compras, `trg_compras_cxp` sigue
  restringido a `condicion_pago = 'credito'`. Del lado de ventas, desde
  `migrations/0024_pagos_contado_multimetodo.sql` (2026-08-25) `trg_factura_venta_cxc`
  **ya no** restringe la apertura a `credito` -- ver "Pago de contado al emitir" mas abajo
  para el porque.
- **Pagos**: `trg_pagos_cobros_io` y `trg_pagos_proveedores_io` son `INSTEAD OF INSERT`:
  validan el origen del pago (exactamente uno entre caja o cuenta bancaria), validan que
  el monto no exceda el saldo, y generan el movimiento de caja/banco correspondiente.
  `pagos_cobros` (no `pagos_proveedores`) tiene ademas `moneda` (`USD`/`VES`/`COP`/`USDT`,
  default `USD`) y `monto_moneda_origen` (el monto tal como se recibio, solo para
  auditoria) desde la misma migracion -- `monto` sigue siendo siempre el equivalente en
  USD que se aplica contra `saldo_pendiente`. `PagoService.registrar_pago_cobro()`
  (Python, no el trigger) exige ademas que, si el origen es una caja, tenga un turno
  abierto (`fecha_apertura` no nula, `fecha_cierre` nula) -- antes no se validaba.

### Pago de contado al emitir (migrations/0024, 2026-08-25)

Antes, una factura `condicion_pago='contado'` no dejaba ningun rastro de cobro: sin
`CuentaPorCobrar`, sin `PagoCobro`, sin movimiento de caja/banco. Ahora
`VentaService.emitir_factura()` acepta un parametro `pagos: list[dict]` -- **obligatorio
y no vacio si `condicion_pago='contado'`, prohibido si es `'credito'`**. Cada dict trae
`metodo_pago`, `moneda`, `monto_moneda_origen` y exactamente uno de `id_caja`/
`id_cuenta_bancaria` (mismo contrato que `PagoService.registrar_pago_cobro`), mas
`referencia` opcional. Se puede repartir el total entre varias formas de pago y monedas
distintas en la misma factura (ej. parte en efectivo VES, parte por Zelle en USD).

Flujo dentro de la transaccion (todo o nada, un solo `commit()` al final, igual que
comisiones ya hacia): se calcula `total_a_cobrar` (subtotal - descuento + IVA) y se
convierte cada pago a USD con la tasa vigente snapshoteada (`VES`/`COP` dividen por
`tasa_dolar_bcv`/`tasa_cop`; `USD`/`USDT` son 1:1) **antes** de tocar la sesion -- si la
suma no cubre el total, se aborta con `ValueError` sin insertar nada. Si pasa la
validacion, se inserta la factura+lineas (igual que siempre), lo que dispara
`trg_factura_venta_cxc` (ahora tambien para contado) abriendo una `CuentaPorCobrar`; acto
seguido se aplica cada pago con `PagoService._aplicar_pago_cobro()` (variante interna sin
commit propio, para mantener la atomicidad) hasta dejar `saldo_pendiente=0` /
`estado='pagada'`. Si la suma tendida excede el total, cada pago se recorta al saldo
restante (`min(monto_usd, cxc.saldo_pendiente)`) y una linea que quede en 0 se omite --
pero a diferencia de antes, el excedente ya no se pierde: es el "vuelto" (ver mas abajo).

**Vuelto** (`migrations/0027_vuelto_factura.sql`, agregado 2026-08-26): `monto_vuelto =
total_pagado - total_a_cobrar`, calculado y validado en la MISMA transaccion, antes de
insertar nada. Reglas condicionales por `metodo_vuelto`:
- `'efectivo'`: libre (sin autorizacion), pero exige `id_caja_vuelto` y valida saldo
  suficiente contra `CajaService.calcular_saldo_actual()` (equivalente Python de
  `trg_cajas_cierre`, calculable con la caja todavia abierta) usando el mismo lock `WITH
  (UPDLOCK, ROWLOCK)` sobre `Caja` que ya usan `abrir_caja`/`cerrar_caja`. La comparacion
  de saldo se hace DESPUES de aplicar los pagos de contado (no antes): el caso comun es
  que el propio efectivo tendido en esa misma factura financie su propio vuelto.
- `'pago_movil'`/`'transferencia'`: exige `referencia_vuelto` (4-50 caracteres) e
  `id_autorizador_vuelto` con el permiso `'vueltos_bancarios'/'crear'` (mismo mecanismo de
  permiso dedicado que `'descuentos'/'crear'` y `'creditos'/'crear'` -- sin rol SUPERVISOR
  nuevo, ADMIN bypassa siempre, cualquier otro rol necesita que un ADMIN se lo otorgue).
  La UI (`app/ui/factura_form_dialog.py`) reusa `AutorizacionDialog` tal cual (el campo
  generico "motivo" se reetiqueta como "Numero de referencia bancaria" via
  `motivo_label`), sin crear un dialogo nuevo.
- No existe "saldo a favor" como metodo de vuelto (decision de alcance): el excedente
  siempre se entrega al cliente.

El vuelto se persiste en `FacturaVenta` (`monto_vuelto`/`metodo_vuelto`/
`referencia_vuelto`/`autorizado_por_vuelto`/`fecha_autorizacion_vuelto`, estos dos ultimos
`NULL` si es efectivo) y se registra como egreso real: `CajaMovimiento` tipo `'salida'`
(efectivo) o `BancoMovimiento` tipo `'cargo'` (bancario, mismo valor que ya usa
`trg_pagos_proveedores_io`) -- ambas insertadas directamente (sin trigger de por medio,
`CajaService`/`BancoService._registrar_egreso_vuelto()`, sin commit propio).

Detalle no obvio: `_aplicar_pago_cobro()` capa el `monto` aplicado al `saldo_pendiente` de
la CxC (constraint `CHECK` de no-negativo, migrations/0010), asi que la `entrada` que crea
`trg_pagos_cobros_io` para una linea de pago que exceda el total queda corta respecto al
efectivo/banco realmente recibido -- sin corregir esto, el egreso del vuelto restaria ese
mismo excedente una segunda vez (detectado escribiendo los tests de este flujo). Se
corrige registrando el excedente no aplicado como un ingreso adicional en el ORIGEN de esa
misma linea de pago (`CajaService`/`BancoService._registrar_ingreso_excedente()`, tipo
`'entrada'`/`'abono'`) antes del egreso del vuelto, para que el neto por cuenta cuadre con
lo fisicamente recibido y entregado.

Si el caller no indica `metodo_vuelto` explicito pero las formas de pago usaron una unica
caja (efectivo), `VentaService.emitir_factura()` infiere `metodo_vuelto='efectivo'` contra
esa misma caja (nunca se infiere un metodo bancario) -- mismo criterio que un cajero real
("el cambio sale del mismo cajon de donde entro el efectivo"). Esto es tambien lo que
mantiene funcionando `tests/factories.py::pago_contado()` (usado por comisiones/notas de
credito/vendedores para pagar de mas sin calcular el total exacto) sin que esos tests
tengan que declarar nada de vuelto.

Reusar el mecanismo de CxC para contado significa que `VentaService.anular_factura()` ya
maneja el caso genericamente: anular una factura de contado ya pagada genera una
`NotaCreditoCliente` igual que una de credito (ver "Notas de credito automaticas" arriba)
-- comportamiento nuevo, y deseado.

`app/ui/factura_form_dialog.py` (Nueva Factura) muestra una seccion "Formas de Pago"
cuando la condicion es contado, con un dialogo por linea (`app/ui/pago_linea_dialog.py`)
que resuelve el origen (caja abierta o cuenta bancaria activa) segun el metodo elegido; si
no hay ninguna caja abierta, ofrece un dialogo minimo de apertura de turno
(`app/ui/caja_apertura_dialog.py`) -- no es una pantalla de Tesoreria completa, solo lo
necesario para no dejar el flujo de contado en efectivo sin salida.
- **Saldo bancario**: `trg_banco_movimientos_saldo` actualiza
  `cuentas_bancarias.saldo_total_banco` en cada movimiento.
- **Cierre de caja**: `trg_cajas_cierre` calcula `saldo_cierre` a partir de
  `saldo_apertura` y los movimientos del turno cuando se registra `fecha_cierre`.
- **Reversion automatica de un pago borrado directamente**
  (`migrations/0001_reversion_automatica_pagos.sql`, 2026-08-22): borrar una fila de
  `pagos_cobros`/`pagos_proveedores` deshace en cascada todo lo que el
  `INSTEAD OF INSERT` genero:
  - Las FK de `banco_movimientos`/`caja_movimientos` hacia `pagos_cobros`/
    `pagos_proveedores` son `ON DELETE CASCADE` (antes `NO ACTION`): borrar el pago borra
    su movimiento de banco/caja.
  - `trg_banco_movimientos_saldo_del` revierte `saldo_total_banco` (espejo de
    `trg_banco_movimientos_saldo`, AFTER INSERT).
  - `trg_caja_movimientos_cierre_recalc_del` recalcula `cajas.saldo_cierre` si el turno
    ya estaba cerrado cuando se revierte el pago -- sin esto quedaria desactualizado,
    porque `saldo_cierre` solo se calcula una vez, al cerrar.
  - `trg_pagos_cobros_del`/`trg_pagos_proveedores_del` revierten `saldo_pendiente`/
    `estado` de `cuentas_por_cobrar`/`cuentas_por_pagar`, comparando contra
    `factura_venta.total_venta`/`compras.total_compra` para decidir entre `'pendiente'`
    y `'parcial'` (espejo de `trg_pagos_cobros_io`/`trg_pagos_proveedores_io`).

  **Importante**: `VentaService.anular_factura()`/`CompraService.anular_compra()` **ya no
  usan este mecanismo** (ver "Notas de credito automaticas" mas abajo, 2026-08-22) --
  estos triggers quedaron para el caso de borrar directamente un pago mal registrado
  (fuera del flujo de anulacion), donde SI tiene sentido revertirlo por completo porque
  nunca debio existir. Se evaluo usarlos tambien para anular facturas/compras con pagos
  aplicados, pero se descarto: mutan retroactivamente un turno de caja ya cerrado o un
  movimiento bancario ya conciliado (no hay columna `conciliado` que lo impida a nivel de
  schema), y no dejan rastro de que un pago real se revirtio.

- **Notas de credito automaticas al anular** (`migrations/0002_notas_credito_anulacion.sql`,
  2026-08-22, `app/services/notas_credito.py`): cuando `anular_factura()`/
  `anular_compra()` encuentran pagos ya aplicados, en vez de revertirlos (ver punto
  anterior) generan una `NotaCreditoCliente`/`NotaCreditoProveedor` por el monto ya
  cobrado/pagado:
  - `pagos_cobros`/`pagos_proveedores` y sus `banco_movimientos`/`caja_movimientos`
    **no se tocan** -- quedan con su fecha e historial reales para siempre.
  - `cuentas_por_cobrar`/`cuentas_por_pagar` agregaron el estado `'anulada'` al `CHECK`
    de `estado` (antes no existia forma de marcarlas asi, por eso se borraban). Con pagos
    aplicados, la cuenta pasa a `estado='anulada'`, `saldo_pendiente=0` -- no se borra,
    para conservar el vinculo con los pagos que ya se le aplicaron. Sin pagos aplicados,
    se sigue borrando igual que siempre (nada que preservar).
  - `notas_credito_clientes`/`notas_credito_proveedores` (tablas nuevas): registran el
    saldo a favor, vinculado a la factura/compra de origen. Aplicarlo a una operacion
    futura o devolverlo es un desarrollo aparte -- todavia no hay un flujo que consuma
    estas notas, `NotaCreditoService` solo las crea y lista.

  ~~Sigue bloqueada la anulacion si hay `comisiones_factura` calculadas~~ -- resuelto
  (2026-08-23, C14): ver "Comisiones de vendedor" mas abajo. Comisiones `'pendiente'` se
  borran antes de anular; `'pagada'` sigue bloqueando (no se puede revertir un pago ya
  hecho).

- **Comisiones de vendedor** (C14, `migrations/0011_consolidar_producto_precios.sql`,
  `migrations/0012_comisiones_pagos.sql`, `migrations/0013_catalogo_permisos_comisiones.sql`,
  2026-08-23, `app/services/comisiones.py`): regla de negocio -- un vendedor puede vender
  un producto mas caro que su precio de lista (ej. producto de lista $1, lo vende a $2); la
  diferencia ($1) es su comision, nunca negativa si vende igual o mas barato. El monto de
  la venta (`factura_detalle.precio_unitario`/`total_venta`/`cuentas_por_cobrar`) nunca se
  toca -- la comision es un pasivo derivado, calculado aparte, nunca neteado contra la
  venta.
  - **Precios**: se simplificaron a un solo precio de lista por producto (antes hasta 3
    tipos, DETAL/MAYOR/ESPECIAL). `producto_precios` se mantiene (no se borro la tabla)
    pero `CK_producto_precios_tipo` ahora exige `tipo_precio = 'UNICO'` -- la migracion
    consolido los datos existentes con prioridad DETAL>MAYOR>ESPECIAL, respaldando en
    `dbo.auditoria` (accion `MIGRACION_CONSOLIDAR_PRECIOS`) lo que se descarto. Esa
    migracion (0011) restringio el *valor* de `tipo_precio`, pero no agrego ninguna
    `UNIQUE` sobre `id_producto` -- la invariante "un solo precio por producto" vivia solo
    en `PrecioService.establecer_precio()` (check-then-insert-or-update sin lock), sin
    respaldo real en la base. Auditoria de Productos (2026-08-28) lo detecto y
    `migrations/0036_producto_precios_unico_por_producto.sql` lo cerro: agrega
    `UQ_producto_precios_id_producto` (con el mismo patron de deduplicacion+respaldo en
    auditoria que 0011, accion `MIGRACION_DEDUPLICAR_PRECIOS`) y `establecer_precio()` gano
    `WITH (UPDLOCK, ROWLOCK)` sobre la fila existente para que dos ediciones de precio
    concurrentes al mismo producto se serialicen en vez de competir.
  - **Calculo**: `ComisionService.calcular_comisiones_factura()` se llama desde
    `VentaService.emitir_factura()`, en la MISMA transaccion atomica que la venta (despues
    del `flush()` de `factura_detalle`, sin `commit()` propio). Sin vendedor en la factura,
    o sin precio de lista configurado para el producto: no genera comision para esa linea,
    no bloquea la venta.
  - **Pago**: `PagoComisionService.pagar_comisiones_vendedor()` paga en un solo batch TODAS
    las comisiones `'pendiente'` de un vendedor (no hay pago parcial de una linea
    individual), crea `PagoComision` (tabla nueva, **sin** trigger `INSTEAD OF INSERT` a
    proposito -- a diferencia de `pagos_cobros`/`pagos_proveedores`, no hay
    `saldo_pendiente` parcial que proteger; se verifico que `trg_banco_movimientos_saldo`/
    `trg_cajas_cierre` procesan igual un `BancoMovimiento`/`CajaMovimiento` insertado
    directo desde Python que uno insertado por un trigger de otra tabla) +
    `CajaMovimiento`/`BancoMovimiento` con `id_pago_comision`. Lock `WITH (UPDLOCK,
    ROWLOCK)` sobre las `ComisionFactura` pendientes (mismo patron que el resto de la
    sesion, ver seccion de indices/locking) para que dos pagos concurrentes al mismo
    vendedor no paguen dos veces.
  - Catalogo de permisos nuevo modulo `comisiones` (ver/crear/editar/eliminar), distinto
    del `reportes_comisiones` preexistente (solo lectura, ya asignado a VENDEDOR en el seed
    original).
  - **UI completa** (2026-08-28, `app/ui/comisiones_panel.py`): dos modos en el mismo
    panel. Modo gestion (`comisiones:ver`/`crear`, para ADMIN/CAJERO): selector de vendedor,
    tabla de comisiones, filtro por estado, boton "Pagar" → abre dialogo de pago sin monto
    editable (paga el total pendiente en batch), seleccion de metodo/origen caja/banco/referencia.
    Modo "Mis Comisiones" (`reportes_comisiones:ver`, para VENDEDOR): igual pero sin selector
    de vendedor ni boton pagar, titulo "Mis Comisiones" -- ve solo las suyas. Tambien resolvio
    un permiso huerfano: `reportes_comisiones:ver` existia en el catalogo desde el inicio
    (schema_sqlserver.sql linea 877) asignado a VENDEDOR (linea 883) con la intencion de
    "ver propias comisiones", pero `ComisionService.listar_comisiones_vendedor()` exigia
    `comisiones:ver` en su lugar -- VENDEDOR nunca tuvo ese permiso. Nuevo metodo
    `ComisionService.listar_mis_comisiones()` usa el permiso correcto, sidebar respeta el OR
    (`comisiones:ver` O `reportes_comisiones:ver`) para mostrar la entrada a VENDEDOR.

  **Correlativo fiscal** (`migrations/0003_correlativo_notas_credito_clientes.sql`,
  2026-08-22): `NotaCreditoCliente` es un documento que la empresa emite (reduce lo que
  el cliente le debe) y por lo tanto reportable al SENIAT cuando se solicite -- tiene
  `numero_nota_credito` correlativo y unico (`NC-000001`, `MAX(id)+1`, mismo esquema
  simple que `factura_venta.numero_factura`/`_generar_numero_factura()`), generado por
  `_generar_numero_nota_credito_cliente()` en `notas_credito.py`. `listar_notas_credito_clientes()`
  (con filtros de fecha/cliente/estado y paginacion, igual que `listar_facturas()`) esta
  pensado para armar ese reporte cuando lo pidan.

  `NotaCreditoProveedor` **no** tiene correlativo: si se anula una compra ya pagada, el
  documento fiscal (si aplica) lo emite el proveedor hacia la empresa, no al revés -- esa
  tabla sigue siendo solo un registro interno de que se nos debe. Decision confirmada con
  el usuario 2026-08-22.

  Nota: igual que `_generar_numero_factura()`/`_generar_numero_compra()`, el esquema
  `MAX(id)+1` asume que las filas nunca se borran (cierto en producción: una factura
  anulada conserva su fila, y una nota de crédito tampoco se borra nunca). En el entorno
  de test, donde `tests/conftest.py` sí borra filas entre tests pero el `IDENTITY` de SQL
  Server no se resetea, el número generado puede no coincidir con lo que uno esperaría a
  simple vista (no es un bug nuevo, ya lo tenía `numero_factura`; ver
  `tests/services/test_notas_credito.py::test_crear_nota_credito_cliente_correlativo_es_unico_y_valido`).

### Nota técnica sobre SQLAlchemy y triggers

SQL Server no permite el `OUTPUT inserted.*` (que SQLAlchemy usa por defecto para leer el
`IDENTITY` generado) en tablas con triggers habilitados. Por eso, en `models.py`, las
tablas con triggers (`factura_venta`, `factura_detalle`, `compras`, `compra_detalle`,
`cajas`, `pagos_cobros`, `pagos_proveedores`, `banco_movimientos`) tienen
`__table_args__ = {"implicit_returning": False}`. Si se agrega un trigger nuevo a una
tabla existente, hay que recordar este ajuste o los `INSERT`/`UPDATE` fallarán con el
error 8180.

Con `implicit_returning=False`, SQLAlchemy recupera el `IDENTITY` generado ejecutando
`SELECT SCOPE_IDENTITY()` justo después del `INSERT`. Esto funciona para triggers
`AFTER` (el `INSERT` real lo ejecuta el caller; el trigger corre después, en el mismo
scope) pero **no funcionaba** para `pagos_cobros`/`pagos_proveedores`, que usan
`INSTEAD OF INSERT`: ahí el `INSERT` real lo hace el trigger, en un scope distinto al
del caller, así que `SCOPE_IDENTITY()` devolvía `NULL` y SQLAlchemy fallaba con
`TypeError: int() argument ... not 'NoneType'` al primer intento de insertar un pago vía
ORM. (`@@IDENTITY` sí atraviesa el scope del trigger, pero como el trigger inserta
después en `banco_movimientos`/`caja_movimientos` —ambas con su propio `IDENTITY`—
devuelve el id equivocado, no el del pago.) Esto explica por qué nunca existió un
servicio de pagos: no era que faltara construirlo, es que con el trigger original
crasheaba en el primer insert.

**Fix aplicado** (2026-08-21): se agregó `SELECT [id_pago_cobro] FROM @nuevos;` (e
idéntico para `id_pago_proveedor`) al final de cada trigger `INSTEAD OF INSERT`. Ese
`SELECT` llega al cliente como el primer resultset no vacío, antes del
`SELECT SCOPE_IDENTITY()` que agrega SQLAlchemy — y como SQLAlchemy toma la primera fila
no vacía que encuentra, termina leyendo el id correcto sin ningún cambio en el código
Python. Verificado con el ORM real (`session.add(PagoCobro(...)); session.commit()`).
El fix ya está aplicado tanto en `schema_sqlserver.sql` como en la base de datos de
desarrollo (`distribuidora_dj`) vía `ALTER TRIGGER`; cualquier otro entorno que ya tenga
el schema instalado necesita el mismo `ALTER TRIGGER` manual, porque el script no es
idempotente para triggers (solo las `CREATE TABLE` están guardadas con
`IF OBJECT_ID ... IS NULL`).

### Migraciones de schema (2026-08-22)

`schema_sqlserver.sql` sigue siendo el script que arma el schema completo para un
entorno nuevo, pero ya no es el lugar donde se editan cambios de schema en un entorno
que ya tiene datos (como el fix de arriba, que tuvo que aplicarse a mano con
`ALTER TRIGGER` en cada entorno). Ahora existe `dbo.schema_migrations` (tabla que
registra qué cambios ya se aplicaron en esa base) y una carpeta `migrations/` con
archivos `.sql` numerados — ver `migrations/README.md` para la convención completa.
`schema_sqlserver.sql` se auto-registra como la migración `0000_baseline` al final del
propio script.

`python -m app.db.migrar` (`app/db/migrar.py`) aplica los archivos pendientes de
`migrations/` en orden y los registra uno por uno. Si apunta a una base que ya existía
antes de este mecanismo (sin `dbo.schema_migrations`), la crea y marca `0000_baseline`
como aplicada automáticamente antes de seguir — así no hace falta re-ejecutar
`schema_sqlserver.sql` completo (que de todos modos fallaría sobre una base ya poblada,
ver más arriba). Ya se corrió una vez contra `distribuidora_dj` (dev) para bootstrapear
la tabla; `distribuidora_dj_test` la recibe automáticamente porque `tests/conftest.py`
corre el script completo (ya actualizado) la primera vez que crea esa base.

No hay `down`/rollback: revertir un cambio ya aplicado es una migración nueva que
deshace el anterior, igual que se viene manejando con los `ALTER TRIGGER` manuales hasta
ahora.

**Código de cliente autoincremental (`0093`/`0094`, 2026-11-05).** `clientes.codigo_cliente`
lo asigna SQL Server (secuencia `dbo.seq_codigo_cliente` como `DEFAULT`) con formato
`CLI-000123`; el calculado en Python (`SELECT MAX + 1`) tenía una carrera entre estaciones y se
eliminó. El formulario lo muestra siempre de solo lectura y no lo envía, y `update_cliente`
rechaza cambiarlo. La `0094` renumera los clientes existentes **y modifica datos**: ver
`docs/RENUMERACION_CODIGOS_CLIENTE.md` (respaldo + ensayo en copia antes de producción). Las
estaciones nuevas no abren hasta que el servidor tenga las migraciones aplicadas.
La impresora predeterminada pasó a ser **por estación** (`app/utils/impresora_local.py`,
`QSettings`), ya no de la BD compartida.

## 4. Cuentas por pagar "otros": transferencias sin conciliar

El módulo de "cuentas por pagar otros" **no modela pasivos comerciales** (alquileres,
servicios). Representa dinero que ya llegó a una cuenta bancaria de la empresa por
transferencia de un cliente, pero sin comprobante que permita identificar de quién es.
Mientras no se identifique, es dinero pendiente de explicar/atribuir — de ahí que viva
conceptualmente en el lado de "pagar".

El flujo es:

1. `crear_partida_no_conciliada()` registra el monto recibido, opcionalmente enlazado al
   movimiento bancario real que lo trajo.
2. `conciliar_partida()`, una vez identificado el cliente, aplica el monto directamente
   contra su cuenta por cobrar (reduce saldo, actualiza estado) **sin generar un nuevo
   movimiento bancario**, porque el ingreso del dinero ya quedó contabilizado cuando llegó
   la transferencia. Aplicarlo vía el flujo normal de `pagos_cobros` duplicaría el saldo
   bancario, ya que ese trigger siempre crea un movimiento nuevo.

La tabla `cuentas_por_pagar_otros` no existía en el schema original; se agregó siguiendo
el mismo patrón (`IF OBJECT_ID ... IS NULL`) que el resto del archivo.

### Configuración de correo (SMTP) desde la app

Configuración > Correo (`app/ui/config_smtp_panel.py`) guarda el servidor SMTP en la tabla
`configuracion_smtp` (migración 0077, una sola fila) para que el usuario no edite el `.env`.
El usuario solo elige su servicio (Gmail, Outlook/Hotmail, Microsoft 365, Yahoo, iCloud, Zoho)
y escribe correo + contraseña: servidor/puerto/TLS salen del catálogo `PROVEEDORES` en
`app/services/smtp_config.py`; "Otro" muestra los campos manuales. Decisiones:

- Se guarda en la base, no en un archivo local, porque el correo de desbloqueo se dispara
  desde cualquier estación y todas deben compartir la misma cuenta. Sin fila (o fila sin
  usuario/clave) se usan las variables `SMTP_*` del `.env` como respaldo
  (`SmtpConfigService.obtener_efectiva`).
- No hay columna `proveedor`: el selector se reconstruye comparando servidor+puerto+TLS con el
  catálogo (`proveedor_de_servidor`).
- Permisos: reutiliza `empresa`/`ver` y `empresa`/`editar`.
- La contraseña se guarda **cifrada** (`password_cifrada`, migración 0089): cualquier estación la
  cifra con la llave pública del servidor (`clave_cifrado_servidor`) y solo el servidor puede
  descifrarla (llave privada en un archivo protegido con DPAPI de esa máquina,
  `app/services/cifrado_servidor.py`). Nunca se muestra ni va a auditoría; dejar el campo vacío al
  guardar la conserva. La contraseña en texto plano de versiones anteriores la cifra el servidor
  solo al arrancar (`SmtpConfigService.migrar_password`). Si el servidor pierde su llave, la
  contraseña guardada se descarta y hay que escribirla de nuevo.
- **El correo lo envía solo el servidor** (`app/services/cola_correos.py`): una estación nunca
  habla con el SMTP; deja el correo (código de desbloqueo/recuperación, aviso de seguridad) en la
  tabla `cola_correos` y el servidor lo despacha cada ~15 s -- el servicio de Windows
  (`app/servicio_licencia.py`) aunque nadie tenga la app abierta, y la app abierta en el
  servidor. Cada correo se reclama con un UPDATE atómico, así que ambos pueden correr a la vez
  sin duplicar. Reintenta 3 veces, descarta lo vencido (los códigos duran 15 min) y borra el
  contenido del mensaje al enviarlo. Si la estación no tiene servidor encendido, el código no sale.
- Gmail responde a una contraseña mala cerrando la conexión en vez de devolver 535 —
  `email_service._autenticar` lo convierte en `SMTPAuthenticationError`; sin eso la UI
  mostraba "revise el puerto".
- Puerto 465 usa `SMTP_SSL` (SSL directo); el resto, STARTTLS si `usar_tls`.

### Artículo BCV (migración 0079, 2026-10-19)

- `inventario.articulo_bcv` (BIT, default 0), casilla "Artículo BCV" en el formulario de producto.
  Un artículo marcado se factura siempre a su precio guardado: el porcentaje BCV de la factura
  no se le aplica. Los demás artículos de la misma factura sí lo llevan.
- El porcentaje BCV lo aplica el diálogo de factura (`FacturaFormDialog`), no el servicio:
  `_porcentaje_bcv_para(id_producto)` devuelve 0 para un artículo BCV y lo usan el combo de
  precios, el precio a facturar, el precio base del carrito y el recálculo del carrito cuando
  cambia el porcentaje. El combo de productos marca "· Artículo BCV".
- Comisiones: la base de comisión de un artículo BCV tampoco lleva el porcentaje
  (`ComisionService`), así que su comisión es la de siempre (venta − precio de lista).
- No cambia las facturas ya emitidas ni la cuenta por cobrar BCV (que sigue siendo por factura,
  con el porcentaje que se escribió). Una factura con porcentaje BCV cuyos artículos son todos
  Artículo BCV igual abre su cuenta BCV, con el mismo total.
- *No cubierto:* en el diálogo de factura, pasar un artículo a venta "por unidad"
  (`_on_tipo_venta_cambiado`) fija el precio sin porcentaje BCV para cualquier artículo; es un
  comportamiento anterior a este cambio.

### Revisión de cobros, comisiones y pantallas chicas (2026-10-06)

- **Pagos de cuentas por cobrar BCV (migración 0078).** Un pago contra `cuentas_por_cobrar_bcv`
  solo le restaba saldo a la cuenta: no dejaba constancia, no ingresaba a la caja/cuenta bancaria
  y por eso tampoco salía en el historial del cliente. `trg_pagos_cobros_io` no sirve para BCV
  (valida y descuenta de `cuentas_por_cobrar`), así que hay tabla propia `pagos_cobros_bcv` y
  `PagoBCVService._registrar_pago_bcv` inserta la fila + el movimiento (`BancoMovimiento` 'abono'
  / `CajaMovimiento` 'entrada', enlazados por `id_pago_cobro_bcv`). Lo usan los tres caminos:
  cobro individual, abono general FIFO y factura de contado con porcentaje BCV (esta última no
  ingresaba nada a la caja). El sobreabono también ingresa el excedente. `historial_cliente`
  incluye estos pagos y toma el saldo de la factura de la cuenta BCV (la normal queda en 0).
  Bug previo corregido: `numero_nota_credito` es VARCHAR(20) y `ABONO-BCV-` + 14 dígitos no
  cabía, así que todo sobreabono BCV fallaba (ahora `ABV-...`).
  *No cubierto:* anular una factura BCV con pagos no revierte estos movimientos (los de
  `pagos_cobros` los revierte un trigger al borrar el pago; aquí no hay equivalente).
- **Doble conversión en el diálogo de pago de factura.** Con transferencia/punto de venta el
  campo "Monto" ya es USD (lo calcula el bloque Bs + tasa) pero se enviaba `moneda='VES'`, y
  `emitir_factura` lo dividía otra vez por la tasa (Bs 4.000 a tasa 40 contaban $2,50). Con el
  bloque Bs la moneda queda fija en USD (`METODOS_CON_BLOQUE_BS`); el Bs y la tasa viajan en
  `monto_bolivares`/`tasa_cambio`. Los diálogos de cobro de CxC (normal y BCV) mandaban Bs con
  `moneda='USD'` (la factura mostraba "4.000 USD"): ahora `moneda='VES'` si hay Bs.
- **Pago de comisiones con filtro BCV.** El panel mostraba/confirmaba el total filtrado pero
  `pagar_comisiones_vendedor` pagaba TODO lo liberado. Ahora recibe `ids_comision` (las
  mostradas) y `monto_esperado` (lo confirmado; si no coincide se rechaza sin pagar). Sin esos
  parámetros mantiene el comportamiento de siempre (pagar todo lo liberado).
- **`Proveedor.dias_credito`.** El tooltip decía "0 = de contado, no se le podrá comprar a
  crédito" pero nada lo comprobaba. `CompraService.registrar_compra` y `crear_compra_desde_oc`
  ahora lo exigen (mismo gate que `Cliente.dias_credito` en ventas). **Efecto en datos
  existentes:** los proveedores con 0 días (el default de la columna) solo podrán comprarse de
  contado hasta que se les configuren los días.
- **Pantallas chicas.** Los diálogos tenían tamaño fijo (cliente 920x900) y en monitores de
  ~768 px de alto —o con escala de Windows al 125-150 %— la barra de tareas tapaba los botones.
  `app/ui/pantalla.py`: `ajustar_tamano` acota el tamaño a `availableGeometry()` y
  `hacer_desplazable` pone el cuerpo en un `QScrollArea` dejando el pie de botones siempre
  visible. Aplicado a todos los diálogos con `setFixedSize`/mínimos grandes y a la ventana
  principal. Los diálogos nuevos deben usarlo en vez de `setFixedSize`.

### Cuentas bloqueadas, "otros movimientos" y blindaje de la base (2026-10-23)

- **Bloqueo temporal y escalonado** (`app/services/bloqueo.py`): 5 intentos fallidos bloquean 5 min;
  si al vencer falla otra vez, 15 min, luego 1 hora. Antes era permanente y cualquiera podía dejar
  fuera a los ADMIN a propósito. Se levanta antes con un código al correo o un ADMIN. Al bloquearse
  se avisa por correo a los ADMIN (1 aviso por cuenta cada 30 min), la campana muestra las cuentas
  bloqueadas y la auditoría del fallo indica desde qué PC.
- **"Otros movimientos" trazables** (migración 0090): un préstamo/anticipo exige de dónde sale el
  dinero (caja con turno y saldo, o banco con saldo y referencia) y registra el egreso; una
  transferencia sin identificar exige el abono bancario real que la trajo (un movimiento = una
  partida, no más que su monto, no atribuido ya a un pago); conciliar solo contra facturas con saldo
  y deja un registro (`conciliaciones_partida`) que el historial del cliente muestra como abono.
- **Historial del cliente**: el monto de la factura es lo que paga el cliente (subtotal - descuento
  + IVA) y el SALDO PENDIENTE total suma también las cuentas BCV.
- **Blindaje de la base**:
  - `DB_PASSWORD` puede vivir como `DB_PASSWORD_DPAPI=dpapi:...` (cifrado con DPAPI de esa PC, no
    sirve copiado a otra): `python -m app.proteger_env` lo aplica al `.env`/`config.env` (deja
    `.bak`; `--revertir` lo deshace -- `docker compose` necesita `DB_PASSWORD` en claro) y el
    instalador ya lo escribe así. La conexión va con `Encrypt=yes` y `APP=NexoERP`.
  - Migración 0091: el rol `nexo_app_sin_borrado` (al que el instalador agrega el usuario de la
    app) tiene DENY DELETE sobre pagos, movimientos de caja/banco, notas de crédito, conciliaciones
    y auditoría, y DENY UPDATE sobre las bitácoras. **No aplica a sysadmin/db_owner**: la app debe
    correr con el usuario limitado del instalador, no con `sa`.
  - Migración 0092: triggers que guardan en `auditoria_cambios_db` el valor anterior/nuevo (JSON),
    usuario SQL, PC y programa de cada cambio a dinero e inventario. Lo hecho por fuera de la app
    (`APP_NAME()` distinto de `NexoERP*`) queda con `fuera_de_la_app = 1` y la campana avisa a quien
    ve la auditoría. No impide el cambio: lo hace visible y reversible.
  - El instalador abre el puerto de SQL Server en el Firewall de Windows solo para la red local
    (`remoteip=LocalSubnet`).
  - Pendiente consciente: el certificado de SQL Server sigue siendo autofirmado
    (`TrustServerCertificate=yes`); `datos_estaciones.txt` (lo genera el instalador del servidor)
    contiene la clave en claro y **se borra solo a las 24 h** (`app/services/datos_estaciones.py`,
    lo ejecutan el servicio de Windows del servidor y la app abierta en el servidor).

## 5. Auditoría

`auditoria.py` expone `registrar_evento()` (usuario, acción, módulo, detalle en texto o
JSON) y `consultar_auditoria()` (filtros por fecha, usuario, módulo, acción, con
paginación) para el reporte de trazabilidad del rol ADMIN.

La tabla `auditoria` tampoco existía en el schema original; se agregó como tabla
append-only, con FK a `usuarios` en `ON DELETE SET NULL` para no perder el historial si
un usuario se elimina.

Está conectada a los siguientes eventos, cubriendo todos los módulos con operaciones de
escritura:

- **Login** (`auth.py`)
- **Clientes / Proveedores / Vendedores**: alta, edición, baja
- **Inventario**: categorías, productos y precios (alta, edición, baja)
- **Ventas**: emisión y anulación de factura
- **Compras**: registro y anulación
- **Tesorería**: bancos y cuentas bancarias (CRUD), apertura/cierre de caja, movimientos
  manuales de caja
- **Pagos**: aplicación de pago a cliente/proveedor
- **Tasas de cambio**: cada registro nuevo
- **Usuarios**: alta, edición, cambio de estado
- **Roles y permisos**: alta/edición/baja de rol, asignar/revocar/reemplazar permisos
- **Cuentas por cobrar/pagar otros**: alta, abono, conciliación
- **Configuración de empresa**: cada actualización

En los métodos donde no existía forma de saber quién ejecutó la acción se agregó un
parámetro opcional (`id_usuario` o, en `usuarios.py`, `realizado_por` para no
confundirlo con el usuario que es objeto de la operación). Todos son opcionales con
valor por defecto `None`, así que no rompen código existente que no lo use.

Nota: `anular_factura()`/`anular_compra()` (2026-08-22, actualizado 2026-08-22) revierten
el stock y cierran la cuenta por cobrar/pagar asociada. Si ya se le aplicaron pagos, esos
pagos no se tocan — se genera una nota de crédito por el monto ya cobrado/pagado y la
cuenta pasa a `estado='anulada'` en vez de borrarse, ver "Notas de credito automaticas"
en la sección 3. Sin pagos aplicados, la cuenta se sigue borrando (nada que preservar).
Comisiones sobre alguna línea (solo aplica a ventas, C14 resuelto 2026-08-23, ver
"Comisiones de vendedor" más abajo): las `'pendiente'` se borran antes de anular, las
`'pagada'` siguen bloqueando con `ValueError`. El mecanismo es borrar las líneas de
`factura_detalle`/
`compra_detalle` (dispara los triggers de stock y de recálculo de total) antes de tocar
`cuentas_por_cobrar`/`cuentas_por_pagar` — `trg_factura_venta_cxc`/`trg_compras_cxp` solo
tocan cuentas en estado `'pendiente'`, así que si ya hay pagos aplicados (`'parcial'`/
`'pagada'`) el trigger no la altera y fijar `estado='anulada'` después es seguro.

## 5.1 Novedades por versión y saludo al entrar (2026-11-06)

Al abrir la app (justo después de mostrar la ventana principal, `MainWindow.mostrar_bienvenida`) se muestra UNA cosa:

- **Primer ingreso del usuario** (un solo `LOGIN` en auditoría): saludo "¡Bienvenido, Luis!".
- **Versión nueva** desde la última que vio ese usuario en esa estación: ventana "Novedades", filtrada por los módulos
  que su rol puede ver (cada cambio puede declarar `modulos`; sin `modulos` es general).
- **Cualquier otro caso**: toast breve que se quita solo ("Buenos días, Luis · Bienvenido de nuevo").

La última versión vista se guarda por estación y usuario en QSettings (`app/utils/novedades_local.py`), igual que
la impresora: no toca la base de datos. Un fallo al mostrarla se registra y nunca impide trabajar. El pie del menú
lateral ("Novedades · vX") reabre la ventana a pedido.

**Cómo publicar novedades de una versión:** (1) subir `VERSION` en `app/version.py` (única fuente: la usan la app, el
sidebar y `packaging/construir.ps1`); (2) agregar la entrada en `app/assets/novedades.json` con tipos
`nuevo|mejorado|general` y, si aplica, los `modulos` (claves del sidebar). `tests/test_novedades.py` falla si
`VERSION` no tiene entrada o si hay un tipo/módulo inexistente.

**Criterio editorial (discreción):** se cuenta solo lo útil y visible (máx. 6 líneas de una frase, sin detalle técnico),
lo más útil con `"destacado": true`. **No se acumulan entre versiones:** se muestra solo la entrada de la versión
instalada (quien se salta versiones no ve las intermedias; tampoco al reabrirla desde el menú lateral). Los arreglos de algo que no debió fallar no se anuncian: van todos en la única línea
`general` "Mejoras de estabilidad y funcionamiento." (no existe el tipo `corregido`). Las pruebas hacen cumplir estos límites. Lógica pura en `app/novedades.py`; diálogo en
`app/ui/novedades_dialog.py`; el saludo reutiliza `Toast` con el tipo `"saludo"`.

## 6. Panel general (`dashboard.py`)

`get_panel_general_data()` devuelve en una sola llamada:

- Ventas de hoy y % vs. ayer (excluye facturas `ANULADA`)
- Saldo total por cobrar / por pagar y cantidad de cuentas vencidas
- Conteo de productos en alerta de stock
- Serie de 7 días para el gráfico de ventas semanales
- Cajas con turno abierto hoy y su cajero
- Últimas 5 facturas emitidas
- Top 5 productos con menor stock (con categoría)

## 7. Autorización (RBAC)

**Hallazgo de auditoría 2026-08-22, resuelto el mismo día**: `UsuarioService.verificar_permiso()`
existía desde el principio (con tests), pero ningún servicio lo llamaba — la matriz de
permisos se podía editar pero no bloqueaba nada. Ahora está aplicado en los 18 módulos
de servicio.

- **Punto de entrada**: `require_permiso(session, id_usuario, recurso, accion)` en
  `app/services/permisos.py`. Se llama como primera línea de cada método de **escritura**
  (crear/editar/eliminar/emitir/anular/aplicar/asignar/etc.) **y de lectura**
  (`listar_*`/`obtener_*`/`buscar`/`consultar_*`/`dashboard.py`) en los 18 servicios.
  `id_usuario=None` (actor desconocido) se trata como **no autorizado**, no como "confiar
  por defecto" — decisión explícita del usuario, más estricta que dejarlo pasar.
- **ADMIN bypassa la matriz por completo** (superusuario): el seed de
  `schema_sqlserver.sql` no le asigna ninguna fila en `rol_permisos` a propósito, así que
  sin este bypass ADMIN quedaría bloqueado de todo. Cualquier otro rol se valida contra
  `rol_permisos`.
- La consulta contra `rol_permisos` está **duplicada** entre `require_permiso()` y
  `UsuarioService.verificar_permiso()` (misma lógica) a propósito: `usuarios.py` necesita
  importar `require_permiso()` para proteger sus propios métodos, e importar
  `UsuarioService` desde `permisos.py` crearía un ciclo de imports.
- **Catálogo de permisos** (`migrations/0004_catalogo_permisos_modulos.sql`): el seed
  original solo tenía 3 filas (`inventario:ver`, `reportes_ventas:ver`,
  `reportes_comisiones:ver`, todas para VENDEDOR). Se agregaron ~51 permisos más, uno por
  cada combinación recurso/acción relevante en los 18 módulos. `accion` está restringido
  por `CK_permisos_accion` a exactamente `'ver'/'crear'/'editar'/'eliminar'` — operaciones
  que no son CRUD literal se mapearon al más cercano (emitir factura/registrar compra →
  `crear`, anular factura/compra → `eliminar`, abrir/cerrar turno de caja → `editar`,
  asignar permisos a un rol → `editar`). Ningún permiso nuevo se asignó a VENDEDOR/CAJERO
  en el seed — quedan cerrados hasta que un ADMIN los otorgue explícitamente.
- **Lecturas gateadas (2026-08-22, segunda pasada)**: se agregó `id_usuario` a todos los
  `listar_*`/`obtener_*`/`buscar` de los 18 servicios, más `DashboardService.get_panel_general_data()`
  y `AuditoriaService.consultar_auditoria()` (acción `ver` sobre el recurso del módulo).
  Un método interno que ya llama a otro método gateado con la misma acción/actor
  (`CajaService.obtener_estado_cajas()` → `listar_cajas()`, `PermisoService.obtener_matriz_rol()`
  → `listar_permisos()`) simplemente reenvía el `id_usuario` recibido en vez de duplicar el
  chequeo. `EmpresaService.guardar_configuracion()` es la excepción: en vez de llamar a
  `obtener_configuracion()` (gateada con `empresa:ver`) usa la query directa, porque su
  propio actor solo tiene garantizado `empresa:editar` — acoplar una escritura a un
  permiso de lectura distinto sería un bug esperando pasar.
- **`AuditoriaService.consultar_auditoria()` usa `id_usuario_actor`, no `id_usuario`**:
  ese nombre de parámetro ya estaba tomado (filtro "traer solo los eventos de este
  usuario"), así que el actor que ejecuta la consulta va en un parámetro nuevo separado.
  También es el único módulo con un *lazy import* de `require_permiso()` (dentro del
  método, no al tope del archivo) en vez de la duplicación de lógica que usa
  `usuarios.py`/`permisos.py`: `auditoria.py` no puede importar `permisos.py` al cargar el
  módulo porque `permisos.py` importa `AuditoriaService` para su propio logging, y ambos
  enfoques (import diferido vs. duplicar la consulta a `rol_permisos`) resuelven el mismo
  ciclo — se eligió el import diferido aquí para no triplicar esa lógica.
- **`crear_nota_credito_cliente()`/`crear_nota_credito_proveedor()` (`notas_credito.py`)
  siguen sin gatear a propósito** (a diferencia de sus `listar_notas_credito_*`, que sí lo
  están): son un efecto secundario interno de `anular_factura()`/`anular_compra()` (ya
  gateadas con `ventas:eliminar`/`compras:eliminar`), no una acción que un usuario invoque
  directamente. `AuditoriaService.registrar_evento()` tampoco se gatea, por la misma razón
  (logging interno, no una acción de usuario).
- **Bootstrap del primer ADMIN no se ve afectado**: `scripts/create_admin_user.py` inserta
  el `Usuario` directo contra el modelo (no pasa por `UsuarioService.crear_usuario()`),
  igual que `tests/factories.py::crear_usuario_admin()` — evita el problema de "necesito
  un ADMIN para crear el primer ADMIN".
- **Abrir/cerrar turno de caja se restringe a ADMIN, no al RBAC genérico** (2026-08-25):
  `CajaService.abrir_caja()`/`cerrar_caja()` (`app/services/tesoreria.py`) usaban
  `require_permiso(..., "cajas", "editar")` — cualquier rol con ese permiso otorgado podía
  abrir/cerrar turnos. Fijar el saldo inicial/final de una caja es más sensible que
  "editar" un registro cualquiera, así que ahora usan un helper dedicado
  `_require_admin()` que exige `rol.nombre == "ADMIN"` directamente en vez de consultar
  `rol_permisos` — ningún otro rol califica sin importar qué permisos tenga asignados.
  `app/ui/caja_apertura_dialog.py` no necesitó cambios: ya capturaba
  `PermisoDenegadoError` de `abrir_caja()` y lo mostraba en pantalla.
- **UI de Usuarios + Roles/Permisos, y filtrado del sidebar por rol (2026-08-27)**: el
  backend (`RolService`/`PermisoService`/`UsuarioService`) existía completo desde antes
  sin ninguna pantalla — `MODULOS_CONFIG["usuarios"]` caía en `PlaceholderView`. Se agregó
  `app/ui/usuarios_panel.py` (listado + alta/edición + activar/desactivar + desbloqueo
  manual, pestaña "Usuarios") y `app/ui/roles_permisos_panel.py` (CRUD de roles +
  checkbox-grid de permisos por rol, pestaña "Roles y Permisos"), ambas dentro de un solo
  `QTabWidget` para no sumar una segunda entrada de sidebar. El checkbox-grid de ADMIN se
  deshabilita (con aviso) en vez de dejar tildar algo que no tendría efecto: ADMIN
  bypassa `require_permiso()` por completo sin importar `rol_permisos`.

  **Modelo final de roles** (decisión del usuario): ADMIN (superadmin, bypass total),
  CAJERO (día a día: factura, cobra, aplica/devuelve notas de crédito —
  `migrations/0030_permisos_rol_cajero.sql` le otorga 13 permisos que la migración 0004
  había dejado sin asignar a propósito) y VENDEDOR (rep de campo de solo lectura:
  `inventario:ver` + sus propios `reportes_ventas:ver`/`reportes_comisiones:ver`, seed
  original sin cambios). Sin un rol Supervisor intermedio todavía: las autorizaciones
  sensibles (`descuentos`, `creditos`, `vueltos_bancarios`, `notas_credito:editar`)
  quedan reservadas solo a ADMIN — es dato en `rol_permisos`, no código, así que un rol
  intermedio futuro es agregar la fila + tildar casillas desde esta misma pantalla.
  Recordar que abrir/cerrar turno de caja sigue restringido a ADMIN literal sin importar
  la matriz (`_require_admin()`, ver arriba) — otorgarle `cajas:editar` a CAJERO no le
  habilita eso.

  **Bug encontrado al construir esto**: `UsuarioService.verificar_permiso()` no tenía el
  bypass de ADMIN que sí tiene `require_permiso()` — sin caller real hasta ahora (solo
  tests), así que nunca se había notado. Se usó para calcular qué módulos mostrar en el
  sidebar según el rol (`MainWindow._calcular_modulos_visibles()` +
  `MODULO_PERMISO`, `app/ui/main_window.py`); sin el fix, un ADMIN real se hubiera
  quedado sin ver ningún módulo en el menú. Corregido con el mismo bypass que
  `require_permiso()`, test de regresión en `test_usuarios.py`.

  **Filtrado del sidebar por rol** (`app/ui/sidebar.py`): es solo UX (evitar que un
  usuario entre a un módulo y choque con "sin permiso") — la barrera de seguridad real
  sigue siendo `require_permiso()` en cada servicio, sin ninguna dependencia de esto. Una
  sección entera de la sidebar (ej. "ADMINISTRACIÓN") se omite si ninguno de sus módulos
  queda visible para el rol, en vez de dejar un título de sección huérfano.

  **Auditoría de Usuarios (2026-08-27), todos los hallazgos resueltos el mismo día**:
  - **[Medio] Auto-desactivación y "último ADMIN" sin guard server-side**:
    `UsuarioService.cambiar_estado()` solo tenía el chequeo en la UI
    (`usuarios_panel.py`) — cualquier otro punto de entrada al servicio podía desactivar
    la propia cuenta, o entre varios ADMIN dejar el sistema sin ninguno activo. Ahora
    valida `id_usuario != realizado_por` y, si el objetivo es ADMIN, que quede al menos
    otro ADMIN activo después del cambio — mismo criterio en servicio y UI (defensa en
    profundidad, no solo un guard visual).
  - **`email` obligatorio pero no único**: agregado `_validar_email_unico()`
    (`usuarios.py`), mismo patrón que `_validar_nombre_usuario_unico()` — sin esto, dos
    usuarios con el mismo correo podían recibir códigos de desbloqueo/recuperación
    cruzados (`RecuperacionAccesoService` busca por `nombre_usuario`, no por email).
  - **Sin tope de longitud** en `nombre_usuario`/`nombre`/`apellido`/`email` (ni cliente
    ni servidor) y sin tope de bytes en `clave` (bcrypt exige ≤72 bytes utf-8, ver
    `PASSWORD_MAX_BYTES` en `auth.py` — sin esto, un texto muy largo pegado disparaba un
    error crudo de SQL Server o de la librería bcrypt en vez de un mensaje claro).
    Validado en `usuarios.py`/`auth.py` y con `setMaxLength()` en
    `usuario_form_dialog.py`.
  - **Vínculo Usuario↔Vendedor sin unicidad**: `_resolver_vinculo_vendedor()` ahora
    rechaza vincular un `Vendedor` que ya está vinculado a otro usuario — mezclaría
    reportes/comisiones entre ambos logins sin forma de distinguirlos.
  - **Bypass de ADMIN por nombre de rol, sin protección de UI**: `require_permiso()`
    identifica al superusuario por el string literal `"ADMIN"` (no un flag estable), y
    `RolesPermisosPanel` es la primera pantalla que permite renombrar/eliminar roles.
    `RolService.actualizar_rol()`/`eliminar_rol()` ahora rechazan renombrar o eliminar el
    rol `ADMIN` específicamente — cerraba la única vía (aunque hoy inalcanzable, ya que
    solo ADMIN llega a esa pantalla) para que un futuro rol con `'permisos'/'editar'`
    se autoescalara o dejara el sistema sin superusuario.

- **UI de Tasas de Cambio (2026-08-27)**: `app/ui/tasas_panel.py` +
  `app/ui/tasa_registro_dialog.py` — tasa vigente con delta vs. ayer, alta de una tasa
  nueva, histórico exportable. Sin edición/eliminación: `TasaService` no las tiene, cada
  registro es un snapshot histórico inmutable. **Auditoría del módulo (2026-08-27),
  todos los hallazgos resueltos el mismo día**:
  - **[Medio] Sin aviso ante un posible error de tipeo**: como `emitir_factura()`/
    `registrar_compra()` leen `ControlDeTasa` directo para convertir pagos en VES/COP,
    una tasa mal tipeada (ej. `4.20` en vez de `42.00`) afectaba de inmediato todas las
    ventas en esa moneda sin ningún paso intermedio. `TasasPanel._confirmar_si_salto_
    brusco()` ahora pide confirmación (no bloquea — una tasa SÍ puede saltar de verdad
    en una crisis cambiaria) cuando el nuevo valor difiere más de 30% del último
    registrado, para BCV/paralelo/COP.
  - **`tasa_paralelo`/`tasa_cop` sin validar en el servidor**: `registrar_tasa()` solo
    validaba `tasa_bcv > 0` — ahora los tres campos exigen ser mayores a cero si se
    proveen (ni la UI ni la base tenían esta guarda; `DECIMAL(10,2)` no tiene `CHECK`).
  - **Etiqueta "vs. ayer" podía ser engañosa**: `obtener_tasa_actual()` comparaba
    contra la tasa registrada más reciente antes de hoy sin verificar que fuera
    literalmente de ayer — con un hueco de varios días sin registrar (fin de semana,
    feriado) el porcentaje era real pero la comparación no era con "ayer". Ahora solo
    calcula el `porcentaje_vs_ayer_*` cuando la tasa anterior es del día calendario
    inmediatamente anterior; si no, queda en `None` (la UI ya lo maneja: sin porcentaje,
    no se muestra nada). Beneficia también a `TasaTicker`, que usa el mismo método.

## 8. Validaciones de negocio destacadas

- **Códigos/identificaciones obligatorios**: `clientes.py` y `proveedores.py` exigen
  código e identificación al crear y no permiten vaciarlos al editar. Esto es necesario
  porque SQL Server, a diferencia de otros motores, solo permite **una fila con NULL**
  por columna `UNIQUE` — dos clientes sin código violarían la restricción.
- **Stock y crédito en ventas**: `emitir_factura()` valida disponibilidad de stock
  (agrupando ítems repetidos) y, si la condición es `credito`, que la deuda actual del
  cliente más la nueva factura no supere `limite_credito`.
- **Crédito exige `Cliente.dias_credito` configurado (2026-08-25)**: antes cualquier
  cliente podía facturarse a crédito sin importar `dias_credito` (columna
  `NOT NULL DEFAULT 0`) — un cliente nuevo sin configurar terminaba con vencimiento
  inmediato (0 días) sin ningún aviso. Ahora `emitir_factura()` rechaza
  `condicion_pago='credito'` si `cliente.dias_credito <= 0` (gate de elegibilidad, aplica
  incluso si se pasa `fecha_vencimiento` explícita para datos backdateados). Para un
  cliente que sí califica, se puede dar una cantidad de días distinta a la configurada
  para una factura puntual vía `dias_credito_personalizados`, pero requiere autorización
  de un supervisor (`motivo_dias_credito` + `id_autorizador_dias_credito`, permiso
  `'creditos'/'crear'`, migración `migrations/0025_autorizacion_dias_credito.sql`) —
  mismo mecanismo que ya existía para descuentos (`'descuentos'/'crear'`), generalizado en
  un único `app/ui/autorizacion_dialog.py::AutorizacionDialog(recurso, accion, ...)`
  reutilizable. `FacturaVenta.dias_credito_aplicados` guarda el snapshot de los días
  efectivamente usados (configurados u override) para cada factura de crédito.
  `app/ui/factura_form_dialog.py` refleja esto con un checkbox "Usar días de crédito
  configurados del cliente" — `vencimiento_input` pasó a ser siempre un valor derivado
  (ya no editable a mano libremente sin autorización).
- **Clientes, proveedores, vendedores, productos, bancos y cuentas bancarias nunca se
  borran físicamente** (resuelto 2026-08-22, ver el hallazgo "deletes sin guarda" en la
  sección 9): `delete_cliente()`/`ProveedorService.eliminar()`/`VendedorService.eliminar()`/
  `ProductoService.eliminar()`/`BancoService.eliminar_banco()`/`eliminar_cuenta()` ahora
  siempre lanzan `ValueError` explicando que hay que usar `cambiar_estado(...)` /
  `cambiar_estado_cliente(...)` / `cambiar_estado_banco(...)` / `cambiar_estado_cuenta(...)`
  en su lugar — sin importar si la fila tiene dependientes o no, para no depender de un
  conteo que puede quedar desactualizado apenas se registre la primera factura/compra/
  movimiento. El nuevo campo `estado_*` (`ACTIVO`/`INACTIVO`, migración
  `0005_estado_desactivacion_entidades.sql`) sigue el mismo patrón que ya existía en
  `usuarios.estado` y `vendedores.estado_vendedor` (este último existía pero no lo usaba
  nada hasta ahora). `CategoriaService.eliminar()`/`RolService.eliminar_rol()` NO
  cambiaron — ya tenían su propia guarda por conteo de dependientes y siguen borrando de
  verdad cuando no hay ninguno.
- **Crédito de proveedor en compras**: `registrar_compra()` aplica la misma validación
  simétrica sobre `proveedores.limite_credito`.
- **Ruta obligatoria para vendedores (2026-09-01)**: `VendedorService.crear()` exige
  `id_ruta` (no se puede crear un vendedor sin ruta asignada), pero la columna
  `vendedores.id_ruta` sigue siendo `NULLABLE` en BD (`migrations/0038`) — mismo criterio
  que `codigo_vendedor`/`identificacion_vendedor`: un entorno con vendedores ya cargados no
  puede satisfacer un `NOT NULL` sin inventar una ruta genérica sobre datos reales. El
  módulo Vendedores gano una pestaña "Rutas" (`app/ui/rutas_panel.py`) para administrar el
  catálogo y un combobox de ruta en `VendedorFormDialog`.
- **Geolocalización obligatoria (clientes y rutas, 2026-09-01)**: `clientes.latitud`/
  `longitud` y `rutas.latitud`/`longitud` (`migrations/0039`, `DECIMAL(10,7)`, ambas
  columnas NULLABLE en BD) fijan un punto de referencia por cliente y por ruta. Es
  obligatoria a nivel de servicio (decisión de producto, revierte el diseño "opcional"
  original del mismo día): `create_cliente()`/`RutaService.crear()` exigen `latitud`/
  `longitud` (`is None`, no falsy — `0.0` es una coordenada legítima, ecuador/meridiano de
  Greenwich), y `update_cliente()`/`RutaService.actualizar()` no permiten vaciarlas una vez
  cargadas — mismo criterio "no permite vaciar" que `codigo_cliente`/`nombre_ruta`. La
  columna sigue `NULLABLE` en BD por el motivo de siempre: no forzar un backfill sobre
  clientes/rutas ya existentes.

  La UI usa un mapa Leaflet + OpenStreetMap embebido vía `QWebEngineView`
  (`app/ui/mapa_widget.py`, ya incluido en el wheel completo de PySide6 — no es
  dependencia nueva), sin costo ni API key, comunicando JS→Python sin `QWebChannel`
  (esquema de URL ficticio `mapaclick://`, ver docstring del módulo). Se usa en
  `ClienteFormDialog` (mapa editable, un solo marcador, campos lat/lng con asterisco),
  en `RutaFormDialog` (mapa editable, modo `"zona"` — ver "Zona de cobertura de ruta"
  más abajo) y en la pestaña "Mapa" de Vendedores (`app/ui/mapa_rutas_panel.py`, solo
  lectura, pinta los clientes geolocalizados de la ruta seleccionada vía
  `ClienteService.listar_clientes_por_ruta` — el vínculo es indirecto, Cliente →
  Vendedor → Ruta — junto con la zona de cobertura de esa ruta).

  En modo editable el mapa agrega, vía `app/ui/geo_http.py` (llamadas HTTP livianas,
  siempre en un `QThread` aparte — `HttpWorker` — para no congelar la UI, nunca lanzan:
  cualquier fallo devuelve `None`/`[]`):
  - Centrado inicial automático en la ubicación aproximada del dispositivo por IP
    (`ipapi.co`, sin GPS ni permisos del SO) para no arrancar siempre en un punto fijo
    lejano al usuario — solo centra/hace zoom, nunca fija una coordenada por sí solo.
  - Búsqueda de lugares por nombre (Nominatim/OpenStreetMap) — funciona igual que un
    click en el mapa: mueve el marcador y emite `coordenadas_cambiadas`.

  Requiere conexión a internet para ver el mapa (decisión aceptada por el usuario a
  cambio de no pagar ni gestionar API keys) — las tiles de OpenStreetMap y las llamadas
  de `geo_http.py` no se pueden evitar. Leaflet en sí (JS/CSS + iconos de marcador) SÍ
  está vendorizado en `app/ui/web/leaflet/` y se carga desde disco
  (`QUrl.fromLocalFile`) en vez de su CDN público — cargarlo por red en cada apertura de
  diálogo sumaba 1-2 round-trips (DNS+TLS+descarga) solo para la librería antes de poder
  pintar nada (hallazgo de rendimiento, 2026-09-01: "la vista del mapa tarda en
  cargar"). Además, `MapaWidget` dispara `setHtml()` (lo único lento: crear la página de
  Chromium) con `QTimer.singleShot(0, ...)` en vez de en `__init__`, para que el diálogo
  que lo contiene quede visible de inmediato en lugar de bloquear su apertura completa.

- **Fixes de auditoría sobre Vendedores/Rutas/geolocalización (2026-09-02)**:
  - `VendedorFormDialog` cargaba el combo de rutas con una query directa
    (`session.query(Ruta)...`), sin pasar por `RutaService.listar()` — cualquier usuario
    con permiso `vendedores/crear` o `vendedores/editar` veía el catálogo de rutas aunque
    no tuviera `rutas/ver`. Ahora usa `RutaService.listar()` (requiere `id_usuario` nuevo
    en el constructor del diálogo) y cae a una lista vacía ante `PermisoDenegadoError`.
  - `VendedorService.crear()`/`actualizar()` validan que el `id_ruta` recibido exista y
    esté `ACTIVO` (`_validar_ruta_activa()`) — antes solo la UI restringía el combo a
    rutas activas, un llamado directo al servicio podía asignar una ruta desactivada sin
    aviso.
  - CAJERO tenía `vendedores/ver` (desde `migrations/0030`) pero nunca `rutas/ver`:
    abría el módulo Vendedores pero las pestañas nuevas "Rutas"/"Mapa"
    (`migrations/0038`) le tiraban "Sin permiso". `migrations/0041` se lo otorga.
  - `HttpWorker` (`app/ui/geo_http.py`) se creaba con `parent=self` (el widget que lo
    lanza, ej. `MapaWidget`/`RutaFormDialog`). Cerrar la app mientras una búsqueda/
    geolocalización/cálculo de trazado sigue en vuelo (timeout de 5s) destruye un
    `QThread` todavía corriendo al desmontar el árbol de widgets — fatal en Qt. Ahora los
    workers no tienen padre Qt, se auto-registran en un set a nivel de módulo mientras
    corren y se limpian solos al terminar (`_limpiar()`); `app/main.py` conecta
    `QApplication.aboutToQuit` a `esperar_workers_pendientes()` para esperarlos antes de
    cerrar.
  - Cobertura de tests nueva: `id_ruta` obligatorio/válido/activo en
    `tests/services/test_vendedores.py`, y `tests/ui/test_geo_http.py` (funciones puras
    de `geo_http.py` mockeando `urllib.request.urlopen`, sin necesitar base de datos).

- **Zona de cobertura de ruta reemplaza origen/destino/trazado (2026-09-03,
  `migrations/0043_rutas_zona_poligono.sql`)**: decisión de negocio del usuario -- "una
  ruta para un vendedor no es un punto A/B, es una zona donde todos los clientes dentro
  de esa zona son atendidos por ese vendedor". Reemplazo completo (no conviven ambos
  modelos): se eliminaron `rutas.latitud`/`longitud`/`destino_latitud`/
  `destino_longitud`/`trazado_geojson` (migrations/0039/0040) y se agregó
  `rutas.zona_geojson` -- igual que su antecesor, NO es GeoJSON real, es una lista plana
  JSON `[[lat,lng], ...]`, ahora los vértices de un polígono en vez de dos puntos.
  `RutaService.crear()`/`actualizar()` exigen al menos 3 vértices (`_validar_zona()`,
  cada uno con lat/lng en rango) -- mismo criterio "obligatorio por servicio, NULLABLE en
  BD" que el resto de este módulo. Se quitó por completo la dependencia de OSRM
  (`geo_http.py::calcular_ruta_por_calles()` y su test eliminados -- ya no hace falta
  calcular un trazado por calles) y con ella cualquier llamada de red al guardar una
  ruta; solo Nominatim (buscar lugar) e ipwho.is (centrado inicial) siguen en uso.
  - **Dibujo del polígono**: `app/ui/mapa_widget.py` gana `modo="zona"` (reemplaza
    `modo="ruta"`) -- cada click en el mapa acumula un vértice (`vertice_zona_agregado`
    Signal) en vez de mover un marcador único; el dialogo (`RutaFormDialog`) es dueño de
    la lista de vértices y llama `agregar_vertice_zona()`/`deshacer_vertice_zona()`/
    `limpiar_zona()`/`establecer_zona()` para reflejarla -- mismo patrón "el mapa solo
    dibuja lo que se le pide" que ya usaba `modo="punto"`. El polígono se redibuja
    completo en cada cambio (listas cortas, no vale la pena diffear) -- menos de 3
    vértices se ve como línea punteada (feedback visual de los primeros clicks, todavía
    no es un polígono válido). `RutaFormDialog` quitó el toggle "Marcando: Origen/
    Destino", las dos filas de coordenadas manuales y el label "Calculando trazado por
    calles…" -- v1 sin edición manual de coordenadas de vértice, solo clicks en el mapa
    + "Deshacer último punto"/"Limpiar zona".
  - **`RutaService.contiene_punto(ruta, lat, lng)`**: point-in-polygon por ray casting
    (`_punto_en_poligono()`, aproximación planar -- suficiente para el tamaño de una
    zona de reparto local, no pensada para polígonos que crucen el antimeridiano/un
    polo). `RutaService.sugerir_ruta_por_ubicacion(session, lat, lng)` devuelve la
    primera ruta ACTIVA (por `nombre_ruta`) cuya zona contiene el punto, o `None`.
  - **Sugerencia de vendedor por geografía en `ClienteFormDialog`** (decisión de negocio
    2026-09-03: "puede ser automática por geografía pero debe poder asignarse manual si
    el usuario no acepta la sugerencia"): reemplaza el antiguo
    `_confirmar_cercania_a_ruta()` (alerta bloqueante de "punto lejos del trazado",
    basada en `RutaService.distancia_a_trazado()` -- eliminado junto con el resto del
    modelo de trazado). `_sugerir_vendedor_por_ubicacion()` corre en cada cambio de
    coordenada (click/edición manual/precarga al editar) y consulta
    `sugerir_ruta_por_ubicacion()`: si la zona resuelta tiene exactamente un vendedor
    ACTIVO, lo **preselecciona** en el combo -- pero solo si el cliente es NUEVO y el
    combo todavía está en "Sin asignar" (nunca reasigna un cliente existente ni pisa una
    elección manual ya hecha); con cero o varios vendedores en la zona, o sin zona que
    contenga el punto, solo se actualiza un label informativo (`lbl_sugerencia_ruta`),
    sin tocar el combo. Nunca bloquea el guardado.
  - **Mapa general de rutas** (`mapa_rutas_panel.py`): pinta la zona de la ruta
    seleccionada (`establecer_zona()`) junto con sus clientes geolocalizados
    (`mostrar_puntos()`, ya no recibe `puntos_ruta` -- no hay más marcadores de origen/
    destino que pintar). `MapaWidget.ajustarVista()` (JS) ahora encuadra la unión de
    marcadores + polígono de zona en vez de solo marcadores.
  - Tests: `tests/services/test_rutas.py` reescrito para el modelo de zona (validación
    de vértices, `contiene_punto`, `sugerir_ruta_por_ubicacion`); los tests de
    `calcular_ruta_por_calles` se quitaron de `tests/ui/test_geo_http.py` junto con la
    función.

- **Seguimientos a la zona de cobertura (mismo día, 2026-09-03)**:
  - **Marcadores numerados por vértice + orden por ángulo**: cada clic ahora deja un
    circleMarker azul numerado (1, 2, 3...) además del contorno (`redibujarZona()` en
    `mapa_widget.py`, tooltip permanente con clase CSS `.zona-vertice-tooltip`) --
    feedback en vivo de cada punto marcado, no solo del polígono final. Clickear fuera
    del orden del perímetro producía una figura auto-intersectada ("moño") en vez de un
    área limpia -- `RutaFormDialog._ordenar_por_angulo()` reordena los vértices por
    ángulo alrededor de su centroide antes de cada redibujado, así el polígono nunca
    queda cruzado sin importar el orden de clic. El orden de clic real se conserva
    aparte (`self._vertices`) solo para que "Deshacer último punto" siga quitando el
    clic más reciente (no el que quede último tras reordenar); lo que se dibuja y se
    persiste como `zona_geojson` es siempre `_ordenar_por_angulo(self._vertices)`. Los
    números mostrados en el mapa reflejan el orden del contorno resultante, no el de
    clic -- pueden "correrse" al agregar un punto nuevo, tradeoff aceptado a cambio de
    que el polígono se vea siempre limpio.
  - **Geolocalización nativa de Windows para "Mi ubicación"** (`app/ui/geo_windows.py`,
    nuevo): reemplaza `navigator.geolocation` de Chromium/QtWebEngine, que en desktop sin
    GPS depende del proveedor de ubicación por red de Chromium -- que necesita una clave
    de API de Google que los builds de QtWebEngine no traen configurada, así que
    `getCurrentPosition()` fallaba casi siempre con `POSITION_UNAVAILABLE` (hallazgo del
    usuario: "el botón no está funcionando bien"). Ahora usa el `Geolocator` nativo de
    WinRT (paquetes `winrt-Windows.Devices.Geolocation`/`winrt-Windows.Foundation`/
    `winrt-Windows.Foundation.Collections`, `requirements.txt`/`requirements-lock.txt`
    con marcador `; sys_platform == "win32"` -- no rompe instalación en Linux/Mac/CI),
    que consulta el proveedor de ubicación del propio Windows (Configuración >
    Privacidad > Ubicación -- GPS si el equipo lo tiene, o WiFi/red que Windows ya
    resuelve) sin depender de ninguna clave de terceros. Nota de dependencia: `winsdk`
    (el paquete "clásico" para esto) ya no tiene wheels para Python 3.13+ y falla al
    compilar desde código fuente en este entorno -- `winrt-Windows.*` es su sucesor
    (paquetes por namespace) y sí tiene wheels hasta cp313/cp314. Probado end-to-end
    2026-09-03: `Geolocator.request_access_async()` devuelve `ALLOWED` y
    `get_geoposition_async()` devuelve lat/lng/accuracy reales en este equipo, y el
    flujo completo `HttpWorker` (QThread) + `asyncio.run()` dentro corriendo junto al
    loop de eventos de Qt no bloquea ni cuelga (script de prueba standalone, sin la
    GUI completa). La UI ahora también muestra la precisión lograda ("Ubicación fijada
    (precisión: ±N m)") en vez de solo fijar el punto a ciegas -- en un equipo sin
    WiFi/GPS puede caer a resolución por IP (decenas de km, mismo orden de magnitud que
    cualquier otro método sin hardware dedicado, no es un bug). `_MapaPage` perdió el
    canal `mapaclick://geoerror` y el permiso de Geolocation del navegador (ya no los
    usa nadie -- todo el flujo de "Mi ubicación" es Python nativo ahora, no JS).
  - **Diálogos de Ruta/Cliente agrandados** (pedido del usuario, más espacio para
    marcar la geolocalización con precisión): `RutaFormDialog` 460×680 → 620×780 (mapa
    mín. 230→340px alto); `ClienteFormDialog` 860×740 → 920×800 (mapa mín.
    380×230→440×300).

## 9. Pendiente / próximos pasos sugeridos

- ~~UI: faltan módulos de servicio sin pantalla propia~~ — resuelto. Todos los módulos
  tienen pantalla propia hoy: login, clientes, inventario, facturación, vendedores,
  config. de empresa, dashboard, usuarios (2026-08-27, ver sección 7 "UI de Usuarios +
  Roles/Permisos"), control de tasas (2026-08-27: `app/ui/tasas_panel.py` +
  `app/ui/tasa_registro_dialog.py` — tasa vigente con delta vs. ayer, alta de una tasa
  nueva y el histórico exportable con selector de rango de días; sin edición/eliminación
  porque `TasaService` no las tiene, cada registro es un snapshot histórico inmutable),
  proveedores (`proveedores_panel.py`, 2026-08-28), compras (`compras.py`/`ComprasView`,
  2026-08-28), bancos (`bancos_panel.py`, 2026-08-29), cuentas bancarias
  (`cuentas_bancarias_panel.py`, 2026-08-29), cajas incluido el cierre de turno
  (`cajas_panel.py`/`caja_cierre_dialog.py`, 2026-08-31 — el diferimiento a propósito que
  decía esta sección quedó obsoleto ese día), comisiones (`ComisionesPanel` con modo
  gestión para admin/cajero y modo "Mis Comisiones" de solo lectura para el vendedor), y
  cuentas por pagar/cuentas por cobrar (resuelto 2026-08-28: `CuentasPorPagarPanel`/
  `CuentasPorCobrarPanel`, ambos con filtro de estado —incluida "Vencida", derivada en el
  momento porque ninguna trigger persiste ese estado— y diálogo de pago/cobro contra
  `PagoService`; `PagoService.listar_cuentas_por_cobrar()` es nuevo, simétrico a
  `listar_cuentas_por_pagar()`).
- ~~RBAC modelado pero no aplicado~~ — resuelto (2026-08-22), ver sección 7. ~~Sigue
  pendiente extenderlo a operaciones de lectura~~ — también resuelto (2026-08-22, misma
  sección).
- ~~Deletes sin guarda de integridad (clientes, proveedores, vendedores, inventario,
  bancos/cuentas bancarias)~~ — resuelto (2026-08-22): en vez de agregar una guarda de
  conteo, se decidió que estas 5 entidades nunca se borran físicamente. Ver sección 8.
- ~~Reversión de pagos ya aplicados a una cuenta por cobrar/pagar~~ — resuelto
  (2026-08-22) con nota de crédito automática. Ver "Notas de credito automaticas" en la
  sección 3. ~~Reversión de comisiones~~ — resuelto (2026-08-23), ver "Comisiones de
  vendedor" más abajo.
- Notas de crédito (`notas_credito.py`): ~~sin correlativo fiscal~~ — resuelto
  (2026-08-22), ver sección 3. ~~Sigue faltando el flujo para consumirlas~~ — resuelto
  del lado cliente (2026-08-27): `aplicar_nota_credito_cliente()` (abono a otra factura
  del mismo cliente, transferencia contable interna, sin autorización) y
  `devolver_nota_credito_cliente()` (egreso real de efectivo/banco, fechado hoy —
  no retroactivo — con autorización de supervisor SIEMPRE obligatoria vía el permiso
  dedicado `'notas_credito'/'editar'`, distinto de `'notas_credito'/'crear'` que ya
  tiene cualquiera que pueda iniciar la operación; reusa
  `CajaService`/`BancoService._registrar_egreso_vuelto()` tal cual, mismo mecanismo que
  el vuelto de facturación). UI: `HistorialClienteWindow` gana los botones "Aplicar
  Nota de Crédito"/"Devolver Nota de Crédito" (`aplicar_nota_credito_dialog.py`/
  `devolver_nota_credito_dialog.py`) y un indicador de saldo disponible. El lado
  proveedor (`NotaCreditoProveedor`) sigue sin flujo de consumo — desarrollo aparte,
  pendiente si el negocio lo necesita.

  UX de seguimiento (2026-08-27): el proceso contable de 2 pasos (anular = reversión
  fiscal del documento, devolver = operación de tesorería aparte con su propia
  autorización) es el estándar del sector (SAP B1, QuickBooks, Odoo) y no se
  simplifica — pero antes obligaba a navegar a otro módulo (Clientes > Historial)
  para completar el segundo paso, sin ningún aviso de que hacía falta.
  `FacturacionPanel.anular_factura_seleccionada()` ahora ofrece un seguimiento
  inmediato: si la anulación generó una nota de crédito con saldo disponible,
  pregunta "¿Deseas devolver el dinero al cliente ahora?" y abre
  `DevolverNotaCreditoDialog` ahí mismo si se confirma. `FacturaDetalleDialog`
  también gana un atajo simétrico ("Devolver esta nota") cuando la factura que se
  está viendo generó una nota con saldo disponible — sin este dato ya persistido
  (`VentaService.obtener_factura()` ahora expone `nota_credito` en su dict de
  retorno), había que ir a buscarla al historial del cliente sin ninguna pista de
  que existía. Ninguno de los dos ahorra el paso de autorización — solo evitan la
  navegación innecesaria.
- ~~Riesgo de *clock skew*~~ — resuelto (2026-08-23). `registrar_pago_cobro()`/
  `registrar_pago_proveedor()` (`app/services/pagos.py`) ahora fijan `fecha_pago =
  datetime.now()` en Python cuando no se recibe explícito, en vez de dejar que
  `trg_pagos_cobros_io`/`trg_pagos_proveedores_io` usen `ISNULL(fecha_pago, GETDATE())`
  (reloj del SQL Server). Con esto todo el flujo de caja — `CajaService.abrir_caja()`/
  `cerrar_caja()` y los pagos — queda en el mismo reloj (el de la app), eliminando el
  desfase que `trg_cajas_cierre` podía usar mal al sumar `saldo_cierre`. Sin cambios de
  schema/trigger. Detectado 2026-08-22 escribiendo
  `tests/services/test_pagos.py::test_borrar_pago_cobro_con_turno_de_caja_ya_cerrado_recalcula_saldo_cierre`.
- ~~Sin migraciones formales del schema~~ — resuelto (2026-08-22). Ver nota al final de
  la sección 3.
- ~~Flujo de "vuelto" en pagos de contado~~ — resuelto (2026-08-26,
  `migrations/0027_vuelto_factura.sql`). Ver "Vuelto" en la sección 3 para el detalle
  completo: efectivo libre con validación de saldo de caja real; pago móvil/transferencia
  con referencia bancaria obligatoria + autorización de supervisor (permiso dedicado
  `'vueltos_bancarios'/'crear'`, reusa `AutorizacionDialog` existente); egreso real
  (`CajaMovimiento`/`BancoMovimiento`) en la misma transacción atómica de la factura.
  Pendiente aparte, no incluido en ese desarrollo: reflejar el vuelto en el PDF de la
  factura/recibo impreso -- resuelto mas abajo, ver "Auditoría integral de Facturación
  2026-08-26".
- **Auditoría integral de Facturación 2026-08-26** (posterior al desarrollo de vuelto):
  hallazgos Crítico (2), Alto (4) y Medio (2) -- todos resueltos el mismo día salvo uno
  diferido a propósito:
  - **[Crítico] `anular_factura`/`anular_compra` no eran atómicas con su nota de
    crédito compensatoria**: cada una comiteaba en una transacción separada de
    `NotaCreditoService.crear_nota_credito_cliente`/`crear_nota_credito_proveedor` --
    si esa segunda inserción fallaba, la anulación ya había quedado comprometida sin
    su compensación (el dinero que el cliente ya pagó desaparecía contablemente sin
    dejar rastro ni forma de revertir). Se agregaron núcleos internos sin commit propio
    (`_crear_nota_credito_cliente`/`_crear_nota_credito_proveedor`,
    `app/services/notas_credito.py`) y ambas anulaciones ahora crean la nota ANTES de
    su único `commit()`. De paso, la generación de `numero_nota_credito` (que leía
    `MAX(id)+1` sin lock, vulnerable a la misma carrera que ya se había corregido para
    `numero_factura`) pasó a usar el mismo patrón placeholder+flush+rename que
    `VentaService._numero_factura_temporal()`.
  - **[Crítico] Vuelto y pagos mixtos invisibles/incorrectos en toda la UI de
    consulta**: `listar_facturas()`/`obtener_factura()` (`ventas.py`) y
    `obtener_historial_cliente()` (`historial_cliente.py`) usaban un `dict`/`.first()`
    que se quedaba con UNA sola línea de pago arbitraria cuando había más de una (pago
    mixto, ver `PagoLineaDialog`) -- ahora agrupan todas las líneas y devuelven un
    sentinel `"mixto"` cuando el método difiere entre ellas, que la UI traduce en vez
    de mostrar crudo. `factura_detalle_dialog.py` ganó una tarjeta "Formas de pago" con
    el desglose línea por línea y el vuelto (monto/método/referencia/autorizador), que
    hasta entonces estaba persistido pero no se mostraba en ningún lado de la app.
  - **[Alto] `factura_pdf.py` no imprimía método de pago ni vuelto**: agregados a la
    caja de datos de la factura (del vuelto solo monto+método -- la referencia
    bancaria y quién autorizó quedan como información de auditoría interna, mismo
    criterio ya usado para el motivo/autorizador de un descuento).
  - **[Alto] `HistorialClienteWindow` fallaba en silencio**: un error de conexión al
    cargar el historial se veía igual que "cliente sin historial" (tabla vacía, sin
    ningún aviso). Ahora usa `QMessageBox.critical`, mismo patrón que
    `facturacion_panel.py`.
  - **[Alto] Sin UI para cerrar un turno de caja -- diferido a propósito (decisión del
    usuario, 2026-08-26)**: en ese momento `CajaService.cerrar_caja()` existía pero
    funcionaba solo vía `PlaceholderView`, sin pantalla propia. ~~Resuelto 2026-08-31~~:
    ver "Cajas" en la lista de módulos UI más abajo en esta sección --
    `cajas_panel.py`/`caja_cierre_dialog.py` cubren listado de movimientos del turno,
    cuadre y cierre.
  - **[Medio] Faltaba lock `WITH (UPDLOCK, ROWLOCK)` sobre `ComisionFactura` en
    `anular_factura`**: agregado, mismo patrón que
    `PagoComisionService.pagar_comisiones_vendedor` -- sin esto, un pago de comisiones
    concurrente podía marcar una fila 'pagada' justo después de que la anulación la
    leyera como 'pendiente' pero antes de borrarla, rompiendo la trazabilidad entre
    `PagoComision.monto` y las líneas que lo componen.
  - **[Medio] `FacturaDetalleDialog` no desglosaba Subtotal/Descuento/IVA**: agregada
    una línea de resumen sobre el total (mismo criterio que
    `factura_pdf.py::_filas_totales`) -- antes había que exportar a PDF para verlo.
  - El vuelto también se agregó a `HistorialClienteWindow` (columna "Vuelto" +
    exportación) -- mismo fix que el hallazgo de vuelto invisible, aplicado a esa
    tercera superficie de UI.
- **Auditoría del módulo de Facturación 2026-08-25**: hallazgos Crítico/Alto (IVA no
  reflejado en el total de "Nueva Factura", condición de carrera en el límite de crédito,
  pérdida de datos si `emitir_factura` falla) y la mayoría de los Medio/Bajo (caja
  re-solicitada en cada entrada, sin validación proactiva de stock, filtro de cliente sin
  límite, sin feedback visual durante la emisión, comentario desactualizado,
  `consultar_limite_disponible` sin reflejar elegibilidad de crédito, columna Vendedor en
  el listado, cobertura de tests) — todos resueltos el mismo día. Quedaron dos hallazgos
  Bajo deliberadamente sin aplicar, por desproporcionados frente al resto del batch:
  - **Filtro de facturas por rango de fechas**: `VentaService.listar_facturas()` ya acepta
    `fecha_desde`/`fecha_hasta`, pero exponerlo en la UI (`BotonFiltros`) requeriría
    extender `toolbar_popups.py` para soportar `QDateEdit` (hoy solo maneja
    `QComboBox`/`QCheckBox` para detectar "filtros activos" y limpiarlos) — un cambio de
    arquitectura del componente compartido, no un ajuste puntual de este módulo.
  - **Editar una línea del carrito/formas de pago en "Nueva Factura"**: hoy solo se puede
    agregar/quitar, en ambas tablas — es el mismo patrón en toda la app (`clientes_panel`,
    `inventario_panel`, etc.), no algo específico de facturación; cambiarlo ahí sin
    tocarlo en el resto dejaría la app inconsistente.
  - Tampoco se tocó el hallazgo Bajo de reordenar/acortar la duración de los locks de
    stock (`WITH (UPDLOCK, ROWLOCK)` se piden antes de validar descuento/tasa/pagos): el
    riesgo de introducir un problema de orden de locks (ahora hay dos: `Inventario` para
    stock y `Cliente` para el límite de crédito) superaba el beneficio marginal frente al
    resto de los cambios de esta auditoría.
- **Segunda auditoría del módulo de Facturación 2026-08-25 (N1/N2)**: sin regresiones
  sobre la auditoría anterior. Dos hallazgos nuevos, ambos resueltos el mismo día:
  - **N1 (Alto) — `estado_factura` binario vs. filtro/badge de 5 estados en la UI**:
    `factura_venta.estado_factura` solo vale `EMITIDA`/`ANULADA` en toda la base de
    código, pero `FacturacionPanel` ofrecía un filtro con `PAGADA`/`PARCIAL`/`VENCIDA`
    que nunca podía coincidir con nada (0 filas siempre), y los badges de color para esos
    tres estados nunca se usaban. Se agregó `VentaService._calcular_estado_visual()`
    (`app/services/ventas.py`), que deriva el estado real desde `CuentaPorCobrar` con el
    mismo criterio ya usado en `DashboardService.CUENTA_ABIERTA`/`historial_cliente.py`/
    `reportes.py` (pendiente/parcial + `fecha_vencimiento` pasada = vencida — nunca se
    persiste como tal, el `CHECK` la admite pero ningún trigger la asigna).
    `listar_facturas()`/`obtener_factura()` adjuntan el resultado como atributo Python
    `estado_visual` en cada `FacturaVenta` (no mapeado, calculado en un solo batch por
    página para evitar N+1); `listar_facturas()` también traduce el filtro `estado` a un
    subquery contra `cuentas_por_cobrar` en vez de comparar directo contra la columna. La
    UI (`facturacion_panel.py`, `factura_detalle_dialog.py`) ahora lee `estado_visual` en
    vez de `estado_factura` crudo. `factura_pdf.py` no se tocó — ahí la comparación contra
    `"ANULADA"` (para la marca de agua) es un chequeo binario legítimo.
  - **N2 (Medio) — deadlock potencial en el lock de stock**: el `WITH (UPDLOCK, ROWLOCK)`
    de disponibilidad se adquiría iterando `cantidades_por_producto.items()` en el orden
    de aparición en el carrito (decidido por el usuario), sin normalizar por
    `id_producto` — dos facturas concurrentes con los mismos productos en carritos
    armados en distinto orden podían adquirir los locks en orden cruzado y producir un
    deadlock de SQL Server. Fix de una línea: `sorted(cantidades_por_producto.items())`
    antes del loop (`app/services/ventas.py`), mismo orden total para cualquier
    transacción.
  - **N3 (cobertura, Medio) — sin test de concurrencia real**: todo el código defensivo
    `WITH (UPDLOCK, ROWLOCK)` (stock, límite de crédito, comisiones) estaba validado solo
    por lectura, nunca ejercitado con dos conexiones reales compitiendo. Se agregó
    `test_emitir_factura_bloquea_stock_con_updlock_rowlock_concurrente`
    (`tests/services/test_ventas.py`): abre una segunda `Session` real sobre
    `test_engine` (no se puede compartir `db_session` entre threads), sostiene el lock
    manualmente sobre la fila de `Inventario` y comprueba con un `threading.Thread` que
    `emitir_factura()` sobre el MISMO producto se queda bloqueada esperando (assert
    `hilo.is_alive()` con `timeout=1.5`) hasta que la primera transacción libera el lock
    — no es un test de timing/probabilístico, verifica el bloqueo real de SQL Server.
  - **N4 (cobertura, Bajo) — sin test del gate `pagos/crear` en contado**: se agregó
    `test_emitir_factura_contado_sin_permiso_pagos_falla`: un usuario con `ventas/crear`
    pero sin `pagos/crear` no puede facturar de contado (`ventas.py`, `if pagos:
    require_permiso(...)`), aunque sí podría de crédito.
- **CI ya corría pytest automáticamente (N5 lo confirma)**: `.github/workflows/tests.yml`
  ya disparaba la suite completa en cada push a `main` y cada pull request desde
  "Resuelve C1-C10 del checklist de producción" — no había nada que arreglar en el
  workflow en sí. Lo que estaba roto era la nota más abajo en este mismo documento
  ("Pendiente: correr la suite en CI... hoy es manual"), escrita antes de que el workflow
  existiera y nunca actualizada después. Corregida.
- Cobertura de pruebas automatizadas: hecha para los 18 módulos de servicio más el
  runner de migraciones. Hay un harness de pytest (`tests/`) contra una base de datos
  SQL Server de prueba dedicada (real, no mock — necesario para validar los triggers),
  con 557 tests (2026-08-25). Ver `tests/conftest.py` para la estrategia de aislamiento entre tests
  (limpieza por `DELETE` en orden trigger-safe, no rollback, porque los servicios hacen
  su propio `commit()`) y `tests/factories.py` para los helpers de datos base.
  `tests/test_migrar.py` corre contra la base de datos de test real (no una copia
  aislada) para probar el bootstrap de `dbo.schema_migrations`; tiene un fixture
  (`_preservar_schema_migrations_real`, agregado 2026-08-22 tras encontrar el bug) que
  respalda y restaura esa tabla para no borrar el registro de migraciones ya aplicadas.
  CI (`.github/workflows/tests.yml`, agregado en "Resuelve C1-C10 del checklist de
  produccion") ya corre la suite automaticamente en cada push a `main` y en cada pull
  request, contra un contenedor `sqlserver` efimero del propio workflow (con health
  check antes de instalar el driver ODBC 18 y correr `pytest -q`) -- no requiere Docker
  ni nada manual del lado del desarrollador. Nota corregida en la auditoria de
  facturacion 2026-08-25 (N5): esta linea decia "Pendiente: correr la suite en CI (hoy es
  manual...)" desde antes de que el workflow existiera, y quedo asi sin actualizar
  despues de agregarlo.
- **Auditoria de Vendedores y Clientes 2026-08-27** (evaluando si ambos modulos estaban
  listos para seguir avanzando): Clientes ya estaba listo (requeridos + unicidad
  validados en servicio y reforzados con `UNIQUE` real en BD, delete fisico bloqueado,
  RBAC completo, UI paginada con filtros). Vendedores tenia varios huecos frente a ese
  mismo estandar, todos resueltos el mismo dia:
  - **`codigo_vendedor`/`identificacion_vendedor` sin proteccion de unicidad**, a
    diferencia de los mismos campos en Cliente -- se podian crear vendedores duplicados
    con el mismo codigo interno o cedula. `migrations/0031_unique_vendedor_codigo_identificacion.sql`
    agrega la proteccion con un indice unico FILTRADO (`CREATE UNIQUE INDEX ... WHERE
    campo IS NOT NULL`, no un `UNIQUE CONSTRAINT` normal) -- en su momento (2026-08-27)
    ambos campos eran legitimamente opcionales en Vendedor, a diferencia de Cliente/
    Proveedor, y SQL Server (a diferencia de Postgres/el estandar ANSI) trata todos los
    NULL como el mismo valor dentro de un `UNIQUE` normal, permitiendo maximo una fila
    con NULL. **Decision revertida (2026-09-01, pedido del usuario)**: `codigo_vendedor`/
    `identificacion_vendedor` pasaron a ser obligatorios, igual que en Cliente/Proveedor
    (`VendedorService.crear()`/`actualizar()` los exigen no vacios, `vendedor_form_dialog.py`
    los marca con asterisco). El indice unico filtrado de la migracion 0031 sigue vigente
    sin cambios de schema -- ya no se esperan NULLs en la practica, pero el filtro
    `WHERE campo IS NOT NULL` sigue siendo valido igual que el `UNIQUE` plano de Cliente/
    Proveedor es valido porque el servicio (no la base) es quien garantiza el no-vacio.
  - **`VendedorService.crear()`/`actualizar()` no validaban nada** (ni `nombre_vendedor`
    requerido pese a ser `NOT NULL` en BD, ni duplicados) -- ahora siguen el mismo patron
    `_validar_unico()`/requerido que `clientes.py`, incluidos `codigo_vendedor`/
    `identificacion_vendedor` desde 2026-09-01 (ver parrafo anterior).
  - **`VendedorService.listar()` no paginaba** (D-01) y **`VendedoresPanel` no tenia
    filtro de estado** -- ambos igualados a `ClienteService.list_clientes()`/
    `ClientesPanel`. Los 3 callers de `VendedorService.listar()` que dependian del
    `list[Vendedor]` plano (`VendedoresPanel`, el selector de vendedor de
    `FacturaFormDialog`, el combo de vendedor vinculado de `UsuarioFormDialog`) se
    actualizaron a leer `resultado["items"]` con `estado_vendedor="ACTIVO"` y un
    `por_pagina` alto (esos dos ultimos son selectores que necesitan TODOS los activos,
    no una pagina).
  - Tests nuevos para cada hallazgo (`tests/services/test_vendedores.py`) + el hueco
    menor que tenia Clientes (`update_cliente` nunca se probaba re-validando duplicado al
    cambiar codigo/identificacion, solo el camino de `create_cliente`) cerrado en
    `tests/services/test_clientes.py`.

- **Requerimientos nuevos del cliente (2026-09-01)** -- lista entregada para evaluar,
  auditada contra el codigo actual. Dos necesitaban una decision de negocio del equipo
  antes de poder disenarlos (no eran huecos tecnicos, era ambiguedad de alcance);
  decision recibida el 2026-09-03:
  - **"Activacion por categorias por ruta"**: resuelto como reporte (2026-09-03,
    `ReporteService.activacion_clientes()` en `reportes.py` + pantalla en
    `reportes_panel.py`, "Activación de Clientes"). Historia completa de la definicion:
    la version original de "cliente activo" (compro al menos la unidad minima de venta
    del sistema en el periodo) requeria un campo que no existe en `Inventario` (hay que
    agregarlo -- ver mas abajo), asi que el equipo decidio una v1 mas simple para no
    bloquear el reporte en eso ("vamos con v1 simple, si hace falta luego le agregamos lo
    que haga falta"): activacion = cantidad de facturas del cliente en el rango
    (cualquier factura cuenta, sin filtrar por tamaño de compra), comparada contra la
    **cuota de activacion de su vendedor asignado** -- decision de negocio (2026-09-03):
    la meta se define por **vendedor**, no por cliente/ruta/categoria (`Vendedor.
    meta_activacion`, `migrations/0042_vendedor_meta_activacion.sql`, configurable desde
    `VendedorFormDialog` -- "Meta de Activación (ventas/mes por cliente)", opcional,
    `VendedorService._validar_meta_activacion()` exige positivo si se define). Por cada
    cliente el reporte calcula `efectividad_pct` = facturas del cliente / meta de su
    vendedor * 100 (None si el vendedor no tiene meta configurada -- sin eso no hay
    contra que comparar), filtrable por vendedor, con resumen de clientes
    activos/totales y efectividad promedio. Tests en `test_reportes.py`
    (`test_activacion_clientes_*`) y `test_vendedores.py` (`test_*_meta_activacion*`).
    Pendiente si el negocio lo pide despues: refinar el conteo para exigir la unidad
    minima de venta por factura en vez de contar cualquier factura -- esa unidad NO
    existe hoy como campo (confirmado revisando `producto_form_dialog.py`/`Inventario`
    en `models.py`: `cantidad_caja`/`cantidad_unidad` son cantidades de stock, no una
    unidad de venta configurable) y quedaria sin definir si es fija por producto (ej. 1
    caja, 1 unidad suelta) o variable segun como se factura cada uno.
  - **"Asignacion de cuotas y entrega de ejecucion en curso y cierre graficado o
    porcentual"**: el mas grande de la lista (grep de "cuota"/"meta"/"objetivo"/"target"
    no da ningun hit real de metas de venta). Decision de negocio (2026-09-03): la cuota
    se carga a nivel de **Ruta** (no por vendedor individual); el sistema extrae los
    resultados de ejecucion real (los datos de facturacion por ruta/periodo ya existen,
    ver `ReportesService.ventas_por_ruta`) y esos resultados se expresan en un reporte
    -- "en curso" (avance dentro del periodo) y "final" (cierre del periodo) -- al que
    el negocio llama **"termometro de ventas"**. Preguntas que siguen abiertas antes de
    disenarlo: ¿en que unidad se mide la cuota (dolares facturados, unidades, clientes
    activos/efectividad del punto anterior)? ¿cada cuanto se asigna (mensual/quincenal/
    semanal)? ¿quien carga el numero de la cuota y como (carga manual por periodo, o
    formula ej. % de crecimiento vs mismo periodo anterior)? ¿el "termometro" es una
    pantalla/reporte dentro de la app (gauge o barra de progreso) o solo el dato crudo
    que el equipo comercial formatea aparte?

  Los otros cuatro puntos de la lista ya estan tecnicamente claros, sin nada que definir
  con el equipo:
  - **"Dolares totales facturados por ruta"**: resuelto (2026-09-02) --
    `ReportesService.ventas_por_ruta` (`reportes.py`), mismo reporte que
    `ventas_por_vendedor` agrupado por `Vendedor.id_ruta` (factura sin vendedor/ruta cae
    en el grupo "Sin ruta" en vez de perderse); expuesto en `reportes_panel.py`.
  - **"Drop site de facturacion"**: resuelto (2026-09-02) -- el cliente aclaro que no es
    un punto de entrega/logistica sino un KPI: **ticket promedio** (total facturado en $
    dividido entre la cantidad de facturas). Definicion final:
    - Desglosado por ruta y por vendedor (no un unico numero global) -- mismo patron de
      agrupacion que "Dolares totales facturados por ruta" arriba, extendiendo
      `ReportesService.ventas_por_vendedor` (agregar `total / cantidad_facturas` como
      columna, agrupado tambien por `Vendedor.id_ruta`).
    - Sobre un rango de fechas seleccionable por el usuario, igual que el resto de los
      reportes (`aging_cuentas_por_cobrar`, `ventas_por_vendedor`).
    - Excluye facturas `ANULADA`, mismo criterio que `DashboardService._total_ventas_del_dia`
      y el resto de los KPIs de ventas del sistema.
  - **"Facturacion vs rentabilidad"**: ya existe a nivel de producto
    (`ReportesService.margen_utilidad_productos`, compara ingreso vs costo por producto
    en un rango de fechas, ordenado por margen). Extenderlo a ruta/vendedor es el mismo
    patron de agrupacion que el punto anterior.
  - **"Analisis de vencimiento" (saldo a favor + dias por factura + numero de
    factura/nota + emision de notas de credito)**: ya existe casi todo, repartido en dos
    reportes separados -- `ReporteService.aging_cuentas_por_cobrar` (dias vencidos y
    numero de factura por fila) y `ReporteService.notas_credito_emitidas`
    (`saldo_disponible` y numero de nota, correlativo fiscal); la emision de notas de
    credito ya es automatica al anular una factura con pagos aplicados (ver
    `NotaCreditoService` en la seccion 3/"Notas de credito automaticas"). Falta unificar
    ambos reportes en una sola vista por cliente en vez de mirarlos por separado.
  - **"Mapeo de ruta / geolocalizacion de cliente"**: completo (2026-09-01, ver
    `app/ui/mapa_rutas_panel.py`, `app/ui/ruta_form_dialog.py`, `migrations/0038`-`0040`)
    -- clientes geolocalizados pintados junto con su ruta, busqueda de cliente que centra
    el mapa, toggle "Mostrar clientes". El modelo de ruta en si (originalmente origen ->
    destino con trazado real por calles via OSRM) fue reemplazado 2026-09-03 por una zona
    de cobertura (poligono de vertices, `migrations/0043`) -- ver "Zona de cobertura de
    ruta reemplaza origen/destino/trazado" mas arriba en esta seccion.

- **Reporte "Productos Proximos a Vencer"** (2026-09-07, `ReporteService.productos_proximos_a_vencer()`
  en `reportes.py`): filtra `Inventario` por `fecha_vencimiento` dentro de una ventana
  configurable (`dias_horizonte`, default 30) y categoria opcional, devuelve dias
  restantes por fila. UI en `reportes_panel.py` (nuevo tipo de reporte, filtros de dias
  horizonte + categoria, export incluido).
- **Auditoria del modulo de reportes y su exportacion** (2026-11-07, `reportes.py`, `reportes_panel.py`,
  `exportacion.py`). Decisiones que no se deducen del codigo:
  - **Aging / morosos con corte pasado** (`_cuentas_al_corte`): el saldo de una cuenta es el de hoy, asi
    que para un corte anterior se reconstruye sumando los pagos (`pagos_cobros`, `pagos_cobros_bcv`,
    `pagos_proveedores`) y las notas de credito aplicadas posteriores al corte, y solo entran facturas
    emitidas hasta esa fecha. Las aplicaciones de nota de credito no tienen tabla propia: se leen de
    `Auditoria` (`APLICACION_NOTA_CREDITO_CLIENTE`). Cuentas con saldo 0 no se listan (la cuenta normal de
    una factura BCV queda en 0 por diseno).
  - **BCV** entra en estado de cuenta del cliente, cobros del periodo (columna `cartera`) y clientes
    morosos. El cargo de una factura BCV va por su cuenta BCV, no por la normal.
  - **Kardex**: `saldo_apertura` = stock actual - suma de todos los movimientos reconstruidos (carga inicial
    y ajustes manuales, que no dejan movimiento). Hace que el saldo final cuadre con el inventario.
  - **Facturas anuladas** se filtra por fecha de ANULACION (evento de auditoria), no de emision.
  - **Libro de Ventas**: lista las anuladas (montos en 0, fuera de totales), separa exento de base
    imponible, y agrega tasa BCV de la factura y total en Bs. Las notas de credito NO restan del IVA: las
    unicas que existen nacen de anular una factura (que ya cuenta en 0) o de un sobreabono (no es una venta).
  - **Exportacion**: Excel lleva periodo/filtros/totales (`filtros=`) y anchos ajustados; ambos aceptan
    `secciones=` (tablas extra, p.ej. NC del Libro de Ventas); el PDF acepta `apaisado=` y siempre iguala
    columnas/encabezados/anchos para que una tabla no se desborde de la hoja. Los filtros impresos son los
    de los combos al momento de generar (`_combos_snapshot`), no los actuales.
  - **Bultos y unidades en los reportes de venta** (2026-11-08). `costo_producto` es el costo de UNA unidad
    (decision del usuario). Valorizacion ya multiplicaba por `cantidad_unidad` (correcta); el Margen de
    utilidad ahora pasa las lineas `tipo_venta='bulto'` a unidades con `cantidad_caja` antes de multiplicar el
    costo. "Productos mas vendidos", "Margen de utilidad" y "Ventas a clientes por producto" ya no suman bultos
    con unidades: llevan columnas `bultos` y `unidades` separadas (pantalla, Excel/CSV y PDF); las lineas viejas
    sin `tipo_venta` cuentan como unidades. Compras y Kardex no se tocan: las compras entran siempre en unidades.
- **Exportar un listado paginado lleva TODAS las filas** (2026-11-08). Cuentas por Cobrar, Cuentas por Pagar y las
  tres pestanas de Compras (ODC, recepciones, facturas) exportaban lo que decia la tabla: solo la pagina visible
  (20 filas). Ahora `app/ui/exportacion_completa.py` (`ExportacionCompletaMixin`) lanza un `QueryWorker` que vuelve
  a pedir el listado con los mismos filtros y `por_pagina=POR_PAGINA_EXPORTACION` y escribe el archivo; cada panel
  aporta una tarea y una funcion de filas (`filas_exportacion_*`) cuyas celdas son las de la tabla (hay tests que
  lo comparan). Regla: un export NUNCA lee `QTableWidget`; si agregas un listado paginado, exporta con una tarea.
  Los demas exports (clientes, inventario, facturas, proveedores, vendedores, cuentas bancarias, BCV, historial,
  tasas) ya pedian todo; los reportes no paginan.
- **Revision de consultas** (2026-11-08):
  - `consultar_permiso()` (`services/permisos.py`): usuario + rol + permiso en UNA consulta (antes 3). Lo usan
    `require_permiso`, `UsuarioService.verificar_permiso` y `es_admin_en_sesion`: corre en cada accion de la app,
    asi que con la base en otra red eran 2 esperas de red de menos cada vez. El orden y el texto de los errores
    no cambian.
  - Migracion `0099`: indices compuestos `(id_cuenta, fecha_movimiento DESC)` en `banco_movimientos`,
    `(id_caja, fecha_registro DESC)` en `caja_movimientos` y `(id_cliente_factura, fecha_emision DESC)` en
    `factura_venta` (reemplazan a los de una sola columna, que quedaban cubiertos) mas los de las claves foraneas
    que alguna consulta usa (`*_detalle.id_producto` del kardex, `id_factura_origen`/`id_compra_origen` de las
    notas de credito, `clientes.id_categoria_cliente`, `cuentas_bancarias.id_banco`, `vendedores.id_ruta`). NO se
    indexaron `creado_por`/`modificado_por` ni las claves de las tablas de pagos: ninguna consulta filtra por
    ellas y cada indice encarece las escrituras. Para revisar de nuevo: claves foraneas sin indice =
    `sys.foreign_keys` sin `sys.index_columns` (key_ordinal = 1), y `sys.dm_db_missing_index_details` en una base
    con carga real.
  - `listar_cuentas_por_cobrar_por_cliente`: sin filtro de estado ya no trae las cuentas pagadas sin saldo a favor
    (la mayor parte del historial) y trae factura y cliente en la misma consulta (`contains_eager`): antes era
    una consulta extra por cuenta.
  - **Estandar de reportes: lo que AGRUPA se suma en SQL (`GROUP BY`), no en Python.** Ya lo hacen: ventas por
    periodo / cliente / vendedor / ruta, contado vs credito, productos mas vendidos, margen de utilidad, ventas a
    clientes por producto, compras por periodo / proveedor / producto, cumplimiento de proveedores, flujo de caja
    consolidado, conciliacion bancaria y las dos de comisiones. Los reportes que son un LISTADO (libro de ventas,
    anuladas, estados de cuenta, kardex, cobros/pagos del periodo, aging, morosos) arman una fila por documento
    porque esa es su salida; ahi solo se vigila que no haya consultas por fila (`joinedload`/una consulta previa).
    `_periodo_sql()` agrupa por dia o mes; `_TOTAL_FACTURA_SQL` es subtotal - descuento + IVA.
  - `obtener_historial_cliente`: la cuenta por cobrar de cada factura se trae en UNA consulta (antes una por
    factura: un cliente con 3 000 facturas tardaba 4,6 s; ahora ~0,2 s). Hay un test que cuenta consultas.
  - Lecturas pasadas a un hilo aparte: lista de roles y matriz de permisos, y la apertura del detalle de factura
    (Facturacion, Historial del cliente, Comisiones; `tarea_cargar_factura` en `factura_detalle_dialog.py`; la
    guarda `_abriendo_dialogo` se suelta siempre porque la tarea devuelve el error como dato).
  - PDF de reportes: pasado `LIMITE_FILAS_PDF` (20 000) el panel avisa y pide Excel o un rango menor (un PDF
    tarda ~1,5 ms por fila). El Libro de Ventas de 2 anios (120 000 filas) no es un uso normal: el servicio
    tarda 9 s y el Excel 23 s; por mes (~5 000 facturas) son 0,4 s y 0,9 s, y el PDF 7,6 s.
  - Barras de busqueda (30 000 clientes, 15 000 productos, 120 000 facturas; la consulta de cada busqueda, que
    corre en un hilo aparte tras 300 ms de pausa): Clientes 27-45 ms, Inventario 11-23 ms, Facturacion 36-48 ms,
    Cuentas por cobrar con texto 40 ms (antes 319: el nombre se filtraba en Python DESPUES de agrupar; ahora en
    SQL antes de agrupar), busqueda global 100-260 ms (recorre varias tablas).
  - Consumo de la app (MainWindow real con ventanas, 19 modulos abiertos, base de 120 000 facturas): 65 MB Python +
    Qt, 164 MB tras importar todo, ~400-440 MB con todos los modulos abiertos; CPU en reposo ~1 % de un nucleo;
    sin fuga (5 recorridos completos: 438-445 MB estables, hilos y handles constantes); 3 conexiones a la base.
    Combos de Reportes: `_ModeloLista` (lista (id, texto) sin un objeto por elemento) en vez de
    `QStandardItemModel`: +74 MB en vez de +109 MB al abrir el modulo. Los tres limites que
    quedaban (abrir Reportes congelaba ~1,3-2,7 s; los refrescos periodicos de Facturacion/Inventario/Compras eran
    sincronos y dejaban huecos de hasta ~0,5 s cada 30 s; un listado de 100 000+ filas tardaba ~4-8 s en llenar la
    tabla) se resolvieron el 2026-11-08, ver "Limites de rendimiento resueltos" mas abajo.
  - Medido con 120 000 facturas / 300 000 lineas / 36 000 cuentas por cobrar (antes -> ahora): Cuentas por Cobrar
    62,5 s -> 0,3 s; productos mas vendidos (2 anios) 8,7 s -> 0,08 s; margen 9,0 s -> 0,07 s; ventas a clientes por
    producto 26,9 s -> 3,5 s. Los indices de 0099 no cambiaron los tiempos de banco/caja (70 y 16 ms): quedan por
    ser baratos, pero no fueron la ganancia.
- **Auditoria de busquedas y rendimiento** (2026-11-07). Medido contra la base de pruebas con 30k-200k filas:
  - `app/services/busqueda_sql.py` es el unico lugar que arma un LIKE (`patron_contiene` + `contiene`). `ilike`
    de SQLAlchemy genera `lower(col) LIKE lower(patron)`; con colacion `*_CI_*` (la de por defecto) `contiene`
    usa `LIKE` directo (~30 % menos tiempo, mas en columnas largas). Antes varios servicios no escapaban `%`/`_`.
  - `paginar()` pide primero la pagina y solo cuenta (`COUNT(*)`) si la pagina esta llena o vacia mas alla de la
    primera: una busqueda con pocos resultados ya no recorre la consulta dos veces.
  - `listar_facturas` con `texto_busqueda`: tres ramas unidas (numero / cliente / vendedor) y los ids se
    resuelven ANTES de pedir la pagina. Con `ORDER BY fecha_emision DESC` + el filtro dentro, SQL Server recorre
    el indice de fechas evaluando el filtro fila por fila (0.4-0.9 s con 100k facturas; ahora ~30-40 ms).
    Se intento lo mismo en la bitacora de auditoria y NO convino (empeora con mas de 1000 coincidencias): su
    costo es el escaneo del texto de `detalle`, acotado por el rango de fechas del panel (30 dias).
  - Los paneles de Clientes, Facturacion y Auditoria consultan en un `QueryWorker` con descarte de respuestas
    viejas (`_id_carga`); la busqueda mientras se escribe es `silencioso`. El refresco periodico de Facturacion
    ya no es sincrono (ver "Limites de rendimiento resueltos").
  - Auditoria de productos: paginada (50) en `AuditoriaService.consultar_auditoria_producto`, con conteos por
    accion de todo el filtro; el filtro por producto ya no mezcla el 12 con el 123.
  - Migracion 0095: indices de `factura_venta.id_vendedor`, lineas por producto, `fecha_pago` de pagos y
    `caja_movimientos.fecha_registro`, y los de `pagos_cobros_bcv` (no tenia ninguno).
  - Limite que queda: buscar texto dentro del `detalle` de la bitacora de auditoria con ~200k eventos tarda
    ~0.5-0.7 s (hay que leer ese campo largo). El rango de fechas del panel (30 dias por defecto) lo acota; el
    panel y el dialogo de auditoria de producto ya van paginados y en hilo aparte.
  - Descartado tras medir: indice cubriente sobre `clientes` (solo mejora el listado sin filtro y empeora
    algunas busquedas); el ORM ya envia VARCHAR para columnas `String`, el problema de NVARCHAR solo afecta
    SQL crudo con `text()` y parametros.
- **Carga asincrona de listados y caja por estacion** (2026-11-07):
  - `app/ui/carga_asincrona.py` (`CargaAsincronaMixin`: `cargar_async`, `buscar_con_pausa`) es el mecanismo comun:
    la consulta corre en un `QueryWorker`, la respuesta vieja se descarta por id de carga y la busqueda mientras
    se escribe es `silencioso`. `sincrono=True` sigue existiendo pero ya no lo usa ningun refresco automatico. Lo usan inventario, proveedores, vendedores, rutas, usuarios, bancos, cuentas bancarias, CxC,
    CxC BCV, CxP y las tres pestanas de compras. En `tests/ui/conftest.py` el worker se sustituye por uno
    inmediato (`WorkerInmediato`) para que `panel.cargar_x()` deje la tabla poblada; los tests del camino
    asincrono (`test_carga_asincrona.py`) usan un worker falso.
  - Antes CxC, CxC BCV y bancos "debounceaban" mal (`QTimer.singleShot` no se puede cancelar, o ni habia
    debounce): una consulta por tecla. CxP filtraba la busqueda en Python DESPUES de paginar (total y paginas
    inconsistentes); ahora `listar_cuentas_por_pagar(texto_busqueda=...)` filtra antes de paginar.
  - N+1 eliminados con `joinedload`: cuentas por pagar (compra/proveedor/OC), compras, OC, notas de recepcion,
    vendedores (ruta) y cuentas bancarias (banco). Se pintaban en el hilo de la ventana con una consulta por fila.
  - Reportes: los catalogos de los combos (8 listas completas, algunas repetidas en 7 combos) se piden en un
    worker como tuplas `(id, texto)` y los combos del mismo catalogo comparten un `QStandardItemModel`.
  - Movimientos de una cuenta bancaria: `BancoMovimientoService.listar_paginado` (50 por pagina) con los totales
    de TODA la cuenta sumados en SQL; antes traia todos los movimientos y consultaba el usuario de cada fila.
  - Cuentas bancarias: el refresco de saldos cada 30 s corre en segundo plano y solo si el panel esta visible.
  - **Caja por estacion** (`app/utils/caja_local.py`, QSettings local): `CajaAperturaDialog` guarda la caja que
    abre la estacion; el gate de Facturacion, el cobro en efectivo (`PagoLineaDialog(solo_caja_estacion=True)`)
    y el vuelto usan solo esa. Antes, con cualquier caja abierta en otra estacion, el gate no ofrecia abrir la
    propia. Compras, CxC/CxP y Comisiones siguen listando todas las cajas abiertas.
    **Al actualizar:** una estacion con el turno de caja abierto desde antes no tiene guardada su caja (el vinculo
    estacion -> caja nace al abrir turno con `CajaAperturaDialog`): al facturar le pedira abrir caja y no podra
    elegir la que ya tiene abierta. Hay que cerrar ese turno desde el panel Cajas (ADMIN) y volver a abrirlo desde
    Facturacion. No se adivina la caja por usuario porque con el mismo usuario en varias estaciones una tomaria la
    caja de otra.
  - **Cobros a clientes: una sola fuente del monto** (`app/ui/conversion_bolivares.py`, `ConversionBolivaresMixin`,
    usado por `PagoCobroDialog`, `AbonoGeneralDialog` y sus equivalentes BCV). Zelle y Binance son metodos en
    dolares: el monto en $ se escribe (precargado con la deuda) y los Bs son referencia de solo lectura; cambiar
    la tasa recalcula los Bs, nunca el $. Transferencia y punto de venta: se escribe en Bs y el $ sale de la tasa
    (solo lectura). Antes todo metodo bancario usaba el segundo modo: al elegir Zelle el $ pasaba a derivarse
    de unos Bs en 0 y de la tasa. Sin Bs el $ queda vacio (no en 0,01) y se rechaza al aplicar.
  - **Moneda de la cuenta bancaria** (migraciones 0096 y 0097; `app/services/moneda_cuentas.py`):
    - `cuentas_bancarias.moneda` es `VES`, `USD` o `COP` (CHECK en la base). Una cuenta solo recibe pagos en su
      moneda: Zelle/Binance a `USD`, un pago en pesos (`moneda='COP'`, o la tasa COP en los dialogos de cobro) a
      `COP`, el resto de los metodos bancarios a `VES`. `BancoService.validar_cuenta_para_pago` lo exige en el
      servidor (cobros, abono general, pago a proveedor, comisiones, devolucion de nota de credito y vuelto); las
      pantallas solo ofrecen las cuentas de la moneda del pago. El reembolso de nota de credito de proveedor NO
      valida (su pantalla no tiene metodo de pago).
    - 0096 deja todas las cuentas en `VES`. **0097 deduce la moneda por el historial** (`pagos_cobros`,
      `pagos_cobros_bcv`, `pagos_proveedores`, `pagos_comisiones`): si todos los pagos de la cuenta son de la misma
      moneda, la cuenta queda en ella (aviso `MONEDA_CUENTA_DEDUCIDA` en la auditoria); si hay pagos mezclados NO
      se adivina, queda en `VES` y deja `MONEDA_CUENTA_REVISAR` para que un ADMIN decida; sin pagos no cambia.
    - Cambiar la moneda de una cuenta CON movimientos: solo ADMIN y con confirmacion explicita
      (`confirmar_cambio_moneda=True`, que la pantalla manda tras mostrar `CuentaBancariaService.resumen_uso`:
      movimientos y pagos por metodo). No toca el historial, solo lo que la cuenta acepta a futuro; queda en la
      auditoria como `CAMBIAR_MONEDA_CUENTA_BANCARIA`. Sin movimientos se cambia libremente.
    - **Saldo en pesos** (migracion 0098): `cuentas_bancarias.saldo_total_banco_cop` (DECIMAL(20,2)). El monto
      "local" de cada movimiento (`banco_movimientos.monto_bolivares`, que con la tasa COP ya llevaba los pesos) va
      a `saldo_total_banco_cop` si la cuenta es COP y a `saldo_total_banco_bs` si no; `saldo_total_banco` (USD)
      sigue sumando el equivalente en dolares de cualquier cuenta. `trg_banco_movimientos_saldo` se recreo con ese
      enrutado por `cuentas_bancarias.moneda`. Un cobro en pesos (`moneda='COP'`) sin `monto_bolivares` usa
      `monto_moneda_origen` como monto local (`_aplicar_pago_cobro` y su equivalente BCV). La 0098 pasa a su saldo
      propio los pesos que las cuentas COP ya habian acumulado en `saldo_total_banco_bs`. Nota de nombres: la
      columna sigue llamandose `monto_bolivares` aunque para una cuenta COP guarde pesos (no se renombro para no
      tocar los triggers de pagos).
    - Cambiar una cuenta de VES a COP (o al reves) mueve su saldo local de una columna a la otra
      (`CuentaBancariaService._reclasificar_saldo_local`); de/hacia USD no mueve nada.
    - Formulario de cuenta: se muestra solo el saldo inicial de la moneda (VES: Bs, USD: $, COP: pesos). El
      listado tiene filtro por moneda y la columna "SALDO COP"; cada moneda muestra solo su columna de saldo (VES:
      MONTO EN BS; USD: SALDO; COP: SALDO COP; Todas: las tres) y la exportacion respeta lo mismo. El dialogo de
      movimientos de una cuenta COP rotula el monto local como COP.
  - **Migrado despues** (misma fecha): Cajas (estado de cajas en hilo aparte; el historial de movimientos de una
    caja pagina de a 50 con los totales del rango sumados en SQL), Comisiones (una sola ruta `_recargar_comisiones`
    en hilo aparte; el filtro de estado ya no vuelve a consultar), historial de cliente (historial, saldos y notas
    de credito en una pasada; si falla avisa en vez de dejar la tabla vacia), detalle de CxC y CxC BCV (la consulta
    corre en un hilo y el dialogo se abre al llegar) y la busqueda de cliente/producto del formulario de factura
    MIENTRAS SE ESCRIBE (con `session_factory`; ver abajo).
  - Detalle de CxC/BCV: `sesion_para_dialogo()` crea una sesion que sobrevive a la tarea y viaja en el resultado
    (`{"session": ...}`); el dialogo la usa para cobrar/refrescar y la cierra al salir. Si la respuesta llega tarde
    (otro doble clic ya pidio otro detalle) `_recibir_carga` la cierra; si la tarea falla despues de crearla, la
    cierra la propia tarea. `CargaAsincronaMixin.done()` espera los hilos de un QDialog (accept/reject no pasan por
    `closeEvent`).
  - Formulario de factura: solo la busqueda al teclear es asincrona. Enter (cliente/producto), el cliente nuevo y la
    carga inicial siguen sincronos a proposito: el cajero (o el lector de codigos) espera el resultado en ese
    instante, y una busqueda sincrona anula la que iba en vuelo (`_cancelar_busqueda_pendiente`) para que no
    repueble el combo despues. Sin `session_factory` (otros usos, tests) todo sigue en el hilo de la ventana.
  - **Los dos que quedaban, tambien migrados** (para que toda la app siga el mismo esquema, aunque hoy no haga falta
    por volumen): el detalle de pagos de Cuentas por pagar y los formularios de producto, usuario y cuenta
    bancaria. Mismo patron "carga previa": el panel pide en un hilo (`_tarea_form_producto`, `_tarea_form_usuario`,
    `_tarea_form_cuenta`, `_tarea_detalle_pagos_proveedor`) los catalogos y el registro a editar con una sesion de
    `sesion_para_dialogo()`, abre el formulario al llegar y cierra la sesion al terminar. Los formularios reciben
    `precargado={...}` (categorias/precio, roles/vendedores, bancos/tiene_movimientos) y, sin ese argumento,
    consultan ellos mismos como antes. `categorias=None` en el producto significa "sin permiso
    'categorias'/'ver'" (el formulario avisa); tras crear una categoria nueva el combo SI se vuelve a consultar.
    `listar_pagos_proveedor` trae caja y cuenta (con banco) en la misma consulta.
  - Con esto no queda ningun listado ni formulario que consulte la base en el hilo de la ventana al abrirse, salvo
    lo que se dejo a proposito sincrono: Enter y carga inicial del formulario de factura y las acciones
    puntuales (guardar, anular, cobrar) que el usuario espera en el acto.
- **Tasa opcional en el abono general por Zelle/Binance** (2026-11-08): los dos dialogos de abono general (CxC y CxC
  BCV) pedian siempre una tasa para cualquier pago bancario, y con Zelle/Binance el campo ni se muestra (solo se
  precarga la BCV del dia): sin ninguna tasa registrada el cajero quedaba bloqueado por un campo que no veia. Zelle y
  Binance se pagan en dolares, igual que la deuda: la tasa solo da el equivalente en bolivares. Ahora
  `moneda_cuentas.tasa_del_abono(metodo, tasa)` valida: con Zelle/Binance la tasa puede ser `None` (el pago y el
  movimiento bancario se guardan con `monto_bolivares`/`tasa_cambio` NULL, el saldo en Bs de la cuenta no se mueve y
  el texto de auditoria no lleva Bs); con cualquier otro metodo sigue siendo obligatoria y mayor a cero, y una tasa
  dada (aun con Zelle) no puede ser cero ni negativa. `PagoService.aplicar_abono_general_cliente` y
  `PagoBCVService.aplicar_abono_general_cliente_bcv` lo usan; el dialogo manda `tasa_cambio=None` e `id_tasa=None`
  cuando no hay tasa. Con tasa el comportamiento no cambia. El cobro de una sola factura ya aceptaba pagos sin tasa.
- **Conciliacion de bancos por moneda de la cuenta** (2026-11-08, `app/ui/conciliacion_bancos_dialog.py`): antes
  mostraba siempre los dos lados (saldos en $ y en Bs, tasa, columnas Monto/Tasa/Monto BS) y obligaba a escribir una
  tasa. Ahora `_aplicar_modo_moneda()` lee `cuentas_bancarias.moneda` de la cuenta elegida: una cuenta USD solo muestra
  dolares (saldo final en $, columna Monto) y una VES/COP solo su moneda local (saldo final en BS o COP, columna
  "Monto BS"/"Monto COP"); la tasa ya no esta en la pantalla principal. Un solo juego de etiquetas (saldo inicial,
  entradas, salidas, diferencia) en la moneda de la cuenta. Los totales se suman en SQL (`_suma_por_tipo`) en vez de
  recorrer todos los movimientos anteriores en Python. Se corrigio de paso `_marcar_conciliado`, que comparaba el saldo
  calculado en Bs contra el saldo final en dolares. Movimiento manual: cuenta USD pide solo el monto en $ y guarda
  `monto_bolivares`/`tasa_cambio` NULL; cuenta VES/COP pide el monto local y la tasa (precargada con la del dia) y el
  equivalente en $ se calcula sin mostrarse. Al cambiar de cuenta se descartan los manuales sin guardar (eran de otra
  moneda). `tests/ui/test_conciliacion_por_moneda.py`.
- **Reportes de listado paginados** (2026-11-08, `reportes_panel.py`): control de pagina global
  (`ControlPaginacion`) en el pie, 100 filas por pagina (`POR_PAGINA_REPORTE`), oculto cuando solo hay una pagina; el
  boton Generar vuelve a la pagina 1 y el cambio de pagina repite la consulta. Exportar un reporte paginado vuelve a
  pedirlo COMPLETO en un hilo (`_con_resultado_completo`, con los filtros con que se genero lo que se ve, no con los
  que el usuario toco despues) y la pantalla conserva su pagina; el limite de PDF se evalua con el total de la
  paginacion. Dos tipos de paginacion:
  - **En la base** (`REPORTES_PAGINADOS_EN_SQL`): el servicio recibe `pagina`/`por_pagina` (`paginar()` central) y
    devuelve `paginacion`; con `pagina=None` devuelve todas las filas y `paginacion=None` (lo que usa la
    exportacion). Los totales se calculan en la base sobre TODO el filtro y no cambian al pasar de pagina. Son:
    Libro de Ventas (el total en Bs se agrupa por (total, tasa) y se multiplica por la cantidad de facturas iguales:
    da exactamente la suma del redondeo factura a factura), movimientos de caja, movimientos por cuenta bancaria (saldo
    corrido con `SUM() OVER (ORDER BY fecha, id)` y saldo inicial con una suma previa: ya no se trae todo el historial
    de la cuenta a Python), notas de credito de cliente, notas de credito de proveedor, devoluciones a proveedor,
    pagos a proveedores y cobros del periodo (la pagina de las dos carteras, normal y BCV, se elige con un UNION ALL de
    (cartera, id, fecha) y despues se cargan solo esos pagos; orden fecha, cartera, id).
  - **En la tarea del hilo** (`_tarea_paginada`, `paginar_lista`): aging CxC / CxC BCV / CxP, facturas anuladas,
    kardex, estados de cuenta de cliente y proveedor, clientes morosos, activacion de clientes, ordenes de compra
    abiertas (el servicio devuelve `total_vencidas` para su chip), valorizacion de inventario, stock bajo minimo,
    productos sin movimiento, historico de precios, cierre diario por cajero y productos proximos a vencer. Estos
    reconstruyen el resultado en Python (saldos corridos, JSON de auditoria, eventos de varias tablas, corte a una
    fecha), asi que el servicio sigue armando el resultado completo y la tarea lo corta despues: la pantalla dibuja
    una pagina y la exportacion pide el resultado completo, pero la consulta de base de datos sigue siendo la completa.
    Medidos son rapidos (aging CxC 5 382 cuentas 377 ms, morosos 425 ms, kardex 63 ms). Sus etiquetas y totales salen
    del resultado completo, no de las filas de la pagina. Cobros/pagos/notas de credito/devoluciones, caja, banco y
    libro de ventas, y ademas CxC otras, CxP otras y proximos vencimientos, estan en `REPORTES_PAGINADOS_EN_SQL`.
  - No se paginan: los que agrupan (ventas por periodo/cliente/vendedor/ruta, margen, productos mas vendidos, compras
    por..., cumplimiento de proveedores, flujo de caja, comisiones, conciliacion, saldo consolidado), porque devuelven
    pocas filas, y el arqueo de caja (los movimientos de un solo turno). Siguen con el tope de
    `LIMITE_FILAS_PANTALLA`.
  - **Exportacion unificada**: Reportes usa `ExportacionCompletaMixin` como los demas paneles. `_exportar` pide el
    destino, resuelve `_info_pdf()` (lee los combos) en el hilo de la ventana y lanza UNA tarea
    (`_tarea_exportar_reporte`) en un hilo: si el reporte es paginado vuelve a pedirlo completo con los filtros con
    que se genero (`_consulta_completa`), arma las filas (`_filas_para_exportar`/`_secciones_para_exportar` solo leen el
    modo y el resultado) y escribe el archivo. Antes eran dos hilos y armar las filas de un reporte grande congelaba la
    ventana. El aviso final es el comun de la app ("Exportacion exitosa").
  - `estado_cuenta_cliente` y `estado_cuenta_proveedor` recorrian todos los pagos por cada cuenta (cuadratico): ahora
    suman por cuenta en una pasada (cliente con 3 559 movimientos: 1,4 s -> 0,38 s). `estado_cuenta_cliente` sigue
    leyendo TODAS las aplicaciones de notas de credito de la auditoria (no hay forma de filtrarlas por cliente en SQL).
  - Medido con 120 000 facturas, 100 000 cobros, 60 000 notas de credito y 150 000 movimientos de banco y de caja
    (2 anios): Libro de Ventas pagina 1 300 ms (completo 8,5 s); movimientos de caja 86 ms (completo 4,8 s);
    movimientos de banco 264 ms (completo 5,2 s); cobros del periodo pagina 1 124 ms y pagina 1000 104 ms (completo
    8,9 s); notas de credito de cliente pagina 1 108 ms (completo 3,4 s); un mes de Libro de Ventas 106 ms.
- **Busqueda global mas rapida** (2026-11-08): de ~300 ms a ~70 ms con 120 000 facturas. (1) Los permisos se
  resuelven una vez por busqueda (`UsuarioService.permisos_del_usuario`: a lo sumo dos consultas) en vez de tres
  consultas por cada tipo de resultado y por cada accion. (2) La busqueda de facturas pide primero los ids por el
  indice (angosto) del numero de factura, ordenados por id, y despues carga solo esas facturas: con pocas coincidencias
  buscar directo ordenando por fecha recorria las 120 000 facturas con una consulta de clave por fila (170 ms; ahora
  ~25 ms). Las facturas se numeran en orden, asi que las mas recientes son las de id mayor.
- **Refresco de saldos de Cuentas Bancarias** (2026-11-08): usaba su propio temporizador y repoblaba la tabla cada 30 s
  perdiendo la cuenta seleccionada y el scroll. Ahora usa `AutoRefresco(asincrono=True)` como Facturacion, Inventario y
  Compras: carga en un hilo, solo si el panel se ve y no hay un dialogo abierto, y vuelve a seleccionar la cuenta por
  id con la tabla ya repoblada.
- **Blindaje contra conexion perdida** (2026-11-10): un cobro fallaba con el SQL crudo en pantalla (`TCP Provider: Se ha
  forzado la interrupcion de una conexion existente por el host remoto (10054)` / `Communication link failure`).
  Causa: el dialogo mantiene su sesion (y una conexion del pool) abierta mientras el usuario lo ve; si la red, un
  firewall o el servidor cierran esa conexion inactiva, la primera consulta del siguiente clic falla. `pool_pre_ping` y
  `pool_recycle` solo protegen las conexiones que se sacan del pool, no las que una sesion ya tiene en su poder.
  Tres capas, todas probadas en `tests/test_conexion_perdida.py` (incluye matar la conexion de verdad con `KILL`):
  1. `SesionResiliente` (`app/db/session.py`, la sesion de `SessionLocal`): si una LECTURA falla por conexion perdida y
     la transaccion no tiene nada que perder (ninguna escritura enviada -- un `SET`, INSERT/UPDATE o flush la marcan --
     ni cambios pendientes en la sesion), hace rollback (descarta la conexion muerta) y repite UNA vez con una conexion
     nueva, que `pool_pre_ping` prueba. Cubre dialogos, paneles, busquedas y cargas en hilo sin tocar cada pantalla.
  2. `reintentar_en_deadlock(func, session=...)` (`app/services/db_utils.py`) repite la operacion completa una vez si se
     perdio la conexion (rollback de `session` antes); sin `session` no repite. Los 9 sitios que lo usan (cobros y
     abonos de CxC, CxC BCV y CxP, emitir factura) ya pasan `session=`. `es_conexion_perdida()` reconoce el corte por
     `connection_invalidated`, SQLSTATE 08xxx y los textos del driver. Una conexion cortada pierde la transaccion
     entera en el servidor, asi que repetir no deja nada a medias.
  3. Mensajes legibles: `MessageBox` (warning y critical) pasa todo texto por `depurar_mensaje_error()`, que reemplaza
     un error de base de datos crudo (huellas: `pyodbc`, `[SQL:`, `ODBC Driver`, `sqlalche.me`...) por "No se pudo X. Se
     perdio la conexion con el servidor..." (o "sistema ocupado" para deadlock/bloqueo, o un mensaje generico), y deja
     el original en el log. Es la red de seguridad de la interfaz: ~75 avisos se arman con `f"...{str(e)}"`. El arranque
     (`_error_de_arranque`) tampoco muestra el driver cuando el servidor esta inaccesible.
  Limites: una escritura fuera de `reintentar_en_deadlock` que pierde la conexion a mitad de camino sigue fallando (con
  mensaje legible); la sesion no repite lecturas despues de un `SET LOCK_TIMEOUT` porque ese ajuste se perderia con la
  conexion. Otras causas posibles del corte (no del codigo): firewall/VPN que cierra conexiones inactivas, o que WSL
  apague la distro de SQL Server cuando no hay sesion abierta (ver `keep_wsl_running.bat`).
- **Filtro por vendedor y alcance del usuario vendedor** (2026-11-10): antes solo Clientes, CxC, CxC BCV, Comisiones y
  unos reportes filtraban por vendedor, y un usuario con rol VENDEDOR (`Usuario.id_vendedor_usuario`) veia TODO el
  negocio (el vinculo solo preseleccionaba el vendedor al facturar). Ahora:
  - **Filtro nuevo**: Facturacion (combo "Vendedor", `VentaService.listar_facturas(id_vendedor=)` y la exportacion) y los
    reportes Libro de ventas, Ventas por periodo, Productos mas vendidos (por el vendedor de la factura), Clientes
    morosos y Cobros del periodo (por el vendedor asignado al cliente, como CxC). Los combos de vendedor de CxC, CxC BCV,
    Clientes y Facturacion se llenan en un hilo aparte (`app/ui/filtros_catalogo.py`; Clientes tambien sus categorias).
  - **Alcance** (`app/services/alcance_vendedor.py`): `vendedor_efectivo(session, id_usuario, id_vendedor)` devuelve el
    vendedor propio del usuario e IGNORA el que pida la pantalla; se aplica en el servicio, no solo en la pantalla.
    Dos criterios: por FACTURA (las que emitio: facturas, libro de ventas, ventas por periodo, productos vendidos,
    `obtener_factura` da `PermisoDenegadoError` con la de otro) y por CLIENTE (los que tiene asignados: clientes, CxC,
    CxC BCV, morosos, cobros, aging, ventas por producto y cliente, activacion, comisiones). Una factura que emitio el
    vendedor A a un cliente de B es de A como factura y de B como cartera. El Panel de inicio (`DashboardService`) cuenta
    solo sus ventas, la cartera de sus clientes y sus facturas recientes; sin pagos a proveedores ni cajas. La busqueda
    global solo encuentra sus clientes, facturas y cuentas por cobrar.
  - **Pantallas**: el combo de vendedor queda fijo en el y deshabilitado (`fijar_vendedor_propio`); en Reportes solo ve
    los de `REPORTES_DE_VENDEDOR` (los acotados a lo suyo) y los catalogos de sus combos solo traen sus clientes (nada de
    proveedores, cajas, cajeros ni cuentas bancarias). Los 34 reportes del negocio entero (compras, bancos, caja,
    inventario valorizado, estados de cuenta, ventas por cliente/ruta...) llaman a `exigir_sin_alcance` y niegan al
    usuario vendedor aunque se llame al servicio directo.
  - Sin vendedor vinculado (ADMIN, CAJERO) nada cambia: eligen el filtro libremente. Limites: el detalle de un cliente,
    su historial y su estado de cuenta se abren desde listados ya acotados pero no verifican el vendedor por id; el
    modulo de Inventario sigue igual (catalogo compartido).
- **Limites de rendimiento resueltos** (2026-11-08):
  - Reportes abre en ~60-100 ms (antes 1,3-2,7 s). Las paginas de filtros ya no se crean las 45 al construir el
    panel: `_filtros_fabricas` (modo -> metodo `_make_filtros_*`) y `_asegurar_pagina(modo)` crea la pagina la primera
    vez que se elige el reporte (o se genera). Los catalogos de los combos (`_GRUPOS_CATALOGO`) se asignan en
    `_aplicar_catalogos()`, que se vuelve a llamar al crear cada pagina y no repite lo ya asignado. Lo que lea un
    combo de otra pagina debe llamar antes a `_asegurar_pagina` (las pruebas usan `_construir_todas_las_paginas`).
  - Refrescos de 30 s de Facturacion, Inventario y Compras: `AutoRefresco(asincrono=True)` llama a
    `recargar(al_terminar)`; el panel carga en un hilo (silencioso, no enciende la barra de carga) y `al_terminar`
    reselecciona la fila por id y conserva el scroll cuando la tabla ya se repueblo. `cargar_async(al_terminar=)`
    lo llama despues de `al_cargar` solo si la respuesta es la vigente (una respuesta vieja no reselecciona). En
    Facturacion el estado de la caja tambien va en hilo (`_tarea_estado_caja`; si falla, el badge se queda como
    estaba). `cargar_facturas(al_terminar=)` hace lo mismo con su worker propio.
  - Tablas de Reportes: `LIMITE_FILAS_PANTALLA` (5 000) filas dibujadas; la etiqueta de total conserva el conteo
    real y agrega "en pantalla las primeras N (la exportacion incluye todas)". La exportacion nunca lee la tabla,
    asi que lleva todas las filas. Libro de ventas con 120 000 filas: 8,5 s -> 0,34 s en pantalla.
- **Columna "Cliente" en Comisiones** (2026-09-07/08, `app/services/comisiones.py`,
  `app/ui/comisiones_panel.py`): `listar_comisiones_vendedor()`/`listar_mis_comisiones()`
  ahora hacen eager load `ComisionFactura.detalle -> FacturaDetalle.factura ->
  FacturaVenta.cliente` (evita N+1) y el panel muestra el cliente de cada factura
  comisionada. Nota de proceso: el mismo dia (66ca20b) se habia agregado primero una
  columna "Estado de Pago" (Liberada/Pendiente, via lookup de `CuentaPorCobrar` por
  fila) -- se revirtio horas despues (22f84c4) a favor de la columna Cliente por
  performance (evitar el lookup por fila) y utilidad percibida; el codigo de estado de
  pago ya no existe en el panel.
- **Saldo corrido en Historial de Cliente** (2026-09-08, `app/services/historial_cliente.py`,
  `app/ui/historial_cliente_window.py`): `obtener_historial_cliente()` ordena las facturas
  cronologicamente y acumula `saldo_pendiente` factura a factura para exponer
  `saldo_corrido` en cada item (el resultado se invierte al final para seguir mostrando
  mas reciente primero en la tabla, pero el acumulado se calculo en orden cronologico).
  Tabla UI y export a Excel incluyen la columna nueva.

## 10. Checklist de producción (consolidado, reemplaza `docs/CHECKLIST_PRODUCCION.md`)

`docs/CHECKLIST_PRODUCCION.md` existió como documento aparte (2026-08-22 en adelante,
**sin versionar** — estaba en `.gitignore`, lo que en sí mismo era el hallazgo V-03 de más
abajo) y quedó congelado el 2026-08-23 pese a que el proyecto siguió avanzando hasta hoy.
Se eliminó y su contenido vigente se fusionó aquí, en un documento sí versionado, para que
no vuelva a desincronizarse del código real. Esta sección reemplaza a aquel archivo por
completo.

### 10.1 Fuera de alcance (confirmado, no re-evaluar en futuras auditorías)

La arquitectura es desktop PySide6 + SQL Server vía `pyodbc`, sin capa HTTP propia. Ítems
típicos de auditoría de backend web **no aplican**:

- Tokens de acceso/refresh, rotación, revocación — no hay tokens; la sesión es el objeto
  `Usuario` en memoria del proceso. El equivalente real (revocación en caliente) ya está
  resuelto: `require_permiso()` revalida `estado`/`bloqueado_desde` en cada llamada.
- CORS, Helmet, headers de seguridad, rate-limit por IP — no hay peticiones HTTP. El
  equivalente real (cooldown + límite de intentos en códigos de recuperación) ya está
  resuelto.
- Validación de payload tipo Zod/Joi/DTO en un boundary HTTP — no hay boundary HTTP; cada
  método de servicio (`if ...: raise ValueError`) es el boundary real.
- IDOR/BOLA por endpoint — no hay endpoints; el control de acceso equivalente es RBAC en
  la firma de cada método de servicio.
- Middleware unificado de excepciones / endpoints `/health/live`, `/health/ready` — no hay
  servidor HTTP. El equivalente real es cada panel UI capturando excepciones + el
  fail-fast de `validar_configuracion()`/`verificar_migraciones_al_dia()` al arrancar. El
  indicador de salud en caliente sigue pendiente (O-04, ver abajo).
- Dockerfile multi-stage / usuario no-root / `.dockerignore` — el ejecutable corre nativo
  en Windows en la máquina de cada empleado; solo la base de datos usa Docker, y solo para
  desarrollo.
- Redis/BullMQ/Celery, Dead Letter Queues, circuit breakers de terceros — no hay
  infraestructura de colas. El equivalente real de "ejecución desacoplada" es
  `QueryWorker` (`app/ui/workers.py`).

### 10.2 Última auditoría integral: 2026-09-06, verificada vigente 2026-09-08

Método: inspección directa de código (RBAC, validaciones, reglas financieras, triggers,
resiliencia, UI/UX) + suite `pytest` completa contra `distribuidora_dj_test` real +
`ruff check`/`ruff format --check`. Resultado: **865/865 tests, sin regresiones, lint y
formato limpios.**

**Scorecard por área:**

| Área | Score | Motivo |
|---|---|---|
| Integridad de datos y triggers | 93% | Secuencia header→detalle→recálculo, orden de borrado en anulación, notas de crédito automáticas, atomicidad (un commit por operación), locks `UPDLOCK`/`ROWLOCK` con test de concurrencia real — todo verificado con evidencia en código. Resta el vacío de manejo de excepciones en `tesoreria.py` (ver P-01 abajo). |
| Validación y seguridad (RBAC/inputs) | 50% | RBAC en sí es sólido (~98% de cobertura, `require_permiso` como primera línea en los 18 servicios). Pero la credencial SMTP filtrada (P-00) es descalificante para cualquier score de seguridad mientras siga expuesta — sin ese hallazgo el área estaría ~85%. |
| Estabilidad UI y asincronía | 68% | Modal unificado (`MessageBox`) casi total (482 usos vs 1-2 nativos residuales). Sin `sys.excepthook` global y con la mayoría de los exports corriendo síncrono en el hilo de UI sin bloqueo de botón. |
| Cobertura de pruebas y robustez | 95% | 865/865 verde contra BD real (no mocks), CI activo, tests de concurrencia real (deadlock/lock), lint/format limpios. |

**Veredicto: CONDICIONADO / NO-GO.** No apto para producción hasta cerrar P-00 a P-04 de
la tabla siguiente.

### 10.3 Pendientes de producción (estado verificado 2026-09-08)

| ID | Prioridad | Ítem | Archivo/módulo | Estado |
|---|---|---|---|---|
| **P-00** | **Bloqueante inmediato** | Credencial SMTP real (Gmail App Password) hardcodeada como valor por defecto, commiteada a git y pusheada a GitHub (`lilblackx/ERP-system`) | `app/config.py:23` (`SMTP_PASSWORD`) | **Abierto** — verificado igual hoy 2026-09-08. Acción: revocar el App Password en Google, generar uno nuevo solo en `.env`, quitar el default de `config.py`, purgar el historial de git (`git filter-repo`/BFG — un commit nuevo no lo borra del historial ya pusheado). |
| **V-01** | P0 | Empaquetado y distribución (instalador/ejecutable standalone, `PyInstaller` o equivalente) | no existe | **Abierto**. Sin esto no hay forma de llevar el sistema a la máquina de cada empleado. Criterio de aceptación: ejecutable/instalador corre en Windows limpio (sin Python/repo) contra la base compartida, con ODBC Driver 18 documentado como prerrequisito. |
| **P-01** | P0 (nuevo, hallazgo 2026-09-06) | Sin `sys.excepthook` global | `app/main.py` | **Abierto**. Una excepción no capturada en un slot de Qt tira la app entera al escritorio sin quedar en log. Solo `QueryWorker.run()` captura, y solo lo que pasa por ahí. |
| **S-02** | P1 | Eventos de autenticación (login OK/fallido/bloqueo) no llegan a `logs/app.log`, solo a `dbo.auditoria` | `app/services/auth.py` | **Abierto**, verificado hoy (cero `import logging` en el archivo). |
| **P-02** | P1 (nuevo, hallazgo 2026-09-06) | `tesoreria.py` sin manejo de excepción/rollback en ningún método (apertura/cierre de caja, movimientos manuales) | `app/services/tesoreria.py` | **Abierto**. Contraste directo con `ventas.py`/`compras.py`/`pagos.py`, que sí capturan y traducen errores de trigger vía `db_utils.py::traducir_error_trigger()`. |
| **P-03** | P1/P2 (nuevo, hallazgo 2026-09-06) | 8 de 10 paneles exportan a Excel síncrono en el hilo de UI sin `setEnabled(False)`/reactivación | `clientes_panel.py`, `proveedores_panel.py`, `inventario_panel.py`, `facturacion_panel.py`, `cuentas_bancarias_panel.py`, `historial_cliente_window.py`, `tasas_panel.py`, `vendedores_panel.py` | **Abierto**. Solo `comisiones_panel.py`/`reportes_panel.py` usan `QueryWorker` correctamente para esto. |
| **D-02** | P1 | Runner de migraciones sin lock entre instancias concurrentes | `app/db/migrar.py::aplicar_migraciones()` | **Abierto**. Envolver en `sp_getapplock` antes de iterar pendientes. |
| **O-03** | P1 | Log estructurado con ID de correlación (hoy texto plano) | `app/logging_config.py` | **Abierto**. |
| **O-04** | P1 | Sin indicador de salud/conectividad en caliente | `app/ui/topbar.py` | **Abierto**. Solo existe el fail-fast al arrancar. |
| **D-01** | P1 (mayormente resuelto, verificado 2026-09-06) | Paginación en listados de catálogo | `app/services/*.py` | **Resuelto en la práctica** para clientes (`clientes.py:108`), proveedores (`proveedores.py:49`), inventario, ventas/facturas, vendedores, cuentas bancarias — verificado con `pagina`/`por_pagina`/`offset().limit()` en código. El checklist original (2026-08-23, "39 llamadas `.all()` sin límite") quedó desactualizado; no se hizo un barrido exhaustivo de los 18 servicios para certificar el 100%, pero no se encontró ningún listado grande sin paginar en la muestra revisada. |
| **X-01** | P2 | Cache del dashboard (recalcula 9 agregaciones en cada apertura, sin TTL) | `app/services/dashboard.py::get_panel_general_data()` | **Abierto**. |
| **X-02** | P2 | Reintento con backoff ante corte de red (hoy solo `pool_pre_ping=True`) | `app/db/session.py` | **Abierto**. |
| **R-02b** | P1 | Exportación PDF/impresión de reportes (la parte Excel ya está resuelta) | nuevo, requiere `QTextDocument`/`QPrinter` | **Abierto**. Sin pantalla de reportes que lo dispare todavía cuando se catalogó; hoy sí existe `reportes_panel.py` — revisar si sigue aplicando. |
| **R-04** | P1 (condicional) | Streaming en exportaciones de detalle grandes (kardex/facturas del año) | `app/services/exportacion.py` | **Abierto pero de bajo riesgo actual** — los reportes existentes son acotados por naturaleza; sube de prioridad el día que exista un reporte sobre una tabla sin acotar. |
| **S-01** | P2 | Mass assignment en creación/edición (`Cliente(**datos)`, `Proveedor(**datos)`) | `app/services/clientes.py:118`, `app/services/proveedores.py:65` | **Abierto**, verificado hoy. Bajo riesgo porque el caller siempre es UI interna, pero es el patrón correcto a fijar antes de que entre dato externo (import masivo, integración). |
| **1b/1c** | P2 (nuevo, hallazgo 2026-09-06) | Validación de formato servidor para identificación (prefijo J/G/V/E/P) y email en clientes/proveedores — hoy solo presencia+unicidad, formato depende 100% de la UI | `clientes.py:23,144`, `proveedores.py:57,89` | **Abierto**. `usuarios.py` sí valida email con regex servidor; clientes/proveedores no tienen equivalente. |
| **3b** | P2 (nuevo, hallazgo 2026-09-06) | Tabla `Auditoria` sin columnas estructuradas `valor_anterior`/`valor_nuevo` — solo `detalle` texto/JSON libre poblado ad-hoc por cada caller | `app/db/models.py:181-191` | **Abierto**, decisión de diseño original, no bloqueante pero limita trazabilidad fina. |
| — | P2 | Sin `Connection Timeout` explícito en la cadena ODBC | `app/config.py::get_database_url()` | **Abierto**, verificado hoy — solo `TrustServerCertificate` está seteado. |
| D-03 | P2 (proceso) | Reversibilidad de migraciones — decisión ya tomada (no hay `down`, una migración nueva deshace la anterior); confirmar por escrito que el respaldo de BD se corre siempre antes de aplicar una migración en un entorno con datos reales | `migrations/README.md`, `docs/BACKUP_RESTORE.md` | Documentado, sin acción de código pendiente. |
| V-02 | P2 | Mensaje de error de `verificar_migraciones_al_dia()` no referencia qué versión del instalador corresponde | `app/db/migrar.py` | Depende de V-01; sin acción hasta que exista. |
| ~~V-03~~ | — | Checklist fuera de control de versión | — | **Resuelto por esta misma consolidación** (2026-09-08): el documento pasó a vivir versionado dentro de `ESTADO_DEL_PROYECTO.md`, ya no existe `docs/CHECKLIST_PRODUCCION.md` como archivo aparte ni entrada en `.gitignore`. |

**Notas sobre `require_permiso()` (verificado 2026-09-06, sigue vigente):** dos métodos
públicos sin guardia propia — `NotaCreditoService.crear_nota_credito_cliente()`/
`crear_nota_credito_proveedor()` (`notas_credito.py`) y el núcleo interno de
`comisiones.py` — son seguros hoy porque nada los llama directo (siempre vía las
variantes internas `_crear_nota_credito_*` desde `anular_factura()`/`anular_compra()`,
que sí están gateadas). Si en el futuro se agrega un caller directo a los públicos,
quedarían sin RBAC — vale agregarles una guardia propia aunque hoy no la necesiten.

**Próximo paso sugerido**: cerrar P-00 (credencial) y P-01 (excepthook) antes de tocar
cualquier otra cosa — son los dos únicos hallazgos con riesgo real de incidente en
producción hoy mismo, no de deuda técnica a mediano plazo.
