from __future__ import annotations

import os
from pathlib import Path
import pytest


def _simple_load_env(dotenv_path: Path) -> None:
    try:
        with dotenv_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
    except Exception:
        pass


# Load .env before tests are collected so skipif() can see secrets
def pytest_configure(config):  # type: ignore[override]
    repo_root = Path(__file__).resolve().parents[1]
    dotenv_path = repo_root / ".env"
    if dotenv_path.exists():
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv(dotenv_path=str(dotenv_path), override=False)
        except Exception:
            _simple_load_env(dotenv_path)


# Force anyio to use asyncio backend to avoid optional trio dependency
@pytest.fixture
def anyio_backend():  # type: ignore[override]
    return "asyncio"
