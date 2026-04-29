# Changelog

## [3.10.0] - 2026-04-29

### Production hardening + boundary cleanup

No behavior change for the working default chain; just removes the
rough edges.

1. **Selenium / chromedriver-autoinstaller now lazy-imported.** EU
   users on the no-browser path don't need a browser at all, so a
   broken Chrome stack must NOT block them. Imports now sit behind
   try/except; the entry points raise a friendly RuntimeError
   pointing the user at `pip install -r requirements.txt`. The
   default chain, `--version`, and `--help` work even if Chrome is
   uninstallable.

2. **ASCII-safe stdout for all user-facing prints.** Em-dashes and
   en-dashes replaced with ASCII so the script renders correctly
   in classic Windows cmd / older PowerShell terminals where the
   default code page isn't UTF-8.

3. **Stale messaging fixed.** Dynamic probe count via
   `len(PROBE_RUNNERS)`. CLI help text reviewed for accuracy.

4. **Security reminder on token success.** After printing a refresh
   token, the user is reminded the token is password-equivalent
   and must be stored securely.

## Earlier versions

- **3.9.x** — incremental hardening of the default chain and a
  diagnostic mode for verifying every fallback path.
- **3.x** — successive improvements to the no-browser EU path,
  multiple TLS/HTTP profiles, and per-region brand configurations.
- **2.x** — initial Kia/Hyundai region support beyond Europe.
- **1.x** — initial release: Kia EU browser-based OAuth flow.
