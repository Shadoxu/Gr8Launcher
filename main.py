import asyncio
import base64
import io
import json
import math
import os
import random
import re
import socket
import shutil
import subprocess
import sys
import threading
import time
import uuid
import warnings
import webbrowser
from pathlib import Path

import launcher_updates

if __name__ == "__main__":
    launcher_updates.startup_guard()

import minecraft_launcher_lib

from PIL import Image
import skins
import banners
import state
import storage
from ui_options import build_options_views
from ui_skins import build_skins_view as build_skins_view_external

warnings.filterwarnings("ignore", category=DeprecationWarning)

import flet as ft
from ui_controls import LegacySelector
import ui_theme
from ui_legacy_features import LegacyFeatures, load_ui_installations as load_installations
from ui_library import ClassicLibraryPage
from ui_profile_assets import profile_badges as build_profile_badges, profile_summary
from credential_store import redact_credentials
from launcher_services import check_internet_connection, read_game_output
from launcher_services import installation_sources_stamp, sync_local_installations, remove_installed_version, remove_profile_record
from colors import get_theme, get_theme_names, get_pagecolor, DEFAULT_THEME
from launcher import (
    discover_local_instances,
    get_external_installations,
    get_installed_versions,
    invalidate_installed_versions_cache,
    get_local_version_catalog,
    get_mod_loader,
    get_version_catalog,
    DownloadCancelled,
    import_external_installations,
    minecraft_directory,
    get_system_memory_mb,
    start_game,
    InstallationProgressTracker,
    get_profile_version_id as resolve_profile_version_id,
    get_profile_game_directory,
    get_latest_release_version,
    prepare_launch_profile,
)
from storage import (
    DEFAULT_SETTINGS,
    load_handled_external_profile_ids,
    load_latest_release_id,
    load_profile_options,
    load_settings,
    load_theme_choice,
    save_installations,
    save_profile_options,
    save_settings,
    save_theme_choice,
    get_active_account,
)

ASSETS_DIR = Path(__file__).resolve().parent / ".assets"
THOUGHTS_FILE = ASSETS_DIR / "thoughts.json"
LATEST_RELEASE_PROFILE_ID = "latest-release"
_PROGRESS_UNCHANGED = object()

DEFAULT_THOUGHTS = [
    "Don't dig straight down in Minecraft or in life; pause, look ahead, and choose a safer next step.",
    "Every great Minecraft build begins with one block, and every big change begins with one small action.",
    "Keep exploring: the diamonds you find in a cave are a reminder that hard seasons can still hold hope.",
    "Place a torch where it's dark, and offer a little kindness where someone needs encouragement.",
    "Your Minecraft inventory has limits; make room in life for what matters most.",
    "A world is built one block at a time, and a good life is shaped by small choices made with care.",
    "It's okay to wander off the map; unexpected paths can lead to your favorite discoveries.",
]


