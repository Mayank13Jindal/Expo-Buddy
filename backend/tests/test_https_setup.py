"""Host configuration uses synthetic files and fake commands, never the live stack."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def https_setup(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("https_setup", scripts / "configure_https.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env").write_text("APP_URL='https://192.168.1.100'\nKEEP_EXISTING='yes'\n")
    return module


def test_https_preview_changes_nothing_and_rejects_nonstandard_port(
    https_setup, tmp_path, monkeypatch
):
    before = (tmp_path / ".env").read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "https_setup",
            "--mode",
            "lan",
            "--url",
            "https://192.168.1.100",
            "--project",
            str(tmp_path),
        ],
    )
    assert https_setup.main() == 0
    assert (tmp_path / ".env").read_bytes() == before
    assert not (tmp_path / "deploy/https.local.yml").exists()
    with pytest.raises(ValueError, match="443"):
        https_setup.origin("https://192.168.1.100:8443")


def test_tailscale_replaces_ports_keeps_other_settings_and_uses_trusted_origin(
    https_setup, tmp_path, monkeypatch
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["tailscale", "status", "--json"]:
            return json.dumps(
                {"BackendState": "Running", "Self": {"DNSName": "fictional.example.ts.net."}}
            )
        return "{}"

    monkeypatch.setattr(https_setup, "run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["https_setup", "--mode", "tailscale", "--project", str(tmp_path), "--apply"]
    )
    assert https_setup.main() == 0
    env = (tmp_path / ".env").read_text()
    assert "APP_URL='https://fictional.example.ts.net'" in env
    assert "KEEP_EXISTING='yes'" in env
    config = (tmp_path / "deploy/https.local.yml").read_text()
    assert "ports: !override" in config and "127.0.0.1:8080:8080" in config
    assert "Caddyfile.proxy" in config and "443:8443" not in config
    assert ["tailscale", "serve", "--bg", "--https=443", "--yes", "http://127.0.0.1:8080"] in calls


def test_failed_https_change_restores_original_configuration(https_setup, tmp_path, monkeypatch):
    import subprocess

    before = (tmp_path / ".env").read_bytes()

    def fail_run(command, **kwargs):
        if "config" in command:
            raise subprocess.CalledProcessError(1, command)
        return ""

    monkeypatch.setattr(https_setup, "run", fail_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "https_setup",
            "--mode",
            "lan",
            "--url",
            "https://192.168.1.101",
            "--project",
            str(tmp_path),
            "--apply",
        ],
    )
    with pytest.raises(subprocess.CalledProcessError):
        https_setup.main()
    assert (tmp_path / ".env").read_bytes() == before
    assert not (tmp_path / "deploy/https.local.yml").exists()


def test_tailscale_does_not_replace_another_service(https_setup, tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        if command[1] == "status":
            return json.dumps(
                {"BackendState": "Running", "Self": {"DNSName": "fictional.example.ts.net."}}
            )
        return json.dumps({"TCP": {"443": {"TCPForward": "localhost:9000"}}})

    monkeypatch.setattr(https_setup, "run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["https_setup", "--mode", "tailscale", "--project", str(tmp_path), "--apply"]
    )
    with pytest.raises(ValueError, match="another app"):
        https_setup.main()
