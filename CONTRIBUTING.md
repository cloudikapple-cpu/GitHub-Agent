# Contributing

Thanks for taking the time. Jarvis is a small codebase with a strict security
model, so a couple of rules matter more than usual.

## Setup

```bash
git clone https://github.com/cloudikapple-cpu/GitHub-Agent.git
cd GitHub-Agent
python -m venv .venv && source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install        # optional, runs ruff before each commit
```

## Before you push

```bash
ruff check jarvis tests
pytest -q
```

CI runs the same two commands on Ubuntu 3.10–3.12, Windows 3.11–3.12 and
macOS 3.12. A red CI blocks the merge.

## Adding a tool

1. Subclass `Tool` (or use `FunctionTool`) in a module under `jarvis/tools/`.
2. **Pass the `SecurityPolicy` in and call the matching check** — `check_path`,
   `check_command`, `check_exec`, `check_desktop`, `check_app_management` or
   `check_network`. A tool that touches the machine without a check will not be
   merged.
3. Set `requires_confirmation = True` for anything destructive, and record
   reversible filesystem changes through `Journal`.
4. Register it in `build_default_registry` and give it a `category`.
5. Add a test that proves the tool refuses when the capability is disabled.

If your change only needs to work for you, write a skill instead — see the
README. Skills do not need a pull request.

## Style

- Ruff with `E`, `F`, `I`, `UP`, `B`; line length 100.
- Type hints on public functions, `from __future__ import annotations` at the
  top of every module.
- Optional dependencies are imported lazily inside the function that needs them,
  and a missing one degrades with a warning instead of breaking startup.
- Docstrings and comments in English; commit messages in the imperative mood
  (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `test:`).

## Security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
