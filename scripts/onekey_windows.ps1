param(
    [ValidateSet("install", "update", "uninstall")]
    [string]$Action = "install",
    [string]$Target = (Join-Path $HOME "xiu3"),
    [string]$Mirror = "",
    [string]$MirrorUrl = "",
    [string]$Source = (Join-Path $HOME ".local\share\xiuxian3\source"),
    [ValidateSet("auto", "release", "source")]
    [string]$SourceMode = "auto"
)

$ErrorActionPreference = "Stop"
$Repository = "https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
$ReleaseArchive = "https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
$ReleaseMirrors = @(
    "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz",
    "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz",
    "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz",
    "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
)
$AcceleratedRepositories = @(
    [PSCustomObject]@{
        Name = "gh-proxy.com"
        Repository = "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
        Probe = "https://gh-proxy.com/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    },
    [PSCustomObject]@{
        Name = "ghfast.top"
        Repository = "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
        Probe = "https://ghfast.top/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    },
    [PSCustomObject]@{
        Name = "ghproxy.vip"
        Repository = "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
        Probe = "https://ghproxy.vip/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    },
    [PSCustomObject]@{
        Name = "gh-proxy.org"
        Repository = "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git"
        Probe = "https://gh-proxy.org/https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs?service=git-upload-pack"
    }
)
$IndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"

function Write-Info([string]$Message) {
    Write-Host "[xiuxian3] $Message"
}

function Add-CommonInstallPaths {
    $paths = @(
        (Join-Path $HOME "AppData\Local\Programs\Python\Python312"),
        (Join-Path $HOME "AppData\Local\Programs\Python\Python311"),
        "C:\Program Files\Git\cmd",
        "C:\Program Files\Git\bin"
    )
    foreach ($path in $paths) {
        if ((Test-Path $path) -and $env:Path -notlike "*$path*") {
            $env:Path = "$path;$env:Path"
        }
    }
}

function Invoke-WingetInstall([string]$Id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "缺少 $Id，且未安装 winget。请安装 Windows App Installer 或手动安装 Python 3.11+ 与 Git。"
    }
    Write-Info "通过 winget 安装 $Id"
    & winget install --id $Id --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget 安装 $Id 失败，退出码 $LASTEXITCODE" }
    Add-CommonInstallPaths
}

function Test-Python311 {
    foreach ($launcher in @("py", "python")) {
        if (-not (Get-Command $launcher -ErrorAction SilentlyContinue)) { continue }
        $pythonArgs = if ($launcher -eq "py") { @("-3") } else { @() }
        & $launcher @pythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

function Ensure-SystemTools {
    if (-not (Test-Python311)) { Invoke-WingetInstall "Python.Python.3.12" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Invoke-WingetInstall "Git.Git" }
    if (-not (Test-Python311)) { throw "需要 Python 3.11 或更高版本；安装后仍未检测到可用 Python。" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git 安装后仍未进入 PATH，请重开终端后重试。" }
}

function Select-Mirror {
    if ($Mirror) { return }
    Write-Host "选择仓库下载方式："
    Write-Host "  1) GitHub 直连"
    Write-Host "  2) 代理组测速并选最低延迟"
    Write-Host "  3) 自定义 Git 地址"
    $choice = Read-Host "请选择 [1]"
    switch ($choice) {
        "2" { $script:Mirror = "accelerated" }
        "3" {
            $script:Mirror = "custom"
            $script:MirrorUrl = Read-Host "输入完整 Git 克隆地址"
            if (-not $script:MirrorUrl) { throw "自定义 Git 地址不能为空" }
        }
        default { $script:Mirror = "direct" }
    }
}

function Get-FastestProxyRepository {
    $best = $null
    foreach ($candidate in $AcceleratedRepositories) {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-WebRequest -Uri $candidate.Probe -UseBasicParsing -TimeoutSec 10
            $watch.Stop()
            if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
            Write-Info "代理测速：$($candidate.Name) $([math]::Round($watch.Elapsed.TotalSeconds, 3))s"
            if ($null -eq $best -or $watch.Elapsed -lt $best.Latency) {
                $best = [PSCustomObject]@{ Repository = $candidate.Repository; Latency = $watch.Elapsed; Name = $candidate.Name }
            }
        } catch {
            $watch.Stop()
            Write-Warning "代理测速失败：$($candidate.Name)"
        }
    }
    if ($null -eq $best) {
        Write-Warning "代理组均不可用，改用 GitHub 直连"
        return $Repository
    }
    Write-Info "选择延迟最低的代理：$($best.Name)"
    return $best.Repository
}

function Update-Source {
    if ($SourceMode -eq "release" -or (-not (Test-Path (Join-Path $PSScriptRoot "..\pyproject.toml")))) {
        Download-ReleaseSource
        return
    }
    $localRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
    if (Test-Path (Join-Path $localRoot "pyproject.toml")) {
        $script:Source = $localRoot
        return
    }
    if (Test-Path (Join-Path $Source ".git")) {
        if ($Action -eq "update") {
            $dirty = & git -C $Source status --porcelain
            if ($dirty) { throw "源码目录有未提交改动：$Source" }
            Write-Info "更新插件源码：$Source"
            & git -C $Source fetch --prune origin
            if ($LASTEXITCODE -ne 0) { throw "Git fetch 失败" }
            & git -C $Source pull --ff-only origin main
            if ($LASTEXITCODE -ne 0) { throw "Git fast-forward 更新失败" }
        }
        return
    }
    if (Test-Path $Source) { throw "源码路径已存在但不是 Git 仓库：$Source" }

    Select-Mirror
    $url = switch ($Mirror) {
        "direct" { $Repository }
        "accelerated" { Get-FastestProxyRepository }
        "custom" { $MirrorUrl }
        default { throw "不支持的仓库下载方式：$Mirror" }
    }
    if ($Mirror -eq "custom" -and -not $url) { throw "custom 模式需要 -MirrorUrl" }
    New-Item -ItemType Directory -Force -Path (Split-Path $Source) | Out-Null
    Write-Info "从 $url 获取插件源码"
    & git clone --depth 1 --branch main $url $Source
    if ($LASTEXITCODE -ne 0 -and $Mirror -eq "accelerated" -and $url -ne $Repository) {
        if (Test-Path $Source) { Remove-Item -Recurse -Force $Source }
        foreach ($candidate in $AcceleratedRepositories) {
            if ($candidate.Repository -eq $url) { continue }
            Write-Info "所选代理克隆失败，尝试代理组中的下一个地址：$($candidate.Name)"
            & git clone --depth 1 --branch main $candidate.Repository $Source
            if ($LASTEXITCODE -eq 0) { $url = $candidate.Repository; break }
            if (Test-Path $Source) { Remove-Item -Recurse -Force $Source }
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "代理组克隆失败，尝试 GitHub 直连"
            & git clone --depth 1 --branch main $Repository $Source
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "仓库下载失败；请更换下载方式或使用 -MirrorUrl。" }
}

function Get-ReleaseUrls {
    switch ($Mirror) {
        "direct" { return @($ReleaseArchive) }
        "accelerated" { return @($ReleaseMirrors + $ReleaseArchive) }
        "custom" {
            if (-not $MirrorUrl) { throw "custom 模式需要 -MirrorUrl" }
            return @($MirrorUrl)
        }
        default { return @($ReleaseMirrors + $ReleaseArchive) }
    }
}

function Download-ReleaseSource {
    $work = Join-Path ([IO.Path]::GetTempPath()) ("xiuxian3-release-" + [guid]::NewGuid().ToString("N"))
    $archive = Join-Path $work "project.tar.gz"
    $extract = Join-Path $work "extract"
    New-Item -ItemType Directory -Force -Path $extract | Out-Null
    try {
        foreach ($url in (Get-ReleaseUrls)) {
            Write-Info "下载 Release 资产：$url"
            try {
                Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -TimeoutSec 180
                & tar -xzf $archive -C $extract
                if ($LASTEXITCODE -ne 0) { throw "tar 解包失败" }
                $project = Get-ChildItem $extract -Recurse -Filter pyproject.toml -File | Select-Object -First 1
                if ($null -eq $project) { throw "资产缺少 pyproject.toml" }
                if ((Test-Path $Source) -and -not (Test-Path (Join-Path $Source ".xiuxian3-release"))) {
                    throw "源码目录已存在且不是 Release 管理目录：$Source；如需开发源码请使用 -SourceMode source"
                }
                if (Test-Path $Source) { Remove-Item -Recurse -Force $Source }
                New-Item -ItemType Directory -Force -Path $Source | Out-Null
                Copy-Item (Join-Path $project.Directory.FullName "*") $Source -Recurse -Force
                Set-Content -Path (Join-Path $Source ".xiuxian3-release") -Value $url -Encoding UTF8
                Write-Info "已准备 Release 源码：$Source"
                return
            } catch {
                Write-Warning "Release 下载失败：$($_.Exception.Message)；尝试下一个地址"
                if (Test-Path $extract) {
                    Remove-Item -Recurse -Force $extract
                    New-Item -ItemType Directory -Force -Path $extract | Out-Null
                }
            }
        }
        throw "无法获取有效的 project.tar.gz；代理失败后直连也不可用，请稍后重试或使用 -SourceMode source。"
    } finally {
        if (Test-Path $work) { Remove-Item -Recurse -Force $work }
    }
}

try {
    $Target = [IO.Path]::GetFullPath($Target)
    $Source = [IO.Path]::GetFullPath($Source)
    if ($Mirror -and $Mirror -notin @("direct", "accelerated", "custom")) { throw "不支持的仓库下载方式：$Mirror" }
    if ($Action -eq "uninstall") {
        $control = Join-Path $Target "xiu3.ps1"
        if (-not (Test-Path $control)) { throw "没有找到控制命令：$control" }
        Write-Warning "卸载会删除宿主目录及 SQLite 数据，请确保已经备份。"
        & $control uninstall --yes
        exit $LASTEXITCODE
    }

    Ensure-SystemTools
    Update-Source
    $installer = Join-Path $Source "scripts\install_windows.ps1"
    if (-not (Test-Path $installer)) { throw "源码目录缺少 scripts\install_windows.ps1：$Source" }
    & $installer $Action $Target --venv (Join-Path $HOME "myenv") --index-url $IndexUrl
    if ($LASTEXITCODE -ne 0) { throw "平台安装器失败，退出码 $LASTEXITCODE" }
} catch {
    Write-Error "[xiuxian3] 安装失败：$($_.Exception.Message)"
    Write-Error "已保留源码、虚拟环境和宿主目录；修复报错后重新运行即可。"
    exit 1
}
