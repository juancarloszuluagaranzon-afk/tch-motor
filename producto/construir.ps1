# Arma el instalador del Estimador TCH: recursos -> PyInstaller -> Inno Setup.
# Uso (desde la raíz de tch-motor):  powershell -ExecutionPolicy Bypass -File producto\construir.ps1
# Requisitos: .venv-build con las librerías del motor y PyInstaller (ver producto\README.md) e Inno Setup 6.
$ErrorActionPreference = "Stop"
$producto = $PSScriptRoot
$raiz = Split-Path -Parent $producto
$py = Join-Path $raiz ".venv-build\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Falta el entorno .venv-build (ver producto\README.md)" }
$version = (& $py -c "import sys; sys.path.insert(0, r'$producto'); from app.version import VERSION; print(VERSION)").Trim()
Write-Output "Estimador TCH $version"

Write-Output "1/3 Recursos (tablero, mapas, satélite y última corrida)"
& $py (Join-Path $producto "preparar_recursos.py")
if ($LASTEXITCODE -ne 0) { throw "Falló la preparación de recursos" }

Write-Output "2/3 Empaquetado (PyInstaller)"
New-Item -ItemType Directory -Force (Join-Path $producto "build") | Out-Null
$v = $version.Split(".") + @("0")
$info = @"
VSVersionInfo(ffi=FixedFileInfo(filevers=($($v[0]),$($v[1]),$($v[2]),0), prodvers=($($v[0]),$($v[1]),$($v[2]),0)),
  kids=[StringFileInfo([StringTable('040A04B0', [StringStruct('CompanyName', 'Riopaila Agrícola'),
  StringStruct('FileDescription', 'Estimador TCH'), StringStruct('FileVersion', '$version'),
  StringStruct('ProductName', 'Estimador TCH'), StringStruct('ProductVersion', '$version')])]),
  VarFileInfo([VarStruct('Translation', [1034, 1200])])])
"@
Set-Content -Path (Join-Path $producto "build\version_info.txt") -Value $info -Encoding utf8
Push-Location $producto
try {
  & $py -m PyInstaller EstimadorTCH.spec --noconfirm --clean --distpath dist --workpath build\pyi
  if ($LASTEXITCODE -ne 0) { throw "Falló PyInstaller" }
} finally { Pop-Location }

Write-Output "3/3 Instalador (Inno Setup)"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Output "No encontré Inno Setup 6: el programa quedó en producto\dist\EstimadorTCH (sin instalador)."; exit 0 }
& $iscc "/DVersion=$version" (Join-Path $producto "instalador.iss")
if ($LASTEXITCODE -ne 0) { throw "Falló Inno Setup" }
Write-Output "Listo: producto\dist\EstimadorTCH-Setup-$version.exe"
