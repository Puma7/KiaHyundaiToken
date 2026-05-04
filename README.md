# KiaHyundaiToken

Get your **Kia** or **Hyundai** OAuth2 refresh token — worldwide.

## How it works

| Region | Brand | Method |
|---|---|---|
| **Europe** | **Kia** | **Direct API login** — no browser, just email + password. ~10 seconds. |
| **Europe** | **Hyundai** | **Direct API login** — same flow as Kia. Experimental. |
| China, Australia, New Zealand, India, Brazil | Kia and/or Hyundai | One-time browser login. Untested — community validation needed. |

EU users get tokens directly via the mobile-app API path, so no browser opens. Other regions go through a one-time browser login.

> **USA / Canada:** These regions use a different authentication method (direct API login, no browser required). Most integrations (e.g. Home Assistant) handle authentication directly for these regions — you typically do not need this tool.

> **"Untested"** means the configuration is plausible but not yet validated with a real account. If you can confirm a region works (or doesn't), please open an issue.

## Security

Treat your **refresh token like a password**. Anyone who has it can access your Kia or Hyundai account and vehicle data (location, lock/unlock, climate, charging) for up to a year. Store it only in a password manager or your Home Assistant secrets file.

Credentials are sent over HTTPS to Kia's or Hyundai's own endpoints. They are never written to disk in plaintext, never sent to a third party, never logged (only server response bodies are logged, and the server doesn't echo passwords back). The terminal hides your password while you type it.

## Requirements

- Windows 10 or 11 (also works on macOS / Linux with Python)
- [Git for Windows](https://git-scm.com/download/win)
- Python 3.10 or newer
- Google Chrome (only needed for non-EU regions, or as the recovery fallback if the EU direct path fails — Kia EU and Hyundai EU both use the no-browser direct API by default)

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

## Quick Start Windows

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

## macOS / Linux

The same shell commands work on both macOS and Linux. Copy the entire block below into a terminal and press Enter.

If your system uses `python3` for Python 3 instead of `python`, use `python3` in the commands below.

```bash
# Always start fresh — sweeps any broken/partial clone first
rm -rf /tmp/KiaHyundaiToken
git clone https://github.com/Puma7/KiaHyundaiToken.git /tmp/KiaHyundaiToken
cd /tmp/KiaHyundaiToken

# (Re)create a clean virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (always use 'python', not 'py', inside a venv)
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Run
python get_token.py
```

If `python3` is not available but `python` already points to Python 3, you can use `python -m venv .venv` instead of `python3 -m venv .venv`.

### Why `python` and not `py`?

After activating a virtual environment, always use **`python`** (not `py`). `py` may invoke a different Python interpreter than the one inside your venv, which causes `ModuleNotFoundError` even though you just installed the packages.

## What happens after you paste

1. PowerShell downloads the code and installs dependencies (a few seconds).
2. The script asks you to **select your region**. Type the number and press Enter.
3. The script asks you to **select your brand** (Kia or Hyundai if both available).
4. **For Kia EU:** the script prompts for your **Kia account email and password**, talks directly to Kia's API, and prints your tokens in ~10 seconds. No browser opens.
5. **For other regions:** a Chrome window opens. Log in normally. The script detects login, completes the OAuth flow, and prints your tokens.

If the EU direct path can't get a token (e.g. an endpoint changed), the script offers a **browser-based fallback** automatically: a 5-second countdown, then Chrome opens for a manual login as a recovery path. Press Ctrl+C during the countdown to skip if you know the issue is something else (e.g. a wrong password).

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

### EU direct mode says "Could not obtain tokens"

99 % of the time this is a typo in your email or password. Run the script again. A diagnostic log is written to `kia_debug.log` in the working directory (passwords are not included). If credentials are correct and it still fails, please open an issue and attach the log.

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

Just run the script again — every login issues a fresh token. Old tokens may stay valid for a while in parallel (the IdP doesn't always invalidate them on new issuance), so if you suspect compromise, also change your account password on Kia's/Hyundai's website.

## Contributing

If you are from a region marked "untested", you can help:

1. **Try it.** Run the script, select your region, report whether it works.
2. **Report.** Open a GitHub issue with your region/brand, whether the login page loaded, whether tokens were returned, and any error messages.
3. **CSS selectors.** If the login page works but the script does not detect login automatically (you had to press Enter), inspect the page after login and report a CSS selector that uniquely identifies a post-login element.

If your region's browser flow keeps failing with login errors, please open an issue with the error message and we'll look into adding a no-browser path.

## Credits

Builds on prior open-source work in the Kia/Hyundai connect ecosystem. Thanks to those communities for the groundwork.
