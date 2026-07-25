# Jarvis

An extensible desktop AI assistant in Python. It talks to any LLM, uses tools to
actually do things on your computer, remembers what matters, reminds you about
it, and can be summoned with a global hotkey — by voice, by text, from the tray
or from Telegram.

```
you> find every TODO in ~/projects, create a report folder and write summary.md
you> remind me every day at 09:00 to review the inbox
you> посмотри на экран и скажи, что за ошибка в терминале
```

On Windows 11? Follow [docs/windows-11.md](docs/windows-11.md) — install, hotkeys,
autostart, winget and antivirus notes in one place.

## What it can do

| Area | Capabilities |
| --- | --- |
| Internet | `web_search` (Tavily, DuckDuckGo fallback), `web_fetch` (Tavily Extract → plain HTTP), `http_request` (any REST API) |
| Files | read, write, append, list, `make_directory`, `delete_path`, `move_path`, `copy_path`, `find_files` (with content search) |
| Undo | `undo_last`, `list_recent_changes` — deletes go to a trash folder, overwrites are backed up |
| Code | `write_file` + `run_python` + `run_shell` — write code, run it, read the output, iterate; optionally inside Docker/Firejail |
| Apps | `install_app` / `uninstall_app` (winget, choco, scoop, brew, apt, dnf, pacman, zypper, snap, flatpak), `list_installed_apps` |
| System | `list_processes`, `kill_process`, `system_info` |
| Desktop | `open_path`, `take_screenshot`, `type_text`, `press_hotkey`, `clipboard`, `notify` |
| Vision | `see_screen`, `look_at_image` — the assistant looks at your screen with a vision model |
| Memory | `remember`, `recall`, `forget` — durable notes in a local vector store, recalled automatically |
| Reminders | `remind_me`, `schedule_task`, `list_jobs`, `cancel_job` — one-shot, interval or daily |
| Sub-agents | `delegate` — hand a subtask to a helper agent, optionally on a cheaper model |
| MCP | every tool of every configured MCP server, stdio or HTTP |
| Skills | your own Python or YAML skills, auto-loaded from `~/.jarvis/skills` |
| Interfaces | terminal REPL, one-shot CLI, desktop window, global hotkey, voice, tray icon, Telegram |

## Install

```bash
git clone https://github.com/cloudikapple-cpu/GitHub-Agent.git
cd GitHub-Agent
pip install -e ".[all]"        # or: pip install -e ".[openai,web,desktop,hotkey,tray]"
cp .env.example .env           # put your API keys here
cp config.example.yaml config.yaml
```

On Windows 11 the `windows` extra pulls in every desktop dependency at once:
`pip install -e ".[windows,openai]"`.

Linux also needs `python3-tk` for the window and `notify-send` for notifications.

## Run

```bash
jarvis                          # interactive terminal
jarvis -m "summarise my notes"  # one-shot
jarvis --gui                    # desktop window (text + microphone)
jarvis --voice                  # speak your requests
jarvis --daemon                 # background: hotkey, tray, reminders, Telegram
jarvis --telegram               # only the Telegram bot
jarvis --profile safe           # read-only mode (safe | dev | yolo)
jarvis --stream                 # print the answer as it is generated
jarvis --dry-run -m "clean up Downloads"   # plan the actions, run nothing
jarvis --sandbox docker -m "benchmark this script"
jarvis --autostart install      # start with the system (install | remove | status)
jarvis --list-tools             # what it can do right now
jarvis -v                       # show every tool call and result
```

### Global hotkey and tray

With `jarvis --daemon` running, press:

- **Ctrl+Alt+Space** — open the window with the cursor in the input field;
- **Ctrl+Alt+V** — open it and start recording your voice immediately.

Both are configurable (`interface.hotkey`, `interface.voice_hotkey`). The tray
icon offers the same actions plus Quit. macOS needs Input Monitoring permission
for the terminal/app running Jarvis.

## Internet through Tavily

Tavily is a search API built for agents — ranked results, clean page text and an
optional synthesised answer.

```bash
TAVILY_API_KEY=tvly-...
```

With the key, `web_search` uses Tavily; without it (or if Tavily errors out) it
falls back to DuckDuckGo, so search never dies. `web_fetch` tries Tavily Extract
first, which copes with JavaScript-heavy pages.

