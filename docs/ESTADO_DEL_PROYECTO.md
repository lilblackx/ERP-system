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
| Roles y permisos | `permisos.py` | CRUD de roles, y escritura de la matriz `rol_permisos` (asignar/revocar/reemplazar conjunto completo). El catálogo de permisos (`recurso`+`accion`) se mantiene fijo vía schema/seed, no se crea desde aquí. También expone `require_permiso()`, el punto de entrada de autorización que usan los otros 17 servicios (ver sección 7) |
| Cuentas por cobrar/pagar "otros" | `otros_movimientos.py` | Préstamos/anticipos a cobrar, y conciliación de transferencias bancarias sin identificar (ver sección 4) |
| Notas de crédito | `notas_credito.py` | Saldo a favor de cliente/proveedor generado automáticamente al anular una factura/compra con pagos ya aplicados (ver sección 3, "Notas de credito automaticas") |
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

  Sigue bloqueada la anulacion si hay `comisiones_factura` calculadas sobre alguna
  linea -- no hay modulo que las gestione todavia, revertirlas queda fuera de alcance.

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

Nota: `anular_factura()`/`anular_compra()` (2026-08-22, actualizado 2026-08-22) revierten
el stock y cierran la cuenta por cobrar/pagar asociada. Si ya se le aplicaron pagos, esos
pagos no se tocan — se genera una nota de crédito por el monto ya cobrado/pagado y la
cuenta pasa a `estado='anulada'` en vez de borrarse, ver "Notas de credito automaticas"
en la sección 3. Sin pagos aplicados, la cuenta se sigue borrando (nada que preservar).
Sigue bloqueada con `ValueError` si ya se calculó una `comisiones_factura` sobre alguna
línea (solo aplica a ventas): no hay módulo que gestione comisiones todavía, revertirlas
queda fuera de alcance. El mecanismo es borrar las líneas de `factura_detalle`/
`compra_detalle` (dispara los triggers de stock y de recálculo de total) antes de tocar
`cuentas_por_cobrar`/`cuentas_por_pagar` — `trg_factura_venta_cxc`/`trg_compras_cxp` solo
tocan cuentas en estado `'pendiente'`, así que si ya hay pagos aplicados (`'parcial'`/
`'pagada'`) el trigger no la altera y fijar `estado='anulada'` después es seguro.

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

## 8. Validaciones de negocio destacadas

- **Códigos/identificaciones obligatorios**: `clientes.py` y `proveedores.py` exigen
  código e identificación al crear y no permiten vaciarlos al editar. Esto es necesario
  porque SQL Server, a diferencia de otros motores, solo permite **una fila con NULL**
  por columna `UNIQUE` — dos clientes sin código violarían la restricción.
- **Stock y crédito en ventas**: `emitir_factura()` valida disponibilidad de stock
  (agrupando ítems repetidos) y, si la condición es `credito`, que la deuda actual del
  cliente más la nueva factura no supere `limite_credito`.
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

## 9. Pendiente / próximos pasos sugeridos

- UI: solo están cubiertos login y clientes; falta construir las pantallas para el
  resto de los módulos de servicio ya implementados (incluida la nueva matriz de
  permisos de `permisos.py`, pensada para un checkbox-grid por rol vía
  `PermisoService.obtener_matriz_rol()` / `establecer_permisos_rol()`).
- ~~RBAC modelado pero no aplicado~~ — resuelto (2026-08-22), ver sección 7. ~~Sigue
  pendiente extenderlo a operaciones de lectura~~ — también resuelto (2026-08-22, misma
  sección).
- ~~Deletes sin guarda de integridad (clientes, proveedores, vendedores, inventario,
  bancos/cuentas bancarias)~~ — resuelto (2026-08-22): en vez de agregar una guarda de
  conteo, se decidió que estas 5 entidades nunca se borran físicamente. Ver sección 8.
- ~~Reversión de pagos ya aplicados a una cuenta por cobrar/pagar~~ — resuelto
  (2026-08-22) con nota de crédito automática. Ver "Notas de credito automaticas" en la
  sección 3. Sigue pendiente la reversión de **comisiones** (`comisiones_factura`): no
  hay módulo que las gestione todavía, así que `anular_factura()` sigue bloqueando si hay
  comisiones calculadas.
- Notas de crédito (`notas_credito.py`): ~~sin correlativo fiscal~~ — resuelto
  (2026-08-22), ver sección 3. Sigue faltando el flujo para consumirlas — aplicar una
  nota disponible como abono a una venta/compra futura, o devolverla como un movimiento
  de caja/banco nuevo (fechado en el momento real de la devolución, no retroactivo). Es
  un desarrollo aparte.
- Riesgo de *clock skew* entre el reloj de la app (Python `datetime.now()`, usado por
  `CajaService.abrir_caja()`/`cerrar_caja()`) y el reloj del SQL Server (`GETDATE()`,
  usado por `trg_pagos_cobros_io`/`trg_pagos_proveedores_io` cuando `registrar_pago_cobro()`/
  `registrar_pago_proveedor()` no reciben `fecha_pago` explícito): si difieren, un pago
  registrado cerca del cierre de turno podría quedar fuera del rango que
  `trg_cajas_cierre` usa para sumar `saldo_cierre`. Detectado 2026-08-22 escribiendo
  `tests/services/test_pagos.py::test_borrar_pago_cobro_con_turno_de_caja_ya_cerrado_recalcula_saldo_cierre`
  (el test necesitó pasar `fecha_pago=datetime.now()` explícito para no ser flaky). No
  resuelto — pendiente decidir si `pagos.py` siempre debe fijar `fecha_pago` en Python o
  si `trg_cajas_cierre` debe usar el reloj del servidor de forma consistente.
- ~~Sin migraciones formales del schema~~ — resuelto (2026-08-22). Ver nota al final de
  la sección 3.
- Cobertura de pruebas automatizadas: hecha para los 18 módulos de servicio más el
  runner de migraciones. Hay un harness de pytest (`tests/`) contra una base de datos
  SQL Server de prueba dedicada (real, no mock — necesario para validar los triggers),
  con 383 tests. Ver `tests/conftest.py` para la estrategia de aislamiento entre tests
  (limpieza por `DELETE` en orden trigger-safe, no rollback, porque los servicios hacen
  su propio `commit()`) y `tests/factories.py` para los helpers de datos base.
  `tests/test_migrar.py` corre contra la base de datos de test real (no una copia
  aislada) para probar el bootstrap de `dbo.schema_migrations`; tiene un fixture
  (`_preservar_schema_migrations_real`, agregado 2026-08-22 tras encontrar el bug) que
  respalda y restaura esa tabla para no borrar el registro de migraciones ya aplicadas.
  Pendiente: correr la suite en CI (hoy es manual, `pytest` requiere Docker/SQL Server
  arriba).
