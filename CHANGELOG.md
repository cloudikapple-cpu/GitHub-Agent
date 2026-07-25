# Changelog

## 0.3.1

### Fixed

- **Desktop tools ignored the security policy.** `open_path`, `take_screenshot`,
  `type_text` and `press_hotkey` were built without a `SecurityPolicy`, so
  `JARVIS_ALLOW_DESKTOP=false` had no effect. They are now constructed with the
  policy and call `check_desktop()` before doing anything.
- **`open_path` could bypass the shell switch.** Opening a `.exe`, `.bat`,
  `.ps1`, `.msi` (and other executable extensions) is code execution, so it now
  also requires `allow_shell`. Every non-URL target goes through `check_path()`,
  which means `allowed_roots` and the secret deny-list finally apply; URLs
  require `allow_network`.
- **Screenshots** are written to `~/.jarvis/screenshots` through `check_path()`
  instead of a `screenshots/` folder next to the current working directory.

### Added

- **Undo journal** (`jarvis/journal.py`). Deletes move the target into
  `~/.jarvis/trash` instead of destroying it, overwrites are backed up first,
  and moves are recorded. Two new tools — `undo_last` and
  `list_recent_changes` — plus an `undo` command in the REPL.
- **Permission profiles**: `jarvis --profile safe|dev|yolo` replaces juggling
  five `JARVIS_ALLOW_*` variables. `--yolo` is now shorthand for the `yolo`
  profile.
- **Streaming in the terminal**: `interface.stream` (or `--stream` /
  `--no-stream`) prints the reply as it is generated. `Agent.stream()` existed
  since 0.3.0 but nothing called it.
- **Windows 11 guide** (`docs/windows-11.md`) and a `windows` extra that
  installs every desktop dependency in one command.
- Tests for the desktop policy, the undo journal and the profiles.

### Changed

- CI runs on **Windows and macOS** as well as Linux (6 jobs), linting is a
  separate job, coverage is reported, and the actions were bumped to
  `checkout@v5` / `setup-python@v6` (the previous versions run on a deprecated
  Node.js).
- Dependabot keeps pip and GitHub Actions dependencies up to date.
- `build_default_registry` is typed against `Config` and shares one journal
  across every filesystem tool.

## 0.3.0

### Added

- **Internet through Tavily.** `web_search` uses the Tavily API when
  `TAVILY_API_KEY` is set, with an automatic DuckDuckGo fallback; `web_fetch`
  tries Tavily Extract before a plain HTTP fetch. Configurable via the new
  `search` section (`provider`, `max_results`, `depth`, `include_answer`).
- **MCP client** (`jarvis/mcp.py`): stdio and HTTP/SSE transports, every tool of
  every configured server exposed as `{server}_{tool}`.
- **Long-term memory** (`jarvis/knowledge.py`): SQLite vector store with
  `remember` / `recall` / `forget`, provider embeddings or an offline hashing
  embedder, and automatic recall of relevant notes before each run.
- **Reminders and scheduled tasks** (`jarvis/scheduler.py`): `remind_me`,
  `schedule_task`, `list_jobs`, `cancel_job`; one-shot, interval and daily
  schedules in English and Russian; executed by the daemon and persisted to
  `~/.jarvis/jobs.json`.
- **Vision** (`jarvis/vision.py`): `see_screen` and `look_at_image`.
- **Execution sandbox** (`jarvis/sandbox.py`): `run_shell` and `run_python`
  inside Docker or Firejail, network off and memory capped by default.
- **Tray icon** (`jarvis/tray.py`) and **autostart** (`jarvis/autostart.py`) for
  Windows, macOS and Linux via `jarvis --autostart install`.
- **Interruptible runs**: `Agent.cancel()`, a streaming `Agent.stream()` and a
  `stream()` interface on every backend; Ctrl+C stops a REPL run, not the
  process.
- **Provider router** (`jarvis/llm/router.py`): local model first, NVIDIA NIM
  (new built-in `nim` provider) as fallback and for heavy requests.
