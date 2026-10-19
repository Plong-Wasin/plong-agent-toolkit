---
name: linux-mint-appimage
description: Install and integrate downloaded AppImages on Linux Mint Cinnamon, including stable storage, desktop launchers, embedded icons, duplicate menu entries, and taskbar pinning. Do not use for generic Linux package installation or AppImage development.
---

# Linux Mint AppImage

Use this skill when the user wants a downloaded `.AppImage` to behave like a normal Linux Mint application: launch from the menu, show the correct icon, and optionally stay pinned to the Cinnamon panel.

## Install in a stable location

- Confirm the requested source path exists, is an AppImage, and is user-owned before changing it. Preserve the executable bit with `test -x` and `chmod +x` when needed.
- Prefer a stable user-owned location such as `~/Applications/<app-slug>/<filename>.AppImage`; `~/Downloads` is a staging area and may be cleaned later.
- Check whether the destination already exists before moving. Do not overwrite an existing application without explicit confirmation.
- After a move, update every launcher that points to the old path. Test the new file with the AppImage runtime's `--appimage-version` option when available; this checks the runtime without launching the GUI.

## Create the menu launcher

Create one curated desktop entry at `~/.local/share/applications/<app-id>.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=<Display name>
Exec=<absolute path to AppImage>
Icon=<absolute path to extracted image or installed icon name>
Terminal=false
Categories=Utility;
```

- Use an absolute `Exec` path and keep the desktop filename stable; the filename is the desktop ID used by Cinnamon.
- Validate the entry with `desktop-file-validate` when installed. Do not create multiple launchers for the same application merely to obtain a panel icon.
- If the AppImage contains an icon, extract it into a temporary directory with `--appimage-extract`, choose the best usable PNG/SVG size, and copy it to a stable user icon path such as `~/.local/share/icons/hicolor/256x256/apps/<app-id>.png`. Point `Icon` at that image. Inspect the image before using it; do not assume a file named `icon` is valid.
- If no embedded icon exists, use an installed icon name or a generic executable icon and report that limitation.

## Handle Cinnamon duplicates

When searching the Mint menu, distinguish applications from recent files:

- A result showing the full AppImage path is commonly a `Recent Files` bookmark created when the AppImage was opened from Nemo or a portal. Inspect `~/.local/share/recently-used.xbel` and remove only the matching `<bookmark>` for that AppImage, preserving unrelated history. Refresh Cinnamon or ask the user to log out and in.
- Cinnamon can generate `*.cinnamon-generated.desktop` entries for applications discovered while running or pinning them. If one duplicates the curated launcher, verify its `Name` and `Exec`, then move only that duplicate to the user's trash rather than deleting unrelated launchers.
- Leave protocol handlers such as `dbx-handler.desktop` in place when they contain `NoDisplay=true`; they are not normal menu entries.
- Refresh the desktop database if available, but treat validation errors from unrelated existing desktop files as separate issues and do not rewrite them while fixing this application.

## Pin to the Cinnamon panel

- Once the curated desktop entry appears in the menu, use the Cinnamon UI: right-click the menu item and choose `Add to panel`, or launch it and choose `Pin to panel` on the running application's panel icon.
- Prefer the UI over editing Cinnamon's internal grouped-window-list JSON directly; Cinnamon may rewrite that state and discard manually inserted IDs. Verify the pin visually after refreshing Cinnamon.
- If the application launches as a separate ungrouped icon, inspect its desktop identity/window class before changing `StartupWMClass`; do not guess a class value.

## Verify and report

Check all of the following before claiming completion:

- the AppImage exists at the final path and remains executable;
- the desktop entry's `Exec` and `Icon` paths exist;
- the menu has one visible launcher for the app, excluding `NoDisplay=true` handlers and unrelated recent-file entries;
- the launcher opens the AppImage, and the panel pin is confirmed if requested.

For Thai-speaking users, summarize the final AppImage path, launcher path, icon path, duplicate cleanup, and any remaining manual panel action in Thai. If a GUI refresh or panel interaction could not be verified, say so explicitly instead of claiming it was pinned.
