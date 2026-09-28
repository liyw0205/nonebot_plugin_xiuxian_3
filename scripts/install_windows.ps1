$ErrorActionPreference = "Stop"

function Show-Usage {
    @"
用法：scripts\install_windows.ps1 [目标宿主目录] [选项]

选项：
  --python PATH       指定系统 Python（默认使用 py -3）
  --venv PATH         指定虚拟环境（默认 `$HOME\myenv）
  --index-url URL     指定 pip 镜像，只影响本次安装
  --run               安装并立即执行 nb run
  -h, --help          显示帮助

脚本不会删除目标目录，不会覆盖已有宿主配置或 data\*.json。
"@
}

function Stop-Install([string]$Message) {
    throw "[xiuxian3] $Message"
}

function Invoke-Retry([scriptblock]$Action, [string]$Description) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            & $Action
            if ($LASTEXITCODE -eq 0) { return }
        } catch {
            if ($attempt -eq 3) { throw }
        }
        if ($attempt -lt 3) {
            Write-Warning "$Description 失败，将在 $attempt 秒后重试（$attempt/3）"
            Start-Sleep -Seconds $attempt
        }
    }
    Stop-Install "$Description 失败"
}

try {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $Action = "install"
    $Arguments = @($args)
    if ($Arguments.Count -gt 0 -and $Arguments[0] -in @("install", "update", "uninstall", "start", "pause", "resume", "stop", "restart", "status")) {
        $Action = $Arguments[0]
        $Arguments = if ($Arguments.Count -gt 1) { $Arguments[1..($Arguments.Count - 1)] } else { @() }
    }
    $Target = $null
    $SystemPython = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "py" }
    $SystemPythonArgs = if ([IO.Path]::GetFileNameWithoutExtension($SystemPython) -ieq "py") { @("-3") } else { @() }
    $Venv = if ($env:VENV_PATH) { $env:VENV_PATH } else { Join-Path $HOME "myenv" }
    $Start = $false
    $IndexUrl = $null
    $Yes = $false

    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        switch ($Arguments[$i]) {
            "--python" {
                if ($i + 1 -ge $Arguments.Count) { Stop-Install "--python 需要一个路径" }
                $SystemPython = $Arguments[++$i]
                $SystemPythonArgs = @()
            }
            "--venv" {
                if ($i + 1 -ge $Arguments.Count) { Stop-Install "--venv 需要一个路径" }
                $Venv = $Arguments[++$i]
            }
            "--index-url" {
                if ($i + 1 -ge $Arguments.Count) { Stop-Install "--index-url 需要一个 URL" }
                $IndexUrl = $Arguments[++$i]
            }
            "--run" { $Start = $true }
            "--yes" { $Yes = $true }
            "-h" { Show-Usage; exit 0 }
            "--help" { Show-Usage; exit 0 }
            default {
                if ($Arguments[$i].StartsWith("-")) { Stop-Install "未知选项：$($Arguments[$i])" }
                if ($null -ne $Target) { Stop-Install "只能指定一个目标宿主目录" }
                $Target = $Arguments[$i]
            }
        }
    }

    if ($null -eq $Target) { $Target = Join-Path $Root "nonebot-bot" }
    $Target = [IO.Path]::GetFullPath($Target)
    $Venv = [IO.Path]::GetFullPath($Venv)
    if ($Action -eq "update" -and -not (Test-Path $Target)) { Stop-Install "更新目标不存在：$Target" }
    New-Item -ItemType Directory -Force -Path $Target, (Join-Path $Target "data") | Out-Null

    if ($Action -notin @("install", "update")) {
        $Control = Join-Path $Target ".xiuxian3\control_windows.ps1"
        if (-not (Test-Path $Control)) { Stop-Install "未找到控制脚本，请先执行 install：$Target" }
        if ($Yes) { & $Control $Target $Venv $Root $Action -Yes } else { & $Control $Target $Venv $Root $Action }
        exit $LASTEXITCODE
    }
    if (-not (Get-Command $SystemPython -ErrorAction SilentlyContinue)) {
        Stop-Install "找不到 $SystemPython。请安装 Python 3.11+，或使用 --python 指定路径。"
    }
    $PythonVersion = (& $SystemPython @SystemPythonArgs -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    $VersionParts = $PythonVersion.Split('.') | ForEach-Object { [int]$_ }
    if ($VersionParts[0] -lt 3 -or ($VersionParts[0] -eq 3 -and $VersionParts[1] -lt 11)) {
        Stop-Install "需要 Python 3.11 或更高版本；当前为 $PythonVersion"
    }

    $VenvPython = Join-Path $Venv "Scripts\python.exe"
    $VenvNb = Join-Path $Venv "Scripts\nb.exe"
    if ((Test-Path $Venv) -and -not (Test-Path $VenvPython)) {
        Stop-Install "虚拟环境目录存在但不可用：$Venv；不会自动删除。"
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Host "[xiuxian3] 创建虚拟环境：$Venv"
        & $SystemPython @SystemPythonArgs -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Stop-Install "创建虚拟环境失败" }
    }

    if ($IndexUrl) { $env:PIP_INDEX_URL = $IndexUrl }
    & $VenvPython -m ensurepip --upgrade *> $null
    & $VenvPython -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) { Stop-Install "虚拟环境没有 pip，请确认 Python 安装包含 ensurepip。" }

    Write-Host "[xiuxian3] 升级 pip、setuptools 和 wheel"
    Invoke-Retry { & $VenvPython -m pip install --upgrade pip setuptools wheel } "pip 基础工具安装"

    Write-Host "[xiuxian3] 安装 NoneBot、适配器和本插件（普通 wheel 安装）"
    $ProjectPipArgs = @("--no-build-isolation")
    if ($Action -eq "update") { $ProjectPipArgs = @("--upgrade", "--upgrade-strategy", "eager", "--no-build-isolation") }
    Invoke-Retry { & $VenvPython -m pip install @ProjectPipArgs "$Root[nonebot,onebot,qq]" } "项目依赖安装"

    function Copy-IfMissing([string]$Source, [string]$Destination) {
        if (-not (Test-Path $Destination)) {
            New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
            Copy-Item $Source $Destination
            Write-Host "[xiuxian3] 写入 $Destination"
        } else {
            Write-Host "[xiuxian3] 保留已有文件 $Destination"
        }
    }

    Copy-IfMissing (Join-Path $Root "examples\nonebot\bot.py") (Join-Path $Target "bot.py")
    Copy-IfMissing (Join-Path $Root "examples\nonebot\pyproject.toml") (Join-Path $Target "pyproject.toml")
    Copy-IfMissing (Join-Path $Root "examples\nonebot\.env.example") (Join-Path $Target ".env")

    $DataRoot = Join-Path $Root "data"
    Get-ChildItem $DataRoot -Recurse -File -Filter *.json | ForEach-Object {
        $Relative = $_.FullName.Substring($DataRoot.Length).TrimStart("\", "/")
        Copy-IfMissing $_.FullName (Join-Path (Join-Path $Target "data") $Relative)
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $Target ".xiuxian3") | Out-Null
    Copy-Item (Join-Path $Root "scripts\control_windows.ps1") (Join-Path $Target ".xiuxian3\control_windows.ps1") -Force
    $ControlLauncher = Join-Path $Target "xiu3.ps1"
    if (-not (Test-Path $ControlLauncher)) {
        @"
param([Parameter(Position=0)][string]`$Command = "status", [Parameter(ValueFromRemainingArguments=`$true)][string[]]`$Rest)
& (Join-Path `$PSScriptRoot ".xiuxian3\control_windows.ps1") "$Target" "$Venv" "$Root" `$Command `$Rest
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 $ControlLauncher
    }
    $CmdLauncher = Join-Path $Target "xiu3.cmd"
    if (-not (Test-Path $CmdLauncher)) {
        "@echo off`r`npowershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"%~dp0xiu3.ps1`" %*`r`n" | Set-Content -Encoding ASCII $CmdLauncher
    }

    Write-Host "[xiuxian3] 校验已安装包、NoneBot 入口和 JSON 内容"
    & $VenvPython -c "import nonebot; import nonebot_plugin_xiuxian_3"
    if ($LASTEXITCODE -ne 0) { Stop-Install "插件导入校验失败" }
    & $VenvNb --help *> $null
    if ($LASTEXITCODE -ne 0) { Stop-Install "nb 命令未安装：$VenvNb" }
    $JsonFiles = Get-ChildItem (Join-Path $Target "data") -Recurse -File -Filter *.json
    if ($JsonFiles.Count -eq 0) { Stop-Install "data 目录没有 JSON 内容" }
    foreach ($JsonFile in $JsonFiles) {
        Get-Content -Raw -Encoding UTF8 $JsonFile.FullName | ConvertFrom-Json | Out-Null
    }
    Write-Host "已校验 $($JsonFiles.Count) 个 JSON 文件"

    if ($Start) {
        Set-Location $Target
        Write-Host "[xiuxian3] 启动宿主：nb run"
        & $VenvNb run
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "安装完成。"
    Write-Host "宿主目录：$Target"
    Write-Host "虚拟环境：$Venv"
    Write-Host "控制命令：Set-Location '$Target'; & '.\xiu3.ps1' start|pause|resume|stop|restart|status|update|uninstall --yes"
} catch {
    Write-Error "[xiuxian3] 安装失败：$($_.Exception.Message)"
    Write-Error "保留当前目录后重试；网络问题可设置 PIP_INDEX_URL 或传入 --index-url。"
    exit 1
}
