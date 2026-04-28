# Changelog

## [3.8.0] - 2026-04-28

### The chain is fully characterized

The v3.7.0 `--debug-all-probes` run gave us the conclusive answer
on Probe 7. The error message — finally extracted thanks to v3.7.0's
deeper diagnostics — was:

```
[Probe 7] Keycloak error: 'recaptcha_failed_v3' (login form re-rendered)
```

The backend Keycloak realm's login form requires a Google reCAPTCHA v3
token (site key `6Ld2GsMrAAAAALfCHMn7fAVEK898yPTFQNYMmNss`). The form
embeds `<input type="hidden" name="g-recaptcha-response">` that must
contain a Google-signed token before submission. Without running
Google's JS in a real browser, we cannot generate that token, and
the backend rejects the POST.

This is by design: every browser-rendered Kia login surface (fassade
AND backend) enforces reCAPTCHA. The only path that doesn't is the
REST API at `/auth/account/signin`, which is what Probes 0-2 use.
That endpoint is exempt from reCAPTCHA because it's designed for the
official mobile app — which has its own attestation (SafetyNet /
Play Integrity) signalling "real device" so reCAPTCHA isn't needed.
Probes 0-2 piggyback on that exemption.

**Probe 7 is now marked HISTORICAL.** The probe chain is complete:

| Probe | Status | Why |
|---|---|---|
| 0 — Plain stdlib signin | **PASS** | REST API at `/auth/account/signin` (no reCAPTCHA, no WAF) |
| 1 — App-flow (curl_cffi + RSA) | **PASS** | Same endpoint as 0, with mobile-app TLS + RSA-encrypted password |
| 2 — Legacy (curl_cffi + plaintext) | **PASS** | Same endpoint, mobile-app TLS, plaintext password |
| 3 — Marketing → CCSP cookie reuse | DEAD | AWS WAF deletes session cookies on CCSP authorize call |
| 4 — OIDC discovery at fassade | DEAD | `/.well-known/openid-configuration` returns 404 |
| 5 — Backend Keycloak ROPC sweep | DEAD | Found 4 existing clients (peukiaidm, account, account-console, admin-cli) — all have ROPC disabled |
| 6 — Device flow at backend | DEAD | Same 4 clients all have device_code grant disabled |
| 7 — Backend authorization_code | DEAD | Backend login form requires Google reCAPTCHA v3 token (`recaptcha_failed_v3`) |

Three working, independent paths (0/1/2). Five fully-characterized
dead ends, each documented with the exact reason and (where useful)
the diagnostic command that revealed it. No further probes planned —
without reverse-engineering the official mobile app's attestation
or paying for a CAPTCHA-solving service, this is the boundary of
what's possible.

### Changed

- `_probe_backend_auth_code` docstring updated to HISTORICAL with
  the concrete reCAPTCHA v3 finding (site key, error code, why
  REST endpoints are exempt).

### Notes

If the day ever comes when:
- Kia adds a new backend client with reCAPTCHA-disabled, OR
- Kia exposes the existing clients' ROPC/device flow grants, OR
- A non-fassade browser flow opens up (e.g. dedicated mobile
  endpoint without challenge),

the existing Probe 5/6/7 code will pick it up automatically the
next time someone runs `--debug-all-probes`. That's the value of
keeping these probes around even when they currently fail — they're
running test cases for any future hardening reversal.

## [3.7.0] - 2026-04-28

### Diagnostic findings from v3.6.0 `--debug-all-probes`

Probe 7's enhanced error extraction (added in v3.6.0) returned no
match in the run, AND `body[:1000]` only captured the page header
(DOCTYPE, head section, OneTrust scripts) — the Keycloak error message
lives much deeper in the form body. So v3.6.0's diagnostic was not
deep enough. v3.7.0 fixes that by:

  1. Searching the **full** response body (not first 1000 chars)
  2. Capturing all `<input type="hidden">` fields from the GET
     response and forwarding them in the POST body
  3. Saving GET and POST HTML to `kia_probe7_get.html` /
     `kia_probe7_post.html` when no error pattern matches, so the
     full response is inspectable
  4. Adding `kc_locale` to the POST data
  5. Logging the GET vs POST body length diff + the POST page title
     as an at-a-glance signal of whether anything changed

