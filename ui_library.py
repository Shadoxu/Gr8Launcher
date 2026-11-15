"""The classic profile manager using shared rows and retained profile ordering."""

from __future__ import annotations

from typing import Callable

import flet as ft

import ui_theme as theme
from launcher import get_profile_version_id
from ui_controls import launcher_button, launcher_icon_button
from ui_profile_assets import profile_badges, profile_icon, profile_summary
from ui_profiles import ProfileList, profile_drag_region, profile_list_surface, profile_row


class ClassicLibraryPage(ft.Container):
    def __init__(self, *, on_new: Callable, on_play: Callable, on_mods: Callable,
                 on_edit: Callable, on_remove: Callable, on_repair: Callable,
                 on_folder: Callable, on_move: Callable, on_order: Callable,
                 busy: Callable[[], bool]):
        self._busy = busy
        self._on_play = on_play
        self._on_mods = on_mods
        self._on_edit = on_edit
        self._on_remove = on_remove
        self._on_repair = on_repair
        self._on_folder = on_folder
        self._on_move = on_move
        self.list_view = ProfileList(on_order_changed=on_order)
        self.summary = ft.Text(size=12, color=theme.MUTED)
        self.new_button = launcher_button("New Profile", on_new, primary=True, icon=ft.Icons.ADD, height=38)
        self.header = ft.Row([
            ft.Text("Profiles", size=24, weight=ft.FontWeight.BOLD, color=theme.TEXT),
            ft.Container(expand=True), self.new_button,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        super().__init__(
            expand=True, padding=ft.Padding(left=28, top=20, right=28, bottom=20),
            content=ft.Column([self.header, self.summary, profile_list_surface(self.list_view)],
                              expand=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        )

    def refresh(self, profiles: list[dict], installed_ids: set[str], selected_id: str,
                *, footer: tuple[ft.Control, ...] | list[ft.Control] = ()) -> None:
        busy = self._busy()
        self.new_button.disabled = busy
        installed = sum(get_profile_version_id(profile) in installed_ids for profile in profiles)
        self.summary.value = f"{len(profiles)} {'profile' if len(profiles) == 1 else 'profiles'} · {installed} installed"
        cards = []
        for profile in profiles:
            pid = profile["id"]
            ready = get_profile_version_id(profile) in installed_ids
            selected = pid == selected_id

            def body(icon, info, profile_id=pid):
                region = profile_drag_region(icon, info, color=theme.MUTED,
                                             view=self.list_view, profile_id=profile_id)
                region.controls[0].ignore_interactions = busy
                region.controls[0].mouse_cursor = ft.MouseCursor.BASIC if busy else ft.MouseCursor.GRAB
                return region

            badges = profile_badges(profile)
            if not ready:
                badges.append(ft.Container(
                    content=ft.Text("Not installed", size=10, color=theme.MUTED),
                    bgcolor=theme.SURFACE_STRONG, border_radius=5,
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                ))
            surface = profile_row(
                profile, icon=profile_icon(profile), badges=badges, details=profile_summary(profile),
                glow_color=theme.ACCENT, selected=selected, body_builder=body,
                actions=[
                    launcher_icon_button(icon=ft.Icons.PLAY_ARROW_ROUNDED, icon_color=theme.ACCENT,
                        tooltip=f"Play {profile['name']}" if ready else f"Install and play {profile['name']}",
                        on_click=lambda e, item=profile: self._on_play(item), disabled=busy),
                    launcher_icon_button(icon=ft.Icons.EXTENSION_OUTLINED, tooltip=f"Manage mods for {profile['name']}",
                        on_click=lambda e, profile_id=pid: self._on_mods(profile_id)),
                    launcher_icon_button(icon=ft.Icons.FOLDER_OPEN_OUTLINED, tooltip="Open game directory",
                        on_click=lambda e, item=profile: self._on_folder(item)),
                    launcher_icon_button(icon=ft.Icons.EDIT_OUTLINED, tooltip=f"Edit {profile['name']}",
                        on_click=lambda e, profile_id=pid: self._on_edit(profile_id), disabled=busy),
                    self._menu(profile, busy),
                ],
            )
            cards.append(ft.Container(
                key=ft.ValueKey(f"library-profile-{pid}"), data=pid, content=surface,
                border=ft.Border.all(0, theme.TRANSPARENT), border_radius=12,
                scale=1.0,
                margin=ft.Margin.only(bottom=8),
            ))
        extras = list(footer)
        if not cards:
            extras.insert(0, ft.Container(
                padding=24, bgcolor=theme.SURFACE, border_radius=12, border=ft.Border.all(1, theme.BORDER),
                content=ft.Text("No profiles yet. Create a profile to get started.", size=13, color=theme.MUTED),
            ))
        self.list_view.set_cards(cards, footer=ft.Column(extras, spacing=14) if extras else None, update=False)

    def _menu(self, profile: dict, busy: bool) -> ft.PopupMenuButton:
        def item(label: str, icon, callback: Callable) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(
                content=ft.Row([ft.Icon(icon, size=18, color=theme.MUTED),
                                ft.Text(label, size=13, color=theme.TEXT)], spacing=10),
                on_click=callback,
            )
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ, icon_color=theme.MUTED, tooltip=f"More actions for {profile['name']}",
            width=36, height=36, disabled=busy, bgcolor=theme.SURFACE,
            shape=ft.RoundedRectangleBorder(radius=8),
            items=[
                item("Move up", ft.Icons.ARROW_UPWARD, lambda e: self._on_move(profile["id"], -1)),
                item("Move down", ft.Icons.ARROW_DOWNWARD, lambda e: self._on_move(profile["id"], 1)),
                item("Repair Minecraft files", ft.Icons.BUILD_OUTLINED, lambda e: self._on_repair(profile)),
                item("Remove profile", ft.Icons.DELETE_OUTLINE, lambda e: self._on_remove(profile["id"])),
            ],
        )

    def leave(self) -> None:
        self.list_view.cancel_drag()
