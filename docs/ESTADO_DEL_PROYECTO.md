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
- **UI**: PySide6, arranque en `app/main.py`. Por ahora hay pantalla de login
  (`login_window.py`), ventana principal (`main_window.py`) y el módulo de clientes
  (`clientes_window.py`, `cliente_form_dialog.py`) como referencia de patrón de UI.
- **Configuración**: `app/config.py` arma la cadena de conexión ODBC desde variables de
  entorno (`.env`, ver `.env.example`). Nunca se versiona `.env` real.

## 2. Módulos de servicio implementados

| Servicio | Archivo | Responsabilidad |
|---|---|---|
| Autenticación | `auth.py` | Hash/verify de contraseñas (bcrypt), `authenticate()` |
| Clientes | `clientes.py` | CRUD, unicidad de código/identificación |
| Proveedores | `proveedores.py` | CRUD, unicidad de código/RIF, límite y días de crédito |
| Vendedores | `vendedores.py` | CRUD, desempeño mensual (ventas, facturas, clientes asignados) |
| Categorías | `categorias.py` | CRUD, conteo de productos asociados |
| Inventario y precios | `inventario.py` | CRUD de productos, alertas de stock/vencimiento, precios por tipo (DETAL/MAYOR/ESPECIAL) con cálculo de margen |
| Ventas | `ventas.py` | Emisión de factura (con validación de stock y de crédito), anulación de factura, listado con filtros |
| Compras | `compras.py` | Registro de compra (con validación de crédito del proveedor), anulación de compra, listado con filtros |
| Tesorería | `tesoreria.py` | Bancos y cuentas bancarias (CRUD, resumen con número enmascarado), apertura/cierre de caja, movimientos manuales de caja |
| Pagos | `pagos.py` | Aplica pagos de clientes/proveedores contra `cuentas_por_cobrar`/`cuentas_por_pagar` (ver nota técnica de la sección 3) |
| Tasas de cambio | `tasas.py` | Registro de tasa, tasa actual con % vs. día anterior, histórico con brecha cambiaria |
| Usuarios | `usuarios.py` | CRUD de usuarios (hash de clave, vínculo opcional con vendedor), verificación de permisos vía matriz `rol_permisos` |
| Roles y permisos | `permisos.py` | CRUD de roles, y escritura de la matriz `rol_permisos` (asignar/revocar/reemplazar conjunto completo). El catálogo de permisos (`recurso`+`accion`) se mantiene fijo vía schema/seed, no se crea desde aquí |
| Cuentas por cobrar/pagar "otros" | `otros_movimientos.py` | Préstamos/anticipos a cobrar, y conciliación de transferencias bancarias sin identificar (ver sección 4) |
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
  el total cambia y la condición de pago es `credito`. Esto tiene una implicación
  importante para el código de aplicación: **la cabecera debe insertarse con el total en
  0 (o el valor por defecto) y dejar que el trigger de recálculo, disparado al insertar
  las líneas, sea el que efectivamente cambie el valor** — si se inserta ya con el total
  correcto, el trigger no detecta cambio y la cuenta por cobrar/pagar nunca se abre. Los
  servicios de `ventas.py` y `compras.py` ya están escritos respetando esto.
- **Pagos**: `trg_pagos_cobros_io` y `trg_pagos_proveedores_io` son `INSTEAD OF INSERT`:
  validan el origen del pago (exactamente uno entre caja o cuenta bancaria), validan que
  el monto no exceda el saldo, y generan el movimiento de caja/banco correspondiente.
- **Saldo bancario**: `trg_banco_movimientos_saldo` actualiza
  `cuentas_bancarias.saldo_total_banco` en cada movimiento.
- **Cierre de caja**: `trg_cajas_cierre` calcula `saldo_cierre` a partir de
  `saldo_apertura` y los movimientos del turno cuando se registra `fecha_cierre`.

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