```yaml
search:
  provider: auto      # auto | tavily | duckduckgo
  max_results: 5
  depth: advanced     # slower, digs deeper
```

## Any custom API

Any OpenAI-compatible endpoint works — OpenRouter, Groq, Together, DeepSeek,
NVIDIA NIM, Mistral, Fireworks, LM Studio, vLLM, llama.cpp, or a corporate
gateway.

```yaml
backend: my-gateway

providers:
  my-gateway:
    kind: openai              # openai | anthropic | ollama
    model: llama-3.3-70b
    base_url: https://api.example.com/v1
    api_key: ${MY_TOKEN}      # read from the environment
    headers:
      X-Title: Jarvis
    temperature: 0.2
    extra_body:
      reasoning_effort: high
```

Or entirely from the environment, with no config file:

```bash
JARVIS_BACKEND=custom JARVIS_API_BASE=https://api.example.com/v1 \
JARVIS_API_KEY=sk-... JARVIS_MODEL=llama-3.3-70b jarvis
```

Or per run: `jarvis -b custom --api-base http://localhost:1234/v1 --model local-model`.

Need a protocol nobody supports? Register your own backend class:

```python
from jarvis.llm import register_backend
register_backend("my-protocol", lambda provider: MyBackend(provider))
```

## Local model + NVIDIA NIM

Run everyday work on a local model for free and privately, and let a cloud model
rescue the hard cases:

```yaml
router:
  enabled: true
  primary: ollama         # local
  fallbacks: [nim]        # NVIDIA NIM when the local one is down
  heavy: nim              # long or explicitly hard requests
  escalate_over_chars: 4000
```

```bash
NVIDIA_API_KEY=nvapi-...
jarvis --router          # or --no-router for a single run
```

The router tries providers in order, remembers which one answered, and reports
every failure in the trace instead of dying.

## Memory and reminders

Durable facts live in a local SQLite vector store (`~/.jarvis/knowledge.db`).
Before each request Jarvis quietly recalls the relevant notes:

```
you> remember that our staging database runs on port 5433
you> which port does staging use?          # answered from memory, no tools
```

Embeddings come from your provider's `/embeddings` endpoint when configured, and
from a built-in offline hashing embedder otherwise.

Reminders and unattended tasks are served by the daemon and survive restarts
(`~/.jarvis/jobs.json`):

```
remind me in 15m to check the deploy
напомни каждый день в 09:00 проверить почту
run "summarise yesterday's commits" every day at 20:00
```

## Undo

Destructive filesystem actions are reversible. `delete_path` moves the target to
`~/.jarvis/trash` instead of destroying it, `write_file` stashes the previous
version first, and `move_path` records where things came from.

```
you> delete the old build folder
you> undo                      # or: "verni papku obratno"
```

`list_recent_changes` shows the journal (`~/.jarvis/journal.jsonl`, last 500
entries).

## MCP servers

Any Model Context Protocol server becomes Jarvis tools — stdio or HTTP, no extra
dependency:

```yaml
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}
```

They appear as `github_create_issue`, `github_search_code`, … A server that fails
to start is skipped with a warning.

## Your own skills

Drop files into `~/.jarvis/skills/` (or `./skills/`). Python skills add real
tools:

```python
from jarvis.tools.base import FunctionTool

def register(registry, config):
    registry.register(FunctionTool(
        name="deploy",
        description="Deploy the current project to staging.",
        parameters={"type": "object", "properties": {}},
        func=lambda: "deployed",
        requires_confirmation=True,
    ))
```

YAML skills are reusable instructions the model can invoke by name:

```yaml
name: daily_report
description: Build my daily report.
prompt: |
  Read ~/notes/today.md, summarise it in five bullets,
  then save the result to ~/reports/report.md.
```

## Integrations with other apps

Declare a service once; the model calls it without ever seeing your token:

```yaml
integrations:
  notion:
    base_url: https://api.notion.com/v1
    headers:
      Authorization: Bearer ${NOTION_TOKEN}
      Notion-Version: "2022-06-28"
  home_assistant:
    base_url: http://homeassistant.local:8123/api
    headers:
      Authorization: Bearer ${HASS_TOKEN}
```

