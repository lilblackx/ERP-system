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
| Compras | `compras.py` | Registro de compra (con validación de crédito del proveedor), listado con filtros |
| Tesorería | `tesoreria.py` | Bancos y cuentas bancarias (CRUD, resumen con número enmascarado), apertura/cierre de caja, movimientos manuales de caja |
| Tasas de cambio | `tasas.py` | Registro de tasa, tasa actual con % vs. día anterior, histórico con brecha cambiaria |
| Usuarios y permisos | `usuarios.py` | CRUD de usuarios (hash de clave, vínculo opcional con vendedor), verificación de permisos vía matriz `rol_permisos` |
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
- **Compras**: registro
- **Tesorería**: bancos y cuentas bancarias (CRUD), apertura/cierre de caja, movimientos
  manuales de caja
- **Tasas de cambio**: cada registro nuevo
- **Usuarios**: alta, edición, cambio de estado
- **Cuentas por cobrar/pagar otros**: alta, abono, conciliación
- **Configuración de empresa**: cada actualización

En los métodos donde no existía forma de saber quién ejecutó la acción se agregó un
parámetro opcional (`id_usuario` o, en `usuarios.py`, `realizado_por` para no
confundirlo con el usuario que es objeto de la operación). Todos son opcionales con
valor por defecto `None`, así que no rompen código existente que no lo use.

Nota: `anular_factura()` solo cambia `estado_factura` a `ANULADA`. No repone stock ni
cancela la cuenta por cobrar automáticamente, porque los triggers de stock/totales
reaccionan a cambios en `factura_detalle`, no a un cambio de estado en la cabecera. Si se
necesita reversión completa al anular, es un desarrollo aparte.

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
  resto de los módulos de servicio ya implementados.
- Gestión de permisos (`permisos` / `rol_permisos`): no hay un servicio de escritura
  para mantener la matriz desde la UI, solo el seed inicial del schema y la verificación
  de lectura (`UsuarioService.verificar_permiso`).
- Reversión de anulación de facturas (reponer stock / cancelar CxC) si el negocio lo
  requiere.
- Cobertura de pruebas automatizadas (hasta ahora la validación se hizo con scripts
  manuales contra una base de datos de desarrollo real).