### Added

- **Probe 7 hidden-form-field extraction**: any `<input type="hidden">`
  tags in the GET response are parsed and their values forwarded in
  the POST body. Some Keycloak setups embed CSRF tokens, session
  continuations or locale hints there and silently reject POSTs that
  don't echo them back.

- **Probe 7 broader error-message regex**: in addition to the named
  classes (`kc-feedback-text`, `input-error`, `alert-error`,
  `pf-c-form__helper-text`), v3.7.0 also matches any element whose
  `class` contains `feedback`, `alert-error`, or `invalid-feedback`,
  with text length 4-200 chars. Much harder for a custom Keycloak
  theme to slip past.

- **Probe 7 HTML dump**: when no error pattern matches, the GET and
  POST HTML are written to `kia_probe7_get.html` / `kia_probe7_post.html`
  next to `kia_debug.log`. This way the full response is available
  for manual inspection — much more useful than truncating into
  the log.

- **Probe 7 length-diff log**: prints `GET body=X chars, POST body=Y
  chars (diff=±N)` so even without a parsed error message we know
  whether the response shape changed at all (silent rejection ≈ same
  length; embedded error ≈ longer).

- **`kc_locale` field added to POST data**: defaults to `en`, but if
  a hidden `kc_locale` field is in the form, that value takes
  precedence. Some Keycloak setups need this for credential
  validation routing.

### Status of the chain (unchanged)

```
0. Plain stdlib signin                                           [PASS today]
1. App-flow (curl_cffi + RSA)                                    [PASS today]
2. Legacy (curl_cffi + plaintext)                                [PASS today]
3. Marketing → CCSP via cookie reuse                             [Historical, FAIL — WAF]
4. OIDC discovery at fassade                                     [Historical, FAIL — 404]
5. Backend Keycloak ROPC sweep                                   [FAIL — clients exist, ROPC off]
6. Device flow at backend (discovery only)                       [FAIL — device flow off for those]
7. Backend Keycloak authorization_code flow (form-based)         [FAIL — login rejected; v3.7
                                                                  diagnostic should reveal why]
```

The next `--debug-all-probes` run with v3.7 will either:
  (a) extract a Keycloak error message → tells us exactly why login
      is rejected (separate user DB / IdP broker / etc.)
  (b) save full HTML to disk → we can inspect manually

Either way, the next iteration is the LAST one for the backend-realm
chase: the answer will be either "fixable, here's how" or "structurally
not viable, mark probe historical".

## [3.6.0] - 2026-04-28

### Diagnostic findings from v3.5.0 `--debug-all-probes`

The v3.5.0 run with the Probe 6 Accept-header fix and the new Probe 7
gave us a clearer picture of the backend Keycloak realm:

**Probe 6 — device flow init (with `Accept: application/json` fixed):**

```
fdc85c00-...           → 400 invalid_client      (not registered at backend)
peukiaidm-online-sales → 401 unauthorized_client (CLIENT EXISTS, device flow disabled)
account                → 401 unauthorized_client (CLIENT EXISTS, device flow disabled)
account-console        → 400 (HTML — Keycloak rendered the login page)
admin-cli              → 401 unauthorized_client (CLIENT EXISTS, device flow disabled)
... (rest invalid_client) ...
```

So device flow is configured-off for every existing backend client.
Confirms Probe 6 is dead — no path to tokens via device_code grant
without backend reconfig at Kia's end.

**Probe 7 — backend Keycloak `authorization_code` flow:**

```
[Probe 7 — Auth GET] status=200    ← Backend renders Keycloak login form ✓
[Probe 7] login form action: https://eu-account.kia.com/auth/realms/eukiaidm/login-actions/authenticate?session_code=...
[Probe 7 — Login POST] status=200  ← Form re-rendered (= login rejected)
```

