---
name: linux-mint-app-hotkey
description: Set up a global keyboard shortcut on Linux Mint (Cinnamon) that launches an application, or focuses/raises its window if it's already open (a "run-or-raise" hotkey). Use whenever the user asks to map a key to a program, e.g. "กด key ลัดเปิด wezterm", "อยากได้ปุ่มลัดเปิด/focus โปรแกรม X", "bind a hotkey to toggle my terminal", "shortcut to open and focus an app". Also use if a shortcut set up this way stops firing, feels laggy, or seems to collide with another binding.
---

# Linux Mint App Hotkey

Cinnamon has no built-in "open, or focus if already open" behavior for arbitrary apps — that only exists for the apps pinned to the panel. To get it for any app, bind a Cinnamon custom keybinding to a small script that checks for an existing window (via `wmctrl`) before deciding whether to focus or launch. This skill is specific to Linux Mint's Cinnamon desktop; the `gsettings` schema and the reload trick in step 6 don't apply on GNOME, KDE, i3, sway, etc.

## 1. Confirm the desktop environment

Check `$XDG_CURRENT_DESKTOP` / `$XDG_SESSION_DESKTOP`. If it isn't Cinnamon, say so before going further — the rest of this skill won't work as written, though the run-or-raise *idea* (script + WM-specific keybinding mechanism) still transfers.

Confirm `wmctrl` is installed (`command -v wmctrl`); it's what lists and focuses windows. `xdotool` is occasionally useful for deeper input debugging but isn't required for the core pattern.

## 2. Identify the target app's window class

Don't guess the window class — wrong guesses make the script silently fail to find an already-open window, so it "launches a new one" every time instead of focusing.

- Look for the app's `.desktop` file (`/usr/share/applications/*.desktop`, `~/.local/share/applications/*.desktop`) and read `StartupWMClass` if present.
- If there's no desktop file or no `StartupWMClass`, launch the app once and inspect `wmctrl -lx` — the third column is `instance.class`. Match against it case-insensitively (`grep -i`) so exact casing doesn't matter later.

## 3. Pick a key combination

Which keys to use is a matter of personal taste, not something to decide alone — ask the user, and offer 2-3 concrete candidates rather than silently picking one.

Before proposing any combo, check it isn't already bound:

```bash
gsettings list-recursively org.cinnamon.desktop.keybindings
gsettings list-recursively org.cinnamon.desktop.keybindings.wm
gsettings list-recursively org.cinnamon.desktop.keybindings.media-keys
```

Two gotchas worth knowing before you rule a combo "safe":

- **`Above_Tab`**: this keysym means "whatever key sits above Tab", which on most layouts is the grave/backtick key. Cinnamon's default `switch-group` binding (`<Alt>Above_Tab`) uses it. It won't collide with, say, `<Super>grave` (different modifier), but if the user reports a backtick-based shortcut "feels like it's doing something else," this is the first thing to check.
- **Bare F-keys**: many laptops route F1-F12 to hardware/media functions unless Fn is held or Fn-lock is toggled, so a shortcut like `<Super>F12` may never reach Cinnamon as an F12 keypress at all. If a function-key binding silently does nothing, don't assume the gsettings config is wrong — verify what keysym is actually arriving with `xev -event keyboard` (run it, then ask the user to click into the tiny window it opens and press the combo).

## 4. Write the run-or-raise script

Copy `scripts/run-or-raise.sh` to `~/.local/bin/<app-slug>-toggle.sh` and fill in the two placeholders, then `chmod +x` it:

- `WM_CLASS_PATTERN` — the class substring from step 2
- `LAUNCH_CMD` — the launch command; prefer the `Exec=` line from the `.desktop` file over guessing the binary name and flags

## 5. Register the Cinnamon custom keybinding

Custom shortcuts live in a relocatable schema, keyed by an id like `custom0`, `custom1`, etc. **Read `custom-list` before writing it** — overwriting it wholesale deletes any custom shortcuts the user already has:

```bash
gsettings get org.cinnamon.desktop.keybindings custom-list
```

Pick the next unused `customN` id, append it to the existing list (don't drop the old entries), then set the three properties on the new path:

```bash
gsettings set org.cinnamon.desktop.keybindings custom-list "['custom0', 'custom1']"   # existing + new
gsettings set org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom1/ name "<label>"
gsettings set org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom1/ command "/home/<user>/.local/bin/<app-slug>-toggle.sh"
gsettings set org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom1/ binding "['<Super>F12']"
```

## 6. If the shortcut doesn't fire after setup

This is the most common snag: Cinnamon only picks up a **brand-new** custom keybinding entry after its keybinding manager reloads. Restarting the Cinnamon shell fixes it, without logging out or closing any open windows:

```bash
nohup cinnamon --replace > /tmp/cinnamon-restart.log 2>&1 & disown
```

Tell the user before running this — the screen flickers for a second while the panel/desktop redraw. If the key still does nothing after a restart, re-check step 3 for a real conflict and step 2 for a wrong window class, in that order, before assuming the mechanism itself is broken.

## Verify and report

- Run the script directly (`bash ~/.local/bin/<app-slug>-toggle.sh`), not just via the key, with no matching window open — confirm it launches the app.
- Run it again while that window is open — confirm `wmctrl -lx` still shows exactly one window for that app, i.e. it focused rather than launching a duplicate.
- Only then ask the user to test the physical key combo.

Summarize in Thai for Thai-speaking users: which key got bound, what script it runs, and any manual step still pending (e.g. "if it stops responding after a Cinnamon update, restart Cinnamon again with the same command").