- **Sub-agent delegation**: the `delegate` tool runs a subtask in a fresh
  context, optionally on another provider, capped at two levels.
- **Dry-run mode**: `jarvis --dry-run` returns the plan and executes nothing.
- **Telegram bot** (`jarvis/telegram_bot.py`): long polling, per-chat context,
  `/reset`, strict user whitelist, confirmations refused by default.
- Tests for the router, search, knowledge base, scheduler, sandbox, Telegram,
  tray and autostart.

### Changed

- `build_default_registry` accepts `backend_factory`, `agent_factory` and
  `depth`, and exposes the shared subsystems on the registry.
- Every optional subsystem degrades with a warning instead of blocking startup.
- README, `config.example.yaml` and `.env.example` rewritten; new feature guide
  in `docs/v0.3-autonomy.md`.

### Fixed

- Quitting from the tray no longer re-enters the shutdown path.
- Telegram configuration is validated before the polling thread starts, so a
  missing token or whitelist is reported instead of dying silently in a thread.
- A failing MCP server or vision dependency can no longer prevent Jarvis from
  starting.
- Recalled notes are folded into the user turn instead of accumulating extra
  system messages in the conversation history.

## 0.2.0

### Added

- **Any custom API.** A `providers` block lets you define unlimited endpoints
  with `base_url`, custom `headers`, `temperature`, `max_tokens` and
  `extra_body`. Works with OpenRouter, Groq, Together, DeepSeek, LM Studio,
  vLLM, llama.cpp and corporate gateways. `register_backend()` adds entirely new
  protocols. New CLI flags: `--model`, `--api-base`, `--api-key`; `-b/--backend`
  now accepts any configured provider name.
- **Security layer** (`jarvis/security.py`): path sandbox (`allowed_roots`),
  secret deny-list, dangerous-command deny-list, per-capability kill switches and
  a JSONL audit log.
- **Full filesystem control**: `make_directory`, `delete_path`, `move_path`,
  `copy_path`, `find_files` (name glob + content search).
- **Application and process management**: `install_app`, `uninstall_app`,
  `list_installed_apps`, `list_processes`, `kill_process`, `system_info` with
  auto-detected package managers (winget, choco, scoop, brew, apt, dnf, pacman,
  zypper, snap, flatpak). Disabled by default.
- **Integrations with other apps**: generic `http_request` tool with named
  services declared in `config.yaml`, plus `clipboard`, `notify` and
  `list_integrations`.
- **Skills**: auto-loaded user extensions from `~/.jarvis/skills` and `./skills`
  — Python tools or YAML prompt macros. A broken skill no longer breaks startup.
- **Voice**: speech-to-text (faster-whisper offline, Google, Vosk) and
  text-to-speech (pyttsx3).
- **Global hotkey**: `Ctrl+Alt+Space` opens the assistant, `Ctrl+Alt+V` opens it
  and starts listening. Backends: pynput or keyboard.
- **Desktop window** (`jarvis --gui`): conversation view, text input, microphone
  button, live tool trace and modal confirmation dialogs.
- **Background daemon** (`jarvis --daemon`) tying hotkeys, window and voice
  together.
- **Persistent memory** with a character budget on top of the message cap.
- `jarvis --list-tools`, `--yolo`, and a `tools` command in the REPL.
- Tests for security, skills, config and memory; GitHub Actions CI running
  pytest and ruff on Python 3.10–3.12.

### Changed

- `run_python` is now gated by its own `allow_exec` switch and asks for
  confirmation.
- Shell commands accept a `cwd` and a configurable timeout.
- Tools carry a `category`, and the registry can describe itself.
- `README`, `.env.example` and `config.example.yaml` rewritten; `SECURITY.md`
  added.

## 0.1.0

- Initial release: agent loop, OpenAI/Anthropic/Ollama backends, web/file/shell/
  desktop tools, conversation memory, terminal CLI.
