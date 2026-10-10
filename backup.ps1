$ErrorActionPreference = 'Stop'
$guardRoot = $PSScriptRoot
$backupRoot = Join-Path $guardRoot 'backups'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$backupTarget = Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-reference-guard')
New-Item -ItemType Directory -Path $backupTarget | Out-Null
Get-ChildItem -LiteralPath $guardRoot -Force | Where-Object Name -notin '.git','.venv','backups','__pycache__','.pytest_cache' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $backupTarget -Recurse
}
Write-Output "Backup: $backupTarget"
