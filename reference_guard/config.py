"""Portable defaults with optional untracked machine-local overrides."""
from __future__ import annotations
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_config(root: Path = ROOT) -> dict:
    root = root.resolve()
    config = tomllib.loads((root / 'config.toml').read_text(encoding='utf-8'))
    local = root / 'config.local.toml'
    if local.exists():
        config.update(tomllib.loads(local.read_text(encoding='utf-8')))
    server = Path(config['server_dir']).expanduser()
    server = (root / server).resolve() if not server.is_absolute() else server.resolve()
    configured_python = config.get('server_python', '')
    if configured_python:
        python = Path(configured_python).expanduser()
        python = (root / python).resolve() if not python.is_absolute() else python.resolve()
    else:
        python = server / 'zotero-pdf2zh-next-venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    config['server_dir'] = str(server)
    config['server_python'] = str(python)
    return config
