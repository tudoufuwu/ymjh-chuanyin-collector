[CmdletBinding()]
param(
    [int]$GamePid,
    [string]$GameProcess = 'wyclx64',
    [int]$Port = 8766,
    [switch]$NoCapture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "找不到 $Python。请先运行 scripts\setup.ps1。"
}

& $Python -m ymjh_chuanyin init --root $ProjectRoot
$RawPath = Join-Path $ProjectRoot 'var\raw\chat-events.jsonl'
$Database = Join-Path $ProjectRoot 'var\archive\chat-archive.db'
$Logs = Join-Path $ProjectRoot 'var\logs'
$Run = Join-Path $ProjectRoot 'var\run'
New-Item -ItemType Directory -Force -Path $Logs, $Run | Out-Null

# This creates the empty SQLite schema before the web server starts.
& $Python -m ymjh_chuanyin import --root $ProjectRoot --input $RawPath --database $Database | Out-Null

$Services = @{}
function Start-LocalService([string]$Name, [string[]]$Arguments) {
    $stdout = Join-Path $Logs "$Name.out.log"
    $stderr = Join-Path $Logs "$Name.err.log"
    $process = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $Services[$Name] = $process.Id
}

Start-LocalService 'importer' @('-m', 'ymjh_chuanyin', 'import', '--root', $ProjectRoot, '--input', $RawPath, '--database', $Database, '--follow')
Start-LocalService 'web' @('-m', 'ymjh_chuanyin', 'serve', '--root', $ProjectRoot, '--database', $Database, '--host', '127.0.0.1', '--port', "$Port")

if (-not $NoCapture) {
    if (-not $GamePid) {
        $processName = [IO.Path]::GetFileNameWithoutExtension($GameProcess)
        $GamePid = (Get-Process -Name $processName -ErrorAction Stop | Select-Object -First 1 -ExpandProperty Id)
    }
    Start-LocalService 'capture' @('-m', 'ymjh_chuanyin', 'capture', '--root', $ProjectRoot, '--pid', "$GamePid", '--out', $RawPath, '--heartbeat', (Join-Path $Run 'capture-heartbeat.txt'), '--quiet')
}

@{ started_at = (Get-Date).ToString('o'); services = $Services } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Run 'services.json')
Write-Host "本地网页已启动：http://127.0.0.1:$Port" -ForegroundColor Green
if ($NoCapture) { Write-Host '只启动了入库和网页；未启动采集器。' -ForegroundColor Yellow }
