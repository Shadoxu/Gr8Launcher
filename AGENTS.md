# Repository Guidelines

## Project Structure & Module Organization

`main.py` is the launch entry point; `wisc/app.py` owns Flet page orchestration. Application modules live in four packages:

| Folder | Start here for |
| --- | --- |
| `wisc/ui/` | Pages, controls, dialogs, profiles, themes, motion, progress, and notifications |
| `wisc/services/` | Minecraft launch/install, instance discovery, profile creation, authentication, skins, artwork, Discord, and updates |
| `wisc/mods/` | Mod providers, compatibility, downloads, metadata, and modpacks |
| `wisc/core/` | Shared state, settings/profiles, native credentials, palette definitions, and resource paths |

Bundled artwork/fonts live in `.assets/`, local tests/scratch work in ignored `temp/`, build/release utilities and the Java skin bridge in `tools/`, installer configuration in `packaging/`, documentation in `docs/`, and the website in `web/` with deployment API functions in `api/`.

## Agent Navigation

- Use [docs/architecture.md](docs/architecture.md) for the module map and resource/entry-point rules. Search the relevant package first, for example `rg -n 'ProfileList' wisc/ui` or `rg --files wisc tools`.
- Avoid whole-workspace scans of generated files or local tests unless the task needs them. Old source copies belong outside the repository; do not recreate `REF/` or `new_ui/` backups.
- Use absolute `wisc.*` imports. Keep package `__init__.py` files lightweight and avoid compatibility copies at the repository root.
- Put new scratch output in `temp/<task>/` and remove it when finished. Retain useful local regression tests; release tools must run without `temp/`.

## Build, Test, and Development Commands

Run from the repository root in a virtual environment. Source supports Python 3.10+; Windows packaging uses x64 Python 3.14.

- `py -3 -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`: set up PowerShell development.
- `python -m pip install -r requirements.txt`: install runtime dependencies.
- `python main.py`: launch; Minecraft needs compatible Java.
- `python -m pip install -r requirements-build.txt`: install pinned build/test dependencies.
- `python tools/build_windows.py --portable-only`: create a ZIP in `dist/`. Omit the flag for an Inno Setup installer; see `docs/releasing.md`.

## Launcher Design Language

Follow `design_theme.txt` and the restored classic components:

- **Palette:** selectable Minecraft themes in `wisc/core/themes.py`, defaulting to Earth 2. Shared chrome uses the fixed dark glass palette; retained feature pages use the selected theme's surface, text, and button tokens through `wisc.ui.theme.apply_legacy_theme`.
- **Typography/assets:** use the supplied Wisc logo and bundled Pixelify Sans for branding and pixel text. Keep existing Minecraft artwork and all bundled font licenses, including the legacy notices in `.assets/font/`. Use system fonts for dense details.
- **Shape:** preserve rounded library cards, compact profile rows, and options cards. Common glass surfaces have rounded corners and no borders; the fixed title bar spans the full width. Keep selection and focus feedback visible.
- **Dropdowns:** use `AcrylicSelector`, or the `LegacySelector` adapter for classic forms. Menus stay anchored to the field width, with 48px closed fields, 5px corners, and theme-colored labels/chevrons. Use one control per filter.
- **Layout:** retain the original top navigation, custom window controls, Home launch panel, and library shelf. Keep selected version artwork across every page and do not restore a separate Home banner. Keep Mods & Modpacks and Options > Updates accessible. Check 1100x650 and larger windows; keep content scrollable and window controls usable.
- **Motion/feedback:** keep the classic tab transitions and reuse `StaggeredReveal`, `ProfileDialogHost`, `ProfileList`, `ProgressHost`, and `ToastHost` for retained features. Keep transitions interruptible, restore state after navigation/canceled drags, and provide concise loading/error feedback.

## Coding Style & Naming Conventions

Use four spaces in new modules; preserve existing indentation, including legacy tabs. Use `snake_case`, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Type-hint helpers. No formatter/linter is configured.

## Testing Guidelines

Use `unittest` (`IsolatedAsyncioTestCase` for async UI), `test_*.py` files, and `test_*` methods. No coverage threshold is configured.

- All tests, UI/browser validation scripts, and scratch output stay local in the ignored `temp/` directory, including maintained regression tests.
- Do not add `.gitignore` exceptions for these files or force-add, stage, commit, or push them unless the user explicitly asks to publish tests.
- GitHub build/release workflows must work from a clean checkout without `temp/` or any local test files. Do not add CI steps that depend on them. Keep the actual build, release, and screenshot utilities in `tools/` versioned.
- Document test commands as local-only; their scripts are not included in a clone.

When the local test files are present, run them from the repository root after installing build dependencies:

```powershell
python -B -m unittest temp.test_release_plan temp.test_release_tag temp.test_publish_screenshot temp.test_ui_toasts
```

## Commit & Pull Request Guidelines

Use focused, descriptive subjects like `Add remote tag validation`. PRs should explain changes, link issues, report validation, and include UI screenshots. New `VERSION` values pushed to `main` trigger publication.

## Release Notes for AI Agents

- For every completed task that adds, changes, fixes, removes, or secures user-facing behavior, create or update one descriptive Markdown fragment in `docs/changes/unreleased/` alongside the code. Follow [docs/changes/README.md](docs/changes/README.md).
- Use `### Added`, `### Changed`, `### Fixed`, `### Removed`, or `### Security` headings and concise bullets explaining the effect for users. Record completed functionality, not plans or implementation logs.
- Use a separate file for each independent task; preserve other agents' fragments. Update the same task's fragment when refining it, and avoid duplicate entries.
- Documentation-only edits, validation-only changes, and internal refactors without visible behavior do not need fragments.
- Before finishing, check that the fragment accurately describes the final change. Do not clear fragments or archive notes when changing `VERSION`; the release workflow archives and clears only successfully published, unchanged fragments.
- Do not bump `VERSION`, stage/commit/push changes, or publish a release merely to maintain notes unless the user requested those actions.

## Security & Configuration Tips

New runtime data lives in Minecraft's `wisc/`; reuse existing `gr8launcher/` folders through `wisc.core.paths.launcher_data_dir`. Preserve native credential storage/redaction and legacy credential aliases. Exclude tokens, personal game data, and generated `build/`/`dist/` artifacts.
