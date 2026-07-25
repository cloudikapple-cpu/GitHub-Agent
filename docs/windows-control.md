# Windows 11 control

Everything in this guide is Windows-specific. On Linux and macOS the same calls
degrade to a no-op or to the previous behaviour, so nothing here has to be
switched off elsewhere.

## Autostart through Task Scheduler

```powershell
jarvis --autostart install
jarvis --autostart status
jarvis --autostart uninstall
```

Until 0.4 this dropped a `.cmd` file into the Startup folder. That approach has
three defects: the console window flashes at every logon, Task Manager's
Startup tab can disable it with one click without telling the application, and
nothing restarts the daemon if it dies.

The installer now registers a logon task called **Jarvis**:

| Property | Value | Why |
| --- | --- | --- |
| Trigger | At logon, delayed | 30 seconds, so Explorer is ready before the global hotkey is claimed |
| Interpreter | `pythonw.exe` | No console window |
| Multiple instances | `IgnoreNew` | Belt and braces next to the PID lock |
| On failure | Restart, 3 times, every minute | A crashed daemon comes back |
| Privileges | Least privilege | No admin prompt at logon |

Inspect or edit it by hand in Task Scheduler, or with
`schtasks /Query /TN Jarvis /V /FO LIST`.

If `schtasks` refuses - group policy, a locked-down machine - the installer
falls back to the Startup shortcut and says so instead of pretending the task
was created.

## Toasts with buttons

Reminders and `notify` now use the Windows 11 notification manager, so they
land in the Notification Centre and survive being missed. A notification can
carry one button:

```
notify me when the report is ready, with a button that opens the folder
```

The model calls `notify(message=..., action_label="Open", action_uri="file:///C:/reports")`.
The button opens the URI through the shell, so any registered protocol works:
`https://`, `file://`, `ms-settings:`, `mailto:`.

Windows shows a toast only for a registered application id. The default is the
PowerShell id, which always exists; point `JARVIS_TOAST_APP_ID` at your own
AUMID if you have one installed.

## PowerShell

`run_shell` reaches only `cmd.exe` on Windows, which leaves out services, the
registry, scheduled tasks, winget queries and every cmdlet that returns
objects. The new `run_powershell` tool covers that:

```
which services are set to start automatically but are not running?
how much free space is left on every disk?
turn off notifications until tomorrow morning
```

Three deliberate choices:

- `-NoProfile` - your profile cannot slow the call down, print a banner or
  redefine a cmdlet under the assistant's feet;
- `-EncodedCommand` - the script travels base64-encoded, so quoting and
  injection do not apply;
- the same `SecurityPolicy` gate as `run_shell`, so `JARVIS_ALLOW_SHELL=false`
  still stops every form of command execution, and the deny-list still applies.

Set `JARVIS_POWERSHELL` to use PowerShell 7 (`pwsh.exe`) instead of the
built-in Windows PowerShell.

## Clipboard history

Windows keeps its own history behind `Win+V`, but no application can read it.
Jarvis therefore keeps a small ring buffer of its own in
`~/.jarvis/clipboard.json` - the last 50 items, 10000 characters each:

```
what did I copy before this?
copy the second item from the clipboard history back
forget the clipboard history
```

The daemon polls every two seconds; the `clipboard` tool also records whatever
it sees, so history works without the daemon. Clear it at any time with
`action="clear_history"`, and remember that anything you copy - passwords
included - lands in that file until it rotates out.

## Hotkey conflicts

Both hotkey backends fail silently when another application already owns a
shortcut: the listener starts, the key does nothing, and nothing appears in the
logs. At startup the daemon now asks Windows directly and prints, for example:

```
Hotkeys active via pynput: ctrl+alt+space; already owned by another
application: ctrl+alt+space - change interface.hotkey in config.yaml or
JARVIS_HOTKEY
```

The usual culprits are Windows Terminal's Quake mode, Nvidia GeForce Overlay,
MSI Afterburner, Yandex Music and Punto Switcher.

## Environment variables added in 0.4

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_POWERSHELL` | `powershell` on Windows, `pwsh` elsewhere | Which interpreter `run_powershell` uses |
| `JARVIS_TOAST_APP_ID` | PowerShell's AUMID | Which application the toast is attributed to |
