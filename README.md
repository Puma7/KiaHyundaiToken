# KiaHyundaiToken v3.0.0

Get your **Kia** or **Hyundai** OAuth2 refresh token — worldwide.

## How it works

| Region | Brand | Method |
|---|---|---|
| **Europe** | **Kia** | **Direct API login** — no browser, just email + password in the terminal. Done in ~10 seconds. |
| Europe | Hyundai | One-time browser login (Kia's EU IdP-redirect flow). Experimental. |
| China, Australia, New Zealand, India, Brazil | Kia and/or Hyundai | One-time browser login. Untested — community validation needed. |

Why two methods? In late 2025 Kia put their EU IdP behind **AWS WAF Bot Control**, which blocks every browser-based OAuth flow regardless of stealth tricks. We worked around it by talking to Kia's CCSP backend directly with the same headers their official Android app sends — so for Kia EU users, the script no longer opens a browser at all. For other regions the browser flow still works because they aren't behind WAF Bot Control.

> **USA / Canada:** These regions use a different authentication method (direct API login, no browser required). Most integrations (e.g. Home Assistant) handle authentication directly for these regions — you typically do not need this tool.

> **"Untested"** means the credentials are extracted from the open-source `hyundai_kia_connect_api` project but have not been validated with a real account yet. If you can confirm a region works (or doesn't), please open an issue.

## Security

Treat your **refresh token like a password**. Anyone who has it can access your Kia or Hyundai account and vehicle data (location, lock/unlock, climate, charging) for up to a year. Store it only in a password manager or your Home Assistant secrets file.

For Kia EU's direct mode: your email and password are sent only to Kia's own endpoints (`idpconnect-eu.kia.com`, `prd.eu-ccapi.kia.com`). They are never written to disk in plaintext, never sent to a third party, never logged. The terminal hides your password while you type it.

## Requirements

- Windows 10 or 11 (also works on macOS / Linux with Python)
- [Git for Windows](https://git-scm.com/download/win)
- Python 3.10 or newer
- Google Chrome (only for non-EU regions or Hyundai EU — Kia EU uses no browser)

For browser-based flows, ChromeDriver is installed **automatically** — the script detects your Chrome version and downloads the matching driver on first run.

**No browser extensions required. No admin rights needed.**

## Before you start

### Opening PowerShell

Press the **Windows key**, type **PowerShell**, and click **"Windows PowerShell"** (not "as Administrator" — you do not need admin rights).

### One-time setup: allow scripts

On a fresh Windows installation, PowerShell blocks all scripts by default. You only need to run this **once** — it stays set permanently:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Type **Y** and press Enter when prompted.

### How pasting works

- **Windows Terminal / new PowerShell:** right-click into the window or press `Ctrl+V` to paste.
- **Classic PowerShell (blue window):** right-click into the window to paste.

After pasting, **press Enter once**. All commands run automatically.

## Quick Start

Copy the **entire gray block** below, paste it into PowerShell, and press Enter. Everything runs automatically.

It is safe to run repeatedly — it always resets to a clean state.

```powershell
# Always start fresh — sweeps any broken/partial clone first
if (Test-Path "$env:TEMP\KiaHyundaiToken") {
    Remove-Item -Recurse -Force "$env:TEMP\KiaHyundaiToken"
}
git clone https://github.com/Puma7/KiaHyundaiToken.git "$env:TEMP\KiaHyundaiToken"
cd "$env:TEMP\KiaHyundaiToken"

# (Re)create a clean virtual environment
if (Get-Command deactivate -ErrorAction SilentlyContinue) { deactivate }
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies (always use 'python', not 'py', inside a venv)
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Run
python get_token.py
```

### Why `python` and not `py`?

After activating a virtual environment, always use **`python`** (not `py`). `py` may invoke a different Python interpreter than the one inside your venv, which causes `ModuleNotFoundError` even though you just installed the packages.

## What happens after you paste

1. PowerShell downloads the code and installs dependencies (a few seconds).
2. The script asks you to **select your region**. Type the number and press Enter.
3. The script asks you to **select your brand** (Kia or Hyundai if both available).
4. **For Kia EU:** the script prompts for your **Kia account email and password**, talks directly to Kia's API, and prints your tokens in ~10 seconds. No browser opens.
5. **For other regions:** a Chrome window opens. Log in normally. The script detects login, completes the OAuth flow, and prints your tokens.

Copy the **Refresh Token** and store it securely.

## Using the token in Home Assistant

In the Kia UVO / Hyundai Bluelink integration:

| Field    | Value                                    |
|----------|------------------------------------------|
| Region   | match your selection above               |
| Brand    | Kia **or** Hyundai (match your choice)   |
| Username | your account email                       |
| Password | the **refresh token** from script output |
| PIN      | only if the integration asks for one     |

The PIN is **not needed** by this tool — it is only required by Home Assistant when sending vehicle commands (remote start, climate, lock/unlock).

## Troubleshooting

### Kia EU direct mode says "Could not obtain tokens"

99 % of the time this is a typo in your email or password. Run the script again. The full request/response log is written to `kia_debug.log` in the working directory — passwords are **not** logged. If credentials are correct and it still fails, Kia may have changed an endpoint; please open an issue and attach the log.

### `ModuleNotFoundError: No module named 'selenium...'`

Packages were installed into a different Python than the one running the script. Make sure you activated the venv with `.\.venv\Scripts\Activate.ps1` before running `python -m pip install ...`. The Quick Start block above does this for you — re-run it.

### Chrome window does not open (browser flows only)

- Make sure Google Chrome is installed and up to date.
- Close all existing Chrome windows and retry.
- Some corporate networks block ChromeDriver downloads; try a home network.
- If you see "Google Chrome not found", verify Chrome is in a standard install location.

### `py` is not recognized

If Python was installed via the **Microsoft Store**, the `py` launcher may not be available. Replace `py -m venv .venv` in the Quick Start with:

```powershell
python -m venv .venv
```

If neither `py` nor `python` works, Python is not installed or not in your PATH. Download it from [python.org](https://www.python.org/downloads/) and check **"Add Python to PATH"** during installation.

### Script is disabled / execution policy error

If you see *"running scripts is disabled on this system"*, run the one-time fix from the **Before you start** section above:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Lost or compromised refresh token

Just run the script again — it always issues a fresh token. The old one becomes invalid as soon as the new one is used.

## Contributing

If you are from a region marked "untested", you can help:

1. **Try it.** Run the script, select your region, report whether it works.
2. **Report.** Open a GitHub issue with your region/brand, whether the login page loaded, whether tokens were returned, and any error messages.
3. **CSS selectors.** If the login page works but the script does not detect login automatically (you had to press Enter), inspect the page after login and report a CSS selector that uniquely identifies a post-login element.

If you have a Kia account in a region other than EU and the script's browser flow keeps failing with an "abuse" / WAF error similar to what Kia EU saw, we may need to apply the same direct-API workaround for your region. That requires the brand-specific app constants (Service ID, App ID, CFB key for the Stamp HMAC) — these are in the `hyundai_kia_connect_api` library. Open an issue with your region and we'll wire it up.

## Credits

The Kia EU direct-API workaround uses constants and the Stamp algorithm sourced from the open-source [`hyundai_kia_connect_api`](https://github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api) library. The breakthrough — POSTing credentials to `/auth/account/signin` with `client_id=fdc85c00...` to get a code that the CCSP token endpoint accepts — was discovered while working around AWS WAF Bot Control on `idpconnect-eu.kia.com/auth/api/v2/*`. Sharing this back is the open-source way.
