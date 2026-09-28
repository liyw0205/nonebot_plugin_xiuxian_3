param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Venv,
    [string]$SourceRoot = "",
    [string]$Action = "status",
    [switch]$Yes
)
$ErrorActionPreference = "Stop"

$Target = [IO.Path]::GetFullPath($Target)
$Venv = [IO.Path]::GetFullPath($Venv)
$State = Join-Path $Target ".xiuxian3"
$PidFile = Join-Path $State "nb.pid"
$LogFile = Join-Path $State "nb.log"
$Nb = Join-Path $Venv "Scripts\nb.exe"
New-Item -ItemType Directory -Force -Path $State | Out-Null

function Get-RunningProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content -Raw $PidFile).Trim()
    if (-not $raw -or $raw -notmatch '^\d+$') { return $null }
    try { return Get-Process -Id ([int]$raw) -ErrorAction Stop } catch { return $null }
}

function Stop-Xiu3 {
    $process = Get-RunningProcess
    if ($null -eq $process) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "[xiu3] 已停止"
        return
    }
    Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
    Wait-Process -Id $process.Id -Timeout 20 -ErrorAction SilentlyContinue
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "[xiu3] stopped"
}

switch ($Action) {
    "start" {
        if ($null -ne (Get-RunningProcess)) { Write-Host "[xiu3] 已经在运行"; break }
        if (-not (Test-Path $Nb)) { throw "找不到 nb：$Nb；请先执行 xiu3 update。" }
        Remove-Item $LogFile -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $Nb -ArgumentList "run" -WorkingDirectory $Target -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile -PassThru
        Set-Content -Path $PidFile -Value $process.Id
        Start-Sleep -Seconds 1
        if ($null -eq (Get-RunningProcess)) { throw "启动失败，请查看 $LogFile" }
        Write-Host "[xiu3] started pid=$($process.Id)"
        Write-Host "[xiu3] log=$LogFile"
    }
    "stop" { Stop-Xiu3 }
    "restart" { Stop-Xiu3; & $PSCommandPath $Target $Venv $SourceRoot "start" }
    "status" {
        $process = Get-RunningProcess
        if ($null -eq $process) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue; Write-Host "[xiu3] stopped"; exit 3 }
        Write-Host "[xiu3] running pid=$($process.Id)"
        Write-Host "[xiu3] log=$LogFile"
    }
    "pause" {
        $process = Get-RunningProcess
        if ($null -eq $process) { throw "当前未运行" }
        $suspend = Get-Command Suspend-Process -ErrorAction SilentlyContinue
        if ($null -eq $suspend) { throw "当前 PowerShell 没有 Suspend-Process；请使用 stop，或安装 PowerShell 7。" }
        Suspend-Process -Id $process.Id
        Write-Host "[xiu3] paused pid=$($process.Id)"
    }
    "resume" {
        if (-not (Test-Path $PidFile)) { throw "当前没有可恢复的进程" }
        $processId = [int](Get-Content -Raw $PidFile)
        $resume = Get-Command Resume-Process -ErrorAction SilentlyContinue
        if ($null -eq $resume) { throw "当前 PowerShell 没有 Resume-Process；请使用 stop/start，或安装 PowerShell 7。" }
        Resume-Process -Id $processId
        Write-Host "[xiu3] resumed pid=$processId"
    }
    "update" {
        if ($SourceRoot -and (Test-Path (Join-Path $SourceRoot "scripts\install_windows.ps1"))) {
            & (Join-Path $SourceRoot "scripts\install_windows.ps1") update $Target --venv $Venv
        } else {
            & (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade --upgrade-strategy eager "nonebot_plugin_xiuxian_3[nonebot,onebot,qq]"
        }
    }
    "uninstall" {
        if (-not $Yes) { throw "卸载会删除宿主目录及 SQLite 数据；请执行 xiu3 uninstall --yes" }
        Stop-Xiu3
        if ($Target -eq [IO.Path]::GetPathRoot($Target) -or $Target -eq $HOME) { throw "拒绝卸载危险目录：$Target" }
        Remove-Item $Target -Recurse -Force
        Write-Host "[xiu3] 已卸载宿主目录；共享虚拟环境未删除：$Venv"
    }
    default { throw "用法：xiu3 {start|pause|resume|stop|restart|status|update|uninstall --yes}" }
}