The backend `peukiaidm-online-sales` client renders Keycloak's
standard login form (no IdP-broker redirect — good). We POST
credentials and Keycloak re-renders the form, which means our login
was rejected. v3.5.0 truncated the response body to 500 chars so we
couldn't see the actual error message. v3.6.0 fixes that.

### Added

- **Probe 7 Keycloak error extraction**: when the login POST returns
  status 200 (= login form re-rendered with error), the response body
  is parsed for Keycloak's standard error patterns
  (`kc-feedback-text`, `input-error`, `alert-error`,
  `pf-c-form__helper-text`) and the extracted message is logged
  prominently. If no pattern matches, the first 1000 characters of
  the body are dumped so the next iteration can debug what's there.

- **`login` submit-button field added to POST**: Keycloak's login
  form has `<input name="login" value="Sign In">` as the submit
  button. Some Keycloak setups treat a missing `login` field as a
  synthetic submit. Including it doesn't hurt the path that already
  works and may unlock the path that doesn't.

### Status of the chain

```
0. Plain stdlib signin                                           [PASS today]
1. App-flow (curl_cffi + RSA)                                    [PASS today]
2. Legacy (curl_cffi + plaintext)                                [PASS today]
3. Marketing → CCSP via cookie reuse                             [Historical, FAIL — WAF]
4. OIDC discovery at fassade                                     [Historical, FAIL — 404]
5. Backend Keycloak ROPC sweep                                   [FAIL — 4 clients found, ROPC off]
6. Device flow at backend (discovery only)                       [FAIL — device flow off for those 4]
7. Backend Keycloak authorization_code flow (form-based)         [FAIL — login rejected; needs error
                                                                  message extraction (v3.6 just added)
                                                                  for next debug-all run]
```

Three working paths (0, 1, 2) — same as before, very robust.
Probes 5/6/7 are research paths into the backend realm's
authentication, currently dead-ending but better-instrumented now.

