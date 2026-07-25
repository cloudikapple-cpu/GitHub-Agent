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

## 3. Run

```powershell
jarvis                      # REPL
jarvis -m "what is on my screen?"
jarvis --gui                # desktop window
jarvis --daemon             # background: hotkeys, tray icon, reminders
jarvis --profile safe       # read-only mode
jarvis --stream             # print the reply as it is generated
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

## 4. Start with Windows

```powershell
jarvis --autostart install   # adds a shortcut to the Startup folder
jarvis --autostart status
jarvis --autostart remove
```

## 5. Permission profiles

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

## 6. Undoing a mistake

Deletes do not destroy anything: the target is moved to `%USERPROFILE%\.jarvis\trash`,
and overwrites are backed up there first.

```
you> undo
```

or ask in plain language — the model has the `undo_last` and
`list_recent_changes` tools.

## 7. Windows-specific notes

- **Installing apps** goes through `winget`. It ships with Windows 11; check it
  with `winget --version`. This capability is off unless the profile is `yolo`
  or `JARVIS_ALLOW_APP_MANAGEMENT=true`.
- **The sandbox** (`--sandbox docker`) needs Docker Desktop with the WSL 2
  backend. `firejail` is Linux-only.
- **Antivirus.** Global hotkey capture and synthetic keystrokes look like a
  keylogger to some security suites. If the hotkey stops working, whitelist the
  Python interpreter inside `.venv`.
- **Paths with spaces** (`C:\Program Files\...`) work as-is; there is no need to
  quote them in a request.
- **Restricting the workspace** is worth doing on a work machine:

  ```ini
  JARVIS_ALLOWED_ROOTS=C:\Users\You\Projects;C:\Users\You\Documents
  ```

- **Audit log**: `%USERPROFILE%\.jarvis\audit.log` records every guarded action.
