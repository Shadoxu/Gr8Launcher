"""Resolve source and packaged resources without depending on the working directory."""

from pathlib import Path
import sys


# PyInstaller gives packaged modules paths below _internal/wisc/ too.
RESOURCE_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = RESOURCE_ROOT / ".assets"
DATA_DIRECTORY_NAMES = ("wisc", "gr8launcher")


def launcher_data_dir(minecraft_directory: str | Path) -> Path:
    """Use Wisc for new data, retaining an existing installation's directory.

    Reusing the legacy folder preserves absolute artwork paths, transaction
    journals, and the account path used to scope native credentials.
    """
    root = Path(minecraft_directory)
    current, legacy = (root / name for name in DATA_DIRECTORY_NAMES)
    if current.is_dir():
        return current
    return legacy if legacy.is_dir() else current


def application_root() -> Path:
    """Return the install directory for a frozen app, or the source root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return RESOURCE_ROOT
