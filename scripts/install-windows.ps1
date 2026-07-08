# Instalador de PacketProof para Windows.
# Crea una tarea programada que arranca el monitor al iniciar sesión.
# Ejecutar en PowerShell:  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $env:USERPROFILE "packetproof"

Write-Host "==> Verificando Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python no encontrado. Instalalo desde https://www.python.org/ o 'winget install Python.Python.3.12'"
    exit 1
}

Write-Host "==> Instalando matplotlib"
python -m pip install --user --quiet matplotlib

Write-Host "==> Copiando archivos a $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Recurse -Force (Join-Path $RepoDir "packetproof") $Dest
$cfg = Join-Path $Dest "config.toml"
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $RepoDir "config.example.toml") $cfg
}

Write-Host "==> Probando objetivos"
python -m packetproof -c $cfg test

Write-Host "==> Creando tarea programada 'PacketProof' (arranca al iniciar sesion)"
$action = New-ScheduledTaskAction -Execute "pythonw.exe" `
    -Argument "-m packetproof -c `"$cfg`" run" -WorkingDirectory $Dest
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Bajo consumo: prioridad baja y sin arrancar si hay poca bateria.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero)
$settings.Priority = 7
Register-ScheduledTask -TaskName "PacketProof" -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName "PacketProof"

Write-Host ""
Write-Host "Listo. PacketProof esta corriendo en segundo plano."
Write-Host "  Reporte: $Dest\packetproof-data\report.html"
Write-Host "  Detener: Stop-ScheduledTask -TaskName PacketProof"
Write-Host "  Quitar:  Unregister-ScheduledTask -TaskName PacketProof"
