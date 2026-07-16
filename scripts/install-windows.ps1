# Instalador de PacketProof para Windows.
# Crea una tarea programada que arranca el monitor al iniciar sesión.
# Ejecutar en PowerShell:  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $env:USERPROFILE "packetproof"

Write-Host "==> Verificando Python"
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pyCmd) {
    Write-Error "Python no encontrado. Instalalo desde https://www.python.org/ (marcá 'Add to PATH') o corré 'winget install Python.Python.3.12'"
    exit 1
}
$python = $pyCmd.Source
Write-Host "    Usando: $python"

# pythonw.exe (sin ventana de consola) al lado del python encontrado.
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = "pythonw.exe" }

Write-Host "==> Instalando matplotlib"
& $python -m pip install --user --quiet matplotlib

Write-Host "==> Copiando archivos a $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Recurse -Force (Join-Path $RepoDir "packetproof") $Dest
$cfg = Join-Path $Dest "config.toml"
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $RepoDir "config.example.toml") $cfg
}

Write-Host "==> Probando objetivos"
Push-Location $Dest
try {
    & $python -m packetproof -c $cfg test
} finally {
    Pop-Location
}

Write-Host "==> Creando tarea programada 'PacketProof' (arranca al iniciar sesion)"
$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "-m packetproof -c `"$cfg`" run" -WorkingDirectory $Dest
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Bajo consumo: prioridad baja y no detener por inactividad.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero)
$settings.Priority = 7
Register-ScheduledTask -TaskName "PacketProof" -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName "PacketProof"

Write-Host ""
Write-Host "Listo. PacketProof esta corriendo en segundo plano."
Write-Host "  Reporte: $Dest\packetproof-data\report.html"
Write-Host "  Estado:  Get-ScheduledTask -TaskName PacketProof"
Write-Host "  Detener: Stop-ScheduledTask -TaskName PacketProof"
Write-Host "  Quitar:  Unregister-ScheduledTask -TaskName PacketProof"
