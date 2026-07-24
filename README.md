# Jarvis

An extensible desktop AI assistant in Python. It talks to any LLM, uses tools to
actually do things on your computer, and can be summoned with a global hotkey by
voice or by text.

```
you> find every TODO in ~/projects, create a report folder and write summary.md
```

## What it can do

| Area | Capabilities |
| --- | --- |
| Internet | `web_search` (DuckDuckGo), `web_fetch` (page text), `http_request` (any REST API) |
| Files | read, write, append, list, `make_directory`, `delete_path`, `move_path`, `copy_path`, `find_files` (with content search) |
| Code | `write_file` + `run_python` + `run_shell` — write code, run it, read the output, iterate |
| Apps | `install_app` / `uninstall_app` (winget, choco, scoop, brew, apt, dnf, pacman, zypper, snap, flatpak), `list_installed_apps` |
| System | `list_processes`, `kill_process`, `system_info` |
| Desktop | `open_path`, `take_screenshot`, `type_text`, `press_hotkey`, `clipboard`, `notify` |
| Skills | your own Python or YAML skills, auto-loaded from `~/.jarvis/skills` |
| Interfaces | terminal REPL, one-shot CLI, desktop window, global hotkey, voice |

## Install

```bash
git clone https://github.com/cloudikapple-cpu/GitHub-Agent.git
cd GitHub-Agent
pip install -e ".[all]"        # or: pip install -e ".[openai,web,desktop,hotkey]"
cp .env.example .env           # put your API key here
cp config.example.yaml config.yaml
```

Linux also needs `python3-tk` for the window, and `notify-send` for notifications.

## Run

```bash
jarvis                          # interactive terminal
jarvis -m "summarise my notes"  # one-shot
jarvis --gui                    # desktop window (text + microphone)
jarvis --voice                  # speak your requests
jarvis --daemon                 # background: hotkey summons the window
jarvis --list-tools             # what it can do right now
jarvis -v                       # show every tool call and result
```

### Global hotkey

With `jarvis --daemon` running, press:

- **Ctrl+Alt+Space** — open the window with the cursor in the input field;
- **Ctrl+Alt+V** — open it and start recording your voice immediately.

Both are configurable (`interface.hotkey`, `interface.voice_hotkey`). macOS needs
Input Monitoring permission for the terminal/app running Jarvis.

## Any custom API

Any OpenAI-compatible endpoint works — OpenRouter, Groq, Together, DeepSeek,
Mistral, Fireworks, LM Studio, vLLM, llama.cpp, or a corporate gateway.

```yaml
# config.yaml
backend: my-gateway

providers:
  my-gateway:
    kind: openai              # openai | anthropic | ollama
    model: llama-3.3-70b
    base_url: https://api.example.com/v1
    api_key: ${MY_TOKEN}      # read from the environment
    headers:                  # any extra headers the provider needs
      X-Title: Jarvis
    temperature: 0.2
    extra_body:               # provider-specific parameters
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

## Safety

Full control is powerful, so there are guard rails. See [SECURITY.md](SECURITY.md).

- Every risky tool asks for confirmation before running.
- `security.allowed_roots` limits the filesystem to chosen folders.
- Secrets (`.ssh`, `.aws`, `*.pem`, `.env`, …) are always off limits.
- Catastrophic commands (`rm -rf /`, `mkfs`, `curl | sh`, `Format-Volume`, …) are refused.
- Installing/removing applications is **off by default**.
- Every guarded action is written to `~/.jarvis/audit.log`.
- Kill switches: `JARVIS_ALLOW_SHELL`, `JARVIS_ALLOW_EXEC`, `JARVIS_ALLOW_DESKTOP`,
  `JARVIS_ALLOW_APP_MANAGEMENT`, `JARVIS_ALLOW_NETWORK`.

`--yolo` disables confirmations and enables app management. Use it only in a VM.

## Architecture

```
jarvis/
  agent.py         reasoning loop: LLM <-> tools
  config.py        providers, security, voice, interface, memory, integrations
  security.py      path sandbox, command deny-list, audit log
  memory.py        conversation history, persistence, context budget
  skills.py        loads user skills (.py and .yaml)
  voice.py         speech-to-text and text-to-speech
  hotkey.py        global shortcuts (pynput / keyboard)
  ui.py            Tkinter window with text + microphone
  daemon.py        background process tying hotkey + window + voice
  cli.py           command line interface
  llm/             openai (any compatible API), anthropic, ollama
  tools/           web, files, shell, apps, desktop, integrations
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check jarvis tests
```

## Roadmap

- Long-term semantic memory (embeddings over your notes and past sessions)
- Scheduler: run skills on a timer or on file/system events
- System tray icon with a proper always-on daemon and autostart
- Streaming replies and interruptible runs
- MCP client support to reuse the whole Model Context Protocol tool ecosystem
- Vision: screenshot understanding for real GUI automation
- Sandboxed execution (Docker/Firejail) for untrusted code
- Multi-agent delegation (planner + workers)

## License

MIT — see [LICENSE](LICENSE).