Then: *"turn off the kitchen lights"* → `http_request(service="home_assistant", ...)`.

## Telegram

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USERS=123456789
jarvis --telegram              # or automatically inside --daemon
```

Only whitelisted user ids are served, each chat keeps its own context (`/reset`
clears it), and tools that need confirmation are refused by default — a chat
cannot show a dialog. The bot refuses to start without a whitelist.

## Safety

Full control is powerful, so there are guard rails. See [SECURITY.md](SECURITY.md).

### Permission profiles

| Profile | Shell | Code | Keyboard/mouse | Installing apps | Confirmations |
| --- | --- | --- | --- | --- | --- |
| `safe` | — | — | — | — | yes |
| `dev` (default) | yes | yes | yes | — | yes |
| `yolo` | yes | yes | yes | yes | no |

```bash
jarvis --profile safe        # a read-only assistant
jarvis --profile yolo        # only in a VM
```

- Every risky tool asks for confirmation before running.
- Destructive file actions are journalled and reversible with `undo_last`.
- `--dry-run` shows the plan without touching anything.
- `execution_sandbox.mode: docker|firejail` runs shell and code with no network,
  a memory cap and no access to your home directory.
- `security.allowed_roots` limits the filesystem to chosen folders — desktop
  actions, screenshots and `open_path` obey it too.
- Opening an executable (`.exe`, `.bat`, `.ps1`, `.msi`, …) counts as running
  code and requires `allow_shell`.
- Secrets (`.ssh`, `.aws`, `*.pem`, `.env`, …) are always off limits.
- Catastrophic commands (`rm -rf /`, `mkfs`, `curl | sh`, `Format-Volume`, …) are refused.
- Installing/removing applications is **off by default**.
- Every guarded action is written to `~/.jarvis/audit.log`.
- Kill switches: `JARVIS_ALLOW_SHELL`, `JARVIS_ALLOW_EXEC`, `JARVIS_ALLOW_DESKTOP`,
  `JARVIS_ALLOW_APP_MANAGEMENT`, `JARVIS_ALLOW_NETWORK`.

## Architecture

```
jarvis/
  agent.py         reasoning loop: LLM <-> tools, recall, dry-run, cancellation
  config.py        providers, router, search, security, memory, scheduler, MCP
  security.py      path sandbox, command deny-list, audit log
  journal.py       undo journal: trash, backups, reversible operations
  sandbox.py       docker / firejail execution
  memory.py        conversation history, persistence, context budget
  knowledge.py     long-term semantic memory (SQLite + embeddings)
  scheduler.py     reminders and unattended tasks
  mcp.py           Model Context Protocol client (stdio + HTTP)
  vision.py        screenshots and image understanding
  skills.py        loads user skills (.py and .yaml)
  voice.py         speech-to-text and text-to-speech
  hotkey.py        global shortcuts (pynput / keyboard)
  ui.py            Tkinter window with text + microphone
  tray.py          system tray icon
  telegram_bot.py  Telegram front end
  autostart.py     login item for Windows / macOS / Linux
  daemon.py        background process tying it all together
  cli.py           command line interface, permission profiles, streaming
  llm/             openai (any compatible API), anthropic, ollama, router
  tools/           web, files, undo, shell, apps, desktop, integrations,
                   memory, scheduler, vision, delegation
```

Guides: [Windows 11](docs/windows-11.md) ·
[autonomy features](docs/v0.3-autonomy.md) · [changelog](CHANGELOG.md).

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check jarvis tests
```

CI runs the suite on Ubuntu (3.10–3.12), Windows (3.11, 3.12) and macOS (3.12).

## Roadmap

- Cost and token accounting per provider, with budgets
- Retry with exponential backoff for every network call
- Encrypted secret storage (system keyring) instead of plain `.env`
- Retrieval over your own documents (folders, wikis, PDFs)
- Web UI and a mobile-friendly remote control
- Streaming tool calls, not just streaming prose
- Event triggers: run a skill when a file, window or device state changes
- Signed builds for Windows and macOS, plus a Docker image for the daemon
- Plugin marketplace for skills

## License

MIT — see [LICENSE](LICENSE).