The backend realm rejects credentials that the fassade accepts. Two
hypotheses:
  (a) Backend has its own user database (different from fassade's),
      and our user only exists at the fassade.
  (b) Backend's `peukiaidm-online-sales` client is configured to
      delegate authentication to an IdP broker, and the form
      we're hitting is a fallback that's never expected to succeed.

The next `--debug-all-probes` run with v3.6 will show us the actual
Keycloak error message, which will tell us which hypothesis is right.

## [3.5.0] - 2026-04-28

### Diagnostic findings from v3.4.0 `--debug-all-probes`

The v3.4.0 Probe 5 sweep produced a major intermediate finding: the
backend Keycloak realm at `eu-account.kia.com/auth/realms/eukiaidm`
has FOUR known clients registered, all returning `unauthorized_client`
(client EXISTS but ROPC not enabled):

  - `peukiaidm-online-sales` ← marketing client, also lives at backend
  - `account` (Keycloak default)
  - `account-console` (Keycloak default)
  - `admin-cli` (Keycloak default)

ROPC being disabled doesn't kill the path — it just means we need a
different grant type. The standard Keycloak `authorization_code` flow
should still work for those clients (it's the most common Keycloak
client config). Hence Probe 7 (below).

The v3.4.0 Probe 6 sweep all returned "200 but body not JSON" for
every candidate, which was a logging bug (no Accept header → Keycloak
served HTML instead of JSON). Fixed in this release; the body content
is now captured in the log so a similar mystery doesn't recur.

### Added

- **Probe 7 (NEW)**: backend Keycloak realm `authorization_code` flow.
  Uses the marketing `client_id` (since v3.4.0 confirmed it's
  registered at the backend) and goes through the full Keycloak
  login flow:
    1. GET the backend's authorize URL → expect HTML login form
    2. Parse `<form action="…">` from the response
    3. POST username + password to the form action → expect 302 with
       `code=…` in the Location header
    4. Exchange the code at the backend's token endpoint → tokens

  Bails early with a clear log line if the backend authorize redirects
  to the WAF-protected fassade (i.e., the backend delegates login to
  the fassade — that would put us back in WAF territory). Token
  responses from this path have `iss = eu-account.kia.com/auth/realms/
  eukiaidm`, NOT `iss = "uvo"` like the working probes — printed
  warning notes that Home Assistant may need a token translation step.

- **Probe 6 fixed and improved**:
  - Now sends `Accept: application/json` so Keycloak returns proper
    JSON instead of an HTML login page.
  - When a 200 response is still not JSON, the diagnostic log now
    captures `Content-Type` and the first 300 chars of the body so
    a similar mystery is one log read away from solved.

### Notes

The probe chain now has eight independent paths:

```
0. Plain stdlib signin                                           [PASS today]
1. App-flow (curl_cffi + RSA)                                    [PASS today]
2. Legacy (curl_cffi + plaintext)                                [PASS today]
3. Marketing → CCSP via cookie reuse                             [Historical, FAIL]
4. OIDC discovery at fassade                                     [Historical, FAIL — 404]
5. Backend Keycloak ROPC sweep                                   [Currently no JACKPOT, but
                                                                  found 4 EXISTING clients]
6. Device flow at backend (discovery only)                       [Diagnostic; --device-flow
                                                                  for interactive use]
7. Backend Keycloak authorization_code flow (NEW)                [Untested-in-the-wild yet —
                                                                  next debug-all run will tell]
```

Probe 7 is the most promising new addition. If the backend allows the
marketing client to do `authorization_code` (which is overwhelmingly
the default Keycloak client config), the next `--debug-all-probes` run
should turn it from FAIL to PASS. That would give us a fourth working
path — fully WAF-independent.

## [3.4.0] - 2026-04-28

### Diagnostic findings from v3.3.0 `--debug-all-probes`

Run against a real Kia EU account on 2026-04-28 produced this picture
of the chain. We now treat it as the definitive map:

| Probe | Result | What it tells us |
|---|---|---|
| 0 — Plain stdlib signin | PASS | The v3.0 path still works. Battle-tested primary. |
| 1 — App-flow + RSA + curl_cffi | PASS | TMA84-style app-flow also works. Future-proof against Kia ever requiring `encryptedPassword=true`. |
| 2 — Legacy + curl_cffi | PASS | Plaintext signin via curl_cffi works. Survives if plain `requests` ever gets TLS-filtered. |
| 3 — Marketing → CCSP via cookie reuse | FAIL | WAF deletes the marketing-signin cookies (Set-Cookie Max-Age=0) on the next request. Cookie-reuse bypass is not viable. |
| 4 — OIDC discovery at fassade | FAIL | `idpconnect-eu.kia.com/.well-known/openid-configuration` returns 404. Fassade hides discovery. |
| 5 — Backend Keycloak realm | FAIL but ⚠️ INSIGHTFUL | Backend at `eu-account.kia.com/auth/realms/eukiaidm` IS publicly reachable. Discovery returns full metadata advertising `password`, `device_code`, etc. The fassade client_id `fdc85c00...` returns `invalid_client` here — backend has its own client registry. |

### Added

- **Probe 5 enumeration**: now sweeps `BACKEND_CLIENT_CANDIDATES` (a
  list of plausible client_ids — known fassade clients, Keycloak
  defaults, speculative Kia naming patterns) at the backend realm
  and **distinguishes** the failure modes:
  - `invalid_client` → client unknown at backend, try next
  - `unauthorized_client` → client EXISTS but ROPC disabled
  - `invalid_grant` → client EXISTS, ROPC works, just credentials
    rejected — that's a major future-feature pointer
  - `200 + tokens` → JACKPOT, fully WAF-independent path

  The debug log calls out any client that returned `invalid_grant`
  or `unauthorized_client` separately at the bottom, so a future
  contributor can see at a glance what's reachable.

- **Probe 6 (NEW)**: device flow at the backend Keycloak realm.
  The realm advertises `urn:ietf:params:oauth:grant-type:device_code`
  in `grant_types_supported`. Probe 6 in the chain is **discovery-
  only** — it sweeps client_id candidates at
  `device_authorization_endpoint`, logs which ones accept a
  device-code request, but does NOT block waiting for user input.

- **`--device-flow` CLI flag**: explicit interactive mode for
  Probe 6. Uses the same client_id sweep, picks the first usable
  client, prints the verification URL, and polls the token endpoint
  until the user logs in (or 10 min timeout). User authenticates on
  Kia's official Keycloak page — no password sent from this script.
  Tokens come from the backend realm with `iss` = the realm URL,
  not `iss = "uvo"` like the working probes 0-2 — caveat printed
  to user, since Home Assistant may need an `iss = uvo` token.

### Changed

- **Probes 3 and 4 marked HISTORICAL** in their docstrings. They
  do not currently produce tokens and are confirmed not viable as
  bypass paths. Kept in the chain for documentation value, the
  zero-cost-on-success-from-earlier-probe contract, and so the
  debug log makes it easy to confirm Kia's behavior hasn't
  changed.

### Notes

- Probes 0, 1, 2 = three independent **working** paths. Each uses
  different libraries / encryption / TLS profiles, so the
  probability of all three breaking simultaneously is very low.
- Probes 3, 4 = **historical, expected to fail**. They document
  WAF behavior and serve as continuity check.
- Probes 5, 6 = **research paths**. Not currently producing
  tokens, but Probe 5's enumeration logs help future contributors
  who reverse-engineer the official app to find the right backend
  client_id. Adding it to `BACKEND_CLIENT_CANDIDATES` would
  immediately give us a fourth working path.

## [3.3.0] - 2026-04-28

### Added
- **`--debug-all-probes` CLI flag** for Kia/Hyundai EU. Runs every
  probe in the fallback chain (0..5) regardless of which one
  succeeds, each in its own isolated curl_cffi session, and prints a
  PASS/FAIL summary at the end. The point: the fallback chain only
  gives us future-proofness if it actually still works. Without this
  flag, only the first-successful probe (currently always Probe 0)
  is exercised, and probes 1-5 could silently break without anyone
  noticing until Kia changes the primary path. Run this occasionally
  to confirm the chain is intact.

  Usage: `python get_token.py --debug-all-probes`

  Output example (terminal, in addition to the per-probe entries
  in `kia_debug.log`):
  ```
  ============================================================
  DEBUG-ALL probe results
  ============================================================
    Probe 0: [PASS]  Plain stdlib signin (v3.0 method)
    Probe 1: [PASS]  App-flow (curl_cffi + RSA-encrypted password)
    Probe 2: [PASS]  Legacy (curl_cffi + plaintext signin)
    Probe 3: [FAIL]  Marketing → CCSP via cookie reuse
    Probe 4: [FAIL]  OIDC discovery + ROPC
    Probe 5: [FAIL]  Backend Keycloak realm direct ROPC
  ============================================================
  ```

  Each probe runs with a **fresh curl_cffi session** in debug mode
  to avoid Probe 1 leftover cookies polluting Probe 3's cookie-reuse
  experiment, etc. In normal mode, probes share a session — that's
  intentional, because Probe 3 specifically benefits from carrying
  marketing-signin cookies forward.

- `--version` CLI flag (prints the script version).
- `PROBE_RUNNERS` table at module scope so each probe is callable as
  a unit, both for the chained execution and the debug-all flow.

### Changed
- The 6 per-probe code blocks in `eu_direct_probe` are now defined
  via a single `PROBE_RUNNERS` list. Same execution behavior for
  normal mode; just less code duplication.
- New `_finalize_tokens` and `_finalize_code_to_tokens` helpers
  consolidate the validation step.

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
