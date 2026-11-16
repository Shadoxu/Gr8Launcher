"""Start Gr8 Launcher from source or a Windows package."""

from gr8launcher.services import updates

if __name__ == "__main__":
    updates.startup_guard()

from gr8launcher.app import run

if __name__ == "__main__":
    run()
