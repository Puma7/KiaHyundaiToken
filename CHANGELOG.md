# Changelog

## [3.0.0] - 2026-04-27

### Added
- **Browserless direct-API login for Kia EU.** Kia put their EU IdP
  behind AWS WAF Bot Control in late 2025, which blocks every
  browser-based OAuth flow regardless of stealth tricks (Selenium,
  undetected-chromedriver, real Chrome on the user's own machine —
  all blocked with `error=Bad+Request, classified as abusing
  request`). Kia EU users are now routed to a direct-API path that
  POSTs credentials to `/auth/account/signin` with the CCSP
  client_id, retrieves a code, and exchanges it at the token
  endpoint. End-to-end ~10 seconds, no browser, no WAF interaction.
  Constants (`CCSP_SERVICE_ID`, `APP_ID`, CFB key for the Stamp
  HMAC) sourced from `hyundai_kia_connect_api`.
- Diagnostic log written to `kia_debug.log` for the direct-API path
  so endpoint changes can be debugged from the request/response
  trace (passwords are never logged).

### Changed
- **Routing is now automatic per region/brand.** No more "select
  mode" prompt — Kia EU goes through direct-API, every other
  region/brand goes through the browser flow.

### Removed
- **Mode selection prompt** (Standard / Stealth / Maximum / Direct
  from v2.x). With Direct working for Kia EU and the others not
  helping against WAF, the choice was unnecessary cognitive load.
- **`undetected-chromedriver` dependency**. Used to power the
  Stealth/Maximum browser modes that we now know cannot beat AWS
  WAF Bot Control regardless of stealth depth.
- All Stealth-mode and Maximum-mode browser code paths
  (`_create_stealth_driver`, `_create_maximum_driver`,
  `_navigate_via_click`, `_dump_debug_info`, mobile-UA override).

### Fixed
- The Kia EU "OAuth error … abusing request blocked" failure that
  affected every user of v2.x is the entire reason this version
  exists. v3 routes around it instead of trying to fight WAF.

## [2.1.0] - 2026-03-21

### Added
- **Automatic ChromeDriver management** — chromedriver-autoinstaller
  automatically downloads and installs the correct ChromeDriver version
  matching your installed Chrome. No more manual driver setup.
- **Anti-bot-detection flag** — `--disable-blink-features=AutomationControlled`
  prevents websites from detecting Selenium automation, reducing the chance
  of being blocked during login.
- **Automatic retry on driver failure** — if ChromeDriver fails to start
  (e.g. version mismatch after a Chrome update), the script automatically
  cleans up and reinstalls the correct version before retrying.
- **Safe cleanup guard** — the automatic retry only deletes directories
  that match a ChromeDriver version pattern (e.g. `125.0.6422.78/`),
  preventing accidental deletion of system directories.
- New dependency: `chromedriver-autoinstaller>=0.6.2`

### Changed
- **User-Agent updated** from ancient Chrome 18 (Android) to modern
  Chrome 125 (Windows desktop) for the default User-Agent string. The
  `_CCS_APP_AOS` suffix is preserved. Per-brand overrides (e.g. Brazil's
  iOS User-Agent) are unaffected.
- ChromeOptions are now created via a `_build_chrome_options()` factory
  function, ensuring a fresh instance on each driver start attempt
  (prevents state leaking between retries).
- Driver errors now raise `RuntimeError` instead of calling `sys.exit(1)`,
  so the script is safe to import as a module and the `finally` cleanup
  block always runs.

### Fixed
- Full exception chain preserved (`from e`) in all error paths within
  `install_chromedriver()`, making it possible to debug unexpected
  Chrome detection failures.

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
