# Changelog

## [3.2.1] - 2026-04-28

### Fixed
- **v3.2.0 was broken on Windows because the curl_cffi 0.15.0
  Windows wheel does not contain the `_android` impersonation
  profiles** (`chrome131_android`, `chrome124_android`, etc.) —
  every probe failed with `"Impersonating chrome124_android is
  not supported"` and the user got no tokens despite valid
  credentials. Two fixes:

  1. **Probe 0 added at the start of the chain**: stdlib `requests`
     + plaintext signin at `/auth/account/signin` with the CCSP
     `client_id`. This is the same code path that worked end-to-end
     in v3.0.0 against a real Kia EU account, and it does not depend
     on curl_cffi at all. So even when the curl_cffi build is broken,
     the script still gets a token.
  2. **TLS impersonation profile fallback**: when a curl_cffi profile
     is unsupported by the local build, `_create_curl_cffi_session`
     now tries the next profile, and the next, ending at no-
     impersonation as a last resort. Profile validity is checked with
     a single trivial HEAD request to kia.com before returning the
     session.

### Changed
- `TLS_IMPERSONATE_POOL` cleaned up: dropped all `_android` and `_ios`
  variants in favor of widely-supported baseline profiles (`chrome`,
  `chrome131`, `chrome124`, `chrome120`, `chrome116`, `safari17_0`,
  `safari17_2_ios`). The `chrome` alias always picks the latest
  available profile in any curl_cffi build.

## [3.2.0] - 2026-04-27

### Added
- **Five-stage fallback chain for the EU direct path.** If one
  endpoint changes or one path gets blocked, the next one takes
  over automatically. Each probe is logged in detail, so a future
  break is easy to diagnose:
  1. **App-flow** — RSA-encrypted password at /auth/account/signin
     with the CCSP client_id (current primary, what the mobile app
     does). Unchanged from v3.1.x.
  2. **Legacy signin** — plaintext password at /auth/account/signin
     with the CCSP client_id. Defensive fallback.
  3. **Marketing → CCSP via cookie reuse** — sign in with the
     marketing OAuth client (kia.com online-sales / Hyundai
     hyundai-europe), then GET the WAF-protected CCSP authorize
     endpoint on the same curl_cffi session. The aws-waf-token
     cookie issued during marketing signin may persuade the WAF
     to let the second request through. Tries both normal and
     `prompt=none` (silent SSO) variants.
  4. **OIDC discovery + ROPC** — fetches /.well-known/openid-
     configuration. If discovery advertises grant_types_supported
     that includes "password", attempts ROPC at the advertised
     token_endpoint. Even when ROPC isn't supported, the discovery
     dump in the debug log reveals new endpoints if Kia adds them.
  5. **Backend Keycloak realm at eu-account.kia.com** — the JWT
     issued by the public IdP fassade has `iss` pointing here. If
     the backend realm is reachable from the public internet (and
     accepts ROPC), this is a clean fully-headless path completely
     independent of the WAF-protected fassade. Speculative; the
     `device_authorization_endpoint` value (if advertised) is
     also captured for a possible future device-flow probe.

  All five probes share a curl_cffi session, randomized User-Agent,
  and randomized TLS impersonation profile. Cookies persist across
  probes within a single run.

### Changed
- `eu_direct_probe` now writes a section header for each probe
  (Probe 1 / Probe 2 / …) into the debug log so the chain is easy
  to follow when troubleshooting.
- Probe 3+ are skipped gracefully when their per-brand config
  fields are missing (e.g. a future brand without
  `marketing_client_id` set).

### Notes
- **Probes 3, 4, 5 are speculative as of this release** — they
  haven't been validated against a real Kia/Hyundai EU account
  because Probes 1+2 are still working. They'll start mattering
  the day Kia changes something. Whichever fires first will tell
  us what Kia changed and which path survived.
- The browser-based fallback (v3.1.1) still kicks in when all
  five direct probes return None.

## [3.1.1] - 2026-04-27

### Added
- **Automatic browser fallback when the EU direct path fails.** If
  both the app-flow and legacy-signin paths return no tokens, the
  script announces the failure, gives the user a 5-second countdown
  to skip with Ctrl+C, then opens Chrome and runs the marketing-
  client login flow as a recovery path. Useful when an endpoint
  changes (the typo theory is wrong) — at least one chance to log
  in before giving up.
