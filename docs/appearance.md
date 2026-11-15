# Launcher themes

Choose a Minecraft theme in **Options > UI > Theme Selection**. Earth 2 is the
default; Redstone, Sculk, Gold, Lush, Amethyst, Cherry Blossom, and Earth 1 are
also available. The choice is saved and applies immediately when the launcher
is idle. Finish active installations or mod operations before switching themes.

The original top navigation, home banner, library cards, and Mojangles title
are restored. Mods, modpacks, notifications, progress, and update dialogs follow
the same selected palette, matte rounded cards, compact buttons, and system-font
headings and details. Mojangles remains on the original launcher title and home
banner.

Profiles and the Mods profile selector share their artwork, badges, and build
details. Drag a profile by its grip to save its order; use its action menu for
repair, moving, or removal. The editor offers all bundled block/face icons and
custom PNG, JPEG, and WebP images. Custom icons are copied into launcher data so
moving their source image does not lose the selection. Latest Release supports
the same icon choices and extra Java arguments.

To customize a palette from source, edit its entry in `colors.THEMES`:

| Theme token | Controls |
| --- | --- |
| `bg`, `surface`, `card`, `card_hover` | Page and card backgrounds |
| `btn_primary`, `btn_primary_text` | Primary buttons, selection, and progress |
| `text_primary`, `text_secondary`, `text_muted` | Text and icons |
| `border` | Card and input boundaries |

`ui_theme.apply_legacy_theme` maps these tokens to the retained feature controls.
Colors retain their roles through theme changes, including button styles and
transparent tints; a shared hex value does not conflate background and text.
Error, warning, and loader colors keep their separate meanings. Minecraft art
and skins retain their original colors. Font files and licenses remain bundled
under `.assets/font/` and `.assets/fonts/`.
