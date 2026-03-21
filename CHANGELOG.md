# Changelog

## [2.0.0] - 2026-03-21

### Added
- **Global multi-region support** — Europe, China, Australia, New Zealand,
  India, and Brazil with both Kia and Hyundai where available
- Two-step selection flow: pick your region first, then your brand
- Manual login fallback (press Enter) for regions without a known CSS
  selector for automatic login detection
- Per-region status labels (confirmed / experimental / untested) with
  warnings shown at startup
- Warning message for untested regions when the login page may not render
  in a desktop browser
- Early detection of authorization code (skips Enter prompt if the
  redirect already happened)
- "Contributing new regions" section in README
- "About PINs" section in README explaining that PINs are only needed
  for vehicle commands, not for token retrieval
- Region/brand table in README showing supported combinations
- `.gitignore` to exclude Python bytecode cache

### Changed
- **Breaking:** `BRANDS` dict replaced by nested `REGIONS` dict (region ->
  brand hierarchy)
- `select_brand()` replaced by `select_region_and_brand()` with two-step
  prompts
- User-Agent string is now per-brand (configurable in the REGIONS config)
- Token URL and redirect URL are now explicit per-brand fields instead of
  being derived from a single base URL
- Kia EU login page language changed from German to English
  (`ui_locales=en`)
- README rewritten for multi-region workflow

### Fixed
- Browser now always closes on errors or Ctrl+C (entire driver lifecycle
  wrapped in try/finally)
- Clean Ctrl+C handling (KeyboardInterrupt caught separately)
- Token exchange POST now has a 30-second timeout (prevents infinite hang
  if the server is unresponsive)
- OAuth error detection tightened from `"error"` to `"error="` to avoid
  false positives on URLs containing the word "error" in their path
- Defensive `brand.get("status")` instead of direct dict access
- Clean error message when user closes Chrome manually (no more
  chromedriver stacktrace)
- `driver.quit()` in finally block protected against already-dead session
- Quick Start: `deactivate` no longer shows red error on first run

### Notes
- USA and Canada use a fundamentally different authentication method (direct
  API login without browser). These regions are not yet supported but noted
  in the README.
- Untested regions have credentials sourced from the open-source project
  `hyundai-kia-connect-api`. Community validation is needed.

## [1.3.0] - 2026-03-21

### Fixed
- Replace emoji (checkmark/cross) with ASCII `[OK]`/`[ERROR]` to prevent
  `charmap` codec crash on Windows with legacy code page (cp1252)

### Added
- **Hyundai EU support** (experimental) — script now prompts to select Kia or
  Hyundai at startup, with separate OAuth endpoints per brand
- "Before you start" section in README: how to open PowerShell, one-time
  execution policy fix (`Set-ExecutionPolicy`), how pasting works
- Troubleshooting entries for `py` launcher missing, execution policy error

### Changed
- Brand configuration moved into a `BRANDS` dict for clean multi-brand support
- README updated for dual-brand (Kia + Hyundai EU)
- Clarified that no admin rights are needed

## [1.2.1] - 2026-03-21

### Fixed
- Removed signal handler that caused double `driver.quit()` crash on Ctrl+C
- Separate error messages for login timeout (5 min) vs redirect timeout (20 sec)
- Removed debug print that leaked authorization code to console
- `git pull` replaced with `git fetch + reset --hard` to avoid merge conflicts on re-runs

### Changed
- Git added to Requirements list (was silently required)

### Added
- Troubleshooting entry for locked `.venv` files on Windows

## [1.2.0] - 2026-03-21

### Fixed
- Quick Start now works on repeated runs (clone-or-pull, recreate venv each time)
- Minimum Selenium version bumped to 4.6.0 (required for automatic ChromeDriver management)

### Changed
- Quick Start uses `$env:TEMP\KiaHyundaiToken` as fixed location
- `deactivate` called before recreating venv to avoid Permission Denied errors
- Removed outdated comments about manual chromedriver installation

## [1.1.0] - 2026-03-21

### Fixed
- Wait for OAuth redirect to complete before extracting authorization code
- Use flexible regex for code extraction (fixes crash on changed code format)
- Safer token response handling with `.get()`

### Changed
- README rewritten with corrected Quick Start (`python -m pip`, `ensurepip`, `python` vs `py`)
- Removed unused `webdriver-manager` dependency
- Script renamed from `GetToken` to `get_token.py`
- Quick Start now clones this repo instead of downloading from an external gist

### Added
- `requirements.txt`
- Troubleshooting section in README
- `CHANGELOG.md`

## [1.0.0] - 2026-03-21

### Added
- Initial Selenium-based token fetching script (based on fuatakgun's gist)
- Basic README
