<#
.SYNOPSIS
  Allow other computers on the INTERNAL network to reach the application.
  Only needed when .streamlit\config.toml binds to the server's internal IP.

.EXAMPLE
  # Allow only the HR / Finance subnet (recommended):
  .\deploy\open_firewall.ps1 -RemoteAddress 10.20.30.0/24

.EXAMPLE
  # Allow the server's local subnet:
  .\deploy\open_firewall.ps1
#>
param(
    [int]$Port = 8501,
    [string]$RemoteAddress = "LocalSubnet",
    [string]$RuleName = "Time and Attendance Processor"
)
$ErrorActionPreference = "Stop"
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol TCP -LocalPort $Port `
    -RemoteAddress $RemoteAddress -Action Allow -Profile Domain,Private | Out-Null
Write-Host "Inbound TCP $Port allowed from $RemoteAddress (Domain/Private profiles only)."
Write-Host "Never expose this port to the internet (Public profile is not opened)."
