# Contributing to Archlot

Thanks for wanting to help. Archlot is a small codebase on purpose, so the bar for
new structure is high and the bar for clear fixes is low.

## Read this first

[`AGENT.md`](AGENT.md) is the single source of truth for code rules: thread
boundaries, policy, message history, tool results, and how to verify a change.
Read it before touching `agent/`, `tools/`, or `ui/`.

## Development setup

Archlot is developed on Arch Linux + niri. To run the full app you need:

```bash
sudo pacman -S --needed python-gobject gtk4 at-spi2-core grim wtype wl-clipboard ffmpeg
sudo usermod -aG input "$USER"   # log out and back in
```

You do not need a running desktop to run the test suite.

## Checks

```bash
python -m compileall -q core agent tools ui archlot.py
python -m unittest discover -s tests -t .
```

Both commands must pass. CI runs the same checks on Python 3.11, 3.12 and 3.13.
Tests that need a live AT-SPI session skip themselves when it is unavailable.

## Rules

- **Keep the dependency direction.** `archlot.py → agent / tools / ui → core`.
  `agent/`, `tools/` and `ui/` must not import each other.
- **GTK only in `ui/`.** `gi.repository.Atspi` is the one approved exception, and
  only in `tools/a11y.py`, on a worker thread.
- **No new dependencies.** The runtime uses the standard library plus PyGObject.
  Do not add pytest, ruff, or a new top-level package.
- **One source of truth per concern.** Policy lives in `tools/policy.py`, history in
  `agent/history.py`, coordinate conversion in one function.
- **Structured tool results.** Return `ToolResult` with an `error_kind`; do not
  collapse "denied" and "failed" into one string.
- **No secrets in the repo.** API keys live in `~/.config/archlot/config.json` or
  `DEEPSEEK_API_KEY`. Never commit a key, token, or personal log.

## Pull requests

- Keep them small and focused. One behavior change per PR.
- Describe what changed and why, and include the command you ran to verify it.
- Add or update a test under `tests/` when behavior changes.
- Match the existing style: conventional commit subjects such as
  `fix(desktop): ...`, `feat(tools): ...`, `docs: ...`.

## Reporting bugs

Open an issue with:

- what you asked Archlot to do,
- what happened instead,
- the relevant lines from `/tmp/archlot-app.log`,
- your compositor and distribution.

Please do not paste API keys, tokens, or private screen contents into an issue.
For security reports, follow [`SECURITY.md`](SECURITY.md) instead.
