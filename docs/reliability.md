# Reliability settings (0.3.2)

Four mechanisms protect a long working session: retries, the spend ledger, the
tool-output cap and the daemon lock. Everything is on by default and tunable
through environment variables, so nothing has to be edited in `config.yaml`.

## Retries with exponential backoff

Every outbound HTTP call — Tavily search and extract, DuckDuckGo, page fetching
and all three LLM backends — is repeated when the failure looks transient: a
connection error, a timeout, `429`, or a `5xx`. Permanent failures (`400`,
`401`, `404`) are raised at once, so a wrong API key still fails instantly.

Pauses double and carry jitter: roughly 0.5s, 1s, 2s, capped at 8s.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_RETRY_ATTEMPTS` | `3` | Total attempts; `1` disables retrying |
| `JARVIS_RETRY_BASE_DELAY` | `0.5` | First pause, seconds |
| `JARVIS_RETRY_MAX_DELAY` | `8` | Pause ceiling, seconds |

## Budget and token accounting

Every model call is recorded in `~/.jarvis/usage.json`: calls, prompt tokens,
completion tokens and cost per provider per day. Local models (Ollama, LM
Studio, llama.cpp) are recorded with a cost of zero. Providers that report no
usage are estimated at about four characters per token.

When a daily limit is set, Jarvis warns at 80% and refuses further paid calls
once the limit is reached — the run stops with a clear message instead of
quietly spending money.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_BUDGET_DAILY_USD` | unset | Daily ceiling in dollars |
| `JARVIS_USAGE_LOG` | `~/.jarvis/usage.json` | Ledger location |
| `JARVIS_PRICES` | built-in table | JSON with USD per 1M tokens |

Price override example (PowerShell):

```powershell
$env:JARVIS_PRICES = '{"my-model": [0.5, 1.5]}'
$env:JARVIS_BUDGET_DAILY_USD = "2"
```

The ledger keeps the last 30 days and prunes itself.

## Tool-output cap

`find_files` over a large disk or a chatty `run_shell` could fill the whole
context window in one call. Results longer than the cap keep the first 70% and
the last 30% — the tail matters, because shell output and stack traces put the
verdict last — with a marker in between stating how much was removed.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_MAX_TOOL_RESULT` | `20000` | Characters per tool result; `0` disables the cap |

## Context compaction

When the conversation exceeds `max_messages` or `max_chars`, the oldest turns
leave the window as before — but they are no longer forgotten silently. A short
note stays next to the system prompt: how many messages were trimmed, how the
session started and which tools have already been used.

## One daemon at a time

`jarvis --daemon` takes a PID lock at `~/.jarvis/daemon.lock`. A second daemon
would duplicate every reminder and fight over the global hotkey, so it refuses
to start and says which process already holds the lock. A lock left by a crash
or a reboot is detected as stale and reclaimed automatically.
