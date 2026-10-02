; Instalador de Distribuidora DJ (Inno Setup 6). Un solo instalador con dos modos:
;   SERVIDOR : usa un SQL Server que ya exista, crea la base + el usuario SQL de la app, instala el
;              servicio de Windows de licencia y abre el puerto en el firewall.
;   ESTACION : se conecta al servidor; no instala base de datos ni servicio.
; Se compila con packaging\construir.ps1 (pasa Version, Origen, Herramientas y Salida).
;
; Instalacion silenciosa (todos los datos por parametro; sin ventanas):
;   Servidor : DistribuidoraDJ-Setup.exe /VERYSILENT /Tipo=SERVIDOR /Servidor=localhost /Puerto=1433
;              /Base=distribuidora_dj /AdminSql=sa /ClaveAdminSql=... /ClaveAdminApp=...
;   Estacion : DistribuidoraDJ-Setup.exe /VERYSILENT /Tipo=ESTACION /Servidor=PC-SERVIDOR,1433
;              /Base=distribuidora_dj /UsuarioSql=dj_app /ClaveSql=...
; Registro detallado: agregar /LOG="C:\ruta\instalacion.log".

#ifndef Version
  #define Version "1.0.0"
#endif
#ifndef Origen
  #define Origen "..\build\dist\DistribuidoraDJ"
#endif
#ifndef Herramientas
  #define Herramientas "..\build\herramientas\DJ-Herramientas.exe"
#endif
#ifndef Salida
  #define Salida "..\build\instalador"
#endif

#define Nombre "Distribuidora DJ"
#define Servicio "DistribuidoraDJLicencia"
#define ReglaFirewall "Distribuidora DJ - SQL Server"
#define CertNombre "Distribuidora DJ"

