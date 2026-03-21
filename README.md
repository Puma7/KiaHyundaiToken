# KiaHyundaiToken

Get your **Kia** or **Hyundai** (EU) OAuth2 refresh token via a one-time
browser login.

> **Note:** Kia EU is tested and confirmed working. Hyundai EU support is
> **experimental** — it is based on community-provided OAuth values and has
> not yet been validated with a real Hyundai account. If you are a Hyundai
> user and it works (or doesn't), please open an issue so we can confirm.

## Why this exists

The Kia and Hyundai EU login flows require solving a Google reCAPTCHA.
Because CAPTCHAs cannot be automated reliably, most API clients (e.g. Home
Assistant integrations) no longer accept your password directly. Instead, you
log in once in a real browser and use the resulting **refresh token**.

> **Security:** Treat your refresh token like a password. Anyone who has it
> can access your Kia account and vehicle data.

## Requirements

- Windows 10 or 11
- [Git for Windows](https://git-scm.com/download/win)
- Google Chrome installed and up to date
- Python 3.10 or newer

No browser extensions are required. **No admin rights needed.**

## Before you start

### Opening PowerShell

1. Press the **Windows key**, type **PowerShell**, and click
   **"Windows PowerShell"** (not "as Administrator" — you do not need admin
   rights).

### One-time setup: allow scripts

On a fresh Windows installation, PowerShell blocks all scripts by default.
You only need to run this **once** — it stays set permanently:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Type **Y** and press Enter when prompted.

### How pasting works

In this guide you will copy a block of commands and paste it into PowerShell.

- **Windows Terminal / new PowerShell:** right-click into the window or press
  `Ctrl+V` to paste.
- **Classic PowerShell (blue window):** right-click into the window to paste.

After pasting, **press Enter once**. All commands run automatically from top
to bottom. At the end a Chrome window will open — that is expected, do not
close it.

## Quick Start

Copy the **entire gray block** below, paste it into PowerShell, and press
Enter. Everything runs automatically until a Chrome window opens for you to
log in.

It is safe to run repeatedly — it will update the code and recreate the
environment each time.

```powershell
# Clone or update the repository
if (Test-Path "$env:TEMP\KiaHyundaiToken") {
    cd "$env:TEMP\KiaHyundaiToken"
    git fetch origin main
    git reset --hard origin/main
} else {
    git clone https://github.com/Puma7/KiaHyundaiToken.git "$env:TEMP\KiaHyundaiToken"
    cd "$env:TEMP\KiaHyundaiToken"
}

# (Re)create a clean virtual environment
deactivate 2>$null
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

After activating a virtual environment, always use **`python`** (not `py`).
`py` may invoke a different Python interpreter than the one inside your venv,
which causes `ModuleNotFoundError` even though you just installed the packages.

### Running again later

Just paste the same block again. It will:
1. Reset to the latest code from `main`
2. Rebuild the virtual environment from scratch (avoids stale packages)
3. Run the script

## What happens after you paste

1. PowerShell downloads the code and installs dependencies (takes a few
   seconds, you don't need to do anything).
2. The script asks you to **select your brand** (Kia or Hyundai). Type `1`
   or `2` and press Enter.
3. A **Chrome window opens automatically** — this is expected. **Do not close
   it.**
4. The login page appears. Log in with your email and password, and solve
   the reCAPTCHA.
5. After login succeeds, the script finishes the OAuth flow automatically.
   Switch back to PowerShell — it will show:
   - **Refresh Token** — use this as your "password" in clients
   - **Access Token** — usually not needed
6. Chrome closes by itself. You are done.

Copy the **Refresh Token** and store it securely (e.g. in a password manager).

## Using the token in Home Assistant

In the Kia UVO / Hyundai Bluelink integration:

| Field    | Value                                    |
|----------|------------------------------------------|
| Region   | EU                                       |
| Brand    | Kia **or** Hyundai (match your choice)   |
| Username | your account email                       |
| Password | the **refresh token** from script output |
| PIN      | only if the integration asks for one     |

## Troubleshooting

### `ModuleNotFoundError: No module named 'selenium.webdriver.common.by'`

Packages were installed into a different Python than the one running the
script. Fix:

```powershell
# Make sure the venv is active, then:
python -m pip show selenium
python -c "import sys; print(sys.executable)"
```

If `pip show` fails or the executable is not inside `.venv`, you need a fresh
environment. Delete the folder and re-clone the repository.

### `No module named pip.__main__`

The venv was created without pip. Fix:

```powershell
python -m ensurepip --upgrade
python -m pip install --upgrade pip
```

### Chrome window does not open

- Make sure Google Chrome is installed and up to date.
- Close all existing Chrome windows and retry.
- Some corporate networks block ChromeDriver downloads; try a home network.

### Login succeeds but no tokens are printed

- Keep the Chrome window visible during the entire flow.
- Complete login fully, including the reCAPTCHA.
- If the script still does not detect the redirect, close everything and
  rerun from a fresh session.

### Network or access errors

- Ensure outbound connections to `prd.eu-ccapi.kia.com:8080` are allowed.
- VPNs, proxies, and firewalls can interfere — try a different network.

### `py` is not recognized

If Python was installed via the **Microsoft Store**, the `py` launcher may
not be available. Replace `py -m venv .venv` in the Quick Start with:

```powershell
python -m venv .venv
```

If neither `py` nor `python` works, Python is not installed or not in your
PATH. Download it from [python.org](https://www.python.org/downloads/) and
make sure to check **"Add Python to PATH"** during installation.

### Script is disabled / execution policy error

If you see *"running scripts is disabled on this system"*, run the one-time
fix from the **Before you start** section above:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### `Remove-Item .venv` fails / "file in use"

An orphaned Python process from a previous crashed run may lock files inside
`.venv`. Close **all** PowerShell windows, then open a fresh one and retry.

### Lost or compromised refresh token

Revoke sessions by signing out of Kia-related apps, then repeat the Quick
Start to generate a new token.
