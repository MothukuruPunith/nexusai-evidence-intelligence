import os
import stat
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from pydantic import ValidationError

from nexusai.core.config import Settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configure_local.py"


def test_generated_credentials_are_unique_private_and_not_printed(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    configuration = dotenv_values(tmp_path / ".env")
    urls = [configuration[key] for key in configuration if key.endswith("DATABASE_URL")]
    assert len(urls) == 4
    assert len(set(urls)) == 4
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600
    assert configuration["POSTGRES_PASSWORD"] not in result.stdout
    assert configuration["POSTGRES_PASSWORD"] not in result.stderr
    settings = Settings(_env_file=tmp_path / ".env")
    assert settings.database_url is not None


def test_configuration_never_overwrites_existing_file(tmp_path):
    target = tmp_path / ".env"
    target.write_text("existing-private-data")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert target.read_text() == "existing-private-data"
    assert "existing-private-data" not in result.stderr


def test_invalid_port_fails_before_creating_secrets(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env={**os.environ, "NEXUS_DB_PORT": "70000"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()


def test_invalid_database_configuration_does_not_print_credentials():
    try:
        Settings(_env_file=None, database_url="mysql://user:private-password@localhost/db")
    except ValidationError as error:
        assert "private-password" not in str(error)
    else:
        raise AssertionError("Non-PostgreSQL URL unexpectedly accepted")