[Setup]
AppId={{E3009BDE-BFFE-421D-A4A6-5939CEC2EEEE}
AppName={#Nombre}
AppVersion={#Version}
AppVerName={#Nombre} {#Version}
AppPublisher={#Nombre}
#ifdef PruebaSinAdmin
DefaultDirName={userappdata}\DJ-Prueba
#else
DefaultDirName={autopf}\{#Nombre}
#endif
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
OutputDir={#Salida}
OutputBaseFilename=DistribuidoraDJ-Setup-{#Version}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef PruebaSinAdmin
PrivilegesRequired=lowest
#else
PrivilegesRequired=admin
#endif
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\DistribuidoraDJ.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
; Dos copias del instalador a la vez corromperian la configuracion.
SetupMutex=DistribuidoraDJSetupMutex

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Dirs]
; Configuracion, logs y estado de licencia. Los usuarios necesitan escribir aqui (logs, reloj).
Name: "{code:DirDatos}"; Permissions: users-modify

[Files]
Source: "{#Origen}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Las herramientas se extraen al arrancar el asistente (para probar la conexion antes de copiar nada)
Source: "{#Herramientas}"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#Herramientas}"; DestDir: "{app}\herramientas"; Flags: ignoreversion
; Controlador ODBC de Microsoft: solo se instala si falta
Source: "redist\msodbcsql.msi"; DestDir: "{tmp}"; Flags: dontcopy
#ifdef Cer
; Certificado publico (autofirmado) con el que se firmo todo: se instala como de confianza en este equipo
Source: "{#Cer}"; DestDir: "{tmp}"; DestName: "dj-firma.cer"; Flags: dontcopy
#endif

[Icons]
Name: "{group}\{#Nombre}"; Filename: "{app}\DistribuidoraDJ.exe"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\DistribuidoraDJ.exe"; Tasks: desktopicon

[Run]
Filename: "notepad.exe"; Parameters: """{code:DirDatos}\datos_estaciones.txt"""; Description: "Ver los datos para instalar las estaciones"; Flags: postinstall shellexec skipifsilent unchecked; Check: MostrarDatosEstaciones
Filename: "{app}\DistribuidoraDJ.exe"; Description: "Abrir {#Nombre}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\sc.exe"; Parameters: "stop {#Servicio}"; Flags: runhidden; RunOnceId: "DetenerServicio"
Filename: "{sys}\sc.exe"; Parameters: "delete {#Servicio}"; Flags: runhidden; RunOnceId: "BorrarServicio"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#ReglaFirewall}"""; Flags: runhidden; RunOnceId: "BorrarFirewall"
#ifdef Cer
Filename: "{sys}\certutil.exe"; Parameters: "-delstore Root ""{#CertNombre}"""; Flags: runhidden; RunOnceId: "QuitarCertRaiz"
Filename: "{sys}\certutil.exe"; Parameters: "-delstore TrustedPublisher ""{#CertNombre}"""; Flags: runhidden; RunOnceId: "QuitarCertEditor"
#endif

[Code]
const
  NOMBRE_SERVICIO = '{#Servicio}';
  REGLA_FIREWALL = '{#ReglaFirewall}';
  BM_CLICK = $00F5;

var
  PgTipo: TInputOptionWizardPage;
  PgServidor: TInputQueryWizardPage;
  PgClavesApp: TInputQueryWizardPage;
  PgEstacion: TInputQueryWizardPage;
  PgActualizar: TInputQueryWizardPage;
  BtnProbarServidor, BtnProbarEstacion: TNewButton;
  EsActualizacion: Boolean;
  ModoPrevio: String;
  SalidaPorFaltaDeSql: Boolean;
  ConfigFallo: Boolean;
  ToolExtraida, OdbcAsegurado: Boolean;
  MensajeConfig: String;

function PostMessage(hWnd: HWND; Msg: UINT; wParam: Longint; lParam: Longint): BOOL;
  external 'PostMessageW@user32.dll stdcall';

{ ---------- utilidades ---------- }

function DirDatos(Param: String): String;
begin
  { /DirDatos=... solo para pruebas automatizadas; en uso normal es ProgramData\DistribuidoraDJ. }
  Result := ExpandConstant('{param:DirDatos|{commonappdata}\DistribuidoraDJ}');
end;

function ArchivoConfig: String;
begin
  Result := DirDatos('') + '\config.env';
end;

function ValorConfig(const Clave: String): String;
var
  Lineas: TArrayOfString;
  I, P: Integer;
begin
  Result := '';
  if LoadStringsFromFile(ArchivoConfig, Lineas) then
    for I := 0 to GetArrayLength(Lineas) - 1 do
    begin
      P := Pos('=', Lineas[I]);
      if (P > 1) and (CompareText(Trim(Copy(Lineas[I], 1, P - 1)), Clave) = 0) then
      begin
        Result := Trim(Copy(Lineas[I], P + 1, MaxInt));
        Exit;
      end;
    end;
end;

function JsonEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
  StringChangeEx(Result, #9, '\t', True);
  StringChangeEx(Result, #13, '', True);
  StringChangeEx(Result, #10, '', True);
end;

function BoolJson(const Valor: Boolean): String;
begin
  if Valor then Result := 'true' else Result := 'false';
end;

function Par(const Nombre, Defecto: String): String;
begin
  Result := ExpandConstant('{param:' + Nombre + '|' + Defecto + '}');
end;

{ ---------- ODBC y herramientas ---------- }

function OdbcInstalado: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server');
end;

function SqlServerInstalado: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL')
         or RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL');
end;

function AsegurarOdbc: Boolean;
var
  Res: Integer;
begin
  Result := True;
  if OdbcAsegurado or OdbcInstalado then
  begin
    OdbcAsegurado := True;
    Exit;
  end;
  ExtractTemporaryFile('msodbcsql.msi');
  WizardForm.StatusLabel.Caption := 'Instalando Microsoft ODBC Driver 18 para SQL Server...';
  if not Exec('msiexec.exe', '/i "' + ExpandConstant('{tmp}\msodbcsql.msi') + '" /qn IACCEPTMSODBCSQLLICENSETERMS=YES /norestart',
              '', SW_HIDE, ewWaitUntilTerminated, Res) or ((Res <> 0) and (Res <> 3010)) then
  begin
    SuppressibleMsgBox('No se pudo instalar Microsoft ODBC Driver 18 para SQL Server (codigo ' + IntToStr(Res) + ').' + #13#10 +
           'Instalelo manualmente desde https://aka.ms/downloadmsodbcsql y vuelva a ejecutar este instalador.', mbError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  OdbcAsegurado := True;
end;

function RutaHerramientas: String;
begin
  Result := ExpandConstant('{tmp}\DJ-Herramientas.exe');
end;

procedure ExtraerHerramientas;
begin
  if not ToolExtraida then
  begin
    ExtractTemporaryFile('DJ-Herramientas.exe');
    ToolExtraida := True;
  end;
end;

{ Ejecuta DJ-Herramientas.exe <comando>. Los datos viajan en un JSON temporal (no por la linea de
  comandos, donde otros procesos podrian leer las claves) que se borra al terminar. }
function EjecutarTool(const Comando, Json: String; var Mensaje: String): Boolean;
var
  Entrada, Salida: String;
  Res, P: Integer;
  Lineas: TArrayOfString;
  Texto: AnsiString;
begin
  Result := False;
  Mensaje := 'No se pudo ejecutar las herramientas de instalacion.';
  ExtraerHerramientas;
  Entrada := ExpandConstant('{tmp}\dj_entrada.json');
  Salida := ExpandConstant('{tmp}\dj_salida.txt');
  DeleteFile(Salida);
  SetArrayLength(Lineas, 1);
  Lineas[0] := Json;
  SaveStringsToUTF8File(Entrada, Lineas, False);
  try
    if Exec(RutaHerramientas, Comando + ' --entrada "' + Entrada + '" --salida "' + Salida + '"', '', SW_HIDE,
            ewWaitUntilTerminated, Res) then
      if LoadStringFromFile(Salida, Texto) then
      begin
        Mensaje := Trim(String(Texto));
        Result := (Pos('OK', Mensaje) = 1);
        P := Pos(#10, Mensaje);
        if P > 0 then
          Mensaje := Trim(Copy(Mensaje, P + 1, MaxInt));
      end;
  finally
    DeleteFile(Entrada);
  end;
end;

function SoloHost(const Servidor: String): String;
var
  P: Integer;
begin
  Result := Servidor;
  P := Pos(',', Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
end;

{ ---------- valores segun el modo (asistente o parametros /Nombre=valor en modo silencioso) ---------- }

function EsServidor: Boolean;
begin
  if EsActualizacion then
    Result := (ModoPrevio = 'SERVIDOR')
  else if WizardSilent then
    Result := (Uppercase(Par('Tipo', 'SERVIDOR')) = 'SERVIDOR')
  else
    Result := (PgTipo.SelectedValueIndex = 0);
end;

function ValServidor: String;
begin
  if WizardSilent then Result := Par('Servidor', 'localhost') else Result := Trim(PgServidor.Values[0]);
end;
function ValPuerto: String;
begin
  if WizardSilent then Result := Par('Puerto', '1433') else Result := Trim(PgServidor.Values[1]);
  { El instalador fija este puerto en SQL Server (ver ConfigurarSqlLocal), asi que nunca queda vacio. }
  if Result = '' then Result := '1433';
end;
function ConfigurarSqlActivado: Boolean;
begin
  { /ConfigurarSql=0 deja SQL Server tal cual (el administrador ya lo configuro a mano). }
  Result := (Par('ConfigurarSql', '1') <> '0');
end;
function ValBase: String;
begin
  if WizardSilent then Result := Par('Base', 'distribuidora_dj') else Result := Trim(PgServidor.Values[2]);
end;
function ValAdminSql: String;
begin
  if EsActualizacion then
  begin
    if WizardSilent then Result := Par('AdminSql', '') else Result := Trim(PgActualizar.Values[0]);
  end
  else if WizardSilent then Result := Par('AdminSql', '') else Result := Trim(PgServidor.Values[3]);
end;
function ValClaveAdminSql: String;
begin
  if EsActualizacion then
  begin
    if WizardSilent then Result := Par('ClaveAdminSql', '') else Result := PgActualizar.Values[1];
  end
  else if WizardSilent then Result := Par('ClaveAdminSql', '') else Result := PgServidor.Values[4];
end;
function ValClaveAdminApp: String;
begin
  if WizardSilent then Result := Par('ClaveAdminApp', '') else Result := PgClavesApp.Values[0];
end;
function ValServidorEstacion: String;
begin
  if WizardSilent then Result := Par('Servidor', '') else Result := Trim(PgEstacion.Values[0]);
end;
function ValBaseEstacion: String;
begin
  if WizardSilent then Result := Par('Base', 'distribuidora_dj') else Result := Trim(PgEstacion.Values[1]);
end;
function ValUsuarioEstacion: String;
begin
  if WizardSilent then Result := Par('UsuarioSql', '') else Result := Trim(PgEstacion.Values[2]);
end;
function ValClaveEstacion: String;
begin
  if WizardSilent then Result := Par('ClaveSql', '') else Result := PgEstacion.Values[3];
end;

function JsonConexionAdmin(const ExigirAdmin: Boolean): String;
begin
  Result := '{"servidor":"' + JsonEscape(ValServidor) + '","puerto":"' + JsonEscape(ValPuerto) + '",' +
            '"usuario":"' + JsonEscape(ValAdminSql) + '","clave":"' + JsonEscape(ValClaveAdminSql) + '",' +
            '"windows_auth":' + BoolJson(ValAdminSql = '') + ',';
  if ExigirAdmin then Result := Result + '"requiere_sysadmin":true,';
  Result := Result + '"base":""}';
end;

{ Deja el SQL Server de ESTE equipo listo (TCP/IP, puerto fijo, modo mixto). Si hay que cambiar algo reinicia el
  servicio de SQL Server, asi que antes pregunta (en modo silencioso se hace sin preguntar). True = se puede seguir. }
function ConfigurarSqlLocal: Boolean;
var
  Json, Mensaje: String;
begin
  Result := True;
  if not ConfigurarSqlActivado then Exit;
  Json := '{"servidor":"' + JsonEscape(ValServidor) + '","puerto":"' + JsonEscape(ValPuerto) + '","solo_diagnostico":true}';
  if not EjecutarTool('configurar-sql', Json, Mensaje) then
  begin
    MsgBox(Mensaje, mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if Pos('CAMBIOS:', Mensaje) <> 1 then
  begin
    Log('configurar-sql: ' + Mensaje);
    Exit;
  end;
  if not WizardSilent then
    if SuppressibleMsgBox('Para que las estaciones puedan conectarse hay que cambiar la configuracion de SQL Server en este equipo:' + #13#10 + #13#10 +
         Copy(Mensaje, Length('CAMBIOS:') + 2, MaxInt) + #13#10 + #13#10 +
         'Se reiniciara el servicio de SQL Server (las aplicaciones que lo usen perderan la conexion unos segundos). ' +
         'Desea continuar?', mbConfirmation, MB_YESNO, IDYES) <> IDYES then
    begin
      Result := False;
      Exit;
    end;
  WizardForm.NextButton.Enabled := False;
  try
    Json := '{"servidor":"' + JsonEscape(ValServidor) + '","puerto":"' + JsonEscape(ValPuerto) + '"}';
    Result := EjecutarTool('configurar-sql', Json, Mensaje);
  finally
    WizardForm.NextButton.Enabled := True;
  end;
  Log('configurar-sql: ' + Mensaje);
  if not Result then MsgBox(Mensaje, mbError, MB_OK);
end;

{ ---------- paginas del asistente ---------- }

procedure ProbarServidorClick(Sender: TObject);
var
  Mensaje: String;
begin
  if not AsegurarOdbc then Exit;
  if EjecutarTool('probar', JsonConexionAdmin(True), Mensaje) then
    MsgBox(Mensaje, mbInformation, MB_OK)
  else
    MsgBox(Mensaje, mbError, MB_OK);
end;

procedure ProbarEstacionClick(Sender: TObject);
var
  Mensaje, Json: String;
begin
  if not AsegurarOdbc then Exit;
  Json := '{"servidor":"' + JsonEscape(ValServidorEstacion) + '","base":"' + JsonEscape(ValBaseEstacion) +
          '","usuario":"' + JsonEscape(ValUsuarioEstacion) + '","clave":"' + JsonEscape(ValClaveEstacion) + '"}';
  if EjecutarTool('probar', Json, Mensaje) then
    MsgBox(Mensaje, mbInformation, MB_OK)
  else
    MsgBox(Mensaje, mbError, MB_OK);
end;

procedure InitializeWizard;
begin
  EsActualizacion := FileExists(ArchivoConfig) and (ValorConfig('DB_SERVER') <> '');
  if EsActualizacion then ModoPrevio := Uppercase(ValorConfig('MODO_INSTALACION'));

  PgTipo := CreateInputOptionPage(wpSelectDir, 'Tipo de instalacion',
    'Elija como se usara este equipo.', 'Seleccione una opcion:', True, False);
  PgTipo.Add('Servidor: aloja la base de datos y gestiona la licencia de toda la red (un solo equipo por empresa).');
  PgTipo.Add('Estacion: un puesto de trabajo que se conecta al servidor.');
  PgTipo.SelectedValueIndex := 0;

  PgServidor := CreateInputQueryPage(PgTipo.ID, 'Conexion con SQL Server',
    'Se usara un SQL Server que ya exista en este equipo.',
    'Indique como conectarse. El instalador habilita TCP/IP, fija el puerto y el modo mixto en SQL Server (puede reiniciar el servicio), y crea la base de datos y un usuario propio de la aplicacion. Las credenciales de administrador solo se usan durante la instalacion y no se guardan. Con autenticacion de Windows (usuario vacio) su cuenta debe ser administradora de SQL Server.');
  PgServidor.Add('Servidor SQL (nombre, IP o nombre\instancia):', False);
  PgServidor.Add('Puerto TCP (el instalador lo fija en SQL Server para que las estaciones se conecten):', False);
  PgServidor.Add('Nombre de la base de datos:', False);
  PgServidor.Add('Usuario administrador de SQL (vacio = autenticacion de Windows):', False);
  PgServidor.Add('Contrasena del administrador de SQL:', True);
  PgServidor.Values[0] := 'localhost';
  PgServidor.Values[1] := '1433';
  PgServidor.Values[2] := 'distribuidora_dj';
  { Vacio = autenticacion de Windows: funciona aunque 'sa' este deshabilitado (SQL recien instalado solo con Windows auth). }
  PgServidor.Values[3] := '';

  BtnProbarServidor := TNewButton.Create(PgServidor);
  BtnProbarServidor.Parent := PgServidor.Surface;
  BtnProbarServidor.Caption := 'Probar conexion';
  BtnProbarServidor.Width := ScaleX(120);
  BtnProbarServidor.Height := ScaleY(26);
  { En la fila de la etiqueta de la contrasena (a la derecha del texto): abajo del todo taparia el campo. }
  BtnProbarServidor.Left := PgServidor.Edits[4].Left + PgServidor.Edits[4].Width - BtnProbarServidor.Width;
  BtnProbarServidor.Top := PgServidor.PromptLabels[4].Top - ScaleY(5);
  BtnProbarServidor.Anchors := [akTop, akRight];
  BtnProbarServidor.OnClick := @ProbarServidorClick;

  PgClavesApp := CreateInputQueryPage(PgServidor.ID, 'Usuario administrador de la aplicacion',
    'Cree la contrasena del usuario "admin" con la que entrara por primera vez.',
    'Debe tener al menos una mayuscula, una minuscula, un numero y un caracter especial.');
  PgClavesApp.Add('Contrasena del usuario "admin":', True);
  PgClavesApp.Add('Repita la contrasena:', True);

  PgEstacion := CreateInputQueryPage(PgClavesApp.ID, 'Conexion con el servidor',
    'Esta estacion se conectara a la base de datos del servidor.',
    'Use los datos que el instalador del servidor guardo en "datos_estaciones.txt" (carpeta ProgramData\DistribuidoraDJ del servidor).');
  PgEstacion.Add('Servidor SQL (nombre o IP del servidor, coma y puerto; ej. SERVIDOR,1433):', False);
  PgEstacion.Add('Nombre de la base de datos:', False);
  PgEstacion.Add('Usuario SQL de la aplicacion:', False);
  PgEstacion.Add('Contrasena:', True);
  PgEstacion.Values[1] := 'distribuidora_dj';

  BtnProbarEstacion := TNewButton.Create(PgEstacion);
  BtnProbarEstacion.Parent := PgEstacion.Surface;
  BtnProbarEstacion.Caption := 'Probar conexion';
  BtnProbarEstacion.Width := ScaleX(120);
  BtnProbarEstacion.Height := ScaleY(26);
  BtnProbarEstacion.Left := PgEstacion.Edits[3].Left + PgEstacion.Edits[3].Width - BtnProbarEstacion.Width;
  BtnProbarEstacion.Top := PgEstacion.PromptLabels[3].Top - ScaleY(5);
  BtnProbarEstacion.Anchors := [akTop, akRight];
  BtnProbarEstacion.OnClick := @ProbarEstacionClick;

  PgActualizar := CreateInputQueryPage(PgEstacion.ID, 'Actualizacion del servidor',
    'Se detecto una instalacion previa. Se actualizara la base de datos.',
    'Indique un administrador de SQL Server para aplicar los cambios de esquema (vacio = autenticacion de Windows).');
  PgActualizar.Add('Usuario administrador de SQL (vacio = autenticacion de Windows):', False);
  PgActualizar.Add('Contrasena:', True);
  PgActualizar.Values[0] := 'sa';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if EsActualizacion then
  begin
    if (PageID = PgTipo.ID) or (PageID = PgServidor.ID) or (PageID = PgClavesApp.ID) or (PageID = PgEstacion.ID) then
      Result := True
    else if PageID = PgActualizar.ID then
      Result := (ModoPrevio <> 'SERVIDOR');
  end
  else
  begin
    if PageID = PgActualizar.ID then
      Result := True
    else if (PageID = PgServidor.ID) or (PageID = PgClavesApp.ID) then
      Result := not EsServidor
    else if PageID = PgEstacion.ID then
      Result := EsServidor;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if SalidaPorFaltaDeSql then Confirm := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Mensaje, Json: String;
begin
  Result := True;

  if (not EsActualizacion) and (CurPageID = PgTipo.ID) and EsServidor then
  begin
    if not SqlServerInstalado then
    begin
      MsgBox('No se encontro SQL Server en este equipo.' + #13#10 + #13#10 +
             'La instalacion como Servidor necesita un SQL Server existente. Instale SQL Server 2019 o posterior (para pruebas sirve la edicion Express, que es gratuita: ' +
             'https://www.microsoft.com/sql-server/sql-server-downloads), verifique que el servicio este iniciado y vuelva a ' +
             'ejecutar este instalador desde el principio.' + #13#10 + #13#10 + 'La instalacion se cerrara ahora.',
             mbError, MB_OK);
      SalidaPorFaltaDeSql := True;
      PostMessage(WizardForm.CancelButton.Handle, BM_CLICK, 0, 0);
      Result := False;
    end;
    Exit;
  end;

  if (not EsActualizacion) and (CurPageID = PgServidor.ID) then
  begin
    if (ValServidor = '') or (ValBase = '') then
    begin
      MsgBox('Indique el servidor SQL y el nombre de la base de datos.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not AsegurarOdbc then begin Result := False; Exit; end;
    if not ConfigurarSqlLocal then begin Result := False; Exit; end;
    WizardForm.NextButton.Enabled := False;
    try
      Result := EjecutarTool('probar', JsonConexionAdmin(True), Mensaje);
    finally
      WizardForm.NextButton.Enabled := True;
    end;
    if not Result then MsgBox(Mensaje, mbError, MB_OK);
    Exit;
  end;

  if (not EsActualizacion) and (CurPageID = PgClavesApp.ID) then
  begin
    if (not WizardSilent) and (PgClavesApp.Values[0] <> PgClavesApp.Values[1]) then
    begin
      MsgBox('Las contrasenas no coinciden.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    Json := '{"clave":"' + JsonEscape(ValClaveAdminApp) + '"}';
    Result := EjecutarTool('validar-clave', Json, Mensaje);
    if not Result then MsgBox(Mensaje, mbError, MB_OK);
    Exit;
  end;

  if (not EsActualizacion) and (CurPageID = PgEstacion.ID) then
  begin
    if (ValServidorEstacion = '') or (ValBaseEstacion = '') or (ValUsuarioEstacion = '') or (ValClaveEstacion = '') then
    begin
      MsgBox('Complete todos los datos de conexion con el servidor.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not AsegurarOdbc then begin Result := False; Exit; end;
    Json := '{"servidor":"' + JsonEscape(ValServidorEstacion) + '","base":"' + JsonEscape(ValBaseEstacion) +
            '","usuario":"' + JsonEscape(ValUsuarioEstacion) + '","clave":"' + JsonEscape(ValClaveEstacion) + '"}';
    Result := EjecutarTool('probar', Json, Mensaje);
    if not Result then MsgBox(Mensaje, mbError, MB_OK);
    Exit;
  end;

  if EsActualizacion and (CurPageID = PgActualizar.ID) then
  begin
    if not AsegurarOdbc then begin Result := False; Exit; end;
    Json := '{"servidor":"' + JsonEscape(ValorConfig('DB_SERVER')) + '","base":"' + JsonEscape(ValorConfig('DB_NAME')) +
            '","usuario":"' + JsonEscape(ValAdminSql) + '","clave":"' + JsonEscape(ValClaveAdminSql) +
            '","windows_auth":' + BoolJson(ValAdminSql = '') + ',"requiere_sysadmin":true}';
    Result := EjecutarTool('probar', Json, Mensaje);
    if not Result then MsgBox(Mensaje, mbError, MB_OK);
    Exit;
  end;
end;

{ ---------- instalacion ---------- }

{ Hace que este equipo confie en lo firmado por Distribuidora DJ (certificado autofirmado). No es fatal si falla. }
procedure InstalarCertificado;
#ifdef Cer
var
  Res: Integer;
  Cert, Almacen: String;
  I: Integer;
begin
  ExtractTemporaryFile('dj-firma.cer');
  Cert := ExpandConstant('{tmp}\dj-firma.cer');
  for I := 0 to 1 do
  begin
    if I = 0 then Almacen := 'Root' else Almacen := 'TrustedPublisher';
    if not Exec(ExpandConstant('{sys}\certutil.exe'), '-addstore -f ' + Almacen + ' "' + Cert + '"', '', SW_HIDE,
                ewWaitUntilTerminated, Res) or (Res <> 0) then
      Log('No se pudo instalar el certificado en ' + Almacen + ' (codigo ' + IntToStr(Res) + ')');
  end;
end;
#else
begin
end;
#endif

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Res: Integer;
begin
  Result := '';
  InstalarCertificado;
  { En una actualizacion el servicio mantiene bloqueados sus archivos: se detiene antes de copiar. }
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + NOMBRE_SERVICIO, '', SW_HIDE, ewWaitUntilTerminated, Res);
  Sleep(2500);
  if EsServidor and (not EsActualizacion) and (not SqlServerInstalado) then
  begin
    Result := 'No se encontro SQL Server en este equipo. Instale SQL Server y vuelva a ejecutar el instalador.';
    Exit;
  end;
  if not AsegurarOdbc then Result := 'No se pudo instalar el controlador ODBC de SQL Server.';
end;

procedure InstalarServicioYFirewall;
var
  Res: Integer;
  Exe, Puerto: String;
begin
  Exe := ExpandConstant('{app}\DJ-Servicio.exe');
  { Si ya existe (actualizacion) se conserva; si no, se crea con inicio automatico. }
  if not Exec(ExpandConstant('{sys}\sc.exe'), 'query ' + NOMBRE_SERVICIO, '', SW_HIDE, ewWaitUntilTerminated, Res) or (Res <> 0) then
  begin
    Exec(ExpandConstant('{sys}\sc.exe'),
         'create ' + NOMBRE_SERVICIO + ' binPath= "\"' + Exe + '\"" start= auto DisplayName= "Distribuidora DJ - Licencia"',
         '', SW_HIDE, ewWaitUntilTerminated, Res);
    Exec(ExpandConstant('{sys}\sc.exe'),
         'description ' + NOMBRE_SERVICIO + ' "Mantiene validada la licencia de Distribuidora DJ para el servidor y todas sus estaciones."',
         '', SW_HIDE, ewWaitUntilTerminated, Res);
    { Si el proceso se cae, Windows lo reinicia a los 60 s (3 veces; el contador se limpia a las 24 h). }
    Exec(ExpandConstant('{sys}\sc.exe'),
         'failure ' + NOMBRE_SERVICIO + ' reset= 86400 actions= restart/60000/restart/60000/restart/60000',
         '', SW_HIDE, ewWaitUntilTerminated, Res);
  end;
  Exec(ExpandConstant('{sys}\sc.exe'), 'start ' + NOMBRE_SERVICIO, '', SW_HIDE, ewWaitUntilTerminated, Res);

  { Puerto de SQL Server abierto para las estaciones (solo si se indico un puerto fijo). }
  if not EsActualizacion then
  begin
    Puerto := ValPuerto;
    if Puerto <> '' then
    begin
      Exec(ExpandConstant('{sys}\netsh.exe'), 'advfirewall firewall delete rule name="' + REGLA_FIREWALL + '"', '', SW_HIDE, ewWaitUntilTerminated, Res);
      Exec(ExpandConstant('{sys}\netsh.exe'),
           'advfirewall firewall add rule name="' + REGLA_FIREWALL + '" dir=in action=allow protocol=TCP localport=' + Puerto,
           '', SW_HIDE, ewWaitUntilTerminated, Res);
    end;
  end;
end;

procedure ConfigurarInstalacion;
var
  Json, Mensaje, ClaveApp: String;
  Ok: Boolean;
begin
  Ok := False;
  MensajeConfig := '';

  if EsActualizacion then
  begin
    if EsServidor then
    begin
      Json := '{"usuario_admin":"' + JsonEscape(ValAdminSql) + '","clave_admin":"' + JsonEscape(ValClaveAdminSql) +
              '","windows_auth":' + BoolJson(ValAdminSql = '') + ',"config_destino":"' + JsonEscape(ArchivoConfig) + '"}';
      Ok := EjecutarTool('actualizar', Json, Mensaje);
      MensajeConfig := Mensaje;
      if Ok then InstalarServicioYFirewall;
    end
    else
      Ok := True;
  end
  else if EsServidor then
  begin
    { Clave aleatoria para el usuario SQL propio de la aplicacion. }
    if not EjecutarTool('generar-clave', '{}', ClaveApp) then
    begin
      MensajeConfig := ClaveApp;
    end
    else
    begin
      Json := '{"servidor":"' + JsonEscape(ValServidor) + '","puerto":"' + JsonEscape(ValPuerto) + '","base":"' + JsonEscape(ValBase) +
              '","usuario_admin":"' + JsonEscape(ValAdminSql) + '","clave_admin":"' + JsonEscape(ValClaveAdminSql) +
              '","windows_auth":' + BoolJson(ValAdminSql = '') + ',"usuario_app":"dj_app","clave_app":"' + JsonEscape(ClaveApp) +
              '","clave_admin_app":"' + JsonEscape(ValClaveAdminApp) + '","config_destino":"' + JsonEscape(ArchivoConfig) + '"}';
      Ok := EjecutarTool('servidor', Json, Mensaje);
      MensajeConfig := Mensaje;
      if Ok then InstalarServicioYFirewall;
    end;
  end
  else
  begin
    Json := '{"servidor":"' + JsonEscape(ValServidorEstacion) + '","base":"' + JsonEscape(ValBaseEstacion) +
            '","usuario":"' + JsonEscape(ValUsuarioEstacion) + '","clave":"' + JsonEscape(ValClaveEstacion) +
            '","config_destino":"' + JsonEscape(ArchivoConfig) + '"}';
    Ok := EjecutarTool('estacion', Json, Mensaje);
    MensajeConfig := Mensaje;
  end;

  ConfigFallo := not Ok;
  if ConfigFallo then
  begin
    Log('Fallo la configuracion: ' + MensajeConfig);
    SuppressibleMsgBox('La aplicacion se copio, pero la configuracion de la base de datos fallo:' + #13#10 + #13#10 + MensajeConfig +
           '' + #13#10 + #13#10 + 'Corrija el problema y vuelva a ejecutar este instalador (es seguro repetirlo).', mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ConfigurarInstalacion;
end;

function MostrarDatosEstaciones: Boolean;
begin
  Result := (not ConfigFallo) and (not EsActualizacion) and EsServidor
            and FileExists(DirDatos('') + '\datos_estaciones.txt');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('Se conservaron la configuracion (' + DirDatos('') + ') y la base de datos. ' +
           'Elimine esa carpeta manualmente si ya no la necesita.', mbInformation, MB_OK);
end;
