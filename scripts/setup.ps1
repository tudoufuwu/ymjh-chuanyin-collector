[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
    & $Python -m venv (Join-Path $ProjectRoot '.venv')
}

& $VenvPython -m pip install --no-build-isolation --editable $ProjectRoot
Write-Host "安装完成。运行：$ProjectRoot\scripts\start-local.ps1" -ForegroundColor Green
