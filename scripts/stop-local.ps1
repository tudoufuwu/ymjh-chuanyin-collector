[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StatePath = Join-Path $ProjectRoot 'var\run\services.json'
if (-not (Test-Path $StatePath)) {
    Write-Host '没有找到本项目启动记录。'
    exit 0
}

$state = Get-Content -Raw -Encoding utf8 $StatePath | ConvertFrom-Json
foreach ($property in $state.services.PSObject.Properties) {
    $pid = [int]$property.Value
    try {
        Stop-Process -Id $pid -ErrorAction Stop
        Write-Host "已请求停止 $($property.Name)（PID $pid）"
    } catch {
        Write-Host "$($property.Name)（PID $pid）已不在运行。"
    }
}
Remove-Item -Force $StatePath
