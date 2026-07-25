# Jarvis on Windows 11

Everything below assumes a clean Windows 11 machine and PowerShell.

## 1. Install

```powershell
winget install Python.Python.3.12
git clone https://github.com/cloudikapple-cpu/GitHub-Agent.git
cd GitHub-Agent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[windows,openai]"
```

If PowerShell refuses to run the activation script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

The `windows` extra pulls in everything the desktop features need:
`pyautogui` (keyboard, mouse, screenshots), `pyperclip` (clipboard), `psutil`
(processes), `Pillow` (images), `pynput` (global hotkey), `pystray` (tray icon)
and `plyer` (toast notifications).

## 2. Configure

```powershell
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
notepad .env
```

Minimum for a cloud model:

```ini
OPENAI_API_KEY=sk-...
```

Minimum for a fully local setup:

```powershell
winget install Ollama.Ollama
ollama pull llama3.1
```

```ini
JARVIS_BACKEND=ollama
```

The recommended hybrid — a local model for everyday work, NVIDIA NIM for hard
tasks:

```ini
JARVIS_ROUTER=true
JARVIS_ROUTER_PRIMARY=ollama
JARVIS_ROUTER_HEAVY=nim
NVIDIA_API_KEY=nvapi-...
```

For web search, add a Tavily key (free tier is enough):

```ini
TAVILY_API_KEY=tvly-...
```

Without it Jarvis falls back to DuckDuckGo automatically.

## 3. Check the machine before the first run

```powershell
jarvis --doctor
```

The report covers the interpreter, `config.yaml` and `.env`, the selected
provider and its key (or whether Ollama is actually listening), the optional
packages behind desktop control, hotkeys, the tray and voice, the writability of
`%USERPROFILE%\.jarvis`, PowerShell, winget, the sandbox and the permissions in
force. Each line that is not `[ ok ]` carries the command that fixes it:

```
[ ok ] python: 3.12.4 on Windows 11
[warn] env file: no .env in the current folder
        fix: copy .env.example to .env and fill in the keys you use
[fail] api key: provider 'openai' has no API key
        fix: add the key to .env, or run with --api-key
```

Exit code is 1 while any blocking problem remains, so the command also works in
a setup script.

## 4. Run

```powershell
jarvis                      # REPL
jarvis -m "what is on my screen?"
jarvis --gui                # desktop window
jarvis --daemon             # background: hotkeys, tray icon, reminders, clipboard
jarvis --profile safe       # read-only mode
jarvis --stream             # print the reply as it is generated
jarvis --usage              # what today's model calls cost
```

Global hotkeys while the daemon runs:

| Hotkey | Action |
|---|---|
| `Ctrl+Alt+Space` | open the assistant window |
| `Ctrl+Alt+V` | voice command |

Change them in `.env`:

```ini
JARVIS_HOTKEY=ctrl+alt+j
JARVIS_VOICE_HOTKEY=ctrl+alt+m
```

If another application already owns the combination, the daemon reports the
conflict at startup instead of registering a listener that never fires.

## 5. Start with Windows

```powershell
jarvis --autostart install   # registers a Task Scheduler logon task
jarvis --autostart status
jarvis --autostart remove
```

The task is called `Jarvis`. It starts `pythonw.exe` through
`%APPDATA%\Jarvis\jarvis.cmd`, so there is no console flash, waits 30 seconds
after logon to let the network come up, and restarts up to three times after a
crash. Unlike a Startup-folder shortcut it cannot be silently disabled from the
Task Manager's Startup tab; inspect it with:

```powershell
schtasks /query /tn Jarvis /v /fo list
```

## 6. Windows-only capabilities

- **`run_powershell`** runs any cmdlet through `-NoProfile -EncodedCommand`, so
  quoting and Cyrillic text survive intact: services, the registry, scheduled
  tasks, `Get-WinEvent`, winget queries. It asks for confirmation and obeys
  `JARVIS_ALLOW_SHELL`, the command deny-list and the audit log.
- **Toast notifications** land in the Notification Centre and can carry a
  button. Set `JARVIS_TOAST_APP_ID` to change the name shown on the toast.
- **Clipboard history**: the daemon keeps the last 50 entries in
  `%USERPROFILE%\.jarvis\clipboard.json`, so *"what did I copy before this?"* has
  an answer. `clipboard` also does get, set and clear_history.
- **Installing apps** goes through `winget`. It ships with Windows 11; check it
  with `winget --version`. This capability is off unless the profile is `yolo`
  or `JARVIS_ALLOW_APP_MANAGEMENT=true`.

## 7. Permission profiles

| Profile | Shell | Code | Keyboard/mouse | Installing apps | Confirmations |
|---|---|---|---|---|---|
| `safe` | — | — | — | — | yes |
| `dev` (default) | yes | yes | yes | — | yes |
| `yolo` | yes | yes | yes | yes | no |

```powershell
jarvis --profile dev
```

Each switch is still available on its own via `JARVIS_ALLOW_SHELL`,
`JARVIS_ALLOW_EXEC`, `JARVIS_ALLOW_DESKTOP`, `JARVIS_ALLOW_APP_MANAGEMENT` and
`JARVIS_ALLOW_NETWORK`.

## 8. Undoing a mistake

Deletes do not destroy anything: the target is moved to `%USERPROFILE%\.jarvis\trash`,
and overwrites are backed up there first.

```
you> undo
```

or ask in plain language — the model has the `undo_last` and
`list_recent_changes` tools.

## 9. Notes and troubleshooting

- **The sandbox** (`--sandbox docker`) needs Docker Desktop with the WSL 2
  backend. `firejail` is Linux-only.
- **Antivirus.** Global hotkey capture and synthetic keystrokes look like a
  keylogger to some security suites. If the hotkey stops working, whitelist the
  Python interpreter inside `.venv`.
- **`jarvis` is not recognised** after installing: the virtual environment is not
  active. Run `.\.venv\Scripts\Activate.ps1`, or call it as
  `.\.venv\Scripts\jarvis.exe`.
- **Paths with spaces** (`C:\Program Files\...`) work as-is; there is no need to
  quote them in a request.
- **Restricting the workspace** is worth doing on a work machine:

  ```ini
  JARVIS_ALLOWED_ROOTS=C:\Users\You\Projects;C:\Users\You\Documents
  ```

- **Audit log**: `%USERPROFILE%\.jarvis\audit.log` records every guarded action.
- **Spend**: `jarvis --usage` reads `%USERPROFILE%\.jarvis\usage.json`; set
  `JARVIS_BUDGET_DAILY_USD` to cap it.