def load_thoughts() -> list[str]:
    if THOUGHTS_FILE.is_file():
        try:
            with open(THOUGHTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    parsed = [str(item).strip() for item in data if str(item).strip()]
                    if parsed:
                        return parsed
        except Exception:
            pass
    return DEFAULT_THOUGHTS


def get_random_thought() -> str:
    thoughts = load_thoughts()
    return random.choice(thoughts) if thoughts else DEFAULT_THOUGHTS[0]


def main(page: ft.Page):
    page.window.icon = str(ASSETS_DIR / "icons" / "gr8_icon_r_128.ico")
    available_themes = get_theme_names()
    installations = load_installations()
    profile_options = load_profile_options()
    settings = load_settings()
    maximum_memory_mb = get_system_memory_mb()
    settings["ram_mb"] = min(
        maximum_memory_mb, max(256, int(settings.get("ram_mb", 4096)))
    )
    player_name_state = state.player_name_state
    player_name_state["value"] = profile_options["player_name"]
    launch_selection = state.launch_selection
    launch_selection["key"] = profile_options["last_selected_button"]
    profile_picture_state = state.profile_picture_state
    version_catalog, local_latest_release = get_local_version_catalog()
    latest_release_id = load_latest_release_id() or local_latest_release
    online_available = False
    handled_external_profile_ids = load_handled_external_profile_ids()
    installations, handled_external_profile_ids, imports_changed = (
        import_external_installations(
            installations,
            handled_external_profile_ids,
            get_installed_versions(),
            get_external_installations(),
            version_catalog,
        )
    )
    installations, discovered_changed = discover_local_instances(
        minecraft_directory,
        installations,
        get_installed_versions(),
        version_catalog,
    )
    if (imports_changed or discovered_changed) and not save_installations(
        installations, handled_external_profile_ids, latest_release_id
    ):
        installations = load_installations()
        handled_external_profile_ids = load_handled_external_profile_ids()

    theme_choice = load_theme_choice(available_themes)
    theme = get_theme(theme_choice)
    ui_theme.apply_legacy_theme(theme)
    selected_theme = state.selected_theme
    selected_theme["name"] = theme_choice
    active_page = state.active_page
    refresh_state = state.refresh_state
    connectivity_known = state.connectivity_known
    navigation_state = state.navigation_state
    notification_state = state.notification_state
    intro_state = state.intro_state
    options_background_state = state.options_background_state
    danger_zone_state = state.danger_zone_state
    launcher_log_state = state.launcher_log_state
    page.title = "Gr8 Launcher"
    page.window.width = 1100
    page.window.height = 650
    page.window.min_width = 1100
    page.window.min_height = 650
    page.window.resizable = True
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK

    page.window.prevent_close = False
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.fonts = {name: str(ASSETS_DIR / "font" / "mojangles-v2.otf")
                  for name in ("mojangles", "Mojangles", "ps")}
    clipboard_service = ft.Clipboard()
    page.services.append(clipboard_service)

    # imp functions----

    def minimize_window(e):
        page.window.minimized = True
        page.update()

    def maximize_window(e):
        page.window.maximized = not page.window.maximized
        page.update()

    async def close_window(e):
        features.stop()
        await page.window.close()

    features = LegacyFeatures(page, close=close_window)
    page.on_disconnect = features.stop

    progress_host = features.progress
    launch_activity = {'task': None}
    updater_ui = features.updater
    mods_content = features.mods
    discord_presence = features.presence

    async def refresh_latest_release(force=False):
        nonlocal latest_release_id, online_available
        latest, online = await asyncio.to_thread(get_latest_release_version)
        online_available = online
        if latest:
            latest_release_id = latest
            storage.save_installations(storage.load_installations(), latest_release_id=latest)
        return online

    def get_latest_release_profile() -> dict:
        version_id = latest_release_id or ""
        return {
            "id": LATEST_RELEASE_PROFILE_ID,
            "key": LATEST_RELEASE_PROFILE_ID,
            "name": "Latest Release",
            "loader": "Vanilla",
            "minecraft_version": version_id,
            "loader_version": "",
            "version_id": version_id,
            **storage.load_latest_release_options(),
        }

    def get_account_avatar_bytes(account, scale=1):
        avatar = state.launcher_log_state.get('get_head_avatar')
        return avatar(scale=scale) if avatar else skins.render_head_avatar_bytes(skins.get_default_skin(), scale=scale)

    def add_log_lines(lines):
        append = state.launcher_log_state.get('append_logs')
        if append:
            append(lines)

    def add_log_line(line):
        add_log_lines([line])

    def refresh_launch_button():
        refresh = state.launcher_log_state.get('refresh_play_button')
        if refresh:
            refresh()

    def rebuild_profiles_view():
        if not features.closed:
            features.profiles_changed()

    def rebuild_library_view():
        # The original layout rebuilds its profile rows and library shelf together.
        refresh_launch_button()

    def relogin_account(account):
        features.navigate('options_accounts')
        if features.open_ely_login:
            features.open_ely_login(account)


    def finish_launch_progress():
        if launch_activity["task"]:
            launch_activity["task"].finish()
            launch_activity["task"] = None
        progress_host.set_idle(state.launcher_log_state.get("status") or "Ready to play")

    def update_launch_progress(status=None, value=_PROGRESS_UNCHANGED, eta=None):
        if status is not None:
            state.launcher_log_state["status"] = redact_credentials(str(status))
        if value is not _PROGRESS_UNCHANGED:
            state.launcher_log_state["progress"] = value
        if eta is not None:
            state.launcher_log_state["eta"] = str(eta)
        if state.launcher_log_state.get("running") and not state.launcher_log_state.get("game_started"):
            if launch_activity["task"] is None:
                launch_activity["task"] = progress_host.begin(
                    state.launcher_log_state.get("status") or "Preparing Minecraft...",
                    priority=100, delay=0, show_percentage=False,
                )
            launch_activity["task"].update(
                state.launcher_log_state.get("status") or "Preparing Minecraft...",
                value=state.launcher_log_state.get("progress"), detail=state.launcher_log_state.get("eta", ""),
            )
        else:
            finish_launch_progress()
        classic_update = state.launcher_log_state.get("classic_progress")
        if classic_update:
            classic_update(status, None if value is _PROGRESS_UNCHANGED else value, eta)

    async def launch_profile(target: dict):
        if updater_ui and updater_ui.applying:
            notify("Wait for the launcher update to finish before launching Minecraft.", "warning", "Updates")
            return
        if state.launcher_log_state.get("running"):
            return
        if mods_content.busy:
            notify("Wait for the mod operation to finish before launching Minecraft.", "warning", "Mods")
            return

        active_acc = storage.get_active_account()
        username = active_acc.get("username", "Player").strip() or "Player"
        online_available = False

        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", username):
            update_launch_progress(
                "Invalid username: must be 1-16 letters, numbers, or _."
            )
            notify("Your username must contain 1–16 letters, numbers, or underscores.", "warning", "Invalid username")
            return

        discord_presence.set_player(
            username, get_account_avatar_bytes(active_acc, scale=1),
        )

        if not target.get("loader"):
            target["loader"] = "Vanilla"
        if not target.get("minecraft_version"):
            target["minecraft_version"] = target.get("version_id", "1.21.1")

        installed_ids = {item["version_id"] for item in get_installed_versions()}
        is_downloading = target.get("version_id") not in installed_ids

        state.launcher_log_state["running"] = True
        state.launcher_log_state["game_started"] = False
        state.launcher_log_state["downloading"] = is_downloading
        state.launcher_log_state["cancelling"] = False
        state.launcher_log_state["cancel_event"] = threading.Event()
        state.launcher_log_state["target_version_id"] = target.get("version_id")
        state.launcher_log_state["target_profile_id"] = target.get("id")
        discord_presence.prepare_game(target, installing=is_downloading)

        refresh_launch_button()
        rebuild_profiles_view()
        rebuild_library_view()

        update_launch_progress(
            f"Preparing {target.get('name', 'Minecraft')}...", value=None, eta=""
        )
        notify(f"Preparing {target.get('name', 'Minecraft')}…", "info", "Getting ready")

        is_modded = (target.get("loader") or "Vanilla").lower() != "vanilla"
        tracker = InstallationProgressTracker(is_modded=is_modded)

        def report_status(status):
            status_str = str(status)
            add_log_line(f"[*] {status_str}")
            tracker.on_status(status_str)
            lower = status_str.lower()
            if (
                "download" in lower
                or "librar" in lower
                or "asset" in lower
                or "install" in lower
                or "unpack" in lower
            ):
                if not state.launcher_log_state.get("downloading"):
                    state.launcher_log_state["downloading"] = True
                    if not state.launcher_log_state.get("game_started"):
                        discord_presence.prepare_game(target, installing=True)
                    refresh_launch_button()
            elif status_str in (
                "Building launch command...",
                "Starting Minecraft...",
                "Minecraft is running...",
            ):
                if state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                    state.launcher_log_state["downloading"] = False
                    if not state.launcher_log_state.get("game_started"):
                        discord_presence.prepare_game(target)
                    refresh_launch_button()

            # During installation, only the UI loop publishes tracker snapshots.
            # Per-file statuses must not reset measured progress to indeterminate.
            if not state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                update_launch_progress(status_str, value=None, eta="")

        def set_progress_maximum(maximum):
            tracker.on_max(maximum)

        def report_progress(current):
            tracker.on_progress(current)

        callback = {
            "setStatus": report_status,
            "setMax": set_progress_maximum,
            "setProgress": report_progress,
        }

        async def progress_ui_loop():
            while state.launcher_log_state.get(
                "running"
            ) and not state.launcher_log_state.get("game_started"):
                if state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                    ratio, status_text, eta_text = tracker.get_display_state()
                    update_launch_progress(status_text, ratio, eta_text)
                await asyncio.sleep(0.05)

        progress_task = None
        output_task = None
        log_file = None
        settings = storage.load_settings()
        launch_action = settings.get("launch_action", "Keep launcher open")

        try:
            online_available = await refresh_latest_release()
            if online_available:
                account = await asyncio.to_thread(storage.get_active_account, include_credentials=True)
                if account.get("type") == "ely" and not account.get("access_token"):
                    update_launch_progress("Sign in to continue.", value=0.0, eta="")
                    notify("Sign in again to launch Minecraft with your Ely.by account.", "warning", "Sign-in required")
                    relogin_account(account)
                    return
            if target.get("id") == LATEST_RELEASE_PROFILE_ID:
                update_launch_progress("Checking latest release...", value=None, eta="")
                target = get_latest_release_profile()
                if state.launcher_log_state["cancel_event"].is_set():
                    raise DownloadCancelled("Version download cancelled.")
                if not target["version_id"]:
                    raise RuntimeError("Connect to the internet to find the latest release.")
                state.launcher_log_state["target_version_id"] = target["version_id"]
                state.launcher_log_state["downloading"] = (
                    target["version_id"] not in installed_ids
                )
                discord_presence.prepare_game(
                    target, installing=state.launcher_log_state["downloading"],
                )
                refresh_launch_button()
            progress_task = asyncio.create_task(progress_ui_loop())
            process, log_file = await start_game(
                target,
                username,
                online_available,
                callback,
                settings,
                state.launcher_log_state["cancel_event"],
            )
            tracker.finish()
            state.launcher_log_state["game_started"] = True
            state.launcher_log_state["downloading"] = False
            game_account = getattr(process, "gr8_presence_player", active_acc)
            game_face = getattr(process, "gr8_presence_face", None)
            if game_face is None:
                game_face = get_account_avatar_bytes(game_account, scale=1)
            discord_presence.game_started(
                target,
                player_name=str(game_account.get("username") or username),
                face_png=game_face,
            )
            update_launch_progress("Minecraft is running...", value=1.0, eta="")
            notify(f"{target.get('name', 'Minecraft')} is running.", "success", "Minecraft started")
            refresh_launch_button()

            loop = asyncio.get_running_loop()
            output_task = asyncio.create_task(
                asyncio.to_thread(
                    read_game_output, process, log_file,
                    lambda lines: loop.call_soon_threadsafe(add_log_lines, lines),
                    sensitive_values=getattr(process, "gr8_sensitive_values", ()),
                )
            )

            if launch_action == "Hide launcher":
                page.window.visible = False
                page.update()
            elif launch_action == "Close launcher":
                page.run_task(close_window, None)

            exit_code = await asyncio.to_thread(process.wait)
            if output_task is not None:
                await output_task

            if launch_action == "Hide launcher":
                page.window.visible = True
                page.update()

            update_launch_progress(
                (
                    "Ready to play"
                    if exit_code == 0
                    else f"Minecraft exited with code {exit_code}."
                ),
                value=0.0,
                eta="",
            )
            if exit_code == 0:
                notify("Minecraft has closed. You're ready to play again.", "info", "Game closed")
            else:
                notify(f"Minecraft exited with code {exit_code}. Open the logs for details.", "error", "Minecraft stopped")
        except DownloadCancelled:
            update_launch_progress("Version download cancelled.", value=0.0, eta="")
            notify("The version download was cancelled.", "info", "Installation cancelled")
        except Exception as error:
            if launch_action == "Hide launcher":
                try:
                    page.window.visible = True
                    page.update()
                except Exception:
                    pass
            update_launch_progress(f"Launch failed: {error}", value=0.0, eta="")
            notify(str(error), "error", "Launch failed")
        finally:
            discord_presence.game_finished()
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:
                    pass

            state.launcher_log_state["running"] = False
            state.launcher_log_state["game_started"] = False
            state.launcher_log_state["downloading"] = False
            state.launcher_log_state["cancelling"] = False
            state.launcher_log_state["cancel_event"] = None
            state.launcher_log_state["target_version_id"] = None
            state.launcher_log_state["target_profile_id"] = None
            finish_launch_progress()
            refresh_launch_button()
            rebuild_profiles_view()
            rebuild_library_view()

    async def repair_profile(target: dict):
        if updater_ui and updater_ui.applying:
            notify("Wait for the launcher update to finish before repairing Minecraft.", "warning", "Updates")
            return
        if state.launcher_log_state.get("running"):
            return
        if mods_content.busy:
            notify("Wait for the mod operation to finish before repairing Minecraft.", "warning", "Mods")
            return

        try:
            target = prepare_launch_profile(target, get_installed_versions(force_refresh=True))
        except (KeyError, ValueError) as error:
            update_launch_progress(f"Cannot repair this profile: {error}", value=0.0, eta="")
            notify(str(error), "error", "Cannot repair profile")
            return

        loader = str(target.get("loader") or "Vanilla").strip()
        mc_ver = str(
            target.get("minecraft_version") or target.get("version_id") or ""
        ).strip()
        loader_ver = str(target.get("loader_version") or "").strip()

        if not mc_ver:
            update_launch_progress(
                f"Cannot repair {target.get('name', 'Installation')}: missing Minecraft version.",
                value=0.0,
                eta="",
            )
            notify("This profile is missing its Minecraft version.", "error", "Cannot repair profile")
            return

        state.launcher_log_state["running"] = True
        state.launcher_log_state["downloading"] = True
        state.launcher_log_state["cancelling"] = False
        state.launcher_log_state["cancel_event"] = threading.Event()
        refresh_launch_button()
        rebuild_profiles_view()
        rebuild_library_view()

        update_launch_progress(
            f"Repairing & verifying {target.get('name', 'Installation')}...",
            value=None,
            eta="",
        )
        notify(f"Repairing and verifying {target.get('name', 'Installation')}…", "info", "Repair started")

        is_modded = loader.lower() != "vanilla"
        tracker = InstallationProgressTracker(is_modded=is_modded)

        def report_status(status):
            status_str = str(status)
            add_log_line(f"[*] {status_str}")
            # Keep raw file statuses in the log; the UI loop renders progress.
            tracker.on_status(status_str)

        def set_progress_maximum(maximum):
            tracker.on_max(maximum)

        def report_progress(current):
            tracker.on_progress(current)

        def install_callback_handler(name):
            def handler(*args):
                cancel_event = state.launcher_log_state.get("cancel_event")
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Repair cancelled.")
                cb_map = {
                    "setStatus": report_status,
                    "setProgress": report_progress,
                    "setMax": set_progress_maximum,
                }
                cb_map.get(name, lambda *_: None)(*args)
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Repair cancelled.")

            return handler

        install_callback = {
            name: install_callback_handler(name)
            for name in ("setStatus", "setProgress", "setMax")
        }

        async def progress_ui_loop():
            while state.launcher_log_state.get(
                "running"
            ) and state.launcher_log_state.get("downloading"):
                if not state.launcher_log_state.get("cancelling"):
                    ratio, status_text, eta_text = tracker.get_display_state()
                    update_launch_progress(status_text, ratio, eta_text)
                await asyncio.sleep(0.05)

        progress_task = None
        try:
            progress_task = asyncio.create_task(progress_ui_loop())
            if loader.lower() == "vanilla":
                await asyncio.to_thread(
                    minecraft_launcher_lib.install.install_minecraft_version,
                    mc_ver,
                    minecraft_directory,
                    install_callback,
                )
            else:
                mod_loader = get_mod_loader(loader)
                repaired_version = await asyncio.to_thread(
                    mod_loader.install,
                    mc_ver,
                    minecraft_directory,
                    loader_version=loader_ver,
                    callback=install_callback,
                )
                if repaired_version != target["version_id"]:
                    raise RuntimeError("The installer returned a different version than the pinned profile.")
            invalidate_installed_versions_cache()
            tracker.finish()
            update_launch_progress(
                f"Successfully repaired {target.get('name')}.", value=0.0, eta=""
            )
            notify(f"Successfully repaired {target.get('name', 'the profile')}.", "success", "Repair complete")
        except DownloadCancelled:
            update_launch_progress("Repair cancelled.", value=0.0, eta="")
            notify("The profile repair was cancelled.", "info", "Repair cancelled")
        except Exception as error:
            update_launch_progress(f"Repair failed: {error}", value=0.0, eta="")
            notify(str(error), "error", "Repair failed")
        finally:
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            state.launcher_log_state["running"] = False
            state.launcher_log_state["downloading"] = False
            state.launcher_log_state["cancelling"] = False
            state.launcher_log_state["cancel_event"] = None
            finish_launch_progress()
            refresh_launch_button()
            rebuild_profiles_view()
            rebuild_library_view()

    features.on_repair = repair_profile


    def notify(message, icon=ft.Icons.INFO_OUTLINE, title=None, **kwargs):
        if icon in ("info", "success", "warning", "error", "update"):
            kind = icon
        elif icon in (ft.Icons.ERROR_OUTLINE, ft.Icons.ERROR):
            kind = "error"
        elif icon in (ft.Icons.CHECK_CIRCLE, ft.Icons.CHECK_CIRCLE_OUTLINE):
            kind = "success"
        else:
            kind = "info"
        features.notify(message, kind, title, **kwargs)

    def persist_setting(key, value):
        current = load_settings()
        current[key] = value
        if not save_settings(current):
            notify("Could not save settings.", "error")
            return
        settings.update(current)
        if key == "discord_rpc":
            features.presence.set_enabled(bool(value) and not page.web)

    def change_theme(e):
        new_choice = e.control.value
        if new_choice not in available_themes:
            return

        if features.busy:
            e.control.value = selected_theme["name"]
            e.control.update()
            notify("Wait for the current operation before changing themes.", "warning")
            return
        if not save_theme_choice(new_choice):
            notify("Could not save the selected theme.", "error")
            return
        selected_theme["name"] = new_choice
        page.controls.clear()
        build_page(new_choice, active_page.get("name", "options"))

    def get_themes_options() -> list[ft.DropdownOption]:
        return [
            ft.DropdownOption(
                key=theme,
                text=theme,
            )
            for theme in available_themes
        ]


    from ui_components import (
        NavigationTabs,
        tooltip,
        clickable_mouse_cursor,
        window_button_style,
        rounded_button_style,
    )

    def build_page(theme_select, tab="home"):
        theme = get_theme(theme_select)
        if features.library:
            features.library.leave()
            features.library = None
        features.apply_theme(theme)
        page.theme = ft.Theme(
            font_family="Segoe UI", color_scheme_seed=theme["btn_primary"],
            color_scheme=ft.ColorScheme(primary=theme["btn_primary"], on_primary=theme["btn_primary_text"],
                                       surface=theme["surface"], on_surface=theme["text_primary"], outline=theme["border"]),
        )
        page.bgcolor = get_pagecolor()
        clickable_mouse_cursor = {
            ft.ControlState.DISABLED: ft.MouseCursor.BASIC,
            ft.ControlState.DEFAULT: ft.MouseCursor.CLICK,
        }
        window_button_style = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
        rounded_button_style = ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
            mouse_cursor=clickable_mouse_cursor,
        )

        def build_themed_switch(label: str, value: bool, on_change=None):
            return ft.Switch(
                label=label,
                value=value,
                active_color=theme["btn_primary"],
                active_track_color=ft.Colors.with_opacity(0.38, theme["btn_primary"]),
                inactive_thumb_color=theme["text_secondary"],
                inactive_track_color=theme["surface"],
                track_outline_color=ft.Colors.with_opacity(0.4, theme["text_secondary"]),
                on_change=on_change,
            )

        dialog_blur_overlay = ft.Container(
            left=0,
            top=0,
            right=0,
            bottom=0,
            expand=True,
            blur=ft.Blur(4, 4),
            bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
            visible=False,
            animate_opacity=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
        )
        page.overlay.clear()
        page.overlay.append(dialog_blur_overlay)

        def show_dialog_with_blur(dlg: ft.AlertDialog):
            dialog_blur_overlay.visible = True
            page.show_dialog(dlg)
            page.update()

        def hide_dialog_blur(e=None):
            if dialog_blur_overlay.visible:
                dialog_blur_overlay.visible = False
                page.update()

        def close_dialog_with_blur(dlg: ft.AlertDialog):
            dlg.open = False
            hide_dialog_blur()

        def build_themed_alert_dialog(
            title: ft.Control,
            content: ft.Control,
            actions: list[ft.Control],
            modal: bool = False,
            on_dismiss=None,
        ) -> ft.AlertDialog:
            def handle_dismiss(e):
                hide_dialog_blur()
                if on_dismiss:
                    on_dismiss(e)

            return ft.AlertDialog(
                modal=modal,
                title=title,
                content=content,
                actions=actions,
                bgcolor=theme["surface"],
                elevation=0,
                shape=ft.RoundedRectangleBorder(radius=14),
                barrier_color=ft.Colors.TRANSPARENT,
                on_dismiss=handle_dismiss,
            )

        launcher_log_state["tooltip_func"] = tooltip

        def copy_to_clipboard(text: str, message: str = "Copied to clipboard!"):
            try:
                page.run_task(clipboard_service.set, text)
            except Exception:
                pass
            if os.name == "nt":
                try:
                    p = subprocess.Popen(
                        ["clip"],
                        stdin=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    p.communicate(input=text.encode("utf-16le"))
                except Exception:
                    pass
            notify(message, ft.Icons.CHECK_CIRCLE_OUTLINE)

        def open_url(url: str, message: str = ""):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(url)
                else:
                    webbrowser.open(url)
            except Exception:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            if message:
                notify(message, ft.Icons.OPEN_IN_NEW)

        func_buttons = [
            ft.IconButton(
                icon=ft.Icons.HORIZONTAL_RULE,
                on_click=minimize_window,
                icon_color=theme["text_primary"],
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=17,
                style=window_button_style,
            ),
            ft.IconButton(
                icon=ft.Icons.CROP_SQUARE,
                on_click=maximize_window,
                icon_color=theme["text_primary"],
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=17,
                style=window_button_style,
            ),
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                on_click=close_window,
                icon_color=theme["btn_primary"],
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=21,
                style=window_button_style,
            ),
        ]

        theme_dropdown = LegacySelector(
            label="Choose a Theme",
            value=theme_select,
            label_style=ft.TextStyle(size=13, color=theme["text_secondary"]),
            on_select=change_theme,
            options=get_themes_options(),
            border=ft.OutlineInputBorder(side=ft.BorderSide(color=theme["border"])),
        )

        notification_text = ft.Text(
            size=13,
            color=theme["text_primary"],
            expand=True,
            max_lines=3,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        notification_icon = ft.Icon(
            ft.Icons.INFO_OUTLINE, color=theme["btn_primary"], size=19
        )
        notification_timer = ft.ProgressBar(
            value=0,
            bar_height=3,
            bgcolor=theme["border"],
            color=theme["btn_primary"],
            expand=True,
            rtl=False,
        )
        notification_banner = ft.Container(
            width=380,
            visible=False,
            opacity=0,
            offset=ft.Offset(1, -1),
            animate_opacity=ft.Animation(380, ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_offset=ft.Animation(460, ft.AnimationCurve.EASE_OUT_CUBIC),
            bgcolor=ft.Colors.with_opacity(0.9, theme["surface"]),
            border=ft.Border.all(1, color=theme["border"]),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color=ft.Colors.with_opacity(0.2, "#000000"),
                offset=ft.Offset(0, 5),
            ),
            top=12,
            right=12,
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                        content=ft.Row(
                            controls=[notification_icon, notification_text],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=10,
                        ),
                    ),
                    ft.Container(
                        padding=ft.Padding.only(left=12, right=12, bottom=9),
                        content=notification_timer,
                    ),
                ],
            ),
        )

        async def animate_notification(message, icon, epoch):
            try:
                notification_text.value = message
                notification_icon.name = icon
                notification_timer.value = 0
                notification_banner.visible = True
                notification_banner.opacity = 0
                notification_banner.offset = ft.Offset(1, -1)
                try:
                    page.update()
                except Exception:
                    return
                await asyncio.sleep(0.05)
                if notification_state["epoch"] != epoch:
                    return
                notification_banner.opacity = 1
                notification_banner.offset = ft.Offset(0, 0)
                try:
                    page.update()
                except Exception:
                    return
                loop = asyncio.get_running_loop()
                started_at = loop.time()
                while True:
                    await asyncio.sleep(1 / 30)
                    if notification_state["epoch"] != epoch:
                        return
                    elapsed = loop.time() - started_at
                    notification_timer.value = min(1, elapsed / 5)
                    try:
                        notification_timer.update()
                    except Exception:
                        return
                    if elapsed >= 5:
                        break
                if notification_state["epoch"] != epoch:
                    return
                notification_banner.opacity = 0
                notification_banner.offset = ft.Offset(1, -1)
                try:
                    page.update()
                except Exception:
                    return
                await asyncio.sleep(0.5)
                if notification_state["epoch"] == epoch:
                    notification_banner.visible = False
                    try:
                        page.update()
                    except Exception:
                        return
            except Exception:
                return

        def show_notification():
            pending = notification_state.get("pending")
            if pending is None:
                return
            notification_state["pending"] = None
            notification_state["epoch"] += 1
            page.run_task(
                animate_notification,
                pending[0],
                pending[1],
                notification_state["epoch"],
            )

        notification_state["show"] = show_notification

        # ---- animation overhaul: startup ripple & navigation transitions ----
        def prepare_intro(control):
            """Hide a control so the startup ripple can reveal it with a pop."""
            if not intro_state["pending"]:
                return control
            control.opacity = 0
            control.scale = 0.92
            control.offset = ft.Offset(0, 0.06)
            control.animate_opacity = ft.Animation(340, ft.AnimationCurve.EASE_OUT_CUBIC)
            control.animate_scale = ft.Animation(460, ft.AnimationCurve.EASE_OUT_BACK)
            control.animate_offset = ft.Animation(460, ft.AnimationCurve.EASE_OUT_BACK)
            intro_state["targets"].append(control)
            return control

        def reveal_intro(control):
            control.opacity = 1
            control.scale = 1.0
            control.offset = ft.Offset(0, 0)

        async def play_intro_ripple():
            """Reveal every registered control one by one for a ripple entrance."""
            if not intro_state["pending"]:
                return
            intro_state["pending"] = False
            intro_state["running"] = True
            raw_targets = list(intro_state["targets"])
            # Reorder navbar targets to the front so the ripple cascades from top to bottom
            navbar_set = set()
            try:
                navbar_set.update([title_wrap, tabs_pop_wrap, func_buttons_wrap])
            except Exception:
                pass
            targets = [t for t in raw_targets if t in navbar_set] + [
                t for t in raw_targets if t not in navbar_set
            ]
            await asyncio.sleep(0.12)
            try:
                for control in targets:
                    reveal_intro(control)
                    try:
                        control.update()
                    except Exception:
                        pass
                    await asyncio.sleep(0.045)
            finally:
                # Safety net: nothing may stay hidden, even if a control got detached.
                for control in targets:
                    reveal_intro(control)
                try:
                    page.update()
                except Exception:
                    pass
                intro_state["running"] = False

        # ---- content area: this is what swaps when you navigate ----
        page_content = ft.Container(
            expand=True,
            opacity=1.0,
            animate_opacity=ft.Animation(160, ft.AnimationCurve.EASE_IN),
        )

        content_area = ft.Container(
            content=ft.Stack(
                expand=True,
                controls=[page_content, notification_banner],
                clip_behavior=ft.ClipBehavior.NONE,
            ),
            expand=True,
            bgcolor=theme["bg"],
            # border=ft.Border.all(1, color=theme["border"]),
            border_radius=10,
            margin=ft.Margin.only(left=10, top=0, right=10, bottom=10),
        )
        features.mount(page_content, content_area)

        transition_id = 0
        current_page = None

        async def transition_page(name, content, request_id):
            nonlocal tab
            page_content.animate_opacity = ft.Animation(90, ft.AnimationCurve.EASE_OUT)
            page_content.opacity = 0
            page.update()
            await asyncio.sleep(0.08)

            if request_id != transition_id:
                return

            page_content.content = content
            if name in tab_names:
                tab = name
            elif name.startswith("options"):
                tab = "options"
            else:
                tab = "installations"
            previous_tab_index = tabs_buttons.selected_index
            new_tab_index = tab_names.index(tab)
            tabs_buttons.selected_index = new_tab_index
            page_content.animate_opacity = ft.Animation(160, ft.AnimationCurve.EASE_IN)
            page_content.opacity = 1
            page.update()
            if name == "mods":
                features.reveal.show(content, features.mods.reveal_controls)
                features.mods.start_loading()

        def show_page(name, content):
            nonlocal current_page, transition_id, tab
            if page_content.content is None:
                page_content.content = content
                current_page = name
                tab = name if name in tab_names else "options" if name.startswith("options") else "installations"
                tabs_buttons.selected_index = tab_names.index(tab)
                page.update()
                if name == "mods":
                    features.mods.start_loading()
                return
            transition_id += 1
            current_page = name
            page.run_task(transition_page, name, content, transition_id)

        loader_catalog_cache = {}

        def get_profile_version_id(profile):
            return resolve_profile_version_id(profile)

        def is_active_launch_version(version_id, profile_id=None):
            if not launcher_log_state["running"]:
                return False
            return (
                version_id == launcher_log_state["target_version_id"]
                or profile_id == launcher_log_state["target_profile_id"]
            )

        all_ambient_orbs = []

        def create_ambient_gradient_orbs():
            enabled = bool(settings.get("enable_orbs", True))
            first_orb = ft.Container(
                width=450,
                height=450,
                border_radius=225,
                gradient=ft.RadialGradient(
                    colors=[
                        ft.Colors.with_opacity(0.24, theme["btn_primary"]),
                        ft.Colors.with_opacity(0.08, theme["btn_primary"]),
                        ft.Colors.TRANSPARENT,
                    ],
                    stops=[0.0, 0.55, 1.0],
                ),
                left=random.uniform(-120, 260),
                top=random.uniform(-100, 190),
                scale=random.uniform(0.88, 1.16),
                opacity=random.uniform(0.72, 1.0),
                animate_position=ft.Animation(10000, ft.AnimationCurve.EASE_IN_OUT),
                animate_scale=ft.Animation(10000, ft.AnimationCurve.EASE_IN_OUT),
                animate_opacity=ft.Animation(10000, ft.AnimationCurve.EASE_IN_OUT),
                visible=enabled,
            )
            second_orb = ft.Container(
                width=420,
                height=420,
                border_radius=210,
                gradient=ft.RadialGradient(
                    colors=[
                        ft.Colors.with_opacity(
                            0.20, theme.get("btn_primary_hover", theme["btn_primary"])
                        ),
                        ft.Colors.with_opacity(
                            0.06, theme.get("btn_primary_hover", theme["btn_primary"])
                        ),
                        ft.Colors.TRANSPARENT,
                    ],
                    stops=[0.0, 0.55, 1.0],
                ),
                right=random.uniform(-120, 260),
                bottom=random.uniform(-100, 190),
                scale=random.uniform(0.88, 1.16),
                opacity=random.uniform(0.72, 1.0),
                animate_position=ft.Animation(11000, ft.AnimationCurve.EASE_IN_OUT),
                animate_scale=ft.Animation(11000, ft.AnimationCurve.EASE_IN_OUT),
                animate_opacity=ft.Animation(11000, ft.AnimationCurve.EASE_IN_OUT),
                visible=enabled,
            )
            all_ambient_orbs.append((first_orb, second_orb))
            return first_orb, second_orb

        async def _animate_single_orb(
            orb, is_active, coord_mode, min_x, max_x, min_y, max_y
        ):
            await asyncio.sleep(random.uniform(0.1, 0.4))
            while is_active() and settings.get("enable_orbs", True):
                duration = random.randint(8000, 16000)
                anim = ft.Animation(duration, ft.AnimationCurve.EASE_IN_OUT)
                orb.animate_position = anim
                orb.animate_scale = anim
                orb.animate_opacity = anim

                target_x = random.uniform(min_x, max_x)
                target_y = random.uniform(min_y, max_y)
                target_scale = random.uniform(0.88, 1.16)
                target_opacity = random.uniform(0.72, 1.0)

                if coord_mode == "top_left":
                    orb.left = target_x
                    orb.top = target_y
                else:
                    orb.right = target_x
                    orb.bottom = target_y
                orb.scale = target_scale
                orb.opacity = target_opacity

                try:
                    orb.update()
                except Exception:
                    return

                await asyncio.sleep(duration / 1000)

        async def animate_ambient_gradient_orbs(first_orb, second_orb, is_active):
            if not settings.get("enable_orbs", True):
                return
            await asyncio.sleep(0.1)
            t1 = asyncio.create_task(
                _animate_single_orb(first_orb, is_active, "top_left", -120, 260, -100, 190)
            )
            t2 = asyncio.create_task(
                _animate_single_orb(second_orb, is_active, "bottom_right", -120, 260, -100, 190)
            )
            try:
                await asyncio.gather(t1, t2)
            except Exception:
                pass

        def start_active_page_orb_animation():
            page_name = active_page.get("name")
            if page_name == "home":
                callback = globals().get("animate_launcher_log_background")
                if callable(callback):
                    page.run_task(callback)
            elif page_name == "options":
                callback = options_background_state.get("animate")
                if callable(callback):
                    page.run_task(callback)

        def set_orbs_enabled(enabled: bool):
            persist_setting("enable_orbs", enabled)
            for o1, o2 in all_ambient_orbs:
                o1.visible = enabled
                o2.visible = enabled
                try:
                    o1.update()
                except Exception:
                    pass
                try:
                    o2.update()
                except Exception:
                    pass
            if enabled:
                start_active_page_orb_animation()

        from ui_installations import build_installation_editor as _build_installation_editor

        def build_installation_editor(profile=None, name_only=False):
            return _build_installation_editor(
                profile=profile,
                name_only=name_only,
                page=page,
                theme=theme,
                settings=settings,
                installations=installations,
                handled_external_profile_ids=handled_external_profile_ids,
                latest_release_id=latest_release_id,
                version_catalog=version_catalog,
                loader_catalog_cache=loader_catalog_cache,
                navigate=navigate,
                notify=notify,
                online_available=online_available,
                show_dialog_with_blur=show_dialog_with_blur,
                close_dialog_with_blur=close_dialog_with_blur,
                features=features,
            )
        def navigate(name, profile_id=None, force=False):
            nonlocal current_page, transition_id, tab, handled_external_profile_ids
            if name == "profiles":
                name = "options_accounts"
            if current_page == name and active_page.get("profile_id") == profile_id and not force:
                return
            if features.busy and name in ("new_installation", "edit_installation", "configure_installed"):
                notify("Wait for the current operation to finish.", "warning")
                return
            installations[:] = load_installations()
            settings.update(load_settings())
            if name == "edit_installation":
                profile = next(
                    (item for item in installations if item["id"] == profile_id),
                    None,
                )
                if profile is None:
                    notify("This profile is no longer available.", "warning")
                    return
                if profile and is_active_launch_version(
                    get_profile_version_id(profile), profile_id
                ):
                    notify("This profile is busy launching.", ft.Icons.INFO_OUTLINE)
                    return
            if name == "configure_installed" and is_active_launch_version(profile_id):
                notify("This version is busy installing or launching.", ft.Icons.INFO_OUTLINE)
                return
            active_page["name"] = name
            active_page["profile_id"] = profile_id
            features.enter(name, profile_id, defer_load=name == "mods")
            if name == "mods":
                # Retained pages own their state. Do not rebuild the Home
                # launch controls while a different page is being mounted.
                show_page(name, features.mods)
                return

            installed_versions = get_installed_versions(force_refresh=force or name in ("home", "installations"))
            if force or name in ("home", "installations"):
                installations[:], handled_external_profile_ids, imp_changed = (
                    import_external_installations(
                        installations,
                        handled_external_profile_ids,
                        installed_versions,
                        get_external_installations(),
                        version_catalog,
                    )
                )
                installations[:], disc_changed = discover_local_instances(
                    minecraft_directory,
                    installations,
                    installed_versions,
                    version_catalog,
                )
                if imp_changed or disc_changed:
                    save_installations(
                        installations,
                        handled_external_profile_ids,
                        latest_release_id,
                    )

            def open_game_folder(folder_path):
                try:
                    path = Path(folder_path or minecraft_directory)
                    path.mkdir(parents=True, exist_ok=True)
                    if hasattr(os, "startfile"):
                        os.startfile(str(path))
                    elif sys.platform == "darwin":
                        subprocess.Popen(
                            ["open", str(path)],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        subprocess.Popen(
                            ["xdg-open", str(path)],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                except Exception:
                    pass

            profiles_by_version = {
                get_profile_version_id(profile): profile
                for profile in installations
                if get_profile_version_id(profile)
            }
            local_version_ids = {
                version["version_id"] for version in installed_versions
            }
            def confirm_delete(profile_id):
                profile = next((item for item in installations if item['id'] == profile_id), None)
                if profile is None or features.busy:
                    notify('Wait for the current operation to finish.', 'warning')
                    return
                delete_files = ft.Checkbox(label="Also permanently delete this instance's game files",
                                          value=False, visible=bool(profile.get('is_instance')))
                dialog = build_themed_alert_dialog(
                    title=ft.Text('Remove profile?', color=theme['text_primary']),
                    content=ft.Column([
                        ft.Text(f"Remove {profile['name']} from the launcher? Minecraft files are preserved by default.",
                                color=theme['text_secondary']), delete_files], tight=True),
                    actions=[ft.TextButton('Cancel', on_click=lambda e: close_delete_dialog(dialog)),
                             ft.Button('Remove', on_click=lambda e: delete_profile(profile_id, dialog, delete_files.value))])
                show_dialog_with_blur(dialog)

            def confirm_delete_installed_version(version_id):
                if is_active_launch_version(version_id):
                    notify("This version is busy installing or launching.", ft.Icons.INFO_OUTLINE)
                    return
                dialog = build_themed_alert_dialog(
                    title=ft.Text(
                        "Delete installed version?",
                        color=theme["btn_primary"],
                        weight=ft.FontWeight.BOLD,
                    ),
                    content=ft.Text(
                        f"Permanently remove '{version_id}' from Minecraft and its launcher profile?",
                        color=theme["text_primary"],
                    ),
                    actions=[
                        ft.TextButton(
                            "Cancel",
                            on_click=lambda e: close_delete_dialog(dialog),
                            style=ft.ButtonStyle(
                                color=theme["text_secondary"],
                                mouse_cursor=clickable_mouse_cursor,
                            ),
                        ),
                        ft.Button(
                            "Delete version",
                            bgcolor=theme["btn_primary"],
                            color=theme["btn_primary_text"],
                            style=rounded_button_style,
                            on_click=lambda e: delete_installed_version(
                                version_id, dialog
                            ),
                        ),
                    ],
                )
                show_dialog_with_blur(dialog)

            def show_unconfigured_version_info(version_id):
                dialog = build_themed_alert_dialog(
                    title=ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.INFO_OUTLINE, color=theme["btn_primary"], size=22),
                            ft.Text("Unconfigured Version", color=theme["text_primary"], weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    content=ft.Column(
                        spacing=8,
                        tight=True,
                        controls=[
                            ft.Text(
                                f"'{version_id}' is saved on your disk in Minecraft's versions folder, but is not configured as a profile in the launcher.",
                                size=13,
                                color=theme["text_primary"],
                            ),
                            ft.Text(
                                "• To add this version to your launcher, click the '+' button on the right.\n"
                                "• To permanently delete this version from your disk, click the delete (trash) button on the right.",
                                size=12,
                                color=theme["text_secondary"],
                            ),
                        ],
                    ),
                    actions=[
                        ft.Button(
                            "Got it",
                            bgcolor=theme["btn_primary"],
                            color=theme["btn_primary_text"],
                            style=rounded_button_style,
                            on_click=lambda e: close_delete_dialog(dialog),
                        ),
                    ],
                )
                show_dialog_with_blur(dialog)

            def delete_installed_version(version_id, dialog):
                matching_ids = {
                    item["id"]
                    for item in installations
                    if get_profile_version_id(item) == version_id
                }
                updated_installations = [
                    item for item in installations if item["id"] not in matching_ids
                ]
                if not save_installations(
                    updated_installations,
                    handled_external_profile_ids,
                    latest_release_id,
                ):
                    dialog.content = ft.Text("Could not update Launcher profiles.")
                    page.update()
                    return
                if not remove_installed_version(version_id):
                    save_installations(
                        installations, handled_external_profile_ids, latest_release_id
                    )
                    dialog.content = ft.Text(
                        "Could not delete the Minecraft version or update its launcher profile."
                    )
                    page.update()
                    return

                installations[:] = updated_installations
                if launch_selection["key"] in matching_ids:
                    launch_selection["key"] = (
                        "latest-release" if latest_release_id else ""
                    )
                    save_profile_options(
                        player_name_state["value"],
                        launch_selection["key"],
                        profile_picture_state["path"],
                    )
                close_dialog_with_blur(dialog)
                navigate("installations", force=True)
                notify(f"Deleted Minecraft version {version_id}.", ft.Icons.DELETE_OUTLINE)

            def close_delete_dialog(dialog):
                close_dialog_with_blur(dialog)

            def delete_profile(profile_id, dialog, delete_files=False):
                if features.busy:
                    notify('Wait for the current operation to finish.', 'warning')
                    return
                try:
                    removed = remove_profile_record(profile_id, delete_files=bool(delete_files))
                except (OSError, ValueError) as error:
                    notify(error, 'error', 'Could not remove profile')
                    return
                installations[:] = load_installations()
                handled_external_profile_ids.clear()
                handled_external_profile_ids.update(storage.load_handled_external_profile_ids())
                if launch_selection['key'] == profile_id:
                    launch_selection['key'] = 'latest-release' if latest_release_id else ''
                    save_profile_options(player_name_state['value'], launch_selection['key'], profile_picture_state['path'])
                close_dialog_with_blur(dialog)
                navigate('installations', force=True)
                notify(f"Removed {removed['name']}.", 'success')

            installed_versions = get_installed_versions(force_refresh=True)
            installations[:], handled_external_profile_ids, imp_changed = (
                import_external_installations(
                    installations,
                    handled_external_profile_ids,
                    installed_versions,
                    get_external_installations(),
                    version_catalog,
                )
            )
            installations[:], disc_changed = discover_local_instances(
                minecraft_directory,
                installations,
                installed_versions,
                version_catalog,
            )
            if imp_changed or disc_changed:
                save_installations(
                    installations,
                    handled_external_profile_ids,
                    latest_release_id,
                )

            launch_targets = {}
            if latest_release_id:
                launch_targets[LATEST_RELEASE_PROFILE_ID] = get_latest_release_profile()
            for installation in installations:
                version_id = get_profile_version_id(installation)
                if not version_id:
                    continue
                launch_targets[installation["id"]] = {
                    **installation,
                    "key": installation["id"],
                    "version_id": version_id,
                }

            if launch_selection["key"] not in launch_targets:
                installed_ids = {
                    version["version_id"] for version in installed_versions
                }
                launch_selection["key"] = next(
                    (
                        key
                        for key, target in launch_targets.items()
                        if target["version_id"] in installed_ids
                    ),
                    next(iter(launch_targets), ""),
                )
                save_profile_options(
                    player_name_state["value"],
                    launch_selection["key"],
                    profile_picture_state["path"],
                )

            selection_rows = []
            play_button_ref = {}
            active_acc = get_active_account()
            initial_uname = active_acc.get("username", player_name_state["value"]).strip() or "Player"
            player_name_state["value"] = initial_uname

            account_username_text = ft.Text(
                initial_uname,
                size=13,
                weight=ft.FontWeight.W_600,
                color=theme["text_primary"],
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )

            def get_active_player_head_avatar_bytes(scale=4) -> bytes:
                curr_acc = get_active_account()
                # Skin system is disabled for offline mode
                if curr_acc.get("type") == "offline":
                    return skins.render_head_avatar_bytes(skins.get_default_skin("classic"), scale=scale)

                uname = curr_acc.get("username", player_name_state.get("value", "")).strip()
                skin_img = None
                active_choice = skins.load_active_skin_choice()

                # Check custom skin choice
                if active_choice.get("skin_type") == "custom" and active_choice.get("custom_path"):
                    custom_file = Path(active_choice["custom_path"])
                    if custom_file.is_file():
                        try:
                            skin_img = Image.open(custom_file)
                        except Exception:
                            pass

                # Check Ely.by cached skin for current username
                if skin_img is None and uname:
                    cached_file = skins.get_skins_dir() / f"ely_{uname.lower()}.png"
                    if cached_file.is_file():
                        try:
                            skin_img = Image.open(cached_file)
                        except Exception:
                            pass

                # Fallback to Steve (classic default skin)
                if skin_img is None:
                    skin_img = skins.get_default_skin(active_choice.get("model", "classic"))

                try:
                    return skins.render_head_avatar_bytes(skin_img, scale=scale)
                except Exception:
                    return skins.render_head_avatar_bytes(skins.get_default_skin("classic"), scale=scale)

            def build_account_picture(size):
                scale = max(2, int(size // 8))
                avatar_bytes = get_active_player_head_avatar_bytes(scale=scale)
                return ft.Image(
                    src=avatar_bytes,
                    width=size,
                    height=size,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                    gapless_playback=True,
                )

            account_avatar = ft.Container(
                width=36,
                height=36,
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.14, theme["btn_primary"]),
                alignment=ft.Alignment.CENTER,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=build_account_picture(36),
            )
            account_picture_preview = ft.Container(
                width=48,
                height=48,
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.14, theme["btn_primary"]),
                alignment=ft.Alignment.CENTER,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=build_account_picture(48),
            )
            account_picture_status = ft.Text(
                "Synchronized with your Minecraft skin",
                size=12,
                color=theme["text_secondary"],
            )

            def refresh_account_picture():
                account_avatar.content = build_account_picture(36)
                account_picture_preview.content = build_account_picture(48)
                for avatar_control in (account_avatar, account_picture_preview):
                    try:
                        avatar_control.update()
                    except Exception:
                        pass

            launcher_log_state["refresh_account_picture"] = refresh_account_picture
            launcher_log_state["get_head_avatar"] = get_active_player_head_avatar_bytes

            def update_sidebar_username():
                curr_acc = get_active_account()
                uname = curr_acc.get("username", player_name_state["value"]).strip() or "Player"
                player_name_state["value"] = uname
                features.player_changed(get_active_player_head_avatar_bytes())
                account_username_text.value = uname
                try:
                    account_username_text.update()
                except Exception:
                    pass

            def on_account_card_hover(e, container):
                is_hovered = e.data == "true"
                container.bgcolor = (
                    theme.get("card_hover", theme["card"])
                    if is_hovered
                    else theme["card"]
                )
                container.update()

            account_card = ft.Container(
                bgcolor=theme["card"],
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                ink=True,
                tooltip=tooltip("Go to account settings"),
                on_click=lambda e: navigate("options_accounts"),
                content=ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        account_avatar,
                        account_username_text,
                        ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=theme["text_muted"]),
                    ],
                ),
            )
            account_card.on_hover = lambda e, c=account_card: on_account_card_hover(e, c)
            account_card_wrap = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.CLICK,
                content=account_card,
            )

            welcome_row = ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[ft.Container(
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Text(
                                "WELCOME BACK,",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=theme["text_muted"],
                            ),
                            ft.Text(
                                "CLICK PLAY TO LAUNCH THE GAME",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=theme["text_muted"],
                            ),
                            # ft.Text(
                            #     "Ready to play?",
                            #     size=24,
                            #     weight=ft.FontWeight.BOLD,
                            #     color=theme["text_primary"],
                            #     font_family="mojangles"
                            # ),
                        ],
                    ),padding=ft.Padding.only(left=10)),
                    account_card_wrap,
                ],
            )

            launch_status = ft.Text(
                launcher_log_state["status"]
                or (
                    f"Selected {launch_targets[launch_selection['key']]['name']}"
                    if launch_selection["key"] in launch_targets
                    else "Choose a profile to play."
                ),
                size=12,
                color=theme["text_secondary"],
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            )
            launch_eta = ft.Text(
                launcher_log_state.get("eta", ""),
                size=12,
                color=theme["text_muted"],
                text_align=ft.TextAlign.RIGHT,
            )
            selected_target = launch_targets.get(launch_selection["key"])
            selected_version_name = ft.Text(
                selected_target["name"] if selected_target else "Choose a profile",
                size=26,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.WHITE,
                overflow=ft.TextOverflow.ELLIPSIS,
                font_family="mojangles",
                style=ft.TextStyle(
                    shadow=ft.BoxShadow(
                        blur_radius=8,
                        color=ft.Colors.with_opacity(0.90, ft.Colors.BLACK),
                        offset=ft.Offset(0, 2),
                    ),
                ),
            )
            def get_loader_badge_text(target):
                if not target:
                    return "VANILLA"
                loader = target.get("loader", "Vanilla")
                return loader.upper() if loader != "Vanilla" else "VANILLA"

            selected_version_instance_badge = ft.Container(
                content=ft.Text(
                    "INSTANCE",
                    size=10,
                    weight=ft.FontWeight.BOLD,
                    color=theme["btn_primary"],
                ),
                bgcolor=ft.Colors.with_opacity(
                    0.25, theme["btn_primary"]
                ),
                padding=ft.Padding.symmetric(
                    horizontal=8, vertical=4
                ),
                border_radius=6,
                visible=bool(selected_target and selected_target.get("is_instance")),
            )
            selected_version_loader_badge = ft.Container(
                content=ft.Text(
                    get_loader_badge_text(selected_target),
                    size=10,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.WHITE,
                ),
                bgcolor=ft.Colors.with_opacity(
                    0.55, theme["surface"]
                ),
                padding=ft.Padding.symmetric(
                    horizontal=8, vertical=4
                ),
                border_radius=6,
                visible=bool(selected_target and selected_target.get("loader") != "Vanilla"),
            )
            selected_version_title_row = ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    selected_version_name,
                    selected_version_instance_badge,
                    selected_version_loader_badge,
                ],
            )
            selected_version_summary = ft.Text(
                profile_summary(selected_target) if selected_target else "Your installed versions will appear here.",
                size=14,
                weight=ft.FontWeight.W_500,
                color=ft.Colors.with_opacity(0.95, ft.Colors.WHITE),
                style=ft.TextStyle(
                    shadow=ft.BoxShadow(
                        blur_radius=6,
                        color=ft.Colors.with_opacity(0.90, ft.Colors.BLACK),
                        offset=ft.Offset(0, 1.5),
                    ),
                ),
            )

            def get_selected_version_details(target):
                if target is None:
                    return "No profile selected."
                return f"Version ID: {target['version_id']}"

            selected_version_details = ft.Text(
                get_selected_version_details(selected_target),
                size=12,
                weight=ft.FontWeight.W_400,
                color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE),
                selectable=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                style=ft.TextStyle(
                    shadow=ft.BoxShadow(
                        blur_radius=6,
                        color=ft.Colors.with_opacity(0.90, ft.Colors.BLACK),
                        offset=ft.Offset(0, 1.5),
                    ),
                ),
            )

            def is_target_installed(target):
                if not target:
                    return False
                return bool(target.get("version_id") in local_version_ids)

            initial_installed = is_target_installed(selected_target)
            hero_status_icon = ft.Icon(
                ft.Icons.CIRCLE,
                size=10,
                color=theme["btn_primary"] if initial_installed else theme["text_secondary"],
            )
            hero_status_text = ft.Text(
                "Ready to launch" if initial_installed else "Not installed — Click Play to install",
                size=12,
                weight=ft.FontWeight.W_500,
                color=ft.Colors.with_opacity(0.92, ft.Colors.WHITE),
                style=ft.TextStyle(
                    shadow=ft.BoxShadow(
                        blur_radius=6,
                        color=ft.Colors.with_opacity(0.90, ft.Colors.BLACK),
                        offset=ft.Offset(0, 1),
                    ),
                ),
            )
            hero_status_row = ft.Row(
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    hero_status_icon,
                    hero_status_text,
                ],
            )

            def update_hero_status(target):
                installed = is_target_installed(target)
                hero_status_icon.name = ft.Icons.CIRCLE
                hero_status_icon.color = (
                    theme["btn_primary"] if installed else theme["text_secondary"]
                )
                hero_status_text.value = (
                    "Ready to launch"
                    if installed
                    else "Not installed — Click Play to install"
                )
            white_beam = ft.Container(
                left=-100,
                top=0,
                bottom=0,
                width=90,
                height=10,
                opacity=0.0,
                visible=True,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, 0),
                    end=ft.Alignment(1, 0),
                    colors=[
                        ft.Colors.with_opacity(0.0, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.22, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.40, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.22, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                        ft.Colors.with_opacity(0.0, ft.Colors.WHITE),
                    ],
                    stops=[0.0, 0.20, 0.38, 0.50, 0.62, 0.80, 1.0],
                ),
                animate_position=ft.Animation(1000, ft.AnimationCurve.LINEAR),
            )
            shimmer_beam = white_beam
            beam_1 = white_beam
            beam_2 = white_beam

            launch_progress_fill = ft.Container(
                expand=1,
                height=10,
                border_radius=10,
                bgcolor=theme["btn_primary"],
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                visible=False,
                content=ft.Stack(
                    expand=True,
                    controls=[white_beam],
                ),
            )
            launch_progress_empty = ft.Container(
                expand=1000,
                height=10,
                bgcolor=ft.Colors.TRANSPARENT,
            )
            launch_progress_track = ft.Container(
                height=10,
                border_radius=10,
                bgcolor=theme["surface"],
                border=ft.Border.all(1, ft.Colors.with_opacity(0.18, theme["border"])),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Row(
                    spacing=0,
                    controls=[
                        launch_progress_fill,
                        launch_progress_empty,
                    ],
                ),
            )
            launch_progress = launch_progress_track
            launch_progress_container = launch_progress_track

            def set_track_progress(val, force=False):
                if val is None:
                    changed = launcher_log_state.get("progress") is not None
                    launcher_log_state["progress"] = None
                    launch_progress_fill.visible = False
                    launch_progress_empty.visible = True
                    launch_progress_empty.expand = 1000
                    launch_progress_track.value = None
                    return changed
                else:
                    try:
                        v = max(0.0, min(1.0, float(val)))
                    except (ValueError, TypeError):
                        v = 0.0
                    old_v = launcher_log_state.get("progress")
                    if not force and old_v is not None and abs(v - old_v) < 0.003 and (0.005 < v < 0.995):
                        return False
                    launcher_log_state["progress"] = v
                    if v <= 0.001:
                        if launcher_log_state.get("running"):
                            launch_progress_fill.visible = True
                            launch_progress_empty.visible = True
                            launch_progress_fill.expand = 40
                            launch_progress_empty.expand = 960
                        else:
                            launch_progress_fill.visible = False
                            launch_progress_empty.visible = True
                            launch_progress_empty.expand = 1000
                    elif v >= 0.999:
                        launch_progress_fill.visible = True
                        launch_progress_fill.expand = 1000
                        launch_progress_empty.visible = False
                    else:
                        fill_flex = max(40, min(999, int(v * 1000)))
                        empty_flex = max(1, 1000 - fill_flex)
                        launch_progress_fill.visible = True
                        launch_progress_empty.visible = True
                        launch_progress_fill.expand = fill_flex
                        launch_progress_empty.expand = empty_flex
                    launch_progress_track.value = v
                    return True

            set_track_progress(launcher_log_state.get("progress"), force=True)
            launcher_log_state["set_track_progress"] = set_track_progress
            launcher_log_state["white_beam"] = white_beam

            launcher_log_list = ft.ListView(
                controls=[
                    ft.Text(
                        line,
                        size=11,
                        color=theme["text_primary"],
                        font_family="Consolas",
                        selectable=True,
                    )
                    for line in launcher_log_state["lines"][-300:]
                ]
                or [
                    ft.Text(
                        "No launcher output yet. Launch a game to view its logs.",
                        size=12,
                        color=theme["text_secondary"],
                    )
                ],
                expand=True,
                spacing=3,
                auto_scroll=True,
            )
            launcher_log_state["list"] = launcher_log_list
            launcher_log_orb1, launcher_log_orb2 = create_ambient_gradient_orbs()

            def on_copy_logs(e):
                text = "\n".join(launcher_log_state["lines"])
                if text:
                    copy_to_clipboard(text, "Copied launcher logs to clipboard!")
                else:
                    notify("No logs to copy.", ft.Icons.INFO_OUTLINE)

            log_copy_button = ft.IconButton(
                hover_color=ft.Colors.TRANSPARENT,
                icon=ft.Icons.COPY,
                icon_size=16,
                tooltip=tooltip("Copy Logs"),
                icon_color=theme["text_secondary"],
                style=ft.ButtonStyle(mouse_cursor=clickable_mouse_cursor),
                on_click=on_copy_logs,
            )
            log_back_button = ft.IconButton(
                hover_color=ft.Colors.TRANSPARENT,
                icon=ft.Icons.CLOSE,
                icon_size=16,
                tooltip=tooltip("Close Logs"),
                icon_color=theme["text_secondary"],
                style=ft.ButtonStyle(mouse_cursor=clickable_mouse_cursor),
                on_click=lambda e: set_launcher_log_visible(False),
            )
            open_logs_button = ft.TextButton(
                "Open logs",
                icon=ft.Icons.TERMINAL,
                visible=not launcher_log_state["open"],
                style=ft.ButtonStyle(
                    color=theme["text_secondary"],
                    overlay_color=ft.Colors.TRANSPARENT,
                    mouse_cursor=clickable_mouse_cursor,
                ),
                on_click=lambda e: set_launcher_log_visible(True),
            )
            bottom_log_toggle_button = ft.Button(
                "Logs",
                icon=ft.Icons.TERMINAL,
                style=ft.ButtonStyle(
                    bgcolor=theme["surface"],
                    color=theme["text_secondary"],
                    shape=ft.RoundedRectangleBorder(radius=8),
                    mouse_cursor=clickable_mouse_cursor,
                ),
                on_click=lambda e: set_launcher_log_visible(not launcher_log_state["open"]),
            )
            launcher_log_state["bottom_log_toggle_button"] = bottom_log_toggle_button

            floating_logs_window = ft.Container(
                left=28,
                right=28,
                top=20,
                bottom=64,
                bgcolor=ft.Colors.with_opacity(0.96, theme["card"]),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.35, theme["border"])),
                border_radius=16,
                shadow=ft.BoxShadow(
                    blur_radius=28,
                    spread_radius=3,
                    color=ft.Colors.with_opacity(0.65, ft.Colors.BLACK),
                    offset=ft.Offset(0, 8),
                ),
                padding=16,
                visible=launcher_log_state["open"],
                content=ft.Column(
                    expand=True,
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Row(
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Icon(
                                            ft.Icons.TERMINAL,
                                            size=18,
                                            color=theme["btn_primary"],
                                        ),
                                        ft.Text(
                                            "MINECRAFT LOGS",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color=theme["text_primary"],
                                        ),
                                    ],
                                ),
                                ft.Row(
                                    spacing=4,
                                    controls=[
                                        log_copy_button,
                                        log_back_button,
                                    ],
                                ),
                            ],
                        ),
                        ft.Container(
                            expand=True,
                            bgcolor=ft.Colors.with_opacity(0.45, theme["surface"]),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.14, theme["border"])),
                            border_radius=10,
                            padding=10,
                            content=launcher_log_list,
                        ),
                    ],
                ),
            )
            launcher_log_panel = floating_logs_window
            launcher_log_state["floating_logs_window"] = floating_logs_window
            selected_installation_view_ref = {"control": None}
            selected_version_elements_ref = {"control": None}

            def set_launcher_log_visible(visible):
                launcher_log_state["open"] = visible
                log_back_button.visible = visible
                open_logs_button.visible = not visible
                win = launcher_log_state.get("floating_logs_window", floating_logs_window)
                if win is not None:
                    win.visible = visible
                if visible:
                    active_log_list = launcher_log_state.get("list")
                    if active_log_list is not None and launcher_log_state["lines"]:
                        active_log_list.controls = [
                            ft.Text(
                                line,
                                size=11,
                                color=theme["text_primary"],
                                font_family="Consolas",
                                selectable=True,
                            )
                            for line in launcher_log_state["lines"][-300:]
                        ]
                if active_page.get("name") != "home" and visible:
                    nav_fn = navigation_state.get("navigate", navigate)
                    nav_fn("home")
                    return
                try:
                    if win is not None:
                        win.update()
                except Exception:
                    pass
                except Exception:
                    pass

            def return_to_selected_installation():
                set_launcher_log_visible(False)

            def append_launcher_logs(lines):
                active_log_list = launcher_log_state["list"]
                can_update_ui = (
                    active_log_list is not None
                    and active_page.get("name") == "home"
                    and launcher_log_state["open"]
                )
                for line in lines:
                    message = redact_credentials(line.rstrip("\r\n"))
                    if not message:
                        continue
                    if not launcher_log_state["lines"] and active_log_list is not None:
                        active_log_list.controls.clear()
                    launcher_log_state["lines"].append(message)
                    if can_update_ui:
                        active_log_list.controls.append(
                            ft.Text(
                                message,
                                size=11,
                                color=theme["text_primary"],
                                font_family="Consolas",
                                selectable=True,
                            )
                        )
                if len(launcher_log_state["lines"]) > 300:
                    del launcher_log_state["lines"][:-300]
                if active_log_list is not None and len(active_log_list.controls) > 300:
                    del active_log_list.controls[:-300]
                if can_update_ui:
                    try:
                        active_log_list.update()
                    except Exception:
                        pass

            launcher_log_state["append_logs"] = append_launcher_logs

            async def animate_launcher_log_background():
                if launcher_log_state["animation_running"]:
                    return
                launcher_log_state["animation_running"] = True
                try:
                    await animate_ambient_gradient_orbs(
                        launcher_log_orb1,
                        launcher_log_orb2,
                        lambda: active_page.get("name") == "home",
                    )
                finally:
                    launcher_log_state["animation_running"] = False

            globals()["animate_launcher_log_background"] = animate_launcher_log_background


            def launch_is_ready():
                uname = player_name_state["value"].strip() or "Player"
                return bool(
                    launch_selection["key"] in launch_targets
                    and re.fullmatch(
                        r"[A-Za-z0-9_]{1,16}",
                        uname,
                    )
                )

            hero_banner_image_ref = {"control": None}
            hero_banner_view = {"key": None, "src": ""}
            HERO_BANNER_FADE_MS = 220
            HERO_BANNER_OPACITY = 1.0

            library_banner_images = {}

            def apply_card_banner(card_key, banner_path):
                if not banner_path or card_key not in library_banner_images:
                    return
                img_ctrl, grad_ctrl, box_ctrl = library_banner_images[card_key]
                img_ctrl.src = banner_path
                img_ctrl.visible = True
                grad_ctrl.visible = True
                box_ctrl.bgcolor = theme["card"]
                try:
                    img_ctrl.update()
                    grad_ctrl.update()
                    box_ctrl.update()
                except Exception:
                    pass

            async def auto_download_library_banners():
                for k, tgt in list(launch_targets.items()):
                    if banners.get_local_banner_for_target(tgt, minecraft_directory):
                        continue
                    try:
                        resolved_path = await banners.ensure_banner_for_target(
                            tgt, minecraft_directory
                        )
                        if resolved_path:
                            apply_card_banner(k, resolved_path)
                            if launch_selection.get("key") == k:
                                img_ctrl = hero_banner_image_ref.get("control")
                                if img_ctrl is not None and not hero_banner_view.get("src"):
                                    img_ctrl.src = resolved_path
                                    img_ctrl.opacity = HERO_BANNER_OPACITY
                                    hero_banner_view["src"] = resolved_path
                                    try:
                                        img_ctrl.update()
                                    except Exception:
                                        pass
                    except Exception:
                        pass

            async def update_hero_banner(target):
                img_ctrl = hero_banner_image_ref.get("control")
                if img_ctrl is None:
                    return

                target_key = target.get("key")

                def set_opacity(value):
                    img_ctrl.opacity = value
                    try:
                        img_ctrl.update()
                    except Exception:
                        pass

                def show_banner(path):
                    img_ctrl.src = path
                    img_ctrl.opacity = HERO_BANNER_OPACITY
                    try:
                        img_ctrl.update()
                    except Exception:
                        pass

                async def fade_out_current():
                    if (img_ctrl.opacity or 0) <= 0:
                        return
                    set_opacity(0.0)
                    await asyncio.sleep(HERO_BANNER_FADE_MS / 1000)

                # Switching versions: fade the previous version's banner out
                # immediately so it is never visible while the new banner loads.
                if hero_banner_view["key"] != target_key:
                    await fade_out_current()
                    if launch_selection["key"] != target_key:
                        return
                    hero_banner_view["key"] = target_key
                    hero_banner_view["src"] = ""

                # Fast path: fade in a locally cached banner for this version.
                local_path = banners.get_local_banner_for_target(
                    target, minecraft_directory
                )
                if local_path and local_path != hero_banner_view["src"]:
                    show_banner(local_path)
                    hero_banner_view["src"] = local_path

                # Then let the multi-source chain upgrade it to a
                # version-specific banner, cross-fading into the better image.
                resolved = await banners.ensure_banner_for_target(
                    target, minecraft_directory
                )
                if resolved:
                    apply_card_banner(target_key, resolved)
                if not resolved or launch_selection["key"] != target_key:
                    return
                if resolved == hero_banner_view["src"] and (img_ctrl.opacity or 0) > 0:
                    return
                await fade_out_current()
                if launch_selection["key"] != target_key:
                    return
                show_banner(resolved)
                hero_banner_view["src"] = resolved

            card_transition_token = 0

            async def animate_card_selection(target):
                nonlocal card_transition_token
                card_transition_token += 1
                token = card_transition_token
                page.run_task(update_hero_banner, target)

                elem_box = selected_version_elements_ref.get("control")
                if elem_box is None or launcher_log_state["open"]:
                    selected_version_name.value = target["name"]
                    selected_version_instance_badge.visible = bool(target.get("is_instance"))
                    selected_version_loader_badge.visible = bool(target.get("loader") != "Vanilla")
                    selected_version_loader_badge.content.value = get_loader_badge_text(target)
                    selected_version_summary.value = profile_summary(target)
                    selected_version_details.value = get_selected_version_details(target)
                    update_hero_status(target)
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                try:
                    elem_box.animate_opacity = ft.Animation(75, ft.AnimationCurve.EASE_OUT)
                    elem_box.opacity = 0.0
                    elem_box.update()
                except Exception:
                    return

                await asyncio.sleep(0.075)
                if card_transition_token != token:
                    return

                selected_version_name.value = target["name"]
                selected_version_instance_badge.visible = bool(target.get("is_instance"))
                selected_version_loader_badge.visible = bool(target.get("loader") != "Vanilla")
                selected_version_loader_badge.content.value = get_loader_badge_text(target)
                selected_version_summary.value = profile_summary(target)
                selected_version_details.value = get_selected_version_details(target)
                update_hero_status(target)

                try:
                    elem_box.animate_opacity = ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT)
                    elem_box.opacity = 1.0
                    elem_box.update()
                except Exception:
                    pass

            library_cards = {}
            library_status_markers = {}

            def select_launch_target(key):
                if launcher_log_state["running"]:
                    return
                old_key = launch_selection.get("key")
                if old_key == key:
                    return
                launch_selection["key"] = key
                save_profile_options(
                    player_name_state["value"],
                    launch_selection["key"],
                    profile_picture_state["path"],
                )
                selected_target = launch_targets[key]
                for k in (old_key, key):
                    if not k or k not in library_cards:
                        continue
                    card = library_cards[k]
                    is_sel = (k == key)
                    card.border = (
                        ft.Border.all(2, color=theme['btn_primary'])
                        if is_sel
                        else ft.Border.all(2, color=ft.Colors.with_opacity(0.18, theme['border']))
                    )
                    if k in library_status_markers:
                        st_text, st_icon = library_status_markers[k]
                        is_inst = launch_targets[k]['version_id'] in local_version_ids
                        st_text.value = 'Installed' if is_inst else 'Not installed'
                        st_text.color = theme['btn_primary'] if is_sel else theme['text_muted']
                        st_icon.name = ft.Icons.CHECK if is_inst else ft.Icons.DOWNLOAD_OUTLINED
                        st_icon.color = theme['btn_primary'] if is_sel else theme['text_muted']
                        try:
                            st_text.update()
                            st_icon.update()
                        except Exception:
                            pass
                    try:
                        card.update()
                    except Exception:
                        pass

                refresh_launch_button()
                launch_status.value = f"Selected {selected_target['name']}"
                launcher_log_state["status"] = launch_status.value
                try:
                    launch_status.update()
                except Exception:
                    pass
                page.run_task(animate_card_selection, selected_target)

            def build_library_card(key, target):
                is_selected = launch_selection['key'] == key
                is_installed = target['version_id'] in local_version_ids
                is_inst = bool(target.get('is_instance'))
                loader = target.get('loader', 'Vanilla')

                status_text = ft.Text(
                    'Installed' if is_installed else 'Not installed',
                    size=11,
                    weight=ft.FontWeight.NORMAL,
                    color=theme['btn_primary'] if is_selected else theme['text_muted'],
                )
                status_icon = ft.Icon(
                    ft.Icons.CHECK if is_installed else ft.Icons.DOWNLOAD_OUTLINED,
                    size=13,
                    color=theme['btn_primary'] if is_selected else theme['text_muted'],
                )
                library_status_markers[key] = (status_text, status_icon)

                if loader == 'Fabric':
                    loader_bg = ft.Colors.with_opacity(0.18, ft.Colors.BLUE_400)
                    loader_color = ft.Colors.BLUE_300
                elif loader == 'Forge':
                    loader_bg = ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_400)
                    loader_color = ft.Colors.ORANGE_300
                elif loader == 'OptiFine':
                    loader_bg = ft.Colors.with_opacity(0.18, ft.Colors.PURPLE_400)
                    loader_color = ft.Colors.PURPLE_300
                elif loader == 'NeoForge':
                    loader_bg = ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_300)
                    loader_color = ft.Colors.ORANGE_200
                elif loader == 'Quilt':
                    loader_bg = ft.Colors.with_opacity(0.18, ft.Colors.PURPLE_300)
                    loader_color = ft.Colors.PURPLE_200
                else:
                    loader_bg = ft.Colors.with_opacity(0.15, theme['surface'])
                    loader_color = theme['text_secondary']

                mc_ver = str(target.get('minecraft_version') or target.get('version_id') or '').strip()
                if mc_ver.lower() == 'latest-release':
                    mc_ver = 'Release'

                local_banner_path = (
                    banners.get_local_banner_for_target(target, minecraft_directory) or str(ASSETS_DIR / "banners" / ("farmhouse.png" if target.get("loader", "Vanilla") == "Vanilla" else "portal.png"))
                )
                has_banner = bool(local_banner_path)

                card_banner_img = ft.Image(
                    src=local_banner_path,
                    fit=ft.BoxFit.COVER,
                    width=245,
                    height=94,
                    gapless_playback=True,
                    visible=has_banner,
                )
                card_banner_gradient = ft.Container(
                    left=0,
                    right=0,
                    bottom=0,
                    height=24,
                    visible=has_banner,
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.TOP_CENTER,
                        end=ft.Alignment.BOTTOM_CENTER,
                        colors=[
                            ft.Colors.TRANSPARENT,
                            ft.Colors.with_opacity(0.40, theme['card']),
                        ],
                    ),
                )

                top_banner_section = ft.Container(
                    left=0,
                    right=0,
                    top=0,
                    bottom=64,
                    bgcolor=theme['card'] if has_banner else ft.Colors.with_opacity(0.12, theme['surface']),
                    border_radius=ft.BorderRadius(top_left=16, top_right=16, bottom_left=0, bottom_right=0),
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    content=ft.Stack(
                        expand=True,
                        controls=[
                            card_banner_img,
                            card_banner_gradient,
                        ],
                    ),
                )
                library_banner_images[key] = (card_banner_img, card_banner_gradient, top_banner_section)

                tags_row = build_profile_badges(target)

                bottom_info_section = ft.Container(
                    left=0,
                    right=0,
                    bottom=0,
                    height=64,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    bgcolor=ft.Colors.TRANSPARENT,
                    content=ft.Column(
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        spacing=4,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text(
                                        target['name'],
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color=theme['text_primary'],
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        expand=True,
                                    ),
                                    ft.Row(
                                        spacing=4,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[status_icon, status_text],
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=tags_row,
                            ),
                        ],
                    ),
                )

                is_running = bool(launcher_log_state.get("running"))
                card = ft.Container(
                    width=235,
                    height=152,
                    border_radius=16,
                    padding=0,
                    ink=not is_running,
                    disabled=is_running,
                    opacity=0.5 if is_running else 1.0,
                    bgcolor=theme['card'],
                    border=(
                        ft.Border.all(2, color=theme['btn_primary'])
                        if is_selected
                        else ft.Border.all(2, color=ft.Colors.with_opacity(0.18, theme['border']))
                    ),
                    animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
                    content=ft.Stack(
                        expand=True,
                        controls=[
                            top_banner_section,
                            bottom_info_section,
                        ],
                    ),
                )

                def on_card_hover(e, c=card, k=key):
                    if launcher_log_state.get("running") or launch_selection['key'] == k:
                        return
                    is_h = e.data == 'true'
                    c.border = (
                        ft.Border.all(2, color=theme['btn_primary'])
                        if is_h
                        else ft.Border.all(2, color=ft.Colors.with_opacity(0.18, theme['border']))
                    )
                    try:
                        c.update()
                    except Exception:
                        pass

                card.on_hover = on_card_hover
                library_cards[key] = card

                return ft.GestureDetector(
                    mouse_cursor=ft.MouseCursor.BASIC if is_running else clickable_mouse_cursor,
                    on_tap=lambda e, k=key: (None if launcher_log_state.get("running") else select_launch_target(k)),
                    content=card,
                )

            is_running = bool(launcher_log_state.get("running"))
            new_profile_container = ft.Container(
                width=235,
                height=152,
                border_radius=16,
                padding=16,
                ink=not is_running,
                disabled=is_running,
                opacity=0.5 if is_running else 1.0,
                on_click=lambda e: (None if launcher_log_state.get("running") else navigate("new_installation")),
                bgcolor=ft.Colors.with_opacity(0.04, theme["surface"]),
                border=ft.Border.all(1, color=ft.Colors.with_opacity(0.18, theme["border"])),
                alignment=ft.Alignment.CENTER,
                animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        ft.Container(
                            width=42,
                            height=42,
                            border_radius=21,
                            bgcolor=ft.Colors.with_opacity(0.12, theme["btn_primary"]),
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(ft.Icons.ADD, size=22, color=theme["btn_primary"]),
                        ),
                        ft.Text(
                            "New Profile",
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=theme["text_secondary"],
                        ),
                    ],
                ),
            )

            def on_new_profile_hover(e, c=new_profile_container):
                if launcher_log_state.get("running"):
                    return
                is_h = e.data == "true"
                c.bgcolor = ft.Colors.with_opacity(0.08, theme["btn_primary"]) if is_h else ft.Colors.with_opacity(0.04, theme["surface"])
                c.border = ft.Border.all(1, color=theme["btn_primary"]) if is_h else ft.Border.all(1, color=ft.Colors.with_opacity(0.18, theme["border"]))
                try:
                    c.update()
                except Exception:
                    pass

            new_profile_container.on_hover = on_new_profile_hover

            new_profile_card = ft.GestureDetector(
                mouse_cursor=ft.MouseCursor.BASIC if is_running else clickable_mouse_cursor,
                on_tap=lambda e: (None if launcher_log_state.get("running") else navigate("new_installation")),
                content=new_profile_container,
            )

            LIBRARY_CARD_W = 235
            LIBRARY_CARD_GAP = 18

            # Add invisible trailing space-holders with identical width (235px) and 0 height.
            # In a centered wrap, full rows center naturally.
            # On the final partial row, these invisible spacers absorb the remaining column
            # slots, pinning the visible cards to the left (matching the columns above)
            # completely instantly and natively in Flutter's layout engine with 0ms lag!
            library_spacers = [
                ft.Container(width=LIBRARY_CARD_W, height=0)
                for _ in range(8)
            ]

            library_cards_flow = ft.Row(
                wrap=True,
                spacing=LIBRARY_CARD_GAP,
                run_spacing=LIBRARY_CARD_GAP,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    *[build_library_card(k, launch_targets[k]) for k in launch_targets],
                    new_profile_card,
                    *library_spacers,
                ],
            )

            library_scroll_container = ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[library_cards_flow],
            )

            library_shelf_container = ft.Column(
                expand=True,
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Icon(ft.Icons.GRID_VIEW_ROUNDED, size=16, color=theme["btn_primary"]),
                                    ft.Text(
                                        "Your Library",
                                        size=15,
                                        weight=ft.FontWeight.BOLD,
                                        color=theme["text_primary"],
                                    ),
                                    ft.Text(
                                        f"({len(launch_targets)} profiles)",
                                        size=11,
                                        color=theme["text_secondary"],
                                    ),
                                ],
                            ),
                            ft.TextButton(
                                "Manage all",
                                icon=ft.Icons.SETTINGS,
                                icon_color=theme["text_muted"],
                                style=ft.ButtonStyle(
                                    color=theme["text_secondary"],
                                    text_style=ft.TextStyle(size=11),
                                    mouse_cursor=clickable_mouse_cursor,
                                ),
                                on_click=lambda e: navigate("installations"),
                            ),
                        ],
                    ),
                    library_scroll_container,
                ],
            )

            version_rows = []
            selection_rows = []
            selection_highlight = ft.Container(visible=False)

            launch_progress_state = {"maximum": 0}

            def refresh_launch_button():
                button = launcher_log_state.get("play_button")
                if button is None:
                    return
                is_running = launcher_log_state["running"]
                is_downloading = launcher_log_state["downloading"]
                is_game_started = launcher_log_state["game_started"]
                is_cancelling = launcher_log_state["cancelling"]
                button.content = (
                    "CANCELLING..."
                    if is_cancelling
                    else "CANCEL"
                    if is_running and is_downloading
                    else "RUNNING..."
                    if is_running and is_game_started
                    else "STARTING..."
                    if is_running
                    else "PLAY"
                )
                button.icon = (
                    ft.Icons.HOURGLASS_TOP
                    if is_cancelling
                    else ft.Icons.CLOSE
                    if is_running and is_downloading
                    else ft.Icons.SPORTS_ESPORTS_OUTLINED
                    if is_running and is_game_started
                    else ft.Icons.HOURGLASS_TOP
                    if is_running
                    else ft.Icons.PLAY_ARROW
                )
                button.disabled = (
                    is_cancelling
                    or (is_running and not is_downloading)
                    or (not is_running and not launch_is_ready())
                )
                if is_running:
                    button.style.mouse_cursor = {
                        ft.ControlState.DISABLED: ft.MouseCursor.PROGRESS,
                        ft.ControlState.DEFAULT: ft.MouseCursor.PROGRESS,
                    }
                else:
                    button.style.mouse_cursor = clickable_mouse_cursor
                try:
                    button.update()
                except Exception:
                    pass

            def update_launch_progress(status=None, value=None, eta=None):
                status_changed = False
                if status is not None:
                    status_str = redact_credentials(str(status))
                    status_changed = (launcher_log_state.get("status") != status_str)
                    launcher_log_state["status"] = status_str
                    if launcher_log_state["running"]:
                        if status_str.startswith("Download ") or "Download" in status_str:
                            launcher_log_state["downloading"] = True
                        elif status_str in (
                            "Building launch command...",
                            "Starting Minecraft...",
                        ):
                            launcher_log_state["downloading"] = False
                            launcher_log_state["eta"] = ""
                track_changed = False
                if value is not None:
                    set_fn = launcher_log_state.get("set_track_progress", set_track_progress)
                    track_changed = set_fn(value)
                if eta is not None:
                    launcher_log_state["eta"] = eta

                status_control = launcher_log_state.get("status_control")
                eta_control = launcher_log_state.get("eta_control")
                progress_control = launcher_log_state.get("progress_control", launch_progress_track)
                is_on_home = active_page.get("name") == "home"

                need_update = []
                if status is not None and status_control is not None:
                    status_control.value = launcher_log_state["status"]
                    if is_on_home and status_changed:
                        need_update.append(status_control)
                if track_changed and is_on_home and progress_control is not None:
                    need_update.append(progress_control)
                if eta_control is not None and (eta is not None or status_changed):
                    eta_control.value = launcher_log_state.get("eta", "")
                    if is_on_home:
                        need_update.append(eta_control)

                if need_update:
                    try:
                        page.update(*need_update)
                    except Exception:
                        for c in need_update:
                            try:
                                c.update()
                            except Exception:
                                pass

                if status_changed:
                    refresh_launch_button()

            launcher_log_state["classic_progress"] = update_launch_progress

            async def launch_selected_game():
                target = launch_targets.get(launch_selection['key'])
                if target is None:
                    notify('Select a Minecraft profile first.', 'warning')
                    return
                await launch_profile(dict(target))

            async def handle_play_button_action():
                if launcher_log_state["running"]:
                    if launcher_log_state["downloading"]:
                        launcher_log_state["cancelling"] = True
                        cancel_event = launcher_log_state["cancel_event"]
                        if cancel_event is not None:
                            cancel_event.set()
                        append_launcher_logs(
                            ["[Launcher] Cancellation requested; finishing the current file..."]
                        )
                        update_launch_progress(
                            "Cancelling after the current file...", None
                        )
                    return
                await launch_selected_game()

            launcher_log_state["launch_selected_game"] = launch_selected_game

            play_button = ft.Button(
                "CANCEL" if launcher_log_state["running"] and launcher_log_state["downloading"] else "RUNNING..." if launcher_log_state["running"] and launcher_log_state["game_started"] else "STARTING..." if launcher_log_state["running"] else "PLAY",
                icon=(
                    ft.Icons.CLOSE
                    if launcher_log_state["running"] and launcher_log_state["downloading"]
                    else ft.Icons.SPORTS_ESPORTS_OUTLINED
                    if launcher_log_state["running"] and launcher_log_state["game_started"]
                    else ft.Icons.HOURGLASS_TOP
                    if launcher_log_state["running"]
                    else ft.Icons.PLAY_ARROW
                ),
                style=ft.ButtonStyle(
                    bgcolor={
                        ft.ControlState.DEFAULT: theme["btn_primary"],
                        ft.ControlState.DISABLED: theme["surface"],

                    },
                    icon_size=20,
                    color={
                        ft.ControlState.DEFAULT: theme["btn_primary_text"],
                        ft.ControlState.DISABLED: theme["text_muted"],
                    },
                    shape=ft.RoundedRectangleBorder(
                        radius=ft.BorderRadius(
                            top_left=0, bottom_left=0, top_right=10, bottom_right=10
                        )
                    ),
                    mouse_cursor=clickable_mouse_cursor,
                    text_style=ft.TextStyle(
                        weight=ft.FontWeight.BOLD,
                        size=15,
                        letter_spacing=0.5,
                    ),
                ),
                disabled=(
                    launcher_log_state["cancelling"]
                    or (
                        launcher_log_state["running"]
                        and not launcher_log_state["downloading"]
                    )
                    or (not launcher_log_state["running"] and not launch_is_ready())
                ),
                width=200,
                height=52,
                on_click=lambda e: page.run_task(handle_play_button_action),
            )
            play_button_ref["control"] = play_button
            launcher_log_state["play_button"] = play_button
            launcher_log_state["refresh_play_button"] = refresh_launch_button
            refresh_launch_button()

            # Installed configurations vs unconfigured local versions
            configured_version_ids = {
                get_profile_version_id(p) for p in installations
            }
            unconfigured_versions = [
                v
                for v in installed_versions
                if v["version_id"] not in configured_version_ids
            ]

            unconfigured_rows = []
            for idx, version in enumerate(unconfigured_versions):
                is_last = idx == len(unconfigured_versions) - 1
                row_controls = [
                    ft.Icon(
                        ft.Icons.WARNING_AMBER_ROUNDED,
                        color=ft.Colors.ORANGE_400,
                        size=24,
                    ),
                    ft.Column(
                        spacing=2,
                        controls=[
                            ft.Row(
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text(
                                        version["version_id"],
                                        size=14,
                                        weight=ft.FontWeight.W_500,
                                        color=theme["text_primary"],
                                    ),
                                    ft.Container(
                                        content=ft.Text(
                                            "RAW VERSION",
                                            size=9,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.ORANGE_300,
                                        ),
                                        bgcolor=ft.Colors.with_opacity(
                                            0.14, ft.Colors.ORANGE_400
                                        ),
                                        padding=ft.Padding.symmetric(
                                            horizontal=5, vertical=1
                                        ),
                                        border_radius=4,
                                    ),
                                ],
                            ),
                            ft.Text(
                                profile_summary(version),
                                size=12,
                                color=theme["text_secondary"],
                            ),
                        ],
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.INFO_OUTLINE,
                        icon_size=15,
                        tooltip=tooltip(f"About unconfigured version {version['version_id']}"),
                        icon_color=theme["text_muted"],
                        style=rounded_button_style,
                        hover_color=ft.Colors.TRANSPARENT,
                        on_click=lambda e, vid=version[
                            "version_id"
                        ]: show_unconfigured_version_info(vid),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                        tooltip=tooltip(f"Configure {version['version_id']} as a profile"),
                        icon_color=theme["btn_primary"],
                        style=rounded_button_style,
                        disabled=is_active_launch_version(version["version_id"]),
                        on_click=lambda e, selected_version=version: navigate(
                            "configure_installed", selected_version["version_id"]
                        ),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_FOREVER,
                        tooltip=tooltip(f"Permanently delete {version['version_id']} from Minecraft"),
                        icon_color=ft.Colors.RED_400,
                        style=rounded_button_style,
                        disabled=is_active_launch_version(version["version_id"]),
                        on_click=lambda e, version_id=version[
                            "version_id"
                        ]: confirm_delete_installed_version(version_id),
                    ),
                ]
                unconfigured_rows.append(
                    ft.Container(
                        padding=ft.Padding.symmetric(vertical=12, horizontal=16),
                        border=None if is_last else ft.Border.only(
                            bottom=ft.BorderSide(1, color=theme["border"])
                        ),
                        content=ft.Row(
                            controls=row_controls,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            options_views = build_options_views(
                page=page,
                theme=theme,
                settings=settings,
                persist_setting=persist_setting,
                navigate=navigate,
                notify=notify,
                copy_to_clipboard=copy_to_clipboard,
                open_url=open_url,
                theme_dropdown=theme_dropdown,
                available_themes=available_themes,
                maximum_memory_mb=maximum_memory_mb,
                features=features,
                minecraft_directory=minecraft_directory,
                account_picture_preview=account_picture_preview,
                account_picture_status=account_picture_status,
                refresh_account_picture=refresh_account_picture,
                update_sidebar_username=update_sidebar_username,
                play_button_ref=play_button_ref,
                refresh_launch_button=refresh_launch_button,
                rebuild_page_callback=lambda theme_name, cur_page: (page.controls.clear(), build_page(theme_name, cur_page)),
                set_orbs_enabled=set_orbs_enabled,
                show_dialog_with_blur=show_dialog_with_blur,
                close_dialog_with_blur=close_dialog_with_blur,
            )
            options_dashboard = options_views["options"]
            ui_subpage = options_views["options_ui"]
            java_subpage = options_views["options_java"]
            game_subpage = options_views["options_game"]
            accounts_subpage = options_views["options_accounts"]
            launcher_subpage = options_views["options_launcher"]
            about_subpage = options_views["options_about"]

            def open_current_folder(e):
                target = launch_targets.get(launch_selection["key"])
                if target:
                    gdir = target.get("game_directory")
                    if not gdir and target.get("instance_name"):
                        gdir = str(Path(minecraft_directory) / "instances" / target["instance_name"])
                    open_game_folder(gdir or minecraft_directory)
                else:
                    open_game_folder(minecraft_directory)

            def edit_current_profile(e):
                target = launch_targets.get(launch_selection["key"])
                if target and target.get("key") != "latest-release" and "id" in target:
                    navigate("edit_installation", target["id"])
                else:
                    features.edit_latest_profile()

            hero_folder_button = ft.TextButton(
                "Folder",
                icon=ft.Icons.FOLDER_OPEN,
                style=ft.ButtonStyle(
                    color={
                        ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.92, ft.Colors.WHITE),
                        ft.ControlState.HOVERED: ft.Colors.WHITE,
                    },
                    bgcolor={
                        ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                        ft.ControlState.HOVERED: ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
                    },
                    padding=ft.Padding.symmetric(horizontal=14, vertical=0),
                    shape=ft.RoundedRectangleBorder(
                        radius=ft.BorderRadius(
                            top_left=10, bottom_left=10, top_right=0, bottom_right=0
                        )
                    ),
                    mouse_cursor=clickable_mouse_cursor,
                    text_style=ft.TextStyle(
                        weight=ft.FontWeight.W_600,
                        size=13,
                    ),
                ),
                height=52,
                on_click=open_current_folder,
            )

            hero_edit_button = ft.TextButton(
                "Edit",
                icon=ft.Icons.EDIT,
                style=ft.ButtonStyle(
                    color={
                        ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.92, ft.Colors.WHITE),
                        ft.ControlState.HOVERED: ft.Colors.WHITE,
                    },
                    bgcolor={
                        ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                        ft.ControlState.HOVERED: ft.Colors.with_opacity(0.12, ft.Colors.WHITE),
                    },
                    padding=ft.Padding.symmetric(horizontal=14, vertical=0),
                    shape=ft.RoundedRectangleBorder(radius=0),
                    mouse_cursor=clickable_mouse_cursor,
                    text_style=ft.TextStyle(
                        weight=ft.FontWeight.W_600,
                        size=13,
                    ),
                ),
                height=52,
                on_click=edit_current_profile,
            )

            folder_edit_group = ft.Container(
                height=52,
                bgcolor=ft.Colors.with_opacity(0.68, theme["surface"]),
                blur=ft.Blur(8, 8),
                border_radius=ft.BorderRadius(
                    top_left=10, bottom_left=10, top_right=0, bottom_right=0
                ),
                content=ft.Row(
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        hero_folder_button,
                        ft.Container(
                            width=1,
                            height=20,
                            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                        ),
                        hero_edit_button,
                    ],
                ),
            )

            merged_play_group = ft.Container(
                height=52,
                border_radius=10,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                shadow=ft.BoxShadow(
                    blur_radius=12,
                    color=ft.Colors.with_opacity(0.40, ft.Colors.BLACK),
                    offset=ft.Offset(0, 3),
                ),
                content=ft.Row(
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        folder_edit_group,
                        play_button,
                    ],
                ),
            )

            selected_version_elements = ft.Container(
                content=ft.Column(
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        selected_version_title_row,
                        selected_version_summary,
                        selected_version_details,
                        ft.Container(height=4),
                        hero_status_row,
                    ],
                ),
                opacity=1.0,
                animate_opacity=ft.Animation(150, ft.AnimationCurve.EASE_IN_OUT),
            )
            selected_version_elements_ref["control"] = selected_version_elements

            selected_installation_content = ft.Container(
                expand=True,
                padding=ft.Padding.symmetric(horizontal=28, vertical=20),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        selected_version_elements,
                        merged_play_group,
                    ],
                ),
            )
            initial_banner_path = banners.get_local_banner_for_target(selected_target, minecraft_directory) or str(ASSETS_DIR / "banners" / "hero_bg.png")
            hero_banner_image = ft.Image(
                src=initial_banner_path,
                fit=ft.BoxFit.COVER,
                expand=True,
                opacity=HERO_BANNER_OPACITY if initial_banner_path else 0.0,
                animate_opacity=ft.Animation(
                    HERO_BANNER_FADE_MS, ft.AnimationCurve.EASE_OUT
                ),
            )
            hero_banner_image_ref["control"] = hero_banner_image
            hero_banner_view["key"] = (
                selected_target.get("key") if selected_target else None
            )
            hero_banner_view["src"] = initial_banner_path

            hero_banner_img_box = ft.Container(
                left=0,
                top=0,
                right=0,
                bottom=0,
                content=hero_banner_image,
            )

            hero_banner_blur = ft.Container(
                left=0,
                top=0,
                right=0,
                bottom=0,
                content=ft.Row(
                    spacing=0,
                    expand=True,
                    controls=[
                        ft.Container(
                            expand=45,
                            blur=ft.Blur(4, 4, tile_mode=ft.BlurTileMode.CLAMP),
                        ),
                        ft.Container(
                            expand=20,
                            blur=ft.Blur(2.5, 2.5, tile_mode=ft.BlurTileMode.CLAMP),
                        ),
                        ft.Container(
                            expand=15,
                            blur=ft.Blur(1.2, 1.2, tile_mode=ft.BlurTileMode.CLAMP),
                        ),
                        ft.Container(expand=20),
                    ],
                ),
            )

            hero_banner_scrim = ft.Container(
                left=0,
                top=0,
                right=0,
                bottom=0,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.CENTER_LEFT,
                    end=ft.Alignment.CENTER_RIGHT,
                    colors=[
                        ft.Colors.with_opacity(0.70, theme["surface"]),
                        ft.Colors.with_opacity(0.22, theme["surface"]),
                        ft.Colors.with_opacity(0.0, theme["surface"]),
                    ],
                    stops=[0.0, 0.5, 1.0],
                ),
            )

            selected_installation_card = ft.Container(
                height=180,
                border_radius=20,
                bgcolor=theme["card"],
                border=ft.Border.all(1, color=theme["border"]),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Container(
                    border_radius=19,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    content=ft.Stack(
                        expand=True,
                        controls=[
                            hero_banner_img_box,
                            hero_banner_blur,
                            hero_banner_scrim,
                            selected_installation_content,
                        ],
                    ),
                ),
            )
            if selected_target:
                page.run_task(update_hero_banner, selected_target)
            page.run_task(auto_download_library_banners)

            new_installation_button = ft.TextButton(
                "New Profile",
                icon=ft.Icons.ADD,
                icon_color={
                    ft.ControlState.DEFAULT: theme["btn_primary_text"],
                    ft.ControlState.DISABLED: theme["text_muted"],
                },
                disabled=(
                    not online_available
                    or launcher_log_state["running"]
                ),
                tooltip=(
                    "Cannot create new profile while a version is installing or launching."
                    if launcher_log_state["running"]
                    else None
                ),
                style=ft.ButtonStyle(
                    bgcolor={
                        ft.ControlState.DEFAULT: theme["btn_primary"],
                        ft.ControlState.DISABLED: theme["surface"],
                    },
                    color={
                        ft.ControlState.DEFAULT: theme["btn_primary_text"],
                        ft.ControlState.DISABLED: theme["text_muted"],
                    },
                    side={
                        ft.ControlState.DEFAULT: ft.BorderSide(0, ft.Colors.TRANSPARENT),
                        ft.ControlState.DISABLED: ft.BorderSide(1, theme["border"]),
                    },
                    shape=ft.RoundedRectangleBorder(radius=8),
                    mouse_cursor=clickable_mouse_cursor,
                ),
                on_click=lambda e: navigate("new_installation"),
            )
            launcher_log_state["new_installation_button"] = new_installation_button

            danger_zone_controls = []
            if unconfigured_rows:
                danger_zone_content = ft.Column(
                    visible=danger_zone_state["expanded"],
                    spacing=8,
                    controls=[
                        ft.Text(
                            "These raw version folders were detected on your disk in Minecraft's versions directory, but are not configured into Gr8 Launcher profiles. Deleting a version here permanently removes its core jar and json files from your disk.",
                            size=11,
                            color=theme["text_muted"],
                        ),
                        ft.Container(
                            bgcolor=theme["surface"],
                            border=ft.Border.all(
                                1,
                                color=theme["border"],
                            ),
                            border_radius=12,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            content=ft.Column(
                                spacing=0,
                                controls=unconfigured_rows,
                            ),
                        ),
                    ],
                )

                danger_chevron = ft.Icon(
                    ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
                    if danger_zone_state["expanded"]
                    else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
                    color=theme["text_secondary"],
                    size=20,
                )

                danger_count_badge = ft.Container(
                    content=ft.Text(
                        f"{len(unconfigured_rows)} raw {'version' if len(unconfigured_rows) == 1 else 'versions'}",
                        size=10,
                        weight=ft.FontWeight.W_500,
                        color=theme["text_secondary"],
                    ),
                    bgcolor=theme["card"],
                    border=ft.Border.all(
                        1,
                        color=theme["border"],
                    ),
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    border_radius=5,
                )

                def toggle_danger_zone(e):
                    danger_zone_state["expanded"] = not danger_zone_state["expanded"]
                    danger_zone_content.visible = danger_zone_state["expanded"]
                    danger_chevron.icon = (
                        ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
                        if danger_zone_state["expanded"]
                        else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED
                    )
                    page.update()

                danger_zone_header = ft.Container(
                    bgcolor=theme["surface"],
                    border=ft.Border.all(
                        1,
                        color=theme["border"],
                    ),
                    border_radius=10,
                    padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                    ink=True,
                    on_click=toggle_danger_zone,
                    tooltip=tooltip("Click to expand or collapse unconfigured raw versions"),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Icon(
                                        ft.Icons.UNARCHIVE_ROUNDED,
                                        color=theme["text_secondary"],
                                        size=20,
                                    ),
                                    ft.Column(
                                        spacing=2,
                                        tight=True,
                                        controls=[
                                            ft.Row(
                                                spacing=8,
                                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                                controls=[
                                                    ft.Text(
                                                        "UNCONFIGURED RAW VERSIONS",
                                                        size=12,
                                                        color=theme["text_primary"],
                                                        weight=ft.FontWeight.BOLD,
                                                    ),
                                                    danger_count_badge,
                                                ],
                                            ),
                                            ft.Text(
                                                "Hidden by default. Click to expand and manage unconfigured version folders on disk.",
                                                size=11,
                                                color=theme["text_muted"],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            danger_chevron,
                        ],
                    ),
                )

                def on_danger_header_hover(e):
                    is_h = e.data == "true"
                    danger_zone_header.bgcolor = (
                        theme.get("card_hover", theme["card"])
                        if is_h
                        else theme["surface"]
                    )
                    danger_zone_header.border = ft.Border.all(
                        1,
                        color=theme["btn_primary"] if is_h else theme["border"],
                    )
                    danger_zone_header.update()

                danger_zone_header.on_hover = on_danger_header_hover

                danger_zone_controls = [
                    ft.Container(
                        margin=ft.Margin.only(top=16),
                        content=ft.Column(
                            spacing=10,
                            tight=True,
                            controls=[
                                ft.GestureDetector(
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                    content=danger_zone_header,
                                ),
                                danger_zone_content,
                            ],
                        ),
                    )
                ]

            def build_skins_view():
                return build_skins_view_external(page, theme, notify, open_url=open_url, online_available=lambda: online_available, navigate=navigate, features=features)

            home_status_row = ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=5,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    launch_status,
                                    launch_eta,
                                ],
                            ),
                            launch_progress_container,
                        ],
                    ),
                    bottom_log_toggle_button,
                ],
            )

            if name == "installations":
                if features.library is None:
                    features.library = ClassicLibraryPage(
                        on_new=lambda e: navigate("new_installation"),
                        on_play=features.play_profile,
                        on_mods=lambda pid: navigate("mods", pid),
                        on_edit=lambda pid: navigate("edit_installation", pid),
                        on_remove=confirm_delete,
                        on_repair=lambda profile: page.run_task(features.repair_profile, profile),
                        on_folder=features.open_profile_folder,
                        on_move=features.move_profile, on_order=features.reorder_profiles,
                        busy=lambda: features.busy,
                    )
                features.library.refresh(installations, local_version_ids, launch_selection["key"],
                                         footer=danger_zone_controls)

            pages = {
                "skins": ft.Container(),
                "mods": features.mods,
                "home": ft.Container(
                    expand=True,
                    content=ft.Stack(
                        expand=True,
                        controls=[
                            ft.Container(
                                expand=True,
                                padding=ft.Padding(left=28, top=20, right=28, bottom=16),
                                content=ft.Column(
                                    expand=True,
                                    spacing=14,
                                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        welcome_row,
                                        selected_installation_card,
                                        library_shelf_container,
                                        home_status_row,
                                    ],
                                ),
                            ),
                            floating_logs_window,
                        ],
                    ),
                ),
                "installations": features.library,
                "options": options_dashboard,
                "options_ui": ui_subpage,
                "options_java": java_subpage,
                "options_game": game_subpage,
                "options_accounts": accounts_subpage,
                "options_launcher": launcher_subpage,
                "options_about": about_subpage,
                "options_updates": options_views["options_updates"],
            }

            # Startup ripple: register the home sections in visual order so
            # they pop in one by one after the first paint.
            prepare_intro(welcome_row)
            prepare_intro(selected_installation_card)
            prepare_intro(library_shelf_container)
            prepare_intro(home_status_row)

            if name == "new_installation":
                pages[name] = build_installation_editor()
            elif name == "edit_installation":
                profile = next(
                    (item for item in installations if item["id"] == profile_id),
                    None,
                )
                if profile is None:
                    return
                pages[name] = build_installation_editor(profile, name_only=True)
            elif name == "configure_installed":
                version = next(
                    (
                        item
                        for item in installed_versions
                        if item["version_id"] == profile_id
                    ),
                    None,
                )
                if version is None:
                    return
                profile = profiles_by_version.get(profile_id) or {
                    "id": uuid.uuid4().hex,
                    "name": version["version_id"],
                    "loader": version["loader"],
                    "channel": "",
                    "minecraft_version": version["minecraft_version"],
                    "loader_version": version["loader_version"],
                    "version_id": version["version_id"],
                }
                pages[name] = build_installation_editor(profile, name_only=True)
            elif name == "skins":
                pages[name] = build_skins_view()

            if name == "home":
                launcher_log_state["status_control"] = launch_status
                launcher_log_state["progress_control"] = launch_progress
                launcher_log_state["eta_control"] = launch_eta
                launcher_log_state["white_beam"] = white_beam
                launcher_log_state["set_track_progress"] = set_track_progress
                launcher_log_state["floating_logs_window"] = floating_logs_window
                launcher_log_state["bottom_log_toggle_button"] = bottom_log_toggle_button
                if launcher_log_state.get("running"):
                    set_track_progress(launcher_log_state.get("progress"), force=True)
                    if launcher_log_state.get("status"):
                        launch_status.value = launcher_log_state["status"]
                    if launcher_log_state.get("eta"):
                        launch_eta.value = launcher_log_state["eta"]
                    for card in library_cards.values():
                        card.disabled = True
                        card.opacity = 0.5
                    new_profile_container.disabled = True
                    new_profile_container.opacity = 0.5
                    for item in selection_rows:
                        row = item[1]
                        row.disabled = True
                        row.opacity = 0.5
                        if len(item) > 4 and item[4] is not None:
                            item[4].mouse_cursor = ft.MouseCursor.BASIC
                    refresh_launch_button()
                page.run_task(animate_launcher_log_background)
            elif name == "options":
                anim = options_background_state.get("animate")
                if callable(anim):
                    page.run_task(anim)

            show_page(name, pages[name])

        navigation_state["navigate"] = navigate

        tab_names = ["home", "installations", "mods", "skins", "options"]

        def on_tab_select(selected_tab):
            if selected_tab != current_page:
                navigate(selected_tab)

        title_letters = []
        title_controls = []
        for character in "Gr8 Launcher":
            if character == " ":
                title_controls.append(ft.Container(width=6))
                continue

            letter = ft.Container(
                content=ft.Text(
                    character,
                    font_family="Mojangles",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                    color=(
                        theme["btn_primary"]
                        if character == "8"
                        else theme["text_primary"]
                    ),
                ),
                offset=ft.Offset(0, 0),
                animate_offset=ft.Animation(110, ft.AnimationCurve.EASE_OUT),
            )
            title_letters.append(letter)
            title_controls.append(letter)

        is_bouncing = False

        async def bounce_title():
            nonlocal is_bouncing
            if is_bouncing:
                return

            is_bouncing = True
            try:

                async def bounce_letter(letter, delay):
                    await asyncio.sleep(delay)
                    letter.offset = ft.Offset(0, -0.25)
                    page.update()
                    await asyncio.sleep(0.08)

                    letter.offset = ft.Offset(0, 0)
                    page.update()

                await asyncio.gather(
                    *(
                        bounce_letter(letter, index * 0.03)
                        for index, letter in enumerate(title_letters)
                    )
                )
                await asyncio.sleep(0.11)
            finally:
                is_bouncing = False

        def start_title_animation(e):
            page.run_task(bounce_title)

        root_tab = (
            tab
            if tab in tab_names
            else ("options" if tab.startswith("options") else "installations")
        )
        tabs_buttons = NavigationTabs(
            tab_names=tab_names,
            initial_index=tab_names.index(root_tab),
            on_tab_select=on_tab_select,
            app_theme=theme,
            tooltip_func=tooltip,
        )

        title_wrap = prepare_intro(
            ft.Container(
                content=ft.Row(controls=title_controls, spacing=0, tight=True),
                padding=ft.Padding.only(left=15),
                on_click=start_title_animation,
            )
        )
        tabs_pop_wrap = prepare_intro(
            ft.Container(
                content=tabs_buttons,
                alignment=ft.Alignment.CENTER,
            )
        )
        func_buttons_wrap = prepare_intro(
            ft.Container(
                padding=ft.Padding.only(left=8),
                border=ft.Border.only(
                    left=ft.BorderSide(1, color=theme["border"])
                ),
                content=ft.Row(controls=func_buttons, spacing=0, tight=True),
            )
        )

        NAV_SIDE_WIDTH = 200

        navbar_content = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=title_wrap,
                        width=NAV_SIDE_WIDTH,
                        alignment=ft.Alignment.CENTER_LEFT,
                    ),
                    tabs_pop_wrap,
                    ft.Container(
                        content=func_buttons_wrap,
                        width=NAV_SIDE_WIDTH,
                        alignment=ft.Alignment.CENTER_RIGHT,
                    ),
                ],
                spacing=0,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.TRANSPARENT,
            padding=ft.Padding.only(top=10, bottom=10, left=10, right=10),
        )

        navbar = ft.WindowDragArea(content=navbar_content)

        navigate(tab)  # default page shown on load

        features.update_badge = ft.Container(
            width=8, height=8, border_radius=4, bgcolor=theme["btn_primary"],
            right=8, top=6, visible=False,
        )
        tabs_buttons.content.controls.append(features.update_badge)
        features.refresh_update_badge()
        page.add(ft.Stack(expand=True, on_size_change=features.toasts.resize, controls=[
            ft.Column([navbar, content_area], expand=True, spacing=0),
            features.toasts,
            ft.Container(left=20, right=20, bottom=0, content=features.progress),
        ]))
        features.start()
        features.player_changed()
        # Kick off the ripple entrance now that the first frame is committed.
        page.run_task(play_intro_ripple)

    async def refresh_version_catalog():
        nonlocal latest_release_id, online_available
        if refresh_state["running"]:
            return

        was_online = online_available
        was_known = connectivity_known["value"]
        old_latest_release_id = latest_release_id
        refresh_state["running"] = True
        try:
            versions, latest, is_online = await asyncio.to_thread(get_version_catalog)
        except Exception:
            versions, latest = get_local_version_catalog()
            is_online = False

        refresh_state["running"] = False
        if is_online:
            version_catalog[:] = versions
            latest_release_id = latest
            save_installations(
                installations, handled_external_profile_ids, latest
            )
            online_available = True
            connectivity_known["value"] = True
            for btn_key in ("new_installation_button", "skin_refresh_button", "skin_manage_button"):
                b = launcher_log_state.get(btn_key)
                if b is not None:
                    b.disabled = False
                    if btn_key.startswith("skin_"):
                        b.tooltip = None
                    try:
                        b.update()
                    except Exception:
                        pass
            if was_known and not was_online:
                notify("Internet connection restored.", ft.Icons.WIFI)
                if active_page.get("name") == "skins":
                    skin_sync = launcher_log_state.get("skin_sync_task")
                    if skin_sync is not None:
                        page.run_task(skin_sync, False)
            if active_page.get("name") == "home" and (
                not old_latest_release_id
                or old_latest_release_id != latest
            ):
                while intro_state.get("pending") or intro_state.get("running"):
                    await asyncio.sleep(0.05)
                if navigation_state.get("navigate") and active_page.get("name") == "home":
                    navigation_state["navigate"]("home", force=True)
            return

        online_available = False
        connectivity_known["value"] = True
        tooltip_fn = launcher_log_state.get("tooltip_func")
        for btn_key in ("new_installation_button", "skin_refresh_button", "skin_manage_button"):
            b = launcher_log_state.get(btn_key)
            if b is not None:
                b.disabled = True
                if btn_key.startswith("skin_"):
                    tip_msg = "Internet connection required"
                    b.tooltip = tooltip_fn(tip_msg) if tooltip_fn else tip_msg
                try:
                    b.update()
                except Exception:
                    pass
        if active_page.get("name") == "skins":
            skin_sync = launcher_log_state.get("skin_sync_task")
            if skin_sync is not None:
                page.run_task(skin_sync, False)
        if was_known and was_online:
            notify(
                "No internet connection. Installed versions remain available.",
                ft.Icons.WIFI_OFF,
            )
        elif not was_known:
            notify(
                "No internet connection. Installed versions remain available.",
                ft.Icons.WIFI_OFF,
            )

    def check_internet_connection():
        from launcher_services import check_internet_connection as probe
        return probe()

    async def monitor_connectivity():
        nonlocal online_available
        while True:
            connected = await asyncio.to_thread(check_internet_connection)
            if connected and not online_available:
                await refresh_version_catalog()
            elif not connected and online_available:
                online_available = False
                connectivity_known["value"] = True
                tooltip_fn = launcher_log_state.get("tooltip_func")
                for btn_key in ("new_installation_button", "skin_refresh_button", "skin_manage_button"):
                    b = launcher_log_state.get(btn_key)
                    if b is not None:
                        b.disabled = True
                        if btn_key.startswith("skin_"):
                            tip_msg = "Internet connection required"
                            b.tooltip = tooltip_fn(tip_msg) if tooltip_fn else tip_msg
                        try:
                            b.update()
                        except Exception:
                            pass
                if active_page.get("name") == "skins":
                    skin_sync = launcher_log_state.get("skin_sync_task")
                    if skin_sync is not None:
                        page.run_task(skin_sync, False)
                notify(
                    "No internet connection. Installed versions remain available.",
                    ft.Icons.WIFI_OFF,
                )
            await asyncio.sleep(30)

    profiles_json_path = Path(minecraft_directory) / "launcher_profiles.json"
    last_profiles_mtime = [0.0]
    if profiles_json_path.is_file():
        try:
            last_profiles_mtime[0] = profiles_json_path.stat().st_mtime
        except Exception:
            pass

    async def watch_external_profiles():
        stamp = await asyncio.to_thread(installation_sources_stamp, minecraft_directory)
        while not features.closed:
            await asyncio.sleep(2.5)
            if features.busy:
                continue
            try:
                current = await asyncio.to_thread(installation_sources_stamp, minecraft_directory)
                if current == stamp:
                    continue
                changed = await asyncio.to_thread(sync_local_installations)
                stamp = current
                if changed:
                    installations[:] = load_installations()
                    features.profiles_changed()
                    notify('Synced Minecraft profiles and instances.', 'success')
            except Exception as error:
                notify(error, 'error', 'Could not sync profiles')

    build_page(theme_choice)
    page.run_task(refresh_version_catalog)
    page.run_task(monitor_connectivity)
    page.run_task(watch_external_profiles)
    page.run_task(asyncio.to_thread, skins.prune_skin_cache)

if __name__ == "__main__":
    ft.run(main, assets_dir=str(ASSETS_DIR))
