"""Allow running the assistant with ``python -m jarvis``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