Nota: `anular_factura()`/`anular_compra()` (2026-08-22) revierten el stock y cierran la
cuenta por cobrar/pagar asociada, pero **solo si nada se aplicó todavía contra esa
cuenta**: se bloquean con `ValueError` si ya hay `pagos_cobros`/`pagos_proveedores`
aplicados, o (en el caso de ventas) si ya se calculó una `comisiones_factura` sobre
alguna línea. Revertir pagos/comisiones ya aplicados queda fuera de alcance — hay que
deshacerlos a mano primero. El mecanismo es borrar las líneas de
`factura_detalle`/`compra_detalle` (dispara los triggers de stock y de recálculo de
total) y solo después borrar la fila de `cuentas_por_cobrar`/`cuentas_por_pagar` — en ese
orden, porque si se borrara la cuenta primero, `trg_factura_venta_cxc`/`trg_compras_cxp`
la volvería a crear al recalcular el total (mismo problema de reapertura que
`tests/conftest.py` resuelve para el orden de limpieza entre tests). No existe un estado
`ANULADA`/cancelado para `cuentas_por_cobrar`/`cuentas_por_pagar` en el `CHECK` del
schema — por eso la cuenta se borra en vez de cambiarle el estado.

## 6. Panel general (`dashboard.py`)

`get_panel_general_data()` devuelve en una sola llamada:

- Ventas de hoy y % vs. ayer (excluye facturas `ANULADA`)
- Saldo total por cobrar / por pagar y cantidad de cuentas vencidas
- Conteo de productos en alerta de stock
- Serie de 7 días para el gráfico de ventas semanales
- Cajas con turno abierto hoy y su cajero
- Últimas 5 facturas emitidas
- Top 5 productos con menor stock (con categoría)

## 7. Validaciones de negocio destacadas

- **Códigos/identificaciones obligatorios**: `clientes.py` y `proveedores.py` exigen
  código e identificación al crear y no permiten vaciarlos al editar. Esto es necesario
  porque SQL Server, a diferencia de otros motores, solo permite **una fila con NULL**
  por columna `UNIQUE` — dos clientes sin código violarían la restricción.
- **Stock y crédito en ventas**: `emitir_factura()` valida disponibilidad de stock
  (agrupando ítems repetidos) y, si la condición es `credito`, que la deuda actual del
  cliente más la nueva factura no supere `limite_credito`.
- **Crédito de proveedor en compras**: `registrar_compra()` aplica la misma validación
  simétrica sobre `proveedores.limite_credito`.

## 8. Pendiente / próximos pasos sugeridos

- UI: solo están cubiertos login y clientes; falta construir las pantallas para el
  resto de los módulos de servicio ya implementados (incluida la nueva matriz de
  permisos de `permisos.py`, pensada para un checkbox-grid por rol vía
  `PermisoService.obtener_matriz_rol()` / `establecer_permisos_rol()`).
- Reversión de pagos/comisiones ya aplicados a una cuenta por cobrar/pagar: hoy
  `anular_factura()`/`anular_compra()` simplemente se niegan a anular si eso ya pasó (ver
  nota en la sección 5). Si el negocio necesita poder anular igual, revirtiendo también
  los pagos y sus movimientos de caja/banco, es un desarrollo aparte y bastante más
  grande (afecta saldos ya conciliados).
- Sin migraciones formales del schema: los cambios a `schema_sqlserver.sql` (como el fix
  de la sección 3) se aplican a mano en cada entorno con `ALTER TRIGGER`/`ALTER TABLE`.
  El script tampoco es idempotente para triggers (solo las `CREATE TABLE` están
  guardadas con `IF OBJECT_ID ... IS NULL`), así que no se puede simplemente
  re-ejecutar completo sobre una base ya poblada.
- Cobertura de pruebas automatizadas: hecha para los 16 módulos de servicio. Hay un
  harness de pytest (`tests/`) contra una base de datos SQL Server de prueba dedicada
  (real, no mock — necesario para validar los triggers), con 260 tests. Ver
  `tests/conftest.py` para la estrategia de aislamiento entre tests (limpieza por
  `DELETE` en orden trigger-safe, no rollback, porque los servicios hacen su propio
  `commit()`) y `tests/factories.py` para los helpers de datos base. Pendiente: correrlo
  en CI (hoy es manual, `pytest` requiere Docker/SQL Server arriba).
