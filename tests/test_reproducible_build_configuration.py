from __future__ import annotations

import pathlib
import re


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}(?:\s|$)")


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_base_images_are_digest_pinned() -> None:
    from_lines = [
        line for line in _read("Dockerfile").splitlines() if line.startswith("FROM ")
    ]

    assert len(from_lines) == 3
    assert all(DIGEST_PATTERN.search(line) for line in from_lines)


def test_release_service_images_are_digest_pinned() -> None:
    compose = _read("docker-compose.yml")
    workflow = _read(".github/workflows/release-gate.yml")
    local_gate = _read("scripts/run_postgresql_release_gate.sh")

    assert re.search(r"image: postgres:16-alpine@sha256:[0-9a-f]{64}", compose)
    assert re.search(r"image: nginx:alpine@sha256:[0-9a-f]{64}", compose)
    assert re.search(r"image: postgres:16-alpine@sha256:[0-9a-f]{64}", workflow)
    assert re.search(r"postgres:16-alpine@sha256:[0-9a-f]{64}", local_gate)


def test_python_installs_enforce_hashed_locks() -> None:
    dockerfile = _read("Dockerfile")
    workflow = _read(".github/workflows/release-gate.yml")
    production_lock = _read("requirements.txt")
    development_lock = _read("requirements-dev.txt")

    assert "--require-hashes -r requirements.txt" in dockerfile
    assert "pip install --no-cache-dir --upgrade pip" not in dockerfile
    assert "--require-hashes -r requirements.txt" in workflow
    assert "--require-hashes -r requirements-dev.txt" in workflow
    assert "pytest==" in development_lock
    assert "--hash=sha256:" in development_lock
    assert "git+" not in production_lock
    assert (
        "python-pytrakt/archive/"
        "db7a1b6d51496f4f91668f760a3cd83d6ae15137.tar.gz" in production_lock
    )
    assert "--hash=sha256:" in production_lock


def test_release_gate_compares_clean_build_inventories() -> None:
    workflow = _read(".github/workflows/release-gate.yml")
    verifier = _read("scripts/verify_reproducible_build.sh")

    assert "verify_reproducible_build.sh octohubs:release-gate" in workflow
    assert verifier.count("build_image \"") == 2
    assert "pip freeze --all" in verifier
    assert "/lib/apk/db/installed" in verifier
    assert "find /app/frontend/dist" in verifier
    assert "diff -u" in verifier


def test_release_gate_runs_all_frontend_p0_checks() -> None:
    workflow = _read(".github/workflows/release-gate.yml")

    assert "frontend-quality:" in workflow
    assert 'node-version: "24"' in workflow
    assert "cache-dependency-path: frontend/package-lock.json" in workflow
    assert "working-directory: frontend" in workflow
    assert "run: npm ci" in workflow
    assert "run: npm test" in workflow
    assert "run: npm run lint" in workflow
    assert "run: npm run build" in workflow
