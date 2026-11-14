"""A fresh public checkout must bootstrap without an owner's configuration."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('project_setup', SCRIPTS / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
from storage_config import MARKER, NAMES, read_env  # noqa: E402


@pytest.mark.parametrize('passwordless', [True, False])
def test_local_setup_generates_private_config_and_is_idempotent(tmp_path, monkeypatch, passwordless):
    monkeypatch.setattr(setup.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(setup.os, 'getgid', lambda: 1000)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'passwordless': passwordless, 'timezone': 'UTC'}))
    monkeypatch.setattr(sys, 'argv', ['setup', '--local', '--project', str(tmp_path), '--config', str(config)])
    assert setup.main() == 0
    env = read_env(tmp_path / '.env')
    assert env['PASSWORDLESS'] == str(passwordless).lower()
    assert env['GATEWAY_BIND'] == '127.0.0.1'
    assert env['APP_TIMEZONE'] == 'UTC'
    assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600
    for name in NAMES:
        assert (Path(env[f'{name}_DIR']) / MARKER).read_text().strip() == env[f'{name}_VOLUME_ID']
    before = (tmp_path / '.env').read_bytes()
    secret = (tmp_path / '.secrets/encryption_key').read_bytes()
    assert setup.main() == 0
    assert (tmp_path / '.env').read_bytes() == before
    assert (tmp_path / '.secrets/encryption_key').read_bytes() == secret


def test_setup_rejects_string_passwordless_before_writing(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'passwordless': 'false'}))
    monkeypatch.setattr(sys, 'argv', ['setup', '--local', '--project', str(tmp_path), '--config', str(config)])
    with pytest.raises(SystemExit):
        setup.main()
    assert not (tmp_path / '.env').exists()
    assert not (tmp_path / '.secrets').exists()
