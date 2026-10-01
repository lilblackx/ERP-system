# Instalador (Inno Setup + PyInstaller)

Un solo instalador, `DistribuidoraDJ-Setup-<version>.exe`, con dos modos:

| Modo | Qué hace |
|---|---|
| **Servidor** | Usa un **SQL Server que ya exista** en ese equipo (si no hay, avisa y se cierra; se instala SQL Server y se vuelve a empezar). Crea la base de datos, el esquema, un usuario SQL propio de la app (`dj_app`, solo lectura/escritura de datos, **sin** permisos de esquema), el usuario `admin` de la app, abre el puerto en el firewall e instala el **servicio de Windows de licencia**. |
| **Estación** | Pide los datos del servidor, prueba la conexión y escribe la configuración. No instala base de datos ni servicio. |

Si el equipo ya tiene una instalación (existe `config.env`), el instalador entra en modo **actualización**: copia los archivos nuevos y, en el servidor, aplica las migraciones pendientes (pide un administrador de SQL Server para eso).

## Construir el instalador

Requisitos en la PC de construcción: el entorno virtual (`.venv`) con `requirements-dev.txt` + `pyinstaller`, e **Inno Setup 6**.

```powershell
.\packaging\construir.ps1 -Version 1.0.0
```

Genera `build\instalador\DistribuidoraDJ-Setup-1.0.0.exe` (≈ 250 MB). Pasos:

1. Lee `LICENCIA_URL` y `LICENCIA_PUBLIC_KEY` del `.env` y los **hornea** en `app/licencia_embebida.py` (el programa instalado ignora cualquier `.env` para esto).
2. PyInstaller → `build\dist\DistribuidoraDJ\` (`DistribuidoraDJ.exe` y `DJ-Servicio.exe`) y `build\herramientas\DJ-Herramientas.exe` (16 MB, sin Qt).
3. Descarga `packaging\redist\msodbcsql.msi` (ODBC Driver 18, enlace oficial de Microsoft) si falta.
4. Compila `packaging\instalador.iss`.

Opciones: `-SoloEmpaquetar` (sin Inno) y `-SinLicencia` (build de prueba **sin** control de licencia; nunca distribuirlo).

## Dónde queda cada cosa en el equipo del cliente

| Qué | Dónde |
|---|---|
| Programa | `C:\Program Files\Distribuidora DJ\` |
| Configuración (`config.env`), logs, estado del reloj | `C:\ProgramData\DistribuidoraDJ\` |
| Datos para instalar estaciones (solo servidor) | `C:\ProgramData\DistribuidoraDJ\datos_estaciones.txt` |
| Servicio de Windows (solo servidor) | `DistribuidoraDJLicencia` (inicio automático, se reinicia si se cae) |
| Regla de firewall (solo servidor) | `Distribuidora DJ - SQL Server` (TCP, el puerto indicado) |

## Antes de instalar un servidor

- **SQL Server** instalado y el servicio iniciado. Si es Express: en *SQL Server Configuration Manager* → *Protocolos* → habilitar **TCP/IP** y fijar un **puerto estático** (por ejemplo 1433). Sin eso las estaciones no pueden conectarse. El instalador no puede cambiar esa configuración.
- Un usuario **sysadmin** de SQL Server (`sa` o su cuenta de Windows). Se usa solo durante la instalación; no se guarda.

## Instalar una estación

Ejecutar el instalador en la PC cliente, elegir *Estación* e ingresar los datos que el instalador del servidor dejó en `datos_estaciones.txt` (servidor,puerto / base / usuario / contraseña). **Copie esos datos a un lugar seguro y borre el archivo.**

## Instalación silenciosa

```
DistribuidoraDJ-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /LOG="C:\temp\instalacion.log" ^
  /Tipo=SERVIDOR /Servidor=localhost /Puerto=1433 /Base=distribuidora_dj ^
  /AdminSql=sa /ClaveAdminSql="..." /ClaveAdminApp="..."

DistribuidoraDJ-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES ^
  /Tipo=ESTACION /Servidor=PC-SERVIDOR,1433 /Base=distribuidora_dj /UsuarioSql=dj_app /ClaveSql="..."
```

Código de salida 0 = instalado. Si los datos de conexión son inválidos el instalador se detiene **antes** de copiar nada (código 1).

## Herramientas de línea de comandos

`DJ-Herramientas.exe` (en `{app}\herramientas`) lo usa el instalador; también sirve para soporte. Contrato y comandos: `app/instalacion.py`.

## Seguridad: lo que conviene saber

- `config.env` guarda la contraseña del usuario SQL de la app y **cualquier usuario local de Windows puede leerla** (las estaciones la necesitan para conectarse). Es un usuario sin permisos de esquema, pero con acceso a los datos del negocio.
- `datos_estaciones.txt` contiene esa misma contraseña en claro: bórrelo tras instalar las estaciones.
- El instalador **no está firmado**: Windows SmartScreen mostrará una advertencia al ejecutarlo. Para distribuirlo a clientes conviene firmarlo con un certificado de firma de código.
- El empaquetado con PyInstaller **no impide** que alguien con conocimientos extraiga y lea el código; ver `licencias/README.md` ("Qué protege y qué no").

## Qué NO está probado todavía

La instalación como **administrador** en un equipo limpio (creación del servicio con `sc.exe`, regla de firewall, desinstalación, instalación automática de ODBC, actualización con el servicio en marcha) y la apariencia de las pantallas del asistente. Probadas: las herramientas contra SQL Server real, los ejecutables empaquetados, el flujo silencioso (servidor, estación, actualización, datos inválidos) sin privilegios de administrador y la compilación del instalador.
