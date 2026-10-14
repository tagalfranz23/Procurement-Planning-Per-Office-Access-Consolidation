# Run from an Administrator PowerShell to restore the existing MariaDB service.
# This does not initialize, migrate, reset, or replace any database.
$ErrorActionPreference = 'Stop'
Set-Service -Name MariaDB -StartupType Automatic
Start-Service -Name MariaDB
$databaseService = Get-Service -Name MariaDB
$databaseService.WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
Get-Service -Name MariaDB | Select-Object Name, Status, StartType
