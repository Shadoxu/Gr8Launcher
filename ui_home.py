"""Classic Home banner, profile shelf, launch controls, and game log view."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import TYPE_CHECKING, Callable

import flet as ft

import banners
import state
from launcher import get_profile_version_id
from storage import get_active_account, save_profile_options
from skins import get_account_head_avatar_bytes as get_active_player_head_avatar_bytes
from credential_store import redact_credentials
from ui_components import clickable_mouse_cursor, tooltip
from ui_profile_assets import profile_badges as build_profile_badges, profile_summary

if TYPE_CHECKING:
    from ui_legacy_features import LegacyFeatures


def build_home_view(*, page: ft.Page, theme: dict, installations: list[dict],
                    installed_versions: list[dict], latest_release_profile: dict | None,
                    minecraft_directory: str, assets_dir: Path, features: LegacyFeatures,
                    navigate: Callable, notify: Callable, launch_profile: Callable,
                    update_launch_progress: Callable, copy_to_clipboard: Callable,
                    open_game_folder: Callable, prepare_intro: Callable) -> ft.Container:
    launcher_log_state = state.launcher_log_state
    player_name_state = state.player_name_state
    profile_picture_state = state.profile_picture_state
    launch_selection = state.launch_selection
    active_page = state.active_page
    navigation_state = state.navigation_state
    progress_host = features.progress
    local_version_ids = {version["version_id"] for version in installed_versions}
    ASSETS_DIR = assets_dir
    launch_targets = {}
    if latest_release_profile:
        launch_targets[latest_release_profile["id"]] = latest_release_profile
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
    def refresh_account_picture():
        account_avatar.content = build_account_picture(36)
        account_username_text.value = get_active_account().get("username", "Player")
        for avatar_control in (account_avatar, account_username_text):
            try:
                avatar_control.update()
            except Exception:
                pass

    launcher_log_state["refresh_account_picture"] = refresh_account_picture


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

    def is_current_home() -> bool:
        return (not features.closed and active_page.get("name") == "home"
                and launcher_log_state.get("list") is launcher_log_list)

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
    launcher_log_state["floating_logs_window"] = floating_logs_window
    selected_version_elements_ref = {"control": None}

    def set_launcher_log_visible(visible):
        launcher_log_state["open"] = visible
        log_back_button.visible = visible
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
        if not is_current_home() or not banner_path or card_key not in library_banner_images:
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
            if not is_current_home():
                return
            # The hero request already resolves the selected profile's artwork.
            if k == launch_selection.get("key") or banners.get_local_banner_for_target(tgt, minecraft_directory):
                continue
            try:
                resolved_path = await banners.ensure_banner_for_target(
                    tgt, minecraft_directory
                )
                if not is_current_home():
                    return
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
        if not is_current_home() or img_ctrl is None:
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
            if not is_current_home() or launch_selection["key"] != target_key:
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
        if not is_current_home():
            return
        if resolved:
            apply_card_banner(target_key, resolved)
        if not resolved or launch_selection["key"] != target_key:
            return
        if resolved == hero_banner_view["src"] and (img_ctrl.opacity or 0) > 0:
            return
        await fade_out_current()
        if not is_current_home() or launch_selection["key"] != target_key:
            return
        show_banner(resolved)
        hero_banner_view["src"] = resolved

    card_transition_token = 0

    async def animate_card_selection(target):
        nonlocal card_transition_token
        if not is_current_home():
            return
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
        if not is_current_home() or card_transition_token != token:
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
        launcher_log_state["status"] = f"Selected {selected_target['name']}"
        progress_host.set_idle(launcher_log_state["status"])
        page.run_task(animate_card_selection, selected_target)

    def build_library_card(key, target):
        is_selected = launch_selection['key'] == key
        is_installed = target['version_id'] in local_version_ids
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
                    "Cancelling after the current file...", value=None, eta=""
                )
                refresh_launch_button()
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
    launcher_log_state["play_button"] = play_button
    launcher_log_state["refresh_play_button"] = refresh_launch_button
    refresh_launch_button()

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



    home_status_row = ft.Row(
        alignment=ft.MainAxisAlignment.END,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[bottom_log_toggle_button],
    )
    if launcher_log_state.get("running"):
        for card in library_cards.values():
            card.disabled = True
            card.opacity = 0.5
        new_profile_container.disabled = True
        new_profile_container.opacity = 0.5
        refresh_launch_button()
    for control in (welcome_row, selected_installation_card, library_shelf_container, home_status_row):
        prepare_intro(control)
    return ft.Container(
        expand=True,
        content=ft.Stack(
            expand=True,
            controls=[
                ft.Container(
                    expand=True,
                    padding=ft.Padding(left=28, top=20, right=28, bottom=16),
                    content=ft.Column(
                        expand=True, spacing=14,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[welcome_row, selected_installation_card, library_shelf_container, home_status_row],
                    ),
                ),
                floating_logs_window,
            ],
        ),
    )
