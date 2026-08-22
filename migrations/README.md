# Migraciones de schema

`schema_sqlserver.sql` arma el schema completo para un entorno nuevo y se auto-registra
al final como la migracion `0000_baseline` (tabla `dbo.schema_migrations`). A partir de
ahora, **todo cambio de schema en un entorno que ya tiene datos** (nuevo trigger, `ALTER
TABLE`, nueva tabla, cambio de `CHECK`, etc.) se agrega como un archivo `.sql` nuevo acá,
en vez de editar `schema_sqlserver.sql` directamente — ese archivo sigue existiendo para
poder crear un entorno desde cero, pero no vuelve a ejecutarse completo sobre una base ya
poblada (no es idempotente para triggers/constraints, solo para `CREATE TABLE`).

## Convención

- Nombre de archivo: `NNNN_descripcion_corta.sql`, con `NNNN` incremental de 4 dígitos
  (`0001_...`, `0002_...`). El nombre de archivo completo es la "versión" que queda
  registrada en `dbo.schema_migrations` — no reutilizar ni renombrar un archivo ya
  aplicado en algún entorno.
- Statements separados por `GO` en línea propia, igual que en `schema_sqlserver.sql` (T-SQL
  exige que `CREATE TRIGGER`/`CREATE PROCEDURE` sean el único statement de su batch).
- Cada migración debe poder aplicarse una sola vez de forma segura — si el cambio no es
  naturalmente idempotente (p. ej. `ALTER TABLE ... ADD`), no hace falta guardia
  `IF NOT EXISTS`: el runner nunca vuelve a ejecutar un archivo ya registrado.
- No hay `down`/rollback. Revertir un cambio ya aplicado es una migración nueva que
  deshace el anterior.
- Si el cambio toca una tabla con triggers y agrega un trigger nuevo, recordar
  `implicit_returning=False` en `app/db/models.py` (ver nota en `docs/ESTADO_DEL_PROYECTO.md`,
  sección 3).

## Aplicar migraciones pendientes

```bash
python -m app.db.migrar
```

Requiere que el schema base ya exista (`schema_sqlserver.sql` ya corrido al menos una vez
contra esa base — ver README.md). Aplica cada archivo pendiente en orden y lo registra en
`dbo.schema_migrations`; si ese entorno todavía no tiene la tabla `schema_migrations` (bases
que ya existían antes de este mecanismo), el runner la crea y marca `0000_baseline` como
aplicada automáticamente antes de seguir.
