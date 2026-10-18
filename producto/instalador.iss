; Instalador del Estimador TCH (Inno Setup 6). Se arma con construir.ps1, que le pasa la versión.
; Se instala para el usuario (sin permisos de administrador) en %LOCALAPPDATA%\Programs\Estimador TCH.
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{B6B80FB5-8022-493D-B6D2-DF2835D99B5B}
AppName=Estimador TCH
AppVersion={#Version}
AppVerName=Estimador TCH {#Version}
AppPublisher=Riopaila Agrícola
DefaultDirName={localappdata}\Programs\Estimador TCH
DisableDirPage=yes
DefaultGroupName=Estimador TCH
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=EstimadorTCH-Setup-{#Version}
SetupIconFile=icono.ico
UninstallDisplayIcon={app}\EstimadorTCH.exe
UninstallDisplayName=Estimador TCH
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"

[InstallDelete]
; una versión nueva reemplaza todo el programa (la configuración y las llaves viven aparte, en %APPDATA%)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\EstimadorTCH\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Estimador TCH"; Filename: "{app}\EstimadorTCH.exe"
Name: "{autodesktop}\Estimador TCH"; Filename: "{app}\EstimadorTCH.exe"; Tasks: escritorio

[Run]
Filename: "{app}\EstimadorTCH.exe"; Description: "Abrir el Estimador TCH"; Flags: nowait postinstall skipifsilent
