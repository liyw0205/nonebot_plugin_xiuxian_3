from __future__ import annotations

import subprocess
import shlex
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
    assert host["tool"]["nonebot"]["adapters"]["@local"] == []
    assert host["tool"]["nonebot"]["plugins"]["@local"] == ["nonebot_plugin_xiuxian_3"]
    docker_host = tomllib.loads((ROOT / "docker/pyproject.toml").read_text(encoding="utf-8"))
    assert docker_host["project"]["dependencies"] == []
    assert docker_host["tool"]["nonebot"]["adapters"]["@local"] == []
    assert docker_host["tool"]["nonebot"]["plugins"]["@local"] == ["nonebot_plugin_xiuxian_3"]


def test_user_install_guides_start_with_supported_source_checkout() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    assert "git clone --branch " in readme
    assert "bash scripts/onekey.sh install --source-mode source" in readme
    assert "git clone --branch " in installation
    assert "--source-mode source" in installation
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