- Module-level docstring describing the dual execution paths.
- `__version__` constant.
- Friendly `RuntimeError` with `pip install` hint when `curl_cffi`
  or `pycryptodome` is missing, instead of a raw `ImportError`
  traceback. Wrapped at the call site in `_run_eu_direct` so the
  user sees a clean error message.
- Defensive check in `_fetch_signin_pubkey`: explicitly returns
  `(None, None)` when the JWK response is missing the `n` or `e`
  field, instead of relying on a generic exception catch later.

### Fixed
- `_fetch_signin_pubkey` now logs `kid=(empty)` instead of an
  empty string when the IdP returns a JWK without a key ID
  (cosmetic).

## [3.1.0] - 2026-04-27

### Added
- **Hyundai EU direct-API support.** Same non-browser flow as Kia EU,
  using Hyundai's own endpoints (`idpconnect-eu.hyundai.com`,
  `prd.eu-ccapi.hyundai.com`) and `client_id`. Marked experimental
  pending community validation.
- **TLS impersonation via `curl_cffi`.** Direct-API requests are now
  sent with a real mobile-Chrome / mobile-Safari TLS fingerprint
  (rotated per run from a pool of 5 profiles). Future-proof against
  any TLS-based fingerprinting Kia/Hyundai may add.
- **RSA-encrypted password.** Direct-API signin now fetches the IdP's
  public key from `/auth/api/v1/accounts/certs`, encrypts the
  password with PKCS#1 v1.5, and sends `encryptedPassword=true` —
  exactly like the official mobile app. Future-proof against any
  requirement to encrypt credentials.
- **Cookie priming.** Direct-API flow now does an authorize GET
  before the signin POST to seed session cookies, matching the
  official app's request order.
- **Token validation.** After signin succeeds, the freshly-minted
  refresh_token is immediately used to fetch a new access_token.
  Confirms the token actually works against the CCSP API before the
  user pastes it into Home Assistant.
- **Defensive legacy-signin fallback.** If the modern app-flow fails
  (e.g. JWK endpoint down), falls back to the v3.0.0 un-encrypted
  signin path. Still works today, kept as belt-and-braces.

### Changed
- Direct-API code refactored around a per-brand config dict
  (`KIA_EU_BRAND_CONFIG`, `HYUNDAI_EU_BRAND_CONFIG`) instead of
  hard-coded URLs and constants. Adding a new region/brand means
  adding one dict.
- Diagnostic log header now identifies which brand was attempted.
- Dependencies: added `curl_cffi>=0.7.0` and `pycryptodome>=3.20.0`.

### Removed
- Diagnostic Probes 1, 2b, 3, 4 (ROPC, marketing-client signin,
  CCSP authorize, device-register) and the Stamp HMAC machinery
  that supported them. They never produced tokens — only data
  about which endpoints were alive — and the new architecture has
  the app-flow as primary so the diagnostics are no longer needed.

## [3.0.0] - 2026-04-27

### Added
- **Browserless login flow for Kia EU.** Kia tightened anti-bot
  protection on their EU login servers in late 2025, which made
  the browser-based OAuth flow unreliable. Kia EU users now go
  through a non-browser path that talks to Kia's API directly with
  the same headers their official mobile app sends. End-to-end
  ~10 seconds, no Chrome needed. Constants and request-signing
  algorithm sourced from `hyundai_kia_connect_api`.
- Diagnostic log written to `kia_debug.log` so login failures can
  be debugged from request/response status codes (passwords are
  never logged).
- Rotating User-Agent for Kia EU requests, drawn from a pool of
  current real-world browser strings.

### Changed
- **Routing is now automatic per region/brand.** No more mode
  prompt — Kia EU uses the non-browser path, every other
  region/brand uses the browser flow.

### Removed
- Mode selection prompt (Standard / Stealth / Maximum / Direct
  from v2.x).
- `undetected-chromedriver` dependency and the Stealth/Maximum
  browser code paths that depended on it.

### Fixed
- The Kia EU login failure that affected every user of v2.x is
  the reason this version exists. v3 takes a different route.

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
