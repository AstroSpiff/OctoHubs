"""Docker PASSWORD_SECRET rotation remains fail-closed across restarts."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from emby_users.password_crypto import finalize_password_secret_rotation


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _entrypoint_environment(config_dir: Path, password_secret: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{PROJECT_ROOT / 'venv' / 'bin'}:{environment.get('PATH', '')}"
    environment.update(
        {
            "OCTOHUBS_CONFIG_DIR": str(config_dir),
            "OCTOHUBS_DB_HOST": "database.example.test",
            "SECRET_KEY": "session-secret-that-is-long-enough-for-tests",
        }
    )
    environment.pop("PASSWORD_SECRET_PREVIOUS", None)
    if password_secret is None:
        environment.pop("PASSWORD_SECRET", None)
    else:
        environment["PASSWORD_SECRET"] = password_secret
    return environment


def _run_entrypoint(config_dir: Path, password_secret: str | None):
    return subprocess.run(
        ["sh", str(PROJECT_ROOT / "docker-entrypoint.sh"), "/usr/bin/true"],
        cwd=PROJECT_ROOT,
        env=_entrypoint_environment(config_dir, password_secret),
        text=True,
        capture_output=True,
        check=False,
    )


def test_pending_rotation_never_reactivates_the_previous_persisted_key(tmp_path):
    old_secret = "old-password-secret-that-is-long-enough"
    new_secret = "new-password-secret-that-is-long-enough"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"SECRET_KEY=session-secret-that-is-long-enough-for-tests\nPASSWORD_SECRET={old_secret}\n",
        encoding="utf-8",
    )
    marker = tmp_path / ".password-secret-rotation.pending"

    first = _run_entrypoint(tmp_path, new_secret)
    assert first.returncode == 0
    assert f"PASSWORD_SECRET={old_secret}" in env_file.read_text(encoding="utf-8")
    assert marker.read_text(encoding="utf-8").strip() == hashlib.sha256(new_secret.encode()).hexdigest()

    interrupted_restart = _run_entrypoint(tmp_path, None)
    assert interrupted_restart.returncode != 0
    assert "rotation is pending" in interrupted_restart.stdout

    assert finalize_password_secret_rotation(
        {
            "PASSWORD_SECRET": new_secret,
            "PASSWORD_SECRET_ROTATION_ENV_FILE": str(env_file),
            "PASSWORD_SECRET_ROTATION_MARKER": str(marker),
        }
    )
    assert not marker.exists()
    persisted = env_file.read_text(encoding="utf-8")
    assert f"PASSWORD_SECRET={new_secret}" in persisted
    assert old_secret not in persisted

    completed_restart = _run_entrypoint(tmp_path, None)
    assert completed_restart.returncode == 0


def test_entrypoint_rejects_an_explicit_weak_session_secret(tmp_path):
    environment = _entrypoint_environment(
        tmp_path,
        "password-secret-that-is-long-enough-for-tests",
    )
    environment["SECRET_KEY"] = "x"

    result = subprocess.run(
        ["sh", str(PROJECT_ROOT / "docker-entrypoint.sh"), "/usr/bin/true"],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "SECRET_KEY must contain at least 32 non-trivial bytes" in result.stdout


def test_entrypoint_rejects_an_explicit_long_but_trivial_password_secret(tmp_path):
    result = _run_entrypoint(tmp_path, "a" * 32)

    assert result.returncode != 0
    assert "PASSWORD_SECRET must contain at least 32 non-trivial bytes" in result.stdout


def test_entrypoint_rotates_a_persisted_trivial_password_secret(tmp_path):
    weak_secret = "a" * 32
    env_file = tmp_path / ".env"
    env_file.write_text(f"PASSWORD_SECRET={weak_secret}\n", encoding="utf-8")

    result = _run_entrypoint(tmp_path, None)

    assert result.returncode == 0
    persisted = env_file.read_text(encoding="utf-8")
    assert f"PASSWORD_SECRET_PREVIOUS={weak_secret}" in persisted
    assert f"PASSWORD_SECRET={weak_secret}\n" not in persisted
    assert (tmp_path / ".password-secret-rotation.pending").exists()
