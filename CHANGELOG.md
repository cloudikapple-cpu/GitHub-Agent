# Changelog

## 0.5.0

### Added

- **`jarvis --doctor`** (`jarvis/doctor.py`). Everything needed for a first run
  is checked before anything is constructed: the interpreter, `config.yaml` and
  `.env`, the selected provider with its model and key (or whether Ollama is
  actually listening), the optional packages behind desktop control, hotkeys,
  the tray, voice and web search, the writability of `~/.jarvis`, PowerShell,
  winget, the sandbox binary, and the permissions in force. Warnings mean a
  feature is off; failures mean the assistant cannot work. Every non-passing
  line carries the command that fixes it, and the exit code is 1 while a
  blocking problem remains, so the command belongs in a setup script.
- Fourteen tests for the diagnostics, none of which touch the network or the
  real home folder.

### Changed

- A configuration error at startup now points at `jarvis --doctor` instead of
  printing one line and exiting.
- **The Windows 11 guide matches the code again.** It still described autostart
  as a Startup-folder shortcut, which stopped being true in 0.4.0; it now
  documents the Task Scheduler logon task (including how to inspect it),
  `run_powershell`, clipboard history, toasts, the spend report and the
  preflight check, and adds the troubleshooting entry for `jarvis` not being
  recognised outside the virtual environment.
- **`.env.example` documents the settings that existed only in code**: retry
  attempts and backoff, the tool-result cap, the daily budget, the usage ledger
  and price overrides, the PowerShell path and the toast application id.

## 0.4.2

### Fixed

- **The test suite was red on every platform since 0.4.0.** The trim note added
  in 0.3.2 (a summary of the turns that left the conversation window) was
  prepended to the message list but never counted against `max_chars`, so a
  long session could sit inside its nominal budget while the summary grew past
  it on its own. The note now has a ceiling of a quarter of `max_chars` (never
  below 80 characters) and is included in the trimming loop, so the character
  budget is what the model actually receives.
- `tests/test_agent.py` still asserted the pre-0.3.2 shape of a trimmed
  conversation. It now checks the note explicitly, and a companion test covers
  `compact=False`, where only the window is sent.

### Changed

- **CI explains its own failures.** The pytest output is teed to a log which is
  uploaded as an artifact per OS/Python combination and, on a pull request,
  posted as a comment with the failure summary. Diagnosing a red matrix no
  longer means opening six jobs in the browser.

## 0.4.1

### Added

- **`jarvis --usage`**. The ledger written since 0.3.2 had no way out: the
  numbers existed in `~/.jarvis/usage.json` and nothing displayed them. The flag
  prints today's calls, tokens and dollars per provider, accepts a day
  (`jarvis --usage 2026-07-01`), and works with no config file, no API key and
  no provider. The REPL understands `usage` as well.
- **Streaming in the desktop window.** `Agent.stream()` was wired into the
  terminal in 0.3.1 but the GUI still waited in silence for the whole answer.
  With `interface.stream` (or `--stream`) the window now renders the reply as it
  arrives; the daemon passes the same setting through.
- Tests for the CLI surface: the usage report, the permission profiles and the
  new flags.

### Changed

- `jarvis/ui.py` imports `Callable` from `collections.abc`, the first module of
  the `UP035` migration.
- README documents `run_powershell`, the clipboard history, the Task Scheduler
  autostart and the usage report; the roadmap drops what 0.3.2 and 0.4.0
  delivered.

## 0.4.0

### Added

- **`run_powershell`** (`jarvis/tools/powershell.py`). `run_shell` only reaches
  `cmd.exe` on Windows, which leaves out services, the registry, scheduled
  tasks, winget queries and every cmdlet returning objects. The new tool runs
  scripts with `-NoProfile` and `-EncodedCommand`, behind the same
  `SecurityPolicy` gate as the shell.
- **Windows 11 toasts with buttons** (`jarvis/windows.py`). Notifications go
  through the WinRT notification manager, so they land in the Notification
  Centre and can offer an action such as 'Open the folder'. The deprecated tray
  balloon is kept only as a fallback.
- **Clipboard history** (`jarvis/clipboard.py`). A 50-item ring buffer in
  `~/.jarvis/clipboard.json`, filled by the daemon and by the `clipboard` tool
  itself, with `history` and `clear_history` actions.
- **Hotkey conflict detection**. The daemon asks Windows whether a shortcut is
  already owned by another application and says so, instead of starting a
  listener that will never fire.
- **Windows control guide** (`docs/windows-control.md`).
- Tests for the Windows helpers, the PowerShell tool, the clipboard history and
  the new autostart (119 → 151 tests).

### Changed

- **Autostart on Windows is a Task Scheduler logon task**, not a Startup
  shortcut: no console window (`pythonw.exe`), a 30-second delay so Explorer is
  ready before the hotkey is claimed, three automatic restarts after a crash,
  and immunity to the Startup tab's 'Disable' switch. If `schtasks` refuses,
  the Startup shortcut is written as a fallback and the reason is reported.
- **Notification arguments can no longer break the command.** Titles and bodies
  used to be interpolated into a PowerShell string, so an apostrophe in a
  reminder broke it; every string is now passed base64-encoded.

## 0.3.2

### Added

- **Retries with exponential backoff** (`jarvis/retry.py`). Every outbound HTTP
  call — Tavily search and extract, DuckDuckGo, page fetching and the OpenAI,
  Anthropic and Ollama backends — is repeated on connection errors, timeouts,
  `429` and `5xx`, with jittered pauses capped at eight seconds. Permanent
  failures such as `401` still fail instantly. Tunable with
  `JARVIS_RETRY_ATTEMPTS`, `JARVIS_RETRY_BASE_DELAY` and `JARVIS_RETRY_MAX_DELAY`.
- **Budget and token accounting** (`jarvis/budget.py`). Each model call is
  metered into `~/.jarvis/usage.json` per provider and per day, with a built-in
  price table (overridable through `JARVIS_PRICES`) and free local providers.
  `JARVIS_BUDGET_DAILY_USD` warns at 80% and blocks paid calls at 100%.
- **Single-instance lock** (`jarvis/singleton.py`). A second `jarvis --daemon`
  used to duplicate every reminder and fight over the global hotkey; it is now
  refused, and a lock left by a crash is reclaimed automatically.
- **Reliability guide** (`docs/reliability.md`).
- Tests for the retry helper, the ledger, the output cap and the daemon lock
  (93 → 119 tests).

### Changed

- **Tool results are capped** at `JARVIS_MAX_TOOL_RESULT` characters (default
  20000, `0` disables). Oversized output keeps its head and its tail, because
  shell output and stack traces put the verdict last.
- **Trimmed context is summarised.** Turns leaving the conversation window now
  leave a short note next to the system prompt — how many messages were cut,
  how the session started, which tools were already used — instead of vanishing
  silently.
- `ToolRegistry` logs a warning when a skill shadows a built-in tool name,
  which used to happen silently and cost hours of debugging.

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
