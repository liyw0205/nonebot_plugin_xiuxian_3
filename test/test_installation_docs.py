from __future__ import annotations

import os
import subprocess
import shlex
import shutil
import sys
import tarfile
import tomllib
from tempfile import TemporaryDirectory
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_installers_parse_and_expose_help() -> None:
    scripts = [
        ROOT / "scripts/onekey.sh",
        ROOT / "scripts/install.sh",
        ROOT / "scripts/install_termux.sh",
        ROOT / "scripts/control.sh",
    ]
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(
        ["bash", str(scripts[0]), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--mirror MODE" in result.stdout
    assert "--index-url URL" in result.stdout


def test_install_and_control_entrypoints_share_commands_and_paths() -> None:
    expected_commands = ("install", "update", "uninstall", "start", "stop", "restart", "status", "logs", "login")
    expected_options = ("--source-mode", "--source", "--mirror", "--target", "--venv")
    for script in ("onekey.sh", "install.sh", "control.sh"):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / script), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for command in expected_commands:
            assert command in result.stdout, (script, command)
        for option in expected_options:
            assert option in result.stdout, (script, option)
    windows_scripts = ("onekey_windows.ps1", "install_windows.ps1", "control_windows.ps1")
    for script in windows_scripts:
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        for command in expected_commands:
            assert f'"{command}"' in text, (script, command)
        for option in expected_options:
            assert option in text, (script, option)


def test_onekey_control_routing_logs_and_official_qq_login() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = root / "host"
        target.mkdir()
        launcher = target / "xiu3"
        launcher.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o755)
        routed = subprocess.run(
            [
                "bash", str(ROOT / "scripts" / "onekey.sh"), "status",
                "--target", str(target), "--source", str(root / "source"),
                "--source-mode", "source", "--mirror", "direct", "--venv", str(root / "venv"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        routed_args = routed.stdout.splitlines()
        assert routed_args[0] == "status"
        assert shlex.join(routed_args).find("--target") >= 0
        assert str(target) in routed_args
        assert "--source-mode" in routed_args and "source" in routed_args

        state = target / ".xiuxian3"
        state.mkdir()
        (state / "nb.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
        logs = subprocess.run(
            ["bash", str(ROOT / "scripts" / "control.sh"), "logs", "--target", str(target),
             "--source", str(ROOT), "--venv", str(root / "venv"), "--lines", "2"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert logs.stdout.splitlines() == ["two", "three"]

        venv = root / "venv"
        (venv / "bin").mkdir(parents=True)
        python = venv / "bin" / "python"
        python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        python.chmod(0o755)
        (state / "qq_login.py").write_text("# helper stub\n", encoding="utf-8")
        login = subprocess.run(
            ["bash", str(ROOT / "scripts" / "control.sh"), "login", "--target", str(target),
             "--source", str(ROOT), "--venv", str(venv), "--timeout", "5", "--interval", "0.1"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "qq_login.py" in login.stdout
        assert "--timeout\n5\n--interval\n0.1" in login.stdout
        assert "QQ 配置已更新" in login.stdout


def test_requirements_leave_cli_version_to_the_environment() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert requirements == ["nb-cli"]
    assert all("==" not in line for line in requirements)
    assert all("<" not in line for line in requirements)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = project["project"]["optional-dependencies"]
    assert project["project"]["dependencies"] == ["nonebot2>=2.4"]
    assert not {"nonebot", "onebot", "qq"}.intersection(optional_dependencies)
    assert all("nb-cli" not in requirement for values in optional_dependencies.values() for requirement in values)
    assert all("<" not in requirement for values in optional_dependencies.values() for requirement in values)


def test_nonebot_host_template_has_cli_managed_adapter_configuration() -> None:
    host = tomllib.loads((ROOT / "examples/nonebot/pyproject.toml").read_text(encoding="utf-8"))
    assert host["project"]["dependencies"] == []
    assert host["tool"]["nonebot"]["plugin_dirs"] == ["src/plugins"]
    assert host["tool"]["nonebot"]["adapters"]["@local"] == []
    assert host["tool"]["nonebot"]["plugins"]["@local"] == []
    docker_host = tomllib.loads((ROOT / "docker/pyproject.toml").read_text(encoding="utf-8"))
    assert docker_host["project"]["dependencies"] == []
    assert docker_host["tool"]["nonebot"]["adapters"]["@local"] == []
    assert docker_host["tool"]["nonebot"]["plugins"]["@local"] == ["nonebot_plugin_xiuxian_3"]


def test_host_plugin_source_is_replaced_and_loaded_from_plugin_dirs(tmp_path: Path) -> None:
    helper = ROOT / "scripts/install_plugin_source.py"
    source = tmp_path / "source" / "nonebot_plugin_xiuxian_3"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text(
        "from nonebot import on\n\nprobe = on('message')\n", encoding="utf-8"
    )
    (source / "current.py").write_text("version = 'new'\n", encoding="utf-8")

    target = tmp_path / "host"
    plugin = target / "src/plugins/nonebot_plugin_xiuxian_3"
    plugin.mkdir(parents=True)
    (plugin / "stale.py").write_text("version = 'old'\n", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data/profile.json").write_text('{"keep": true}\n', encoding="utf-8")
    (target / ".env").write_text("keep=1\n", encoding="utf-8")
    (target / "pyproject.toml").write_text(
        '[project]\nname = "existing-host"\n\n'
        '[tool.nonebot]\nplugin_dirs = [\n  "custom/plugins",\n]\n'
        'builtin_plugins = []\n\n'
        '[tool.nonebot.adapters]\n"@local" = ["existing-adapter"]\n\n'
        '[tool.nonebot.plugins]\n"@local" = [\n'
        '  "nonebot_plugin_xiuxian_3",\n  "other_plugin",\n]\n',
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(helper), "--source", str(source), "--target", str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    config = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["nonebot"]["plugin_dirs"] == ["custom/plugins", "src/plugins"]
    assert config["tool"]["nonebot"]["plugins"]["@local"] == ["other_plugin"]
    assert config["tool"]["nonebot"]["adapters"]["@local"] == ["existing-adapter"]
    assert (plugin / "current.py").is_file()
    assert not (plugin / "stale.py").exists()
    assert (target / ".env").read_text(encoding="utf-8") == "keep=1\n"
    assert (target / "data/profile.json").read_text(encoding="utf-8") == '{"keep": true}\n'

    loaded = subprocess.run(
        [sys.executable, str(helper), "--validate", "--target", str(target)],
        check=True,
        capture_output=True,
        text=True,
        cwd=target,
    )
    assert "src.plugins.nonebot_plugin_xiuxian_3" in loaded.stdout
    assert not list((target / "src/plugins").glob(".nonebot_plugin_xiuxian_3.*"))

    broken_source = tmp_path / "broken-source"
    broken_source.mkdir()
    previous_pyproject = (target / "pyproject.toml").read_bytes()
    failed = subprocess.run(
        [sys.executable, str(helper), "--source", str(broken_source), "--target", str(target)],
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert (plugin / "current.py").is_file()
    assert (target / "pyproject.toml").read_bytes() == previous_pyproject


def test_xiu3_source_loads_from_managed_host_directory(tmp_path: Path) -> None:
    helper = ROOT / "scripts/install_plugin_source.py"
    target = tmp_path / "host"
    target.mkdir()
    shutil.copyfile(ROOT / "examples/nonebot/pyproject.toml", target / "pyproject.toml")
    shutil.copytree(ROOT / "data", target / "data")

    subprocess.run(
        [
            sys.executable,
            str(helper),
            "--source",
            str(ROOT / "nonebot_plugin_xiuxian_3"),
            "--target",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, str(helper), "--validate", "--target", str(target)],
        check=True,
        capture_output=True,
        text=True,
        cwd=target,
    )
    assert "NoneBot 已加载 src.plugins.nonebot_plugin_xiuxian_3" in result.stdout
    assert not list((target / "src/plugins/nonebot_plugin_xiuxian_3").rglob("__pycache__"))


def test_managed_installers_copy_plugin_source_instead_of_pip_installing_it() -> None:
    linux = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    termux = (ROOT / "scripts/install_termux.sh").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")

    assert "install_plugin_source.py" in linux
    assert 'pip install "${project_pip_args[@]}" "$ROOT"' not in linux
    assert "install_plugin_source.py" in windows
    assert "pip install @ProjectPipArgs $Root" not in windows
    assert 'exec bash "$ROOT/scripts/onekey.sh" "$@"' in termux
    assert "--source \"$XIUXIAN3_SRC/nonebot_plugin_xiuxian_3\"" in installation
    assert 'pip install --no-deps "$XIUXIAN3_SRC"' not in installation


def test_release_install_smoke_checks_plugin_source_loading() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    smoke = workflow.split("      - name: Verify isolated runtime and preserved files\n", 1)[1]
    assert 'src/plugins/nonebot_plugin_xiuxian_3/__init__.py' in smoke
    assert "scripts/install_plugin_source.py --validate" in smoke
    assert '"nonebot-plugin-xiuxian-3" not in' in smoke


def test_user_install_guides_prefer_raw_release_and_label_manual_checkout() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    raw_installer = (
        "https://raw.githubusercontent.com/liyw0205/nonebot_plugin_xiuxian_3/main/scripts/onekey.sh"
    )
    for guide in (readme, installation):
        linux = guide.split("### Linux 一键 Release 安装\n", 1)[1].split("\n### ", 1)[0]
        termux = guide.split("### Termux 一键 Release 安装\n", 1)[1].split("\n### ", 1)[0]
        for section in (linux, termux):
            assert raw_installer in section
            assert "--source-mode release" in section
            assert "git clone" not in section

    assert "Release 一键安装不需要先 clone 仓库" in readme
    assert "不需要先 clone 仓库" in installation
    readme_manual = readme.split("### 手动获取脚本或源码安装\n", 1)[1].split("\n### ", 1)[0]
    install_manual = installation.split("## 手动获取脚本或源码安装\n", 1)[1].split("\n## ", 1)[0]
    for section in (readme_manual, install_manual):
        assert "git clone --branch main" in section
        assert "--source-mode source" in section
    assert "requirements.txt" in installation
    assert "--mirror accelerated" in installation
    assert "$HOME/xiu3" in readme
    assert "$HOME/xiu3" in installation
    assert "ghproxy.net" not in readme
    assert "ghproxy.net" not in installation


def test_adapters_and_drivers_are_installed_through_nb_cli() -> None:
    files = [
        ROOT / "README.md",
        ROOT / "docs/installation.md",
        ROOT / "docs/runtime-framework.md",
        ROOT / "Dockerfile",
        ROOT / "scripts/install.sh",
        ROOT / "scripts/install_windows.ps1",
        ROOT / "scripts/control.sh",
        ROOT / "scripts/control_windows.ps1",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "adapter install" in combined
    assert "driver install" in combined
    assert "--no-restrict-version" in combined
    assert "nonebot_plugin_xiuxian_3[nonebot,onebot,qq]" not in combined
    assert "'.[nonebot,onebot,qq]'" not in combined


def test_readme_documents_adapter_configuration_and_connection_urls() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "COMMAND_START" in readme
    assert "QQ_BOTS" in readme
    assert "c2c_group_at_messages" in readme
    assert "ONEBOT_V11_ACCESS_TOKEN" in readme
    assert "ws://服务器地址:8080/onebot/v11/ws" in readme
    assert "ws://xiuxian3:8080/onebot/v11/ws" in readme
    assert "ONEBOT_V11_WS_URLS" not in readme
    assert "replace-with-your-random-token" not in readme
    assert "ONEBOT_V11_ACCESS_TOKEN" not in (ROOT / "docs/installation.md").read_text(encoding="utf-8") or "仅在启用" in (ROOT / "docs/installation.md").read_text(encoding="utf-8")


def test_qq_login_helper_is_installed_and_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    shell_installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    windows_installer = (ROOT / "scripts/install_windows.ps1").read_text(encoding="utf-8")
    control = (ROOT / "scripts/control.sh").read_text(encoding="utf-8")
    windows_control = (ROOT / "scripts/control_windows.ps1").read_text(encoding="utf-8")
    assert "xiu3 login" in readme and "xiu3 login" in installation
    assert "scripts/qq_login.py" in shell_installer
    assert "scripts\\qq_login.py" in windows_installer
    assert "qq_login.py" in control and "qq_login.py" in windows_control


def test_source_mode_control_update_requires_release_archive(tmp_path: Path) -> None:
    target = tmp_path / "host"
    source = tmp_path / "source"
    fake_bin = tmp_path / "bin"
    target.mkdir()
    (source / "scripts").mkdir(parents=True)
    (source / ".git").mkdir()
    installer = source / "scripts" / "install.sh"
    installer.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$INSTALL_ARGS\"\n", encoding="utf-8")
    installer.chmod(0o755)
    fake_bin.mkdir()
    git_log = tmp_path / "git.log"
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$GIT_LOG\"\n", encoding="utf-8")
    fake_git.chmod(0o755)
    install_args = tmp_path / "install-args"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GIT_LOG": str(git_log),
        "INSTALL_ARGS": str(install_args),
    }

    result = subprocess.run(
        [
            "bash", str(ROOT / "scripts/control.sh"), "update",
            "--target", str(target), "--source", str(source),
            "--source-mode", "source", "--venv", str(tmp_path / "venv"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert "只支持 Release 管理安装" in result.stderr
    assert not git_log.exists()
    assert not install_args.exists()


def test_control_update_without_release_source_does_not_use_package_index(tmp_path: Path) -> None:
    target = tmp_path / "host"
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    target.mkdir()
    command_log = tmp_path / "package-commands.log"
    python = venv / "bin" / "python"
    python.write_text("#!/bin/sh\nprintf 'python %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n", encoding="utf-8")
    python.chmod(0o755)
    nb = venv / "bin" / "nb"
    nb.write_text("#!/bin/sh\nprintf 'nb %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n", encoding="utf-8")
    nb.chmod(0o755)

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/control.sh"), "update", "--target", str(target), "--venv", str(venv)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "COMMAND_LOG": str(command_log)},
    )

    assert result.returncode == 2
    assert "Release 管理安装" in result.stderr
    assert not command_log.exists()
    assert "nonebot_plugin_xiuxian_3" not in (ROOT / "scripts/control.sh").read_text(encoding="utf-8")


def test_control_release_update_routes_to_archive_installer(tmp_path: Path) -> None:
    target = tmp_path / "host"
    source = tmp_path / "release-source"
    (source / "scripts").mkdir(parents=True)
    target.mkdir()
    (source / ".xiuxian3-release").write_text("release archive\n", encoding="utf-8")
    one_key_args = tmp_path / "onekey-args"
    one_key = source / "scripts" / "onekey.sh"
    one_key.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$ONEKEY_ARGS\"\n", encoding="utf-8")
    one_key.chmod(0o755)

    result = subprocess.run(
        [
            "bash", str(ROOT / "scripts/control.sh"), "update",
            "--target", str(target), "--source", str(source),
            "--source-mode", "auto", "--venv", str(tmp_path / "venv"),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "ONEKEY_ARGS": str(one_key_args)},
    )

    args = one_key_args.read_text(encoding="utf-8").splitlines()
    assert args[0] == "update"
    assert args[args.index("--source-mode") + 1] == "release"
    assert args[args.index("--source") + 1] == str(source)


def test_windows_control_update_requires_release_archive_without_pypi_fallback() -> None:
    windows_control = (ROOT / "scripts/control_windows.ps1").read_text(encoding="utf-8")
    update_branch = windows_control.split('    "update" {', 1)[1].split('    "uninstall" {', 1)[0]

    assert "onekey_windows.ps1" in update_branch
    assert "latest project.tar.gz" in update_branch
    assert "pip install" not in update_branch
    assert "nonebot_plugin_xiuxian_3" not in update_branch
    assert "install_windows.ps1" not in update_branch


def test_release_update_downloads_archive_and_preserves_host_state(tmp_path: Path) -> None:
    target = tmp_path / "host"
    source = tmp_path / "release-cache"
    venv = tmp_path / "venv"
    fake_bin = tmp_path / "bin"
    target.mkdir()
    source.mkdir()
    (source / ".xiuxian3-release").write_text("old release\n", encoding="utf-8")
    (target / ".env").write_text("keep-env\n", encoding="utf-8")
    (target / "data").mkdir()
    (target / "data" / "profile.json").write_text("keep-data\n", encoding="utf-8")
    (target / "runtime").mkdir()
    (target / "runtime" / "state.bin").write_text("keep-runtime\n", encoding="utf-8")
    venv.mkdir()
    (venv / "sentinel").write_text("keep-venv\n", encoding="utf-8")

    release_root = tmp_path / "release-root"
    (release_root / "scripts").mkdir(parents=True)
    (release_root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    release_installer = release_root / "scripts" / "install.sh"
    release_installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "target= venv= source_mode=\n"
        "while (($#)); do\n"
        "  case $1 in\n"
        "    --target) target=$2; shift 2 ;;\n"
        "    --venv) venv=$2; shift 2 ;;\n"
        "    --source-mode) source_mode=$2; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "test \"$source_mode\" = source\n"
        "test \"$(cat \"$target/.env\")\" = keep-env\n"
        "test \"$(cat \"$target/data/profile.json\")\" = keep-data\n"
        "test \"$(cat \"$target/runtime/state.bin\")\" = keep-runtime\n"
        "test \"$(cat \"$venv/sentinel\")\" = keep-venv\n"
        ": > \"$UPDATE_MARKER\"\n",
        encoding="utf-8",
    )
    release_installer.chmod(0o755)
    release_archive = tmp_path / "fixture-project.tar.gz"
    with tarfile.open(release_archive, "w:gz") as bundle:
        bundle.add(release_root, arcname=".")

    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        "output= url=\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = -o ]; then shift; output=$1; else url=$1; fi\n"
        "  shift\n"
        "done\n"
        "printf '%s\\n' \"$url\" > \"$CURL_URL\"\n"
        "cp \"$XIUXIAN3_TEST_RELEASE_ARCHIVE\" \"$output\"\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$GIT_LOG\"\n", encoding="utf-8")
    fake_git.chmod(0o755)
    update_marker = tmp_path / "installer-ran"
    curl_url = tmp_path / "curl-url"
    git_log = tmp_path / "git.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        "XIUXIAN3_TEST_RELEASE_ARCHIVE": str(release_archive),
        "UPDATE_MARKER": str(update_marker),
        "CURL_URL": str(curl_url),
        "GIT_LOG": str(git_log),
    }

    subprocess.run(
        [
            "bash", str(ROOT / "scripts/onekey.sh"), "update",
            "--target", str(target), "--source", str(source),
            "--source-mode", "release", "--mirror", "direct", "--venv", str(venv),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert update_marker.is_file()
    assert curl_url.read_text(encoding="utf-8").strip() == (
        "https://github.com/liyw0205/nonebot_plugin_xiuxian_3/releases/latest/download/project.tar.gz"
    )
    assert not git_log.exists()
    assert (source / ".xiuxian3-release").read_text(encoding="utf-8").strip().endswith("project.tar.gz")
    assert (target / ".env").read_text(encoding="utf-8") == "keep-env\n"
    assert (target / "data" / "profile.json").read_text(encoding="utf-8") == "keep-data\n"
    assert (target / "runtime" / "state.bin").read_text(encoding="utf-8") == "keep-runtime\n"
    assert (venv / "sentinel").read_text(encoding="utf-8") == "keep-venv\n"


def test_release_asset_is_built_outside_checkout_root() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    build_step = workflow.split("      - name: Build release asset\n", 1)[1].split(
        "      - name: Publish GitHub Release\n", 1
    )[0]
    publish_step = workflow.split("      - name: Publish GitHub Release\n", 1)[1]

    assert 'asset_path="$RUNNER_TEMP/project.tar.gz"' in build_step
    assert ' -czf "$asset_path" .' in build_step
    assert 'tar -tzf "$asset_path" | grep -Fx \'./pyproject.toml\'' in build_step
    assert 'tar -tzf "$asset_path" | grep -Fx \'./scripts/onekey.sh\'' in build_step
    assert '"$RUNNER_TEMP/project.tar.gz" --verify-tag' in publish_step


def test_user_update_docs_use_release_managed_update_flow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs/release-distribution.md").read_text(encoding="utf-8")
    readme_update = readme.split("## 更新、备份与排错\n", 1)[1].split("## 文档与数据\n", 1)[0]
    installation_update = installation.split("## 控制、更新与备份\n", 1)[1].split("## 排错\n", 1)[0]

    for section in (readme_update, installation_update):
        flow = section.split("```bash\n", 1)[1].split("```", 1)[0]
        commands = ("xiu3 stop", "cp -a", "xiu3 update", "xiu3 start")
        positions = [flow.index(command) for command in commands]
        assert positions == sorted(positions)
        assert "git fetch" not in section
        assert "git pull" not in section
        assert "latest Release" in section
        assert "project.tar.gz" in section

    assert "latest/download/project.tar.gz" in distribution
    assert "xiu3 update" in distribution
    assert "--source-mode release" in readme
    assert "--source-mode release" in installation
    assert "`xiu3 update` 只支持 Release 管理安装" in readme
    assert "`xiu3 update` 只支持 Release 管理安装" in installation
    assert "--source-mode source" in installation
    assert "git -C " not in installation
    assert "scripts/install.sh update" not in installation


def test_windows_update_paths_do_not_run_git_fetch_or_pull() -> None:
    windows_control = (ROOT / "scripts/control_windows.ps1").read_text(encoding="utf-8")
    update_branch = windows_control.split('    "update" {', 1)[1].split('    "uninstall" {', 1)[0]
    assert "& git -C $SourceRoot fetch" not in update_branch
    assert "& git -C $SourceRoot pull" not in update_branch
    assert "onekey_windows.ps1" in update_branch

    windows_bootstrap = (ROOT / "scripts/onekey_windows.ps1").read_text(encoding="utf-8")
    source_update = windows_bootstrap.split("function Update-Source {", 1)[1].split("function Get-ReleaseUrls", 1)[0]
    assert "& git -C $Source fetch" not in source_update
    assert "& git -C $Source pull" not in source_update


def test_accelerated_bootstraps_benchmark_a_proxy_group() -> None:
    shell_bootstrap = (ROOT / "scripts/onekey.sh").read_text(encoding="utf-8")
    windows_bootstrap = (ROOT / "scripts/onekey_windows.ps1").read_text(encoding="utf-8")
    domains = ("gh-proxy.com", "ghfast.top", "ghproxy.vip", "gh-proxy.org")
    for domain in domains:
        assert domain in shell_bootstrap
        assert domain in windows_bootstrap
    assert shell_bootstrap.count("https://github.com/liyw0205/nonebot_plugin_xiuxian_3.git/info/refs") == 4
    assert windows_bootstrap.count(".git/info/refs?service=git-upload-pack") == 4
    assert "select_fastest_proxy" in shell_bootstrap
    assert "Get-FastestProxyRepository" in windows_bootstrap
    assert "time_starttransfer" in shell_bootstrap
    assert "Stopwatch" in windows_bootstrap
