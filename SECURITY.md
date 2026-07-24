# Security

Jarvis can read and write files, run shell commands, execute code, control the
keyboard and install software. Treat it like a second pair of hands on your
machine, and keep the guard rails on.

## Layers of protection

1. **Confirmation.** Every destructive tool sets `requires_confirmation`, so the
   agent must ask before running it. `require_confirmation: false` and `--yolo`
   remove this — only do that in a VM or a container.
2. **Path sandbox.** `security.allowed_roots` restricts every filesystem tool to
   the listed folders. Empty means the whole filesystem.
3. **Secret deny-list.** `~/.ssh`, `~/.gnupg`, `~/.aws`, `*.pem`, `id_rsa*`,
   `.env`, `.git-credentials` and similar paths are refused even inside an
   allowed root.
4. **Command deny-list.** `rm -rf /`, fork bombs, `mkfs`, `dd of=/dev/*`,
   `chmod -R 777 /`, `shutdown`, `curl ... | sh`, `Format-Volume`, `diskpart`
   and friends are rejected before reaching the shell.
5. **Kill switches.** `allow_shell`, `allow_exec`, `allow_desktop`,
   `allow_app_management`, `allow_network` disable whole capability groups.
   App management is **off by default**.
6. **Audit log.** Every guarded action is appended as JSON to
   `~/.jarvis/audit.log`, so you can review what happened.

## Recommended setup for daily use

```yaml
security:
  allowed_roots:
    - ~/projects
    - ~/Documents
  allow_app_management: false
behaviour:
  require_confirmation: true
```

## Things to keep in mind

- **Skills are code.** A skill file runs with your user privileges. Only install
  skills you have read.
- **Prompt injection is real.** A web page or file the agent reads may contain
  instructions. Confirmation prompts are your main defence — read them.
- **Secrets belong in `.env`.** Reference them from `config.yaml` as `${VAR}` so
  tokens never end up in the model's context.
- **Not a sandbox.** The deny-lists reduce accidents; they are not a security
  boundary against a determined attacker. For untrusted work, run Jarvis in a
  container or VM.

## Reporting a vulnerability

Open a GitHub issue with the `security` label, or contact the repository owner
directly for anything sensitive.
