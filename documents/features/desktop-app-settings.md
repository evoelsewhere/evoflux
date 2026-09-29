# Desktop app settings (startup, tray, keep awake)

**Settings → Desktop** (`web/src/routes/settings.desktop.tsx`) holds the
preferences that change how the desktop app process behaves rather than how
agents or the sidecar behave. The Tauri shell owns them; the sidecar never
sees them. In a browser build the page shows the switches disabled with a note
that they need the desktop app.

| Setting | Default | Effect |
| --- | --- | --- |
| Run on startup | off | Opens EvoFlux when the user signs in. |
| Show in system tray (menu bar on macOS) | on | Shows the tray status icon and menu. |
| Keep computer awake | off | Stops idle system sleep while EvoFlux runs. |

Every switch applies immediately; nothing needs a restart.

## Run on startup

The operating system's login entry is the only record, so disabling it from
Task Manager → Startup apps or deleting the entry is reflected on the page
(it refetches when the window regains focus).

| OS | Entry |
| --- | --- |
| Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value named after the product. Task Manager's `StartupApproved\Run` flag counts as off; turning the switch on in EvoFlux clears that flag. |
| macOS | `~/Library/LaunchAgents/<identifier>.login.plist` with `RunAtLoad`. |
| Linux | `$XDG_CONFIG_HOME/autostart/<identifier>.desktop`; `Hidden=true` or `X-GNOME-Autostart-enabled=false` counts as off. An AppImage registers `$APPIMAGE`, not its temporary mount. |

The entry launches the executable with `--autostart`. Such a launch creates
the main window hidden, so EvoFlux waits in the tray (in the Dock and menu bar
on macOS). If the tray icon is off on Windows or Linux, the window opens
normally, because a hidden window could not be reached. On every start an
existing entry is rewritten with the current executable path, so a moved
bundle keeps launching.

Dev builds use a different product name and identifier, so their entry never
replaces the installed app's.

## Show in system tray

When on, the tray icon and its menu (status, active session, navigation,
updates, Quit) behave as before. Closing a window hides it and EvoFlux keeps
running, so scheduled tasks and Remote Control continue.

When off, the icon is hidden. On Windows and Linux, closing the last visible
EvoFlux window then quits the app, and the Windows title-bar menu shows
**Close Window** instead of **Hide to Tray**. macOS keeps its Dock icon, so
closing a window still only hides it.

## Keep computer awake

While on, EvoFlux holds a system-sleep assertion; the display may still turn
off.

| OS | Mechanism |
| --- | --- |
| Windows | `PowerRequestSystemRequired` power request (listed by `powercfg /requests`). Lid close and Start → Sleep still work. |
| macOS | `caffeinate -i -w <EvoFlux pid>` helper. User-requested sleep still works. |
| Linux | `systemd-inhibit --what=idle:sleep --mode=block` around `tail --pid=<EvoFlux pid>`; desktops name EvoFlux when the user asks to suspend. |

The macOS and Linux helpers watch EvoFlux's pid, and the Windows request
belongs to the process, so a crash cannot leave the machine unable to sleep.
The assertion is released on quit and when the switch is turned off.

## Storage and commands

- `desktop-settings.json` in the Tauri app config directory stores
  `tray_icon` and `keep_awake`. Run on startup is read from the OS each time.
- `app_desktop_settings` returns `{ run_on_startup, tray_icon, keep_awake }`;
  `app_update_desktop_settings` takes the same fields, each optional, applies
  them, and returns the new state. Both are granted in
  `desktop/src-tauri/capabilities/default.json`.

## Source

- `desktop/src-tauri/src/desktop_settings.rs` — settings file, commands, tray
  visibility, close-quits rule.
- `desktop/src-tauri/src/autostart.rs` — login entries per OS.
- `desktop/src-tauri/src/keep_awake.rs` — sleep assertion per OS.
- `web/src/hooks/useDesktopSettings.ts` — TanStack Query hooks.
- In-app Help: `desktop-settings` in `web/src/help/locales/`.
