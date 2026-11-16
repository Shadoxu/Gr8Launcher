"""Resolve source and packaged resources without depending on the working directory."""

from pathlib import Path
import sys


# PyInstaller gives packaged modules paths below _internal/gr8launcher/ too.
RESOURCE_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = RESOURCE_ROOT / ".assets"


def application_root() -> Path:
    """Return the install directory for a frozen app, or the source root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return RESOURCE_ROOT
