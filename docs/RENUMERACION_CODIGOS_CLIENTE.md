# Renumeración de códigos de cliente (migraciones 0093 y 0094)

**Modifica datos de producción y no tiene "deshacer" automático.** Seguir este procedimiento
completo: respaldo → ensayo en una copia → aplicar → verificar.

## Qué hace

- **0093**: el código de cliente pasa a generarlo SQL Server (secuencia `dbo.seq_codigo_cliente` como
  `DEFAULT` de `clientes.codigo_cliente`). Solo agrega objetos; **no toca ninguna fila**.
- **0094**: lleva todos los clientes existentes al formato `CLI-000123` (prefijo `CLI-` + número a
  6 dígitos; con más de 6 dígitos simplemente crece) y deja el `DEFAULT` generando ese mismo formato.

Regla de la 0094 para los clientes existentes:

| Código actual | Código nuevo |
|---|---|
| `CLI-001`, `CLI-45`, `57`, `000012` (contiene un número) | **Conserva su número**: `CLI-000001`, `CLI-000045`, `CLI-000057`, `CLI-000012` |
| Dos clientes con el mismo número (`CLI-5` y `5`) | Gana el que ya estaba en formato estándar, o si no el más antiguo; el otro recibe número nuevo |
| Texto sin número, vacío, `NULL`, `0`, o más de 12 dígitos | Número nuevo, a continuación del mayor, por orden de creación (`id_cliente`) |
| Ya en formato `CLI-000123` | No cambia |

El código anterior de cada cliente cuyo código cambia queda guardado en `dbo.clientes_codigo_anterior`
(`id_cliente`, `codigo_anterior`, `codigo_nuevo`, `fecha_cambio`). El código no se copia en ninguna otra
tabla (las facturas guardan `id_cliente`), así que no hay nada más que actualizar.

## Garantías de la migración

Todo corre en **una transacción** y bloquea `dbo.clientes` mientras trabaja. Si cualquier verificación
falla, se revierte **todo** y no queda nada a medias. Verifica: misma cantidad de clientes; filas del
historial = filas actualizadas; todos los códigos con formato estándar y sin repetidos; **ningún cliente
que ya estaba bien fue modificado**; secuencia y `DEFAULT` bien puestos. Cubierto por
`tests/test_migracion_0094.py` (incluye "si falla una verificación final, se revierte todo").

## Procedimiento en producción

### 1. Respaldo (obligatorio)

Ver `docs/BACKUP_RESTORE.md`. Hacerlo **justo antes**, y comprobar que el archivo sirve:

```sql
BACKUP DATABASE [distribuidora_dj] TO DISK = N'<ruta>\antes_0094.bak' WITH INIT, COMPRESSION, CHECKSUM;
RESTORE VERIFYONLY FROM DISK = N'<ruta>\antes_0094.bak' WITH CHECKSUM;
```

Copiar el `.bak` fuera de la máquina del servidor.

### 2. Ensayo en una copia (obligatorio, con los datos reales)

Restaurar ese mismo `.bak` como **otra base** y correr ahí las migraciones reales:

```sql
RESTORE DATABASE [distribuidora_dj_ensayo] FROM DISK = N'<ruta>\antes_0094.bak'
WITH MOVE N'<nombre_logico_datos>' TO N'<ruta>\distribuidora_dj_ensayo.mdf',
     MOVE N'<nombre_logico_log>'   TO N'<ruta>\distribuidora_dj_ensayo.ldf';
-- nombres lógicos:  RESTORE FILELISTONLY FROM DISK = N'<ruta>\antes_0094.bak';
```

Apuntar un `.env` temporal a `DB_NAME=distribuidora_dj_ensayo` y correr `python -m app.db.migrar`.
Revisar el resultado **en la copia**:

```sql
-- ¿Cuántos cambiaron y cómo? (revisar a ojo la lista completa)
SELECT h.id_cliente, c.nombre_razon_social, h.codigo_anterior, h.codigo_nuevo
FROM dbo.clientes_codigo_anterior h JOIN dbo.clientes c ON c.id_cliente = h.id_cliente
ORDER BY h.id_cliente;

-- Todo en formato estándar, sin nulos ni repetidos (las tres deben dar 0):
SELECT COUNT(*) FROM dbo.clientes WHERE codigo_cliente IS NULL
   OR codigo_cliente COLLATE Latin1_General_BIN NOT LIKE 'CLI-[0-9][0-9][0-9][0-9][0-9][0-9]%'
   OR SUBSTRING(codigo_cliente, 5, 20) LIKE '%[^0-9]%';
SELECT COUNT(*) - COUNT(DISTINCT codigo_cliente) FROM dbo.clientes;
SELECT (SELECT COUNT(*) FROM [distribuidora_dj].dbo.clientes) - (SELECT COUNT(*) FROM dbo.clientes);

-- Próximo código que asignará un alta nueva:
SELECT CAST(current_value AS BIGINT) FROM sys.sequences WHERE name = 'seq_codigo_cliente';
```

**No continuar si algo no cuadra o la lista de cambios tiene sorpresas.** Después se borra la base de ensayo.

### 3. Aplicar en producción

- Avisar y cerrar la aplicación en las estaciones (la migración bloquea `clientes` unos instantes y
  las estaciones con la versión anterior no deben dar altas mientras tanto).
- **Primero el servidor**: instalar la nueva versión (el instalador aplica las migraciones pendientes
  con credenciales de administrador de SQL). **Después las estaciones** (solo verifican y copian archivos).

### 4. Verificar

Repetir en producción las consultas de verificación del paso 2 (las tres deben dar 0) y dar de alta un
cliente de prueba desde la app: debe salir con el siguiente `CLI-000nnn`.

## Si algo sale mal

- Si la migración falla, **se revierte sola**: la base queda como estaba (la 0093 queda aplicada, que es
  inocua).
- Si ya se aplicó y hay que volver atrás: **restaurar el respaldo del paso 1** (`docs/BACKUP_RESTORE.md`).
  Los códigos viejos también se pueden volver a poner desde el historial, pero eso no revierte el
  `DEFAULT` ni la secuencia, así que solo es un recurso parcial:

  ```sql
  BEGIN TRAN;
  UPDATE c SET c.codigo_cliente = h.codigo_anterior
  FROM dbo.clientes c JOIN dbo.clientes_codigo_anterior h ON h.id_cliente = c.id_cliente;
  -- revisar y luego COMMIT (o ROLLBACK)
  ```

## Notas

- Los códigos escritos a mano ya no son posibles desde la app: el campo es de solo lectura y los códigos de
  un cliente existente no se pueden cambiar.
- Una secuencia de SQL Server **puede dejar huecos** (un alta que falla igual consume su número).
