"""EPUB-Konvertierung nach Markdown mit Pandoc."""

from __future__ import annotations

import subprocess
from pathlib import Path


def to_markdown(path: Path) -> str:
    result = subprocess.run(
        ["pandoc", "--from=epub", "--to=gfm-raw_html", "--wrap=none", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc ist fehlgeschlagen: {result.stderr.strip()[-500:]}")
    return result.stdout
