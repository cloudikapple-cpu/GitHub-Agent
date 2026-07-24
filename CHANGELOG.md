# Changelog

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
