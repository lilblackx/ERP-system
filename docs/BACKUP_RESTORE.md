# Backup y restore

La base vive en el contenedor Docker `distribuidora_dj_sqlserver` (ver
`docker-compose.yml` y `README.md`). El volumen `sqlserver_data` persiste los datos
mientras el contenedor exista, pero **no es un backup**: si se borra el volumen, se
corrompe el disco, o se pierde la maquina (ver decision de C5 — la app corre en una LAN
cerrada, sin infraestructura cloud detras), los datos se pierden. Esta guia cubre backup
manual con las herramientas nativas de SQL Server (`BACKUP DATABASE`/`RESTORE DATABASE`),
que producen un `.bak` consistente incluso con el motor corriendo — no copiar los
archivos del volumen directamente (`.mdf`/`.ldf`) mientras el contenedor esta activo, el
resultado no esta garantizado consistente.

## Backup manual

1. Generar el `.bak` **dentro** del contenedor (ruta interna, no del host):

   ```bash
   docker exec -it distribuidora_dj_sqlserver /opt/mssql-tools18/bin/sqlcmd \
     -S localhost -U sa -P "<tu DB_PASSWORD>" -C \
     -Q "BACKUP DATABASE distribuidora_dj TO DISK = '/var/opt/mssql/backup/distribuidora_dj.bak' WITH INIT, COMPRESSION"
   ```

   `/var/opt/mssql/backup/` no existe por defecto — crearla una vez:

   ```bash
   docker exec -it distribuidora_dj_sqlserver mkdir -p /var/opt/mssql/backup
   ```

2. Sacar el `.bak` del contenedor al host, con la fecha en el nombre:

   ```bash
   docker cp distribuidora_dj_sqlserver:/var/opt/mssql/backup/distribuidora_dj.bak ./distribuidora_dj_2026-08-23.bak
   ```

3. **Copiar ese archivo a otra maquina o disco de la red.** Un backup que vive en el
   mismo disco que la base no protege contra la falla mas comun (disco de esa PC
   muerto). No hace falta automatizar esto en el codigo del proyecto — alcanza con una
   carpeta compartida de red y copiar el `.bak` ahi despues del paso 2, o programarlo con
   el Programador de tareas de Windows (`schtasks`/Task Scheduler) apuntando a un `.bat`
   que encadene los pasos 1-3.

## Restore

**Antes de restaurar sobre una base existente, hacer un backup de esa base primero** (ver
arriba) — `RESTORE ... WITH REPLACE` destruye el contenido actual sin poder deshacerse.

1. Copiar el `.bak` de vuelta al contenedor:

   ```bash
   docker cp ./distribuidora_dj_2026-08-23.bak distribuidora_dj_sqlserver:/var/opt/mssql/backup/restore.bak
   ```

2. Restaurar (`WITH REPLACE` solo si ya existe una base con ese nombre y se quiere
   sobreescribir a proposito):

   ```bash
   docker exec -it distribuidora_dj_sqlserver /opt/mssql-tools18/bin/sqlcmd \
     -S localhost -U sa -P "<tu DB_PASSWORD>" -C \
     -Q "RESTORE DATABASE distribuidora_dj FROM DISK = '/var/opt/mssql/backup/restore.bak' WITH REPLACE"
   ```

3. Aplicar cualquier migracion que el `.bak` no tenga todavia (un backup mas viejo que el
   `schema_sqlserver.sql`/`migrations/` actual del repo puede quedar atras):

   ```bash
   python -m app.db.migrar
   ```

## Rollback de migraciones de schema

No existe (ni se planea) un mecanismo de `down`/rollback automatico para
`migrations/*.sql` — decision ya documentada en `migrations/README.md`. Revertir un
cambio de schema ya aplicado en un entorno con datos es una migracion nueva que deshace
el anterior (ej. `0010_revertir_columna_x.sql`), nunca editar ni borrar el archivo ya
aplicado. Si el cambio no se puede deshacer de forma segura con datos ya migrados (p. ej.
se borro una columna con datos), la unica via de vuelta atras es un restore desde backup
a un punto anterior a esa migracion.

## Respaldos automaticos en el servidor instalado

El instalador (modo Servidor, instalacion nueva) puede dejar los respaldos configurados
(`respaldos` en `app/instalacion.py`; pagina "Respaldos automaticos" del asistente o los
parametros `/CarpetaRespaldos`, `/RutaDrive`, `/DiasRetencion`, `/Respaldos=0`):

- Trabajos de **SQL Server Agent** (SSMS > SQL Server Agent > Trabajos), no un "Plan de
  mantenimiento" de SSMS: SQL Server no permite crear esos por script. Necesita SQL Server
  Standard o superior (Express no trae Agent; el instalador avisa y sigue).
  - `Nexo ERP - Respaldo completo`: diario 19:00; despues borra los `.bak`/`.trn` con mas de N
    dias (N = 3 por defecto, igual para completos y de log, en local y en Drive).
  - `Nexo ERP - Respaldo de log de transacciones`: cada 30 min (la base queda en recovery FULL y
    el instalador toma un respaldo completo inicial, sin el los respaldos de log fallan).
  - `Nexo ERP - Mantenimiento semanal`: domingo 03:00, `DBCC CHECKDB` + `sp_updatestats`.
- Copia a Google Drive: tarea programada de Windows `Nexo ERP - Copia de respaldos a Google
  Drive` (cada 30 min, script `copiar_respaldos_drive.ps1` en la carpeta de datos) que copia los
  respaldos nuevos a la carpeta de **Google Drive para escritorio** indicada y borra de Drive los
  de mas de N dias. Corre con la sesion del usuario que instalo (SQL Agent no ve esa unidad), asi
  que Drive para escritorio debe estar abierto con la sesion iniciada. La carpeta de Drive es
  **obligatoria** cuando se configuran respaldos. El asistente tiene el boton "Probar carpeta" (y
  no deja avanzar si falla); la prueba (`probar-drive`) comprueba que exista la unidad y la carpeta
  padre, crea el ultimo nivel si falta y escribe, lee y borra un archivo de prueba, con el usuario
  que instala. En modo silencioso la misma prueba corre antes de tocar SQL Server;
  `/SinPruebaDrive=1` la omite (p. ej. si Drive para escritorio aun no tiene la sesion iniciada).
- Las actualizaciones del instalador no tocan los trabajos ni preguntan por respaldos. Para
  configurarlos en un servidor ya instalado, o recrearlos (el comando borra y vuelve a crear los
  tres trabajos), ejecutar `Nexo-Herramientas.exe respaldos --entrada datos.json --salida r.txt`
  con el JSON de `ConfigurarRespaldos` en `packaging/instalador.iss`.

## Que no cubre esta guia

- Backup automatizado corriendo dentro del proyecto (cron/servicio) — no hay
  infraestructura de servidor detras de esta app (ver C5), por eso la recomendacion es
  Task Scheduler de Windows sobre la maquina donde corre el contenedor, no algo que el
  codigo del repo dispare solo.
- Replicacion o alta disponibilidad — fuera de alcance para una LAN de oficina de este
  tamano.
