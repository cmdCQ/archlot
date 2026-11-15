# Security Policy

Archlot is a local agent with the same privileges as your user account. It can run
shell commands, move the pointer, type, read files, and take screenshots. Treat the
model's output as untrusted input, and treat the machine it runs on as the security
boundary.

## Supported versions

Only the latest `main` is supported. There are no maintained release branches yet.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Choose **Advisories** → **Report a vulnerability**.
3. Include reproduction steps, affected files, and the impact you expect.

Do not open a public issue for a security problem, and do not include live API keys,
tokens, or private screen contents in a report.

## What is in scope

- Policy bypass: a dangerous command or action that runs without the expected
  confirmation in `tools/policy.py`.
- Credential exposure: the API key or another secret being logged, sent to the model,
  written to memory, or committed.
- Prompt-injection paths that turn untrusted screen or file content into actions the
  user did not intend.
- Path traversal or workspace escape in the file tools.
- Unsafe handling of AT-SPI, `uinput`, or subprocess input.

## What is not in scope

- An agent that follows a user's explicit instruction to run a destructive command
  after the confirmation dialog. That is the documented behavior.
- Vulnerabilities in third-party applications that Archlot controls through AT-SPI or
  the pointer.
- Models producing wrong answers or imperfect click coordinates. Those are quality
  bugs; open a normal issue.

## Design notes

- The API key stays in `~/.config/archlot/config.json` or `DEEPSEEK_API_KEY`. Only the
  model request leaves the machine.
- `sudo`, `mkfs`, `dd`, shutdown, package removal and system-directory deletion are
  classified as confirm-or-deny in `tools/policy.py`.
- Tool results carry an `error_kind` so a denial is never silently treated as success.
- Adaptive reasoning effort is off by default and visible when enabled.

Reports are handled on a best-effort basis. Please give a reasonable window before
public disclosure.
