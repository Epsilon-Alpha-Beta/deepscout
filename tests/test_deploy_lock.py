import shutil
import subprocess
from pathlib import Path

import pytest


def _body(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[2:])


def test_docker_requirements_lock_matches_uv_lock(tmp_path: Path):
    if shutil.which("uv") is None:
        pytest.skip("uv is required to verify the exported deployment lock")

    generated = tmp_path / "requirements.lock.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--extra",
            "postgres",
            "--format",
            "requirements-txt",
            "--no-emit-project",
            "-o",
            str(generated),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    committed = Path("deploy/requirements.lock.txt")
    assert _body(generated) == _body(committed)
