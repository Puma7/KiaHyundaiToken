# KiaHyundaiToken

Get your Kia (EU) OAuth2 refresh token via a one-time browser login.

## Why this exists

Kia's EU login flow requires solving a Google reCAPTCHA. Because CAPTCHAs
cannot be automated reliably, most API clients (e.g. Home Assistant
integrations) no longer accept your Kia password directly. Instead, you log
in once in a real browser and use the resulting **refresh token**.

> **Security:** Treat your refresh token like a password. Anyone who has it
> can access your Kia account and vehicle data.

## Requirements

- Windows 10 or 11
- Google Chrome installed and up to date
- Python 3.10 or newer

No browser extensions are required.

## Quick Start

Open **PowerShell** and run these commands in order:

```powershell
# Clone the repository
git clone https://github.com/Puma7/KiaHyundaiToken.git
cd KiaHyundaiToken

# Create and activate a virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Bootstrap and install dependencies (always use 'python', not 'py', inside a venv)
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Verify the environment works
python -c "from selenium.webdriver.common.by import By; import requests; print('environment ok')"

# Run the script
python get_token.py
```

### Important: `python` vs `py`

After activating a virtual environment, always use **`python`** (not `py`).
`py` may invoke a different Python interpreter than the one inside your venv,
which causes `ModuleNotFoundError` even though you just installed the packages.

## What happens

1. A Chrome window opens with the mobile user-agent that Kia expects.
2. Log in to your Kia account and solve the reCAPTCHA manually.
3. After login succeeds, the script completes the OAuth flow and prints:
   - **Refresh Token** — use this as your "password" in clients
   - **Access Token** — usually not needed

Store the refresh token securely (e.g. in a password manager).

## Using the token in Home Assistant

In the Kia UVO / Kia Connect (EU) integration:

| Field    | Value                                    |
|----------|------------------------------------------|
| Region   | EU                                       |
| Brand    | Kia                                      |
| Username | your Kia account email                   |
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

### Lost or compromised refresh token

Revoke sessions by signing out of Kia-related apps, then repeat the Quick
Start to generate a new token.
