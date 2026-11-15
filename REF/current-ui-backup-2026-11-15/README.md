# Current launcher UI backup

Archived on 2026-11-15 (Asia/Calcutta) before restoring the older launcher UI.

The original UI source files and design_theme.txt were moved here after every
backup file was verified against its original using SHA-256. The Python files
include main.py, all 15 ui_*.py modules, state.py, and both skin-view controllers.

Tracked .assets/ files, requirements.txt, VERSION, and the appearance/progress
documentation were copied for reference. Their originals remain in the project.
Generated asset caches and personal runtime data are not part of this backup.

backup-manifest.json records each original relative path, file size, SHA-256,
and whether the file was moved or copied. Paths match the original repository
layout. To restore the archived UI, copy entries marked "moved" back to the
project root, preserving their relative paths. Check for replacement files first
to avoid overwriting later work.

This is a UI snapshot, not a standalone launcher. Its shared launcher, account,
storage, skin, mod, and updater services remain in the project root. The older
launcher in REF/wisc-1.2.0 and OneClient in REF/OC_SC are separate references.
