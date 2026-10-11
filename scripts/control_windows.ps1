param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Venv,
    [string]$SourceRoot = "",
    [string]$Action = "status",
    [switch]$Yes,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
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
    "login" {
        $VenvPython = Join-Path $Venv "Scripts\python.exe"
        $QqLogin = Join-Path $State "qq_login.py"
        if (-not (Test-Path $VenvPython)) { throw "找不到虚拟环境 Python：$VenvPython" }
        if (-not (Test-Path $QqLogin)) { throw "找不到扫码 helper：$QqLogin；请先执行 xiu3 update。" }
        $wasRunning = $null -ne (Get-RunningProcess)
        & $VenvPython $QqLogin "--env" (Join-Path $Target ".env") @Rest
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($wasRunning) {
            Write-Host "[xiu3] QQ 配置已更新，正在重启宿主。"
            Stop-Xiu3
            & $PSCommandPath $Target $Venv $SourceRoot "start"
            exit $LASTEXITCODE
        }
        Write-Host "[xiu3] QQ 配置已更新；下次启动将使用新机器人。"
    }
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
        if ($SourceRoot -and (Test-Path (Join-Path $SourceRoot ".xiuxian3-release")) -and (Test-Path (Join-Path $SourceRoot "scripts\onekey_windows.ps1"))) {
            & (Join-Path $SourceRoot "scripts\onekey_windows.ps1") update $Target -Source $SourceRoot -SourceMode release -Mirror direct
            exit $LASTEXITCODE
        }
        if ($SourceRoot -and (Test-Path (Join-Path $SourceRoot "scripts\install_windows.ps1"))) {
            if (Test-Path (Join-Path $SourceRoot ".git")) {
                $dirty = & git -C $SourceRoot status --porcelain
                if ($dirty) { throw "源码目录有未提交改动，先提交或备份后再更新：$SourceRoot" }
                & git -C $SourceRoot fetch --prune origin
                if ($LASTEXITCODE -ne 0) { throw "Git fetch 失败" }
                & git -C $SourceRoot pull --ff-only origin main
                if ($LASTEXITCODE -ne 0) { throw "Git fast-forward 更新失败" }
            }
            & (Join-Path $SourceRoot "scripts\install_windows.ps1") update $Target --venv $Venv
        } else {
            $VenvPython = Join-Path $Venv "Scripts\python.exe"
            $Components = @(
                @{ Group = "adapter"; Name = "QQ" },
                @{ Group = "adapter"; Name = "OneBot V11" },
                @{ Group = "driver"; Name = "FastAPI" },
                @{ Group = "driver"; Name = "HTTPX" },
                @{ Group = "driver"; Name = "websockets" },
                @{ Group = "driver"; Name = "AIOHTTP" }
            )
            foreach ($Component in $Components) {
                $Description = "nb $($Component.Group) update $($Component.Name)"
                Invoke-Retry {
                    & $Nb --cwd $Target --python $VenvPython $Component.Group update $Component.Name
                } $Description
            }
            & $VenvPython -m pip install --upgrade --no-deps nonebot_plugin_xiuxian_3
            if ($LASTEXITCODE -ne 0) { throw "插件更新失败" }
        }
    }
    "uninstall" {
        if (-not $Yes) { throw "卸载会删除宿主目录及 SQLite 数据；请执行 xiu3 uninstall --yes" }
        Stop-Xiu3
        if ($Target -eq [IO.Path]::GetPathRoot($Target) -or $Target -eq $HOME) { throw "拒绝卸载危险目录：$Target" }
        Remove-Item $Target -Recurse -Force
        Write-Host "[xiu3] 已卸载宿主目录；共享虚拟环境未删除：$Venv"
    }
    default { throw "用法：xiu3 {start|pause|resume|stop|restart|status|update|login|uninstall --yes}" }
}
