# Registra (o actualiza) la tarea programada "Estimador TCH mensual" del usuario actual:
# el día 2 de cada mes a las 7:00 corre mensual.ps1 -Publicar; si el PC estaba apagado, corre al encender.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\Agr349\tch-motor\scripts\registrar_tarea.ps1
$nombre = "Estimador TCH mensual"
$raiz = [string][char]92  # carpeta raíz del Programador de tareas

$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$def = $svc.NewTask(0)
$def.RegistrationInfo.Description = "Corrida mensual del Estimador TCH (Earth Engine + ZQM + aforos) y publicación del tablero. Ver tch-motor/scripts/mensual.ps1"
$def.Settings.StartWhenAvailable = $true
$def.Settings.ExecutionTimeLimit = "PT2H"
$def.Settings.DisallowStartIfOnBatteries = $false
$def.Settings.StopIfGoingOnBatteries = $false

$trg = $def.Triggers.Create(4)          # TASK_TRIGGER_MONTHLY
$trg.StartBoundary = "2026-10-02T07:00:00"
$trg.DaysOfMonth = 2                     # máscara de bits: bit 1 = día 2
$trg.MonthsOfYear = 4095                 # los 12 meses

$act = $def.Actions.Create(0)            # TASK_ACTION_EXEC
$act.Path = "powershell.exe"
$act.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Users\Agr349\tch-motor\scripts\mensual.ps1 -Publicar"
$act.WorkingDirectory = "C:\Users\Agr349\tch-motor"

$carpeta = $svc.GetFolder($raiz)
$null = $carpeta.RegisterTaskDefinition($nombre, $def, 6, $null, $null, 3)  # crear o actualizar · sesión interactiva
$t = $carpeta.GetTask($nombre)
Write-Output ("Registrada: " + $t.Name + " | habilitada: " + $t.Enabled + " | próxima ejecución: " + $t.NextRunTime)
