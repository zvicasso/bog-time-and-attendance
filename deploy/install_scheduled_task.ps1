<#
.SYNOPSIS
  Run the Time & Attendance Processor persistently on Windows Server 2022
  (starts at boot, restarts automatically if it stops). Uses only built-in
  Windows Task Scheduler - no third-party software.

.EXAMPLE
  # From an elevated PowerShell prompt in the application folder:
  powershell -ExecutionPolicy Bypass -File .\deploy\install_scheduled_task.ps1

.EXAMPLE
  # Run under a dedicated (non-admin) domain or local account instead:
  .\deploy\install_scheduled_task.ps1 -User "CORP\svc-tap" -Password (Read-Host -AsSecureString)
#>
[CmdletBinding()]
param(
    [string]$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "TimeAttendanceProcessor",
    # Low-privilege built-in account by default. Python must be installed "for all users".
    [string]$User = "NT AUTHORITY\LOCAL SERVICE",
    [SecureString]$Password
)

$ErrorActionPreference = "Stop"
$principalCheck = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated (Administrator) PowerShell window."
}

$python = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtual environment not found. Run setup.bat in $AppDir first." }

# The service account needs to write logs and (optionally) the configured temp folder
$logs = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
& icacls $logs /grant "${User}:(OI)(CI)M" | Out-Null
& icacls $AppDir /grant "${User}:(OI)(CI)RX" | Out-Null

$action   = New-ScheduledTaskAction -Execute $python -Argument "-m streamlit run app.py" -WorkingDirectory $AppDir
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

if ($Password) {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User $User -Password $plain -RunLevel Limited -Force `
        -Description "Time & Attendance Processor (Streamlit) - $AppDir" | Out-Null
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType ServiceAccount -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force -Description "Time & Attendance Processor (Streamlit) - $AppDir" | Out-Null
}

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 6
$url = & $python -m tap.urlinfo
Write-Host "Task '$TaskName' registered and started as $User."
Write-Host "Application URL: $url"
try {
    $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 ($url.TrimEnd('/') + "/_stcore/health")
    Write-Host "Health check: $($health.Content)"
} catch {
    Write-Warning "Health check did not respond yet. Check logs\app.log and Task Scheduler history."
}
