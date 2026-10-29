# Security

TGMCP Desk handles Telegram API credentials and login sessions, so security
reports are welcome.

- Please report vulnerabilities privately via GitHub's
  "Report a vulnerability" (Security → Advisories) on this repository instead of
  opening a public issue.
- Never include your `api_hash`, `.session` files, session strings, phone number
  or chat contents in a report. The in-app "导出诊断包" export is redacted, but
  check it before sharing.

What the app does with your data:

- Stores nothing outside telegram-mcp's install directory (`.env`, `*.session`,
  `logs/`) and its own settings file (paths and preferences only).
- Sends nothing anywhere except: downloads from GitHub (uv, telegram-mcp
  releases) and Telegram connections made by telegram-mcp / the login helper
  through your configured proxy. No telemetry.
