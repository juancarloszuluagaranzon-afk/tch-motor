# Corrida mensual del Estimador TCH (para el Programador de tareas de Windows).
#   1. Corre el motor: Earth Engine + ZQM + base de aforos + maestros -> JSON en tch-dashboard\data
#   2. Con -Publicar: commit y push del tablero (Vercel publica la corrida nueva)
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Agr349\tch-motor\scripts\mensual.ps1 [-Publicar]
param([switch]$Publicar)

$motor = "C:\Users\Agr349\tch-motor"
$tablero = "C:\Users\Agr349\tch-dashboard"
$hoy = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $motor "data\gee\corrida_$hoy.log"

$p = Start-Process -FilePath "$motor\.venv-gee\Scripts\python.exe" `
    -ArgumentList "-u", "`"$motor\scripts\mensual.py`"" -WorkingDirectory $motor `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" -NoNewWindow -Wait -PassThru
if ($p.ExitCode -ne 0) {
    Write-Output "La corrida falló (código $($p.ExitCode)). Revisa $log y $log.err"
    exit $p.ExitCode
}
Get-Content $log -Tail 6 -Encoding UTF8

if ($Publicar) {
    git -C $tablero add data
    git -C $tablero diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Write-Output "Sin cambios en los datos del tablero."; exit 0 }
    git -C $tablero commit -m "Estimados TCH $hoy"
    git -C $tablero push
    # el sitio se publica con la CLI de Vercel (proyecto tch-dashboard enlazado en .vercel);
    # estimador-tch.vercel.app es un alias manual: hay que moverlo al despliegue nuevo
    $vercel = "$env:APPDATA\npm\vercel.cmd"
    $salida = (& $vercel deploy --prod --yes --cwd $tablero 2>&1 | Out-String)
    $m = [regex]::Match($salida, "tch-dashboard-[a-z0-9]+-riegos\.vercel\.app")
    if ($m.Success) {
        & $vercel alias set $m.Value estimador-tch.vercel.app --cwd $tablero
    } else {
        Write-Output "No encontré la URL del despliegue; revisa Vercel. Salida: $salida"
        exit 1
    }
}
