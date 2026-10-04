# Instalador (Inno Setup + PyInstaller)

Un solo instalador, `DistribuidoraDJ-Setup-<version>.exe`, con dos modos:

| Modo | Qué hace |
|---|---|
| **Servidor** | Usa un **SQL Server que ya exista** en ese equipo (si no hay, avisa y se cierra; se instala SQL Server y se vuelve a empezar). **Configura ese SQL Server** (habilita TCP/IP, fija el puerto y el modo de autenticación mixto, reiniciando el servicio si hace falta), crea la base de datos, el esquema, un usuario SQL propio de la app (`dj_app`, solo lectura/escritura de datos, **sin** permisos de esquema), el usuario `admin` de la app, abre el puerto en el firewall e instala el **servicio de Windows de licencia**. |
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

## Firma del instalador (certificado autofirmado)

Es gratis, pero solo es "de confianza" en las PCs que tienen instalado el certificado público. Pensado para instalaciones hechas por nosotros; para distribuir a terceros haría falta un certificado de una CA (p. ej. Azure Trusted Signing).

`construir.ps1` lo hace todo (a menos que se use `-SinFirma`):

1. **Primera vez**: crea el certificado en `packaging\firma\` (`crear-certificado.ps1`) con la contraseña que se le pida:
   - `dj-firma.pfx`: clave **privada**, ignorada por git. **Hacer copia de respaldo y no compartirla**: quien la tenga puede firmar programas que las PCs configuradas aceptarán. Si se pierde o se regenera hay que reinstalar el `.cer` en todas las PCs.
   - `dj-firma.cer`: clave pública (válida 5 años).
2. Firma `DistribuidoraDJ.exe`, `DJ-Servicio.exe`, `DJ-Herramientas.exe` y el instalador (con sello de tiempo: la firma sigue válida después de que venza el certificado). Contraseña: se pide, o la variable `DJ_FIRMA_CLAVE`. Requiere el Windows SDK (`signtool.exe`).
3. Mete el `.cer` dentro del instalador: al instalar, la PC pasa a confiar en él (*Raíz de confianza* y *Editores de confianza*; se quita al desinstalar). Así las actualizaciones posteriores ya salen como "Distribuidora DJ".
4. Deja en `build\instalador\` lo necesario para desplegar: `DistribuidoraDJ-Setup-<version>.exe`, `dj-firma.cer` e `Instalar.bat`.

**Desplegar la primera vez en una PC**: copiar los tres archivos y hacer doble clic en `Instalar.bat` (pide administrador, instala el certificado y lanza el instalador; acepta los mismos parámetros que el instalador, p. ej. `/Tipo=ESTACION ...`). Esto evita la advertencia de SmartScreen, que aparece si se ejecuta el `.exe` directamente en una PC que aún no confía en el certificado. Alternativa manual: `firma\confiar-certificado.ps1` (`-Quitar` lo revierte).

El desinstalador que genera Inno Setup no se firma.

## Dónde queda cada cosa en el equipo del cliente

| Qué | Dónde |
|---|---|
| Programa | `C:\Program Files\Distribuidora DJ\` |
| Configuración (`config.env`), logs, estado del reloj | `C:\ProgramData\DistribuidoraDJ\` |
| Datos para instalar estaciones (solo servidor) | `C:\ProgramData\DistribuidoraDJ\datos_estaciones.txt` |
| Servicio de Windows (solo servidor) | `DistribuidoraDJLicencia` (inicio automático, se reinicia si se cae) |
| Regla de firewall (solo servidor) | `Distribuidora DJ - SQL Server` (TCP, el puerto indicado) |

## Requisitos del equipo

Windows 10 versión 1809 (build 17763) o posterior, o Windows Server 2019 o posterior, de 64 bits. El instalador lo exige (`MinVersion`). En versiones anteriores la app falla al abrir con `DLL load failed while importing QtCore`, porque Qt6Core necesita `icuuc.dll` del sistema (existe desde Windows 10 1703).

## Antes de instalar un servidor

- **SQL Server** instalado y el servicio iniciado. Es lo único que hay que instalar a mano; el instalador hace el resto:
  - Habilita **TCP/IP**, fija el **puerto** indicado (1433 por defecto) y pone el **modo mixto** (*SQL Server and Windows Authentication*), cambiando el registro de la instancia y **reiniciando el servicio de SQL Server** (avisa antes; las demás aplicaciones que usen esa instancia pierden la conexión unos segundos). Si no hay nada que cambiar, no reinicia.
  - La instancia se toma de "Servidor SQL" (`localhost` = la instancia predeterminada, lo normal en producción con SQL Server 2019, o la única instalada; `localhost\NOMBRE`, p. ej. `localhost\SQLEXPRESS` en pruebas, = una con nombre). Si el puerto ya lo usa otra instancia, se detiene con un mensaje.
  - Con servidor remoto no toca nada (solo funciona en el mismo equipo). `/ConfigurarSql=0` desactiva este paso si ya lo configuró a mano.
- Un usuario **sysadmin** de SQL Server. Lo más fiable es dejar el usuario vacío (autenticación de Windows) con una cuenta de Windows que sea sysadmin (la que instaló SQL Server lo es por defecto): `sa` está deshabilitado en un SQL Server recién instalado solo con Windows. Se usa solo durante la instalación; no se guarda.

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
- Sin firma, Windows SmartScreen muestra una advertencia al ejecutar el instalador. Ver la sección "Firma del instalador": con el certificado autofirmado, solo desaparece en las PCs que confían en él.
- El empaquetado con PyInstaller **no impide** que alguien con conocimientos extraiga y lea el código; ver `licencias/README.md` ("Qué protege y qué no").

## Qué NO está probado todavía

La configuración automática de SQL Server (`configurar-sql`: registro real de una instancia + reinicio del servicio) solo está probada con un registro y servicios simulados (tests en `tests/test_instalacion.py`). Falta probarla contra un SQL Server recién instalado, preferiblemente en una VM, con **SQL Server 2019 (instancia predeterminada, el caso de producción)** y con Express (instancia con nombre, el de pruebas). No cubre clústeres de conmutación por error.

La instalación como **administrador** en un equipo limpio (creación del servicio con `sc.exe`, regla de firewall, desinstalación, instalación automática de ODBC, actualización con el servicio en marcha) y la apariencia de las pantallas del asistente. Probadas: las herramientas contra SQL Server real, los ejecutables empaquetados, el flujo silencioso (servidor, estación, actualización, datos inválidos) sin privilegios de administrador y la compilación del instalador.
