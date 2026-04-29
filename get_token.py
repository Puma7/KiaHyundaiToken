"""
KiaHyundaiToken — get a Kia or Hyundai OAuth2 refresh token.

Two execution paths, picked automatically by region + brand:
  * Kia EU / Hyundai EU: browserless direct-API login. POSTs the
    user's credentials (RSA-encrypted) to the IdP's /auth/account/signin
    endpoint with the official mobile-app's TLS fingerprint, exchanges
    the resulting code for tokens, validates the result. ~10 seconds.
  * All other regions: existing Selenium-based one-time browser login.

If the EU direct path fails (e.g. an IdP endpoint changes), the
browser flow is offered as an automatic fallback so the user always
gets at least one chance to recover.

See README for usage and CHANGELOG for version history.
"""

__version__ = "3.9.0"

import argparse
import base64
import datetime as dt
import getpass
import os
import random
import re
import shutil
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import requests
import chromedriver_autoinstaller

session = requests.Session()

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36_CCS_APP_AOS"
)

# Pool of plausible real-world browser User-Agents. The Direct probe
# picks one at random per run so a sequence of users can't be trivially
# fingerprinted as "all coming from the same tool". Not an evasion
# tactic — a real user logging in from a different device every time
# would also rotate. Mix of recent Chrome/Firefox/Safari/Edge across
# Windows, macOS, Linux, Android, iOS.
BROWSER_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36",
]

DEBUG_LOG_FILE = "kia_debug.log"

# ---------------------------------------------------------------------------
# Region and brand configurations
#
# Each brand entry contains:
#   name              – display name
#   status            – "confirmed" | "experimental" | "untested"
#   client_id         – OAuth client ID for the token exchange
#   client_secret     – OAuth client secret for the token exchange
#   login_url         – URL opened in the browser for the user to log in
#   token_url         – endpoint for the authorization-code -> token exchange
#   success_selector  – CSS selector that appears after a successful login,
#                       or None (manual Enter fallback)
#   redirect_url_final – redirect_uri registered with the OAuth server
#   redirect_url      – (EU only) separate authorize URL navigated to AFTER
#                       login in order to obtain the authorization code.
#                       When absent the login page itself redirects to
#                       redirect_url_final?code=... after login.
#   user_agent        – User-Agent string for the browser session
#
# Credential sources:
#   EU     – tested / community-provided
#   Others – extracted from github.com/Hyundai-Kia-Connect/hyundai_kia_connect_api
# ---------------------------------------------------------------------------

REGIONS = {
    "1": {
        "name": "Europe",
        "brands": {
            "1": {
                "name": "Kia",
                "status": "confirmed",
                "client_id": "fdc85c00-0a2f-4c64-bcb4-2cfb1500730a",
                "client_secret": "secret",
                "login_url": (
                    "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/authorize"
                    "?ui_locales=en&scope=openid%20profile%20email%20phone&response_type=code"
                    "&client_id=peukiaidm-online-sales"
                    "&redirect_uri=https://www.kia.com/api/bin/oneid/login"
                    "&state=aHR0cHM6Ly93d3cua2lhLmNvbTo0NDMvZGUvP21zb2NraWQ9MjM1NDU0ODBm"
                    "NmUyNjg5NDIwMmU0MDBjZjc2OTY5NWQmX3RtPTE3NTYzMTg3MjY1OTImX3RtPTE3"
                    "NTYzMjQyMTcxMjY=_default"
                ),
                "token_url": "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/token",
                "success_selector": "a[class='logout user']",
                "redirect_url_final": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
                "redirect_url": (
                    "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=fdc85c00-0a2f-4c64-bcb4-2cfb1500730a"
                    "&redirect_uri=https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect"
                    "&lang=en&state=ccsp"
                ),
                "user_agent": DEFAULT_USER_AGENT,
            },
            "2": {
                "name": "Hyundai",
                "status": "experimental",
                "client_id": "6d477c38-3ca4-4cf3-9557-2a1929a94654",
                "client_secret": "KUy49XxPzLpLuoK0xhBC77W6VXhmtQR9iQhmIFjjoY4IpxsV",
                "login_url": (
                    "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/authorize"
                    "?client_id=peuhyundaiidm-ctb"
                    "&redirect_uri=https%3A%2F%2Fctbapi.hyundai-europe.com%2Fapi%2Fauth"
                    "&nonce=&state=PL_&scope=openid+profile+email+phone&response_type=code"
                    "&connector_client_id=peuhyundaiidm-ctb"
                    "&connector_scope=&connector_session_key=&country=&captcha=1"
                    "&ui_locales=en-US"
                ),
                "token_url": "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/token",
                "success_selector": "button.mail_check",
                "redirect_url_final": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
                "redirect_url": (
                    "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=6d477c38-3ca4-4cf3-9557-2a1929a94654"
                    "&redirect_uri=https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token"
                    "&lang=en&state=ccsp"
                ),
                "user_agent": DEFAULT_USER_AGENT,
            },
        },
    },
    "2": {
        "name": "China",
        "brands": {
            "1": {
                "name": "Kia",
                "status": "untested",
                "client_id": "9d5df92a-06ae-435f-b459-8304f2efcc67",
                "client_secret": "tsXdkUg08Av2ZZzXOgWzJyxUT6yeSnNNQkXXPRdKWEANwl1p",
                "login_url": (
                    "https://prd.cn-ccapi.kia.com/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=9d5df92a-06ae-435f-b459-8304f2efcc67"
                    "&redirect_uri=https://prd.cn-ccapi.kia.com:443/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://prd.cn-ccapi.kia.com/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://prd.cn-ccapi.kia.com:443/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
            "2": {
                "name": "Hyundai",
                "status": "untested",
                "client_id": "72b3d019-5bc7-443d-a437-08f307cf06e2",
                "client_secret": "secret",
                "login_url": (
                    "https://prd.cn-ccapi.hyundai.com/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=72b3d019-5bc7-443d-a437-08f307cf06e2"
                    "&redirect_uri=https://prd.cn-ccapi.hyundai.com:443/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://prd.cn-ccapi.hyundai.com/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://prd.cn-ccapi.hyundai.com:443/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
        },
    },
    "3": {
        "name": "Australia",
        "brands": {
            "1": {
                "name": "Kia",
                "status": "untested",
                "client_id": "8acb778a-b918-4a8d-8624-73a0beb64289",
                "client_secret": "7ScMMm6fEYXdiEPCxaPaQmgeYdlUrfwoh4AfXGOzYIS2Cu9T",
                "login_url": (
                    "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=8acb778a-b918-4a8d-8624-73a0beb64289"
                    "&redirect_uri=https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
            "2": {
                "name": "Hyundai",
                "status": "untested",
                "client_id": "855c72df-dfd7-4230-ab03-67cbf902bb1c",
                "client_secret": "e6fbwHM32YNbhQl0pviaPp3rf4t3S6k91eceA3MJLdbdThCO",
                "login_url": (
                    "https://au-apigw.ccs.hyundai.com.au:8080/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=855c72df-dfd7-4230-ab03-67cbf902bb1c"
                    "&redirect_uri=https://au-apigw.ccs.hyundai.com.au:8080/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://au-apigw.ccs.hyundai.com.au:8080/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://au-apigw.ccs.hyundai.com.au:8080/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
        },
    },
    "4": {
        "name": "New Zealand",
        "brands": {
            "1": {
                "name": "Kia",
                "status": "untested",
                "client_id": "4ab606a7-cea4-48a0-a216-ed9c14a4a38c",
                "client_secret": "0haFqXTkKktNKfzkxhZ0aku31i74g0yQFm5od2mz4LdI5mLY",
                "login_url": (
                    "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=4ab606a7-cea4-48a0-a216-ed9c14a4a38c"
                    "&redirect_uri=https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://au-apigw.ccs.kia.com.au:8082/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
        },
    },
    "5": {
        "name": "India",
        "brands": {
            "1": {
                "name": "Kia",
                "status": "untested",
                "client_id": "d0fe4855-7527-4be0-ab6e-a481216c705d",
                "client_secret": "SHoTtXpyfbYmP3XjNA6BrtlDglypPWj920PtKBJPfleHEYpU",
                "login_url": (
                    "https://prd.in-ccapi.kia.connected-car.io:8080/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=d0fe4855-7527-4be0-ab6e-a481216c705d"
                    "&redirect_uri=https://prd.in-ccapi.kia.connected-car.io:8080/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://prd.in-ccapi.kia.connected-car.io:8080/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://prd.in-ccapi.kia.connected-car.io:8080/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
            "2": {
                "name": "Hyundai",
                "status": "untested",
                "client_id": "e5b3f6d0-7f83-43c9-aff3-a254db7af368",
                "client_secret": "5JFOCr6C24OfOzlDqZp7EwqrkL0Ww04UaxcDiE6Ud3qI5SE4",
                "login_url": (
                    "https://prd.in-ccapi.hyundai.connected-car.io:8080/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=e5b3f6d0-7f83-43c9-aff3-a254db7af368"
                    "&redirect_uri=https://prd.in-ccapi.hyundai.connected-car.io:8080/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://prd.in-ccapi.hyundai.connected-car.io:8080/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://prd.in-ccapi.hyundai.connected-car.io:8080/api/v1/user/oauth2/redirect",
                "user_agent": DEFAULT_USER_AGENT,
            },
        },
    },
    "6": {
        "name": "Brazil",
        "brands": {
            "1": {
                "name": "Hyundai",
                "status": "untested",
                "client_id": "03f7df9b-7626-4853-b7bd-ad1e8d722bd5",
                "client_secret": "yQz2bc6Cn8OovVOR7RDWwxTqVwWG3yKBYFDg0HsOXsyxyPlH",
                "login_url": (
                    "https://br-ccapi.hyundai.com.br/api/v1/user/oauth2/authorize"
                    "?response_type=code"
                    "&client_id=03f7df9b-7626-4853-b7bd-ad1e8d722bd5"
                    "&redirect_uri=https://br-ccapi.hyundai.com.br/api/v1/user/oauth2/redirect"
                ),
                "token_url": "https://br-ccapi.hyundai.com.br/api/v1/user/oauth2/token",
                "success_selector": None,
                "redirect_url_final": "https://br-ccapi.hyundai.com.br/api/v1/user/oauth2/redirect",
                "user_agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
                ),
            },
        },
    },
}

STATUS_LABELS = {
    "confirmed": "",
    "experimental": " -- experimental",
    "untested": " -- untested, community validation needed",
}


def _build_chrome_options(user_agent):
    """Create a fresh ChromeOptions instance with anti-detection flags."""
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument(f"user-agent={user_agent}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # Kia EU's IdP fingerprints these Selenium markers and classifies the
    # CCSP authorize request as an "abusing request". Hide them.
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    return chrome_options


def _apply_stealth(driver):
    """Hide remaining Selenium markers via CDP overrides."""
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                )
            },
        )
    except WebDriverException:
        # CDP is best-effort; not fatal if the driver doesn't support it.
        pass


def install_chromedriver():
    """Install a matching chromedriver. Raises RuntimeError on failure."""
    try:
        chromedriver_autoinstaller.get_chrome_version()
    except Exception as e:
        raise RuntimeError(
            "Google Chrome not found. "
            "Please install Google Chrome and try again."
        ) from e
    try:
        return chromedriver_autoinstaller.install()
    except Exception as e:
        raise RuntimeError(f"Failed to install chromedriver: {e}") from e


def _is_safe_to_delete(driver_path):
    """Only allow deletion of chromedriver-autoinstaller managed directories."""
    driver_dir = os.path.dirname(os.path.abspath(driver_path))
    # chromedriver-autoinstaller installs into a versioned subdirectory
    # e.g. /home/user/.../125.0.6422.78/chromedriver
    # Only delete if the directory name looks like a Chrome version number
    dirname = os.path.basename(driver_dir)
    return bool(re.match(r"^\d+\.\d+\.\d+(\.\d+)?$", dirname))


def _chrome_major_version():
    """Return the installed Chrome major version (e.g. 125), or None.
    Used by undetected-chromedriver to download the matching driver."""
    try:
        full = chromedriver_autoinstaller.get_chrome_version()
        return int(full.split(".")[0])
    except Exception:
        return None


def _create_standard_driver(user_agent):
    """Standard Selenium + chromedriver-autoinstaller path."""
    driver_path = install_chromedriver()

    try:
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=_build_chrome_options(user_agent))
        driver.maximize_window()
        _apply_stealth(driver)
        return driver
    except WebDriverException:
        # Clean up broken install and retry once — only if path is safe
        if _is_safe_to_delete(driver_path):
            try:
                shutil.rmtree(os.path.dirname(os.path.abspath(driver_path)))
            except OSError:
                pass

        try:
            driver_path = chromedriver_autoinstaller.install()
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=_build_chrome_options(user_agent))
            driver.maximize_window()
            _apply_stealth(driver)
            return driver
        except Exception as e:
            raise RuntimeError(
                f"Could not start Chrome after reinstall: {e}"
            ) from e


def _safe_truncate(value, limit=80):
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def create_driver(user_agent):
    """
    Install chromedriver and start Chrome with anti-detection flags.
    Raises RuntimeError if Chrome cannot be started.
    """
    return _create_standard_driver(user_agent)


def select_region_and_brand():
    print("Select your region:\n")
    region_keys = list(REGIONS.keys())
    for key in region_keys:
        region = REGIONS[key]
        brand_names = ", ".join(b["name"] for b in region["brands"].values())
        print(f"  {key}) {region['name']}  ({brand_names})")
    print()

    while True:
        choice = input(f"Enter region (1-{len(region_keys)}): ").strip()
        if choice in REGIONS:
            break
        print("Invalid choice.")

    region = REGIONS[choice]
    print(f"\n-> {region['name']} selected.\n")

    brands = region["brands"]
    if len(brands) == 1:
        brand = next(iter(brands.values()))
        print(f"-> {brand['name']} (only available brand for this region).\n")
    else:
        print("Select your brand:\n")
        for key, brand_cfg in brands.items():
            label = STATUS_LABELS.get(brand_cfg["status"], "")
            print(f"  {key}) {brand_cfg['name']}{label}")
        print()
        while True:
            choice = input(f"Enter brand (1-{len(brands)}): ").strip()
            if choice in brands:
                break
            print("Invalid choice.")
        brand = brands[choice]
        print(f"\n-> {brand['name']} selected.\n")

    status = brand.get("status", "untested")
    if status == "untested":
        print("=" * 60)
        print("WARNING: This region/brand combination has not been")
        print("validated yet. It may or may not work. If you can confirm")
        print("it works (or report issues), please open an issue on GitHub.")
        print("=" * 60 + "\n")
    elif status == "experimental":
        print("=" * 60)
        print("NOTE: This brand is experimental. It is based on")
        print("community-provided values and has not been fully validated.")
        print("=" * 60 + "\n")

    return region, brand


# ---------------------------------------------------------------------------
# Kia EU Direct-API constants (sourced from hyundai_kia_connect_api HEAD).
# These mimic the official Android app. Values verbatim from
# hyundai_kia_connect_api (HEAD) and bluelink-refresh-token.
# ---------------------------------------------------------------------------

# Per-brand EU configuration. Both Kia and Hyundai EU use the same
# OAuth flow shape — only host names, IDs, and the redirect URI differ.
KIA_EU_BRAND_CONFIG = {
    "name": "Kia EU",
    "host": "https://idpconnect-eu.kia.com",
    "client_id": "fdc85c00-0a2f-4c64-bcb4-2cfb1500730a",
    "client_secret": "secret",
    "redirect_uri": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
    "token_url": "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/token",
    # Marketing client used by Probe 3 (cookie-priming via the kia.com
    # online-sales OAuth client). Same IdP host but a different OAuth
    # client; signin against this client returns a code redirected to
    # kia.com — discarded — but the IdP session cookies stay on the
    # session and let us then attempt the CCSP authorize endpoint.
    "marketing_client_id": "peukiaidm-online-sales",
    "marketing_redirect_uri": "https://www.kia.com/api/bin/oneid/login",
    # Backend realm host for Probe 5 (Keycloak realm hidden behind the
    # public-facing IdP fassade). Sourced from the JWT iss field of
    # tokens issued by Probes 1-3.
    "backend_realm_url": "https://eu-account.kia.com/auth/realms/eukiaidm",
}

HYUNDAI_EU_BRAND_CONFIG = {
    "name": "Hyundai EU",
    "host": "https://idpconnect-eu.hyundai.com",
    "client_id": "6d477c38-3ca4-4cf3-9557-2a1929a94654",
    # Hyundai's secret is a real value (Kia's is literally "secret"),
    # publicly known via the open-source community.
    "client_secret": "KUy49XxPzLpLuoK0xhBC77W6VXhmtQR9iQhmIFjjoY4IpxsV",
    # Hyundai redirect ends in /token, Kia ends in /redirect — gotcha.
    "redirect_uri": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
    "token_url": "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/token",
    "marketing_client_id": "peuhyundaiidm-ctb",
    "marketing_redirect_uri": "https://ctbapi.hyundai-europe.com/api/auth",
    # Mirror of the Kia backend-realm naming convention; not yet
    # confirmed against a Hyundai JWT iss field, so Probe 5 may
    # NXDOMAIN here. Logged as "no result" if so.
    "backend_realm_url": "https://eu-account.hyundai.com/auth/realms/euhyundaiidm",
}

# Pool of TLS impersonation profiles for curl_cffi. We keep this list
# to widely-supported baseline profiles (no `_android` suffix) because
# specific mobile/version variants only exist in some curl_cffi build
# combinations. The Windows wheel of curl_cffi 0.15.0, for example,
# rejects `chrome124_android` even though Linux 0.15.0 accepts it.
# `chrome` is the safest — it's an alias for "latest available" and
# always present.
TLS_IMPERSONATE_POOL = [
    "chrome",
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome116",
    "safari17_0",
    "safari17_2_ios",
]


# ---------------------------------------------------------------------------
# Client-ID candidates for Probe 5 (backend Keycloak realm) and Probe 6
# (device flow). Enumerated because the v3.3.0 debug-all run proved that
# the backend realm at eu-account.kia.com IS publicly reachable AND
# advertises grant_types_supported = [..., 'password', 'device_code', ...],
# but the public-fassade client_id "fdc85c00..." gets rejected with
# "invalid_client". The backend realm has its own client registry,
# distinct from what the fassade exposes. So we sweep a list of
# plausible client_ids:
#
#   - The known fassade client (current v3.3.0 default — known to fail
#     with "invalid_client" at the backend, included here for the
#     summary log).
#   - Marketing client (works at fassade for browser logins).
#   - Default Keycloak public clients (`account`, `account-console`,
#     `admin-cli`) — these always exist in any Keycloak realm and
#     sometimes have direct-grants enabled.
#   - Speculative names following Kia naming conventions (kia-connect,
#     kia-app, eukiaidm-connect-app, etc.).
#
# Each entry is (client_id, client_secret). secret=None means "public
# client, do not send client_secret". A "200 with tokens" on any
# combination is a Jackpot — fully WAF-bypassing path. An
# "invalid_grant" instead of "invalid_client" tells us a client EXISTS
# at the backend but the password we sent didn't validate — that's
# also a major finding and goes prominently into the log.
# ---------------------------------------------------------------------------
BACKEND_CLIENT_CANDIDATES = [
    # (client_id, client_secret, comment)
    ("fdc85c00-0a2f-4c64-bcb4-2cfb1500730a", "secret",
     "fassade CCSP client (known to fail at backend, kept for record)"),
    ("peukiaidm-online-sales", None,
     "fassade marketing client (try at backend without secret)"),
    ("account", None,
     "Keycloak default account console client"),
    ("account-console", None,
     "Keycloak default account console client (newer naming)"),
    ("admin-cli", None,
     "Keycloak default admin-cli (rarely has direct grants but cheap to try)"),
    ("kia-connect", None,
     "speculative — mobile app naming"),
    ("kia-connect-app", None,
     "speculative — mobile app naming"),
    ("eukiaidm-connect-app", None,
     "speculative — fassade-style naming"),
    ("eukiaidm-app", None,
     "speculative — fassade-style naming"),
]


def _direct_log(log_path, text):
    """Best-effort append to the debug log."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def _log_response(log_path, label, response):
    """Log status, important headers, and a truncated body."""
    _direct_log(log_path, f"  [{label}] status={response.status_code}")
    location = response.headers.get("Location")
    if location:
        _direct_log(log_path, f"  [{label}] Location: {_safe_truncate(location, 300)}")
    set_cookie = response.headers.get("Set-Cookie")
    if set_cookie:
        _direct_log(log_path, f"  [{label}] Set-Cookie: {_safe_truncate(set_cookie, 300)}")
    body = response.text or ""
    _direct_log(log_path, f"  [{label}] body[:500]: {_safe_truncate(body, 500)}")


def _exchange_code_for_tokens(s, code, brand_config, log_path):
    """Use the IdP token endpoint (not WAF-protected) to swap a code for tokens."""
    url = brand_config["token_url"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": brand_config["redirect_uri"],
        "client_id": brand_config["client_id"],
        "client_secret": brand_config["client_secret"],
    }
    _direct_log(log_path, f"\n  [Token exchange] POST {url}")
    try:
        resp = s.post(url, data=data, timeout=30)
    except Exception as e:
        _direct_log(log_path, f"  [Token exchange] network error: {e}")
        return None
    _log_response(log_path, "Token exchange", resp)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        _direct_log(log_path, "  [Token exchange] body was not valid JSON")
        return None


def _prime_session_cookies(s, brand_config, log_path):
    """
    GET the authorize endpoint to seed initial session cookies. This
    is what the official mobile app does first; some IdP backends
    won't accept a signin POST without these cookies present.
    Best-effort — failures are logged but not fatal (the legacy
    fallback can still try without primed cookies).
    """
    url = (
        f"{brand_config['host']}/auth/api/v2/user/oauth2/authorize"
        f"?response_type=code&client_id={brand_config['client_id']}"
        f"&redirect_uri={brand_config['redirect_uri']}"
        "&lang=en&state=ccsp&country=de"
    )
    _direct_log(log_path, f"\n  [Cookie prime] GET {url}")
    try:
        resp = s.get(url, timeout=30, allow_redirects=True)
        cookie_count = len(s.cookies) if hasattr(s, "cookies") else 0
        _direct_log(
            log_path,
            f"  [Cookie prime] status={resp.status_code} cookies_set={cookie_count}",
        )
    except Exception as e:
        _direct_log(log_path, f"  [Cookie prime] exception: {e}")


def _import_rsa():
    """
    Lazy-import pycryptodome's RSA + PKCS1_v1_5. Raises a clean
    RuntimeError with install hint if the package is missing,
    instead of an opaque ImportError traceback.
    """
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
        return RSA, PKCS1_v1_5
    except ImportError as exc:
        raise RuntimeError(
            "EU direct mode requires pycryptodome for password encryption. "
            "Install it with: python -m pip install pycryptodome"
        ) from exc


def _fetch_signin_pubkey(s, brand_config, log_path):
    """
    Fetch the IdP's RSA public key for password encryption. The endpoint
    returns a JWK wrapped as `{"retValue": {"n":..., "e":..., "kid":...}}`.
    Returns (RSA key, kid) or (None, None) on any failure.
    """
    url = f"{brand_config['host']}/auth/api/v1/accounts/certs"
    _direct_log(log_path, f"\n  [JWK fetch] GET {url}")
    try:
        resp = s.get(url, timeout=30)
    except Exception as e:
        _direct_log(log_path, f"  [JWK fetch] network error: {e}")
        return None, None
    _log_response(log_path, "JWK fetch", resp)
    if resp.status_code != 200:
        return None, None
    try:
        body = resp.json()
        jwk = body.get("retValue") or {}
        if not jwk.get("n") or not jwk.get("e"):
            _direct_log(log_path, "  [JWK fetch] missing 'n' or 'e' in retValue")
            return None, None
        n = int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "=="), "big")
        e_val = int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=="), "big")
        RSA, _ = _import_rsa()
        key = RSA.construct((n, e_val))
        kid = jwk.get("kid", "")
        _direct_log(
            log_path,
            f"  [JWK fetch] parsed key kid={kid or '(empty)'} "
            f"modulus_bits={n.bit_length()}",
        )
        return key, kid
    except (ValueError, KeyError, TypeError) as exc:
        _direct_log(log_path, f"  [JWK fetch] parse error: {exc}")
        return None, None


def _rsa_encrypt(public_key, plaintext):
    """PKCS#1 v1.5 RSA encrypt; return hex string (the format Kia EU expects)."""
    _, PKCS1_v1_5 = _import_rsa()
    cipher = PKCS1_v1_5.new(public_key)
    return cipher.encrypt(plaintext.encode("utf-8")).hex()


def _form_signin_app_flow(s, brand_config, email, password, log_path):
    """
    Modern app-flow signin: prime cookies, fetch RSA pubkey, send the
    encrypted password. This is what the official Kia/Hyundai Connect
    Android app does. Returns the authorization code on success, or
    None if any step fails.
    """
    _prime_session_cookies(s, brand_config, log_path)
    pubkey, kid = _fetch_signin_pubkey(s, brand_config, log_path)
    if pubkey is None:
        _direct_log(
            log_path,
            "  [App-flow] JWK unavailable — caller will fall back to legacy.",
        )
        return None
    encrypted = _rsa_encrypt(pubkey, password)

    url = f"{brand_config['host']}/auth/account/signin"
    data = {
        "client_id": brand_config["client_id"],
        "encryptedPassword": "true",
        "password": encrypted,
        "redirect_uri": brand_config["redirect_uri"],
        "scope": "",
        "nonce": "",
        "state": "ccsp",
        "username": email,
        "connector_session_key": "",
        "kid": kid,
        "_csrf": "",
    }
    _direct_log(log_path, f"\n  [App-flow signin] POST {url}")
    try:
        resp = s.post(url, data=data, timeout=30, allow_redirects=False)
    except Exception as exc:
        _direct_log(log_path, f"  [App-flow signin] network error: {exc}")
        return None
    _log_response(log_path, "App-flow signin", resp)
    if resp.status_code in (302, 303):
        location = resp.headers.get("Location", "")
        match = re.search(r"[?&]code=([^&]+)", location)
        if match:
            return match.group(1)
        if "error_description=" in location or "/error?" in location:
            _direct_log(
                log_path,
                "  [App-flow signin] IdP returned an error page (often: bad credentials).",
            )
        elif "/authorize" in location:
            _direct_log(
                log_path,
                "  [App-flow signin] IdP redirected back to login (often: bad credentials).",
            )
    return None


def _form_signin_legacy(s, brand_config, email, password, log_path):
    """
    Defensive fallback signin using `encryptedPassword=false`. Sends
    the password in the form body. Currently still accepted by the
    Kia/Hyundai EU IdP (December 2026), but if the JWK endpoint goes
    down or the encrypted flow is rejected, this path may still get
    a code. Will likely break first if Kia tightens further.
    """
    url = f"{brand_config['host']}/auth/account/signin"
    data = {
        "client_id": brand_config["client_id"],
        "encryptedPassword": "false",
        "username": email,
        "password": password,
        "redirect_uri": brand_config["redirect_uri"],
        "state": "ccsp",
        "remember_me": "false",
    }
    _direct_log(log_path, f"\n  [Legacy signin] POST {url}")
    try:
        resp = s.post(url, data=data, timeout=30, allow_redirects=False)
    except Exception as exc:
        _direct_log(log_path, f"  [Legacy signin] network error: {exc}")
        return None
    _log_response(log_path, "Legacy signin", resp)
    if resp.status_code in (302, 303):
        location = resp.headers.get("Location", "")
        match = re.search(r"[?&]code=([^&]+)", location)
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Probe 3: marketing-client signin → CCSP authorize on the same session
#
# Theory: AWS WAF Bot Control issues an `aws-waf-token` cookie when a
# session passes its initial challenge. The marketing-client signin
# endpoint isn't WAF-blocked, so we successfully receive that cookie
# during the marketing POST. If we then hit the WAF-blocked CCSP
# authorize endpoint with the SAME curl_cffi session — same TLS
# fingerprint, same WAF token, same KEYCLOAK_IDENTITY cookies set
# during signin — WAF may treat it as a continuation of an already-
# trusted session and let it through. Worst case: WAF ignores the
# token, redirects to /error, and we just return None.
# ---------------------------------------------------------------------------
def _probe_marketing_to_ccsp(s, brand_config, email, password, log_path):
    """
    Probe 3 (HISTORICAL — confirmed not working as of v3.3.0 debug
    run on 2026-04-28): sign in via the marketing OAuth client to
    seed cookies, then use the same session to GET the CCSP authorize
    endpoint. Returns a CCSP authorization code on success, or None.

    Why we keep it: the marketing-cookie-reuse trick was a plausible
    bypass of WAF Bot Control on the CCSP authorize endpoint (after
    a marketing signin we have aws-waf-token + KEYCLOAK_IDENTITY
    cookies that should make us look like a legit returning user).
    Empirically the WAF deletes those cookies on the next request
    (Set-Cookie Max-Age=0) and 302-loops the authorize URL.

    Kept in the chain anyway because: (a) zero cost when probes 0-2
    have already won and we early-return, (b) future Kia config
    changes might re-open the path, (c) the diagnostic log lines
    from this probe are valuable for confirming the WAF is still
    behaving the same way.
    """
    if not brand_config.get("marketing_client_id"):
        _direct_log(log_path, "  [Probe 3] no marketing_client_id configured, skipping.")
        return None

    # Step 1: marketing signin (NOT WAF-blocked) — we just want the cookies.
    signin_url = f"{brand_config['host']}/auth/account/signin"
    signin_data = {
        "client_id": brand_config["marketing_client_id"],
        "encryptedPassword": "false",
        "username": email,
        "password": password,
        "redirect_uri": brand_config["marketing_redirect_uri"],
        "state": "ccsp",
        "remember_me": "false",
    }
    _direct_log(log_path, f"\n  [Probe 3 — Marketing signin] POST {signin_url}")
    try:
        resp = s.post(signin_url, data=signin_data, timeout=30, allow_redirects=False)
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 3 signin] network error: {exc}")
        return None
    _log_response(log_path, "Probe 3 — Marketing signin", resp)
    if resp.status_code not in (302, 303):
        _direct_log(log_path, "  [Probe 3] marketing signin failed (likely bad creds), aborting.")
        return None

    # Now we have IdP session cookies + aws-waf-token on the session.
    # Try the CCSP authorize URL — first normally, then with prompt=none
    # (silent SSO; some WAFs whitelist this because it's machine-to-
    # machine by design).
    ccsp_authorize_base = (
        f"{brand_config['host']}/auth/api/v2/user/oauth2/authorize"
        f"?response_type=code&client_id={brand_config['client_id']}"
        f"&redirect_uri={brand_config['redirect_uri']}"
        "&lang=en&state=ccsp"
    )

    for label, url in (
        ("Probe 3 — CCSP authorize", ccsp_authorize_base),
        ("Probe 3 — CCSP authorize (prompt=none)", ccsp_authorize_base + "&prompt=none"),
    ):
        _direct_log(log_path, f"\n  [{label}] GET {url}")
        try:
            resp = s.get(url, timeout=30, allow_redirects=False)
        except Exception as exc:
            _direct_log(log_path, f"  [{label}] network error: {exc}")
            continue
        _log_response(log_path, label, resp)
        if resp.status_code in (302, 303):
            location = resp.headers.get("Location", "")
            match = re.search(r"[?&]code=([^&]+)", location)
            if match:
                _direct_log(log_path, f"  [{label}] got CCSP code via cookie reuse.")
                return match.group(1)
            if "/error" in location or "error=" in location:
                _direct_log(log_path, f"  [{label}] WAF-blocked (redirect to error).")
    return None


# ---------------------------------------------------------------------------
# Probe 4: OIDC discovery + ROPC against advertised endpoints
#
# Most OAuth/OIDC providers expose a metadata document at
# /.well-known/openid-configuration listing all supported endpoints
# and grant types. If discovery advertises grant_types_supported
# including "password", we get a free-of-charge ROPC attempt at the
# advertised token_endpoint. Even when ROPC isn't supported, the
# discovery dump goes into the debug log and is invaluable next time
# Kia adds or moves an endpoint — we'll see it immediately instead of
# guessing.
# ---------------------------------------------------------------------------
def _probe_oidc_discovery(s, brand_config, email, password, log_path):
    """
    Probe 4 (HISTORICAL — confirmed not useful as of v3.3.0 debug run
    on 2026-04-28): fetch /.well-known/openid-configuration on the
    public fassade and try ROPC at any advertised token_endpoint that
    supports grant_type=password.

    Why it doesn't work: the fassade at idpconnect-eu.kia.com hides
    OIDC discovery — the well-known URL returns 404. So we never get
    metadata to act on. The backend realm (Probe 5) DOES expose
    discovery, but that's covered there.

    Kept in the chain because: (a) zero cost on success-from-probe-N<4,
    (b) if Kia ever turns on discovery on the fassade we'd
    automatically see the new endpoints, (c) the 404 itself is a
    useful confirmation in the debug log.

    Returns a token dict on success, None otherwise. (Returns full
    tokens directly because OIDC ROPC bypasses the code-exchange
    step entirely.)
    """
    discovery_url = f"{brand_config['host']}/.well-known/openid-configuration"
    _direct_log(log_path, f"\n  [Probe 4 — OIDC discovery] GET {discovery_url}")
    try:
        resp = s.get(discovery_url, timeout=30)
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 4 discovery] network error: {exc}")
        return None
    if resp.status_code != 200:
        _log_response(log_path, "Probe 4 discovery", resp)
        return None
    try:
        config = resp.json()
    except ValueError:
        _direct_log(log_path, "  [Probe 4 discovery] body not JSON")
        return None

    # Log everything interesting about what Kia advertises.
    interesting_keys = (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "device_authorization_endpoint",
        "userinfo_endpoint",
        "introspection_endpoint",
        "revocation_endpoint",
        "end_session_endpoint",
        "jwks_uri",
        "grant_types_supported",
        "response_types_supported",
        "scopes_supported",
        "token_endpoint_auth_methods_supported",
    )
    _direct_log(log_path, "  [Probe 4 discovery] advertised metadata:")
    for key in interesting_keys:
        if key in config:
            _direct_log(log_path, f"    {key}: {_safe_truncate(config[key], 200)}")

    if config.get("device_authorization_endpoint"):
        _direct_log(
            log_path,
            "  [Probe 4 discovery] device_authorization_endpoint present — "
            "future feature: implement device-flow login.",
        )

    grant_types = config.get("grant_types_supported", []) or []
    token_endpoint = config.get("token_endpoint")
    if not token_endpoint or "password" not in grant_types:
        _direct_log(
            log_path,
            "  [Probe 4 discovery] ROPC not advertised (or no token_endpoint), nothing to try.",
        )
        return None

    # Discovery says ROPC is supported. Attempt it.
    _direct_log(
        log_path,
        f"\n  [Probe 4 — ROPC] POST {token_endpoint} grant_type=password",
    )
    try:
        resp = s.post(
            token_endpoint,
            data={
                "grant_type": "password",
                "username": email,
                "password": password,
                "client_id": brand_config["client_id"],
                "client_secret": brand_config["client_secret"],
                "scope": "openid profile email phone",
            },
            timeout=30,
        )
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 4 ROPC] network error: {exc}")
        return None
    _log_response(log_path, "Probe 4 ROPC", resp)
    if resp.status_code != 200:
        return None
    try:
        tokens = resp.json()
    except ValueError:
        return None
    if tokens.get("refresh_token") and tokens.get("access_token"):
        return tokens
    return None


# ---------------------------------------------------------------------------
# Probe 5: direct Keycloak realm at eu-account.kia.com
#
# The JWT issued by the public IdP fassade has `iss` =
# "https://eu-account.kia.com/auth/realms/eukiaidm". That's the actual
# Keycloak server behind the fassade. AWS WAF protects the fassade
# (idpconnect-eu.kia.com), but if the backend realm is also reachable
# from the public internet (which it must be, otherwise no one could
# verify JWT issuer URLs), it may not have the same WAF rules — the
# WAF is typically configured per host. Try Keycloak's standard
# OIDC endpoints there. Speculative and not in any prior open-source
# implementation; if it works, it's a clean fully-headless path
# completely independent of the WAF-protected fassade.
# ---------------------------------------------------------------------------
def _backend_realm_discover(s, brand_config, log_path):
    """
    Fetch backend realm OIDC metadata. Returns the parsed config dict
    on success, None on any failure. Also logs interesting metadata.
    """
    realm_url = brand_config.get("backend_realm_url")
    if not realm_url:
        _direct_log(log_path, "  [Probe 5] no backend_realm_url configured, skipping.")
        return None

    discovery_url = f"{realm_url}/.well-known/openid-configuration"
    _direct_log(log_path, f"\n  [Probe 5 — Backend realm discovery] GET {discovery_url}")
    try:
        resp = s.get(discovery_url, timeout=15)
    except Exception as exc:
        _direct_log(
            log_path,
            f"  [Probe 5 discovery] network error: {exc} "
            "(backend realm may not be public-facing — expected for some setups)",
        )
        return None
    if resp.status_code != 200:
        _log_response(log_path, "Probe 5 discovery", resp)
        return None

    try:
        config = resp.json()
    except ValueError:
        _direct_log(log_path, "  [Probe 5 discovery] body not JSON")
        return None

    _direct_log(log_path, "  [Probe 5 discovery] backend realm REACHABLE — metadata:")
    for key in (
        "issuer",
        "token_endpoint",
        "authorization_endpoint",
        "device_authorization_endpoint",
        "grant_types_supported",
        "token_endpoint_auth_methods_supported",
    ):
        if key in config:
            _direct_log(log_path, f"    {key}: {_safe_truncate(config[key], 200)}")

    return config


def _probe_backend_realm(s, brand_config, email, password, log_path):
    """
    Probe 5: enumerate Client-IDs at the backend Keycloak realm.

    The v3.3.0 debug-all run confirmed that:
      - The backend realm at eu-account.kia.com IS publicly reachable
      - It advertises grant_types_supported including 'password' (ROPC)
        and 'urn:ietf:params:oauth:grant-type:device_code'
      - But the fassade client_id "fdc85c00..." is NOT registered there
        (returns "invalid_client")

    So we sweep BACKEND_CLIENT_CANDIDATES — each candidate is a (client_id,
    secret) pair we try with grant_type=password. The error code that
    comes back tells us about each client:
      - "invalid_client"     → client_id doesn't exist at this realm
      - "unauthorized_client"→ client exists but ROPC not enabled for it
      - "invalid_grant"      → client EXISTS, ROPC enabled, but the
                               username/password combination didn't auth
                               (or the user needs MFA, etc.) — that's
                               still a major finding because it means
                               the client is real
      - 200 + tokens         → JACKPOT — fully WAF-independent path
    """
    config = _backend_realm_discover(s, brand_config, log_path)
    if not config:
        return None

    token_endpoint = config.get("token_endpoint")
    if not token_endpoint:
        return None

    grant_types = config.get("grant_types_supported", []) or []
    if "password" not in grant_types:
        _direct_log(
            log_path,
            "  [Probe 5] backend realm doesn't advertise ROPC, nothing to try.",
        )
        return None

    _direct_log(
        log_path,
        f"\n  [Probe 5 — Backend ROPC] sweeping {len(BACKEND_CLIENT_CANDIDATES)} client_id candidates at {token_endpoint}",
    )

    found_existing = []  # [(client_id, error)] for clients that exist but failed auth

    for client_id, client_secret, comment in BACKEND_CLIENT_CANDIDATES:
        data = {
            "grant_type": "password",
            "username": email,
            "password": password,
            "client_id": client_id,
            "scope": "openid profile email phone",
        }
        if client_secret is not None:
            data["client_secret"] = client_secret

        secret_label = "(secret)" if client_secret else "(public)"
        _direct_log(
            log_path,
            f"\n    [Probe 5 try] client_id={client_id} {secret_label}  [{comment}]",
        )
        try:
            resp = s.post(token_endpoint, data=data, timeout=15)
        except Exception as exc:
            _direct_log(log_path, f"      network error: {exc}")
            continue

        if resp.status_code == 200:
            try:
                tokens = resp.json()
            except ValueError:
                _direct_log(log_path, "      200 but body not JSON")
                continue
            if tokens.get("refresh_token") and tokens.get("access_token"):
                _direct_log(
                    log_path,
                    f"      [JACKPOT] {client_id} accepted credentials — "
                    "fully WAF-independent path.",
                )
                return tokens
            _direct_log(log_path, "      200 but no tokens in response")
            continue

        # Non-200: parse error code from response body to classify the failure.
        body = resp.text or ""
        error = ""
        try:
            err_json = resp.json()
            error = err_json.get("error", "")
        except ValueError:
            pass

        if error == "invalid_client":
            _direct_log(log_path, f"      → invalid_client (client unknown at backend)")
        elif error == "unauthorized_client":
            _direct_log(
                log_path,
                f"      → unauthorized_client (CLIENT EXISTS but ROPC not enabled for it)",
            )
            found_existing.append((client_id, "ROPC disabled"))
        elif error == "invalid_grant":
            _direct_log(
                log_path,
                f"      → invalid_grant (CLIENT EXISTS — credentials wrong, or MFA required)",
            )
            found_existing.append((client_id, "credentials rejected"))
        else:
            _direct_log(
                log_path,
                f"      → status={resp.status_code} error={error or 'unknown'} "
                f"body[:200]={_safe_truncate(body, 200)}",
            )

    # No success, but log any "real" clients we found
    if found_existing:
        _direct_log(log_path, "\n  [Probe 5] EXISTING backend clients discovered:")
        for cid, reason in found_existing:
            _direct_log(log_path, f"    - {cid} ({reason})")
        _direct_log(
            log_path,
            "  These would work if we had the right secret / second factor / "
            "authorization. Future-feature opportunity.",
        )
    else:
        _direct_log(
            log_path,
            "  [Probe 5] None of the candidate client_ids are registered at the backend realm.",
        )

    return None


# ---------------------------------------------------------------------------
# Probe 6: device flow (RFC 8628) at the backend Keycloak realm.
#
# The backend realm advertises 'urn:ietf:params:oauth:grant-type:device_code'
# in grant_types_supported. Device flow doesn't require credentials in
# the headless path — instead, it returns a verification_uri + user_code
# which the user opens in any browser (their phone, another PC), logs in
# there, and we poll for tokens. This means:
#   - The user authenticates on Kia's official Keycloak page (no WAF
#     bypass needed — they ARE the browser this time).
#   - Our headless code never touches credentials directly.
#   - Tokens are issued by the backend realm (Keycloak-native tokens),
#     same as Probe 5 ROPC would have given us.
#
# Caveat: device flow ALSO needs a valid backend client_id (same blocker
# as Probe 5). So we sweep the same candidate list at the device-init
# endpoint. If any returns a device_code, we record the capability —
# in normal/debug mode that's all we do (device flow needs interactive
# user input, can't run blocking by default). The user can then opt in
# with `--device-flow` to actually go through the polling cycle.
#
# Even if no candidate works today, the discovery output is logged for
# future iteration: someone reverse-engineering the app may find a real
# backend client_id and add it to BACKEND_CLIENT_CANDIDATES.
# ---------------------------------------------------------------------------
def _probe_device_flow_discover(s, brand_config, log_path):
    """
    Initiate device flow against backend realm with each candidate
    client_id. Returns a list of usable
    {client_id, device_code, user_code, verification_uri,
     verification_uri_complete, expires_in, interval} dicts (empty if
    none worked). Does NOT poll — see _interactive_device_flow_complete.
    """
    config = _backend_realm_discover(s, brand_config, log_path)
    if not config:
        return []

    device_endpoint = config.get("device_authorization_endpoint")
    if not device_endpoint:
        _direct_log(
            log_path,
            "  [Probe 6] backend realm doesn't advertise device_authorization_endpoint",
        )
        return []

    grant_types = config.get("grant_types_supported", []) or []
    if "urn:ietf:params:oauth:grant-type:device_code" not in grant_types:
        _direct_log(log_path, "  [Probe 6] device_code grant not advertised")
        return []

    _direct_log(
        log_path,
        f"\n  [Probe 6 — Device flow init] sweeping candidates at {device_endpoint}",
    )

    findings = []
    for client_id, client_secret, comment in BACKEND_CLIENT_CANDIDATES:
        data = {"client_id": client_id, "scope": "openid"}
        if client_secret is not None:
            data["client_secret"] = client_secret

        secret_label = "(secret)" if client_secret else "(public)"
        _direct_log(log_path, f"\n    [Probe 6 try] client_id={client_id} {secret_label}")
        try:
            # Explicit Accept header — Keycloak otherwise returns HTML
            # if the client thinks it's a browser hitting an endpoint.
            resp = s.post(
                device_endpoint,
                data=data,
                headers={"Accept": "application/json"},
                timeout=15,
            )
        except Exception as exc:
            _direct_log(log_path, f"      network error: {exc}")
            continue

        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                # Keycloak gave us 200 but non-JSON. Log the actual
                # body so we can see what it is (HTML login form?
                # error page? empty?) — without this logging the
                # mystery in v3.4.0 took 24h to solve.
                content_type = resp.headers.get("Content-Type", "(no Content-Type)")
                preview = _safe_truncate(resp.text or "(empty)", 300)
                _direct_log(
                    log_path,
                    f"      200 but body not JSON; Content-Type={content_type} body[:300]={preview}",
                )
                continue
            if not (body.get("device_code") and body.get("user_code")):
                _direct_log(log_path, "      200 but missing device_code/user_code")
                continue
            finding = {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": body["device_code"],
                "user_code": body["user_code"],
                "verification_uri": body.get("verification_uri", ""),
                "verification_uri_complete": body.get("verification_uri_complete")
                                           or body.get("verification_uri", ""),
                "expires_in": body.get("expires_in", 600),
                "interval": body.get("interval", 5),
                "token_endpoint": config.get("token_endpoint"),
            }
            findings.append(finding)
            _direct_log(
                log_path,
                f"      [USABLE] device_code received, user_code={body['user_code']}, "
                f"verification_uri={finding['verification_uri']}",
            )
            continue

        # Non-200: classify
        try:
            err_json = resp.json()
            err = err_json.get("error", "")
        except ValueError:
            err = ""
        if err:
            _direct_log(log_path, f"      → status={resp.status_code} error={err}")
        else:
            body_preview = _safe_truncate(resp.text or "", 200)
            _direct_log(log_path, f"      → status={resp.status_code} body[:200]={body_preview}")

    if findings:
        _direct_log(
            log_path,
            f"\n  [Probe 6] {len(findings)} candidate(s) accepted device-flow init "
            "— interactive flow available via --device-flow",
        )
    else:
        _direct_log(log_path, "\n  [Probe 6] no client_id accepted device-flow init")
    return findings


def _interactive_device_flow_complete(s, finding, log_path):
    """
    Given a device-flow finding, present the verification URI to the
    user and poll the token endpoint until they authenticate (or
    expiration). Returns tokens dict on success, None on failure or
    user-canceled.
    """
    print()
    print("=" * 60)
    print("DEVICE FLOW — interactive login")
    print("=" * 60)
    print()
    print("Open this URL in any browser (your phone is fine):")
    print(f"  {finding['verification_uri_complete']}")
    print()
    if finding['user_code'] not in (finding['verification_uri_complete'] or ""):
        print(f"If asked, enter this code: {finding['user_code']}")
        print()
    print(f"Log in with your Kia account on that page.")
    print(f"This script will pick up automatically once you're done.")
    print(f"(timeout: {finding['expires_in']}s, polling every {finding['interval']}s)")
    print()
    print("Press Ctrl+C to abort.")
    print()

    deadline = time.time() + finding["expires_in"]
    interval = max(int(finding["interval"]), 1)
    poll_data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": finding["device_code"],
        "client_id": finding["client_id"],
    }
    if finding.get("client_secret") is not None:
        poll_data["client_secret"] = finding["client_secret"]

    while time.time() < deadline:
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nDevice flow aborted by user.")
            return None
        try:
            resp = s.post(finding["token_endpoint"], data=poll_data, timeout=15)
        except Exception as exc:
            _direct_log(log_path, f"  [Device flow poll] network error: {exc}")
            print(".", end="", flush=True)
            continue

        if resp.status_code == 200:
            try:
                tokens = resp.json()
            except ValueError:
                continue
            if tokens.get("refresh_token") and tokens.get("access_token"):
                print("\n[OK] Device flow completed.")
                _direct_log(log_path, "  [Device flow] SUCCESS — tokens received.")
                return tokens
            continue

        try:
            err_json = resp.json()
            err = err_json.get("error", "")
        except ValueError:
            err = ""
        if err == "authorization_pending":
            print(".", end="", flush=True)
            continue
        if err == "slow_down":
            interval += 1
            print("(slowing down)", end=" ", flush=True)
            continue
        if err == "expired_token":
            print("\n[ERROR] Device code expired — start over.")
            return None
        if err == "access_denied":
            print("\n[ERROR] Authorization denied on the verification page.")
            return None
        # Unknown error
        body_preview = _safe_truncate(resp.text or "", 200)
        print(f"\n[ERROR] Device flow polling returned status={resp.status_code} body={body_preview}")
        return None

    print("\n[ERROR] Device flow timed out without completion.")
    return None


# ---------------------------------------------------------------------------
# Probe 7: backend Keycloak realm authorization_code flow.
#
# The v3.4.0 debug-all run proved that the marketing client_id
# `peukiaidm-online-sales` is registered at the backend Keycloak realm
# (eu-account.kia.com) — Probe 5 sweep returned `unauthorized_client`
# instead of `invalid_client` for it. ROPC is disabled there, but the
# standard authorization_code flow may not be — that's the most common
# Keycloak client config.
#
# So this probe attempts the FULL Keycloak browser-style flow but
# headlessly: GET the authorize endpoint to receive a Keycloak login
# form (HTML), parse the form action URL, POST username+password to
# that action, hopefully receive a 302 redirect with a code in the
# Location, then exchange the code at the backend's token endpoint.
#
# Two unknowns this probe will tell us about:
#   1. Does the backend authorize endpoint render its own login page,
#      or does it redirect to the WAF-protected fassade login? The
#      former gives us a usable path; the latter is a dead end.
#   2. If we get a Keycloak login form, does the standard form-action
#      POST work, or does Keycloak need additional CSRF / session
#      cookies / WebAuthn / second factor that this probe doesn't
#      handle? The diagnostic log shows what comes back in either case.
#
# Tokens returned by this path have `iss = eu-account.kia.com/auth/...`,
# not `iss = "uvo"` like the working probes. That MAY mean Home
# Assistant rejects them — but it might also work because HA delegates
# to hyundai_kia_connect_api which may accept either issuer. We log a
# clear note so the user can decide.
# ---------------------------------------------------------------------------
def _probe_backend_auth_code(s, brand_config, email, password, log_path):
    """
    Probe 7 (HISTORICAL — confirmed not viable as of v3.7.0 debug run
    on 2026-04-28): try the standard Keycloak authorization_code flow
    at the backend realm. Returns tokens dict on success, None
    otherwise.

    Why it doesn't work: the backend Keycloak login form has Google
    reCAPTCHA v3 wired in (site key `6Ld2GsMrAAAAALfCHMn7fAVEK898yPTFQNYMmNss`).
    The form embeds an `<input type="hidden" name="g-recaptcha-response">`
    that must contain a valid Google-signed token before submission.
    Without running Google's JS in a real browser, we cannot obtain
    that token, and the backend rejects the POST with `recaptcha_failed_v3`.

    This is by design: every browser-rendered Kia login surface (fassade
    UI + backend UI) enforces reCAPTCHA. The REST API at
    /auth/account/signin (Probes 0-2) does NOT enforce reCAPTCHA — it's
    designed for the official mobile app, which has its own attestation
    (SafetyNet/Play Integrity) that signals "real device" without
    needing a JS challenge. We piggyback on that REST endpoint.

    Kept in the chain because: (a) zero cost on success-from-probe-N<7,
    (b) if Kia ever removes reCAPTCHA from the backend or adds a
    different client without it, this probe would automatically pick
    it up, (c) the diagnostic log makes the architectural picture
    clear for future contributors.
    """
    realm_url = brand_config.get("backend_realm_url")
    if not realm_url:
        _direct_log(log_path, "  [Probe 7] no backend_realm_url configured, skipping.")
        return None

    # Use the marketing client_id since Probe 5 confirmed it exists at
    # the backend. Marketing redirect_uri is also a known-valid value.
    backend_client_id = brand_config.get("marketing_client_id")
    backend_redirect = brand_config.get("marketing_redirect_uri")
    if not backend_client_id or not backend_redirect:
        _direct_log(log_path, "  [Probe 7] marketing client/redirect not configured, skipping.")
        return None

    auth_url = (
        f"{realm_url}/protocol/openid-connect/auth"
        f"?client_id={backend_client_id}"
        "&response_type=code"
        f"&redirect_uri={backend_redirect}"
        "&state=ccsp"
        "&scope=openid"
    )

    # ----------------------------------------------------------------
    # Step 1: GET the authorize URL. Keycloak should render an HTML
    # login form. If it instead redirects to the fassade login, we're
    # back in WAF territory — abort.
    # ----------------------------------------------------------------
    _direct_log(log_path, f"\n  [Probe 7 — Auth GET] GET {auth_url}")
    try:
        resp = s.get(auth_url, timeout=15, allow_redirects=False)
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 7] auth GET network error: {exc}")
        return None
    _log_response(log_path, "Probe 7 auth GET", resp)

    # If we get redirected, follow if it's still on the backend host.
    # Bail if it goes to the fassade (WAF-protected).
    if resp.status_code in (302, 303):
        location = resp.headers.get("Location", "")
        if "idpconnect-eu" in location or "idpconnect-eu.hyundai" in location:
            _direct_log(
                log_path,
                "  [Probe 7] backend authorize redirected to WAF-protected fassade — dead end.",
            )
            return None
        if not location:
            return None
        try:
            resp = s.get(location, timeout=15, allow_redirects=False)
        except Exception as exc:
            _direct_log(log_path, f"  [Probe 7] auth follow network error: {exc}")
            return None
        _log_response(log_path, "Probe 7 auth GET (followed)", resp)

    if resp.status_code != 200:
        _direct_log(log_path, f"  [Probe 7] expected 200 with HTML, got {resp.status_code}")
        return None

    get_body = resp.text or ""

    # ----------------------------------------------------------------
    # Step 2: parse the form action URL. Keycloak's login form looks
    # like <form id="kc-form-login" action="..." method="post">. The
    # action URL embeds session/code parameters, so we have to extract
    # it from the rendered HTML.
    # ----------------------------------------------------------------
    form_match = re.search(
        r'<form[^>]+action=["\']([^"\']+)["\']',
        get_body,
        flags=re.IGNORECASE,
    )
    if not form_match:
        _direct_log(
            log_path,
            f"  [Probe 7] no <form action=...> found in HTML response; "
            f"body[:300]={_safe_truncate(get_body, 300)}",
        )
        return None

    form_action = form_match.group(1).replace("&amp;", "&")
    if not form_action.startswith("http"):
        # relative URL — prepend host
        from urllib.parse import urljoin
        form_action = urljoin(auth_url, form_action)
    _direct_log(log_path, f"  [Probe 7] login form action: {_safe_truncate(form_action, 200)}")

    # Extract any hidden form fields from the GET body. Some Keycloak
    # setups embed CSRF tokens / session continuations / locale hints
    # as <input type="hidden"> in the login form, and silently reject
    # POSTs that don't echo them back.
    hidden_fields = {}
    for m in re.finditer(
        r'<input\s+[^>]*type=["\']hidden["\'][^>]*>',
        get_body,
        flags=re.IGNORECASE,
    ):
        tag = m.group(0)
        name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        value_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if name_m:
            hidden_fields[name_m.group(1)] = value_m.group(1) if value_m else ""
    if hidden_fields:
        _direct_log(
            log_path,
            f"  [Probe 7] extracted {len(hidden_fields)} hidden form field(s): "
            f"{list(hidden_fields.keys())}",
        )

    # ----------------------------------------------------------------
    # Step 3: POST credentials to the form action. Keycloak's standard
    # credential submission expects username + password (and optionally
    # credentialId — empty is fine). Also include any hidden fields
    # captured from the GET response, plus the locale hint.
    # ----------------------------------------------------------------
    post_data = dict(hidden_fields)  # start with whatever hidden fields the form had
    post_data.update({
        "username": email,
        "password": password,
        "credentialId": post_data.get("credentialId", ""),
        # Keycloak's submit button is `<input name="login" value="Sign In">`.
        # Some Keycloak setups validate that this field is present —
        # without it the form may be treated as a synthetic submit.
        "login": "Sign In",
        # Locale hint — some Keycloak themes require it for the login
        # to dispatch to the right credential validator.
        "kc_locale": post_data.get("kc_locale", "en"),
    })

    _direct_log(log_path, f"\n  [Probe 7 — Login POST] data fields: {sorted(post_data.keys())}")
    try:
        resp = s.post(
            form_action,
            data=post_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
            allow_redirects=False,
        )
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 7] login POST network error: {exc}")
        return None
    _log_response(log_path, "Probe 7 login POST", resp)

    if resp.status_code not in (302, 303):
        # Keycloak re-rendered the login form with an embedded error.
        # Search the FULL post body (not just first 1000 chars) for any
        # of the known Keycloak error patterns.
        post_body = resp.text or ""
        error_msg = None
        for pattern in (
            r'<span[^>]+class=["\'][^"\']*kc-feedback-text[^"\']*["\'][^>]*>\s*([^<]+?)\s*</span>',
            r'<span[^>]+id=["\']input-error["\'][^>]*>\s*([^<]+?)\s*</span>',
            r'<div[^>]+class=["\'][^"\']*alert-error[^"\']*["\'][^>]*>(?:\s*<[^>]+>\s*)*\s*([^<]+?)\s*<',
            r'<span[^>]+class=["\'][^"\']*pf-c-form__helper-text[^"\']*["\'][^>]*>\s*([^<]+?)\s*</span>',
            # Even-broader fallback: look for anything mentioning
            # "feedback" or "alert" and pull the inner text
            r'<[^>]+class=["\'][^"\']*(?:feedback|alert-error|invalid-feedback)[^"\']*["\'][^>]*>(?:\s*<[^>]+>\s*)*\s*([^<]{4,200}?)\s*<',
        ):
            m = re.search(pattern, post_body, re.DOTALL | re.IGNORECASE)
            if m and m.group(1).strip():
                error_msg = m.group(1).strip()
                break

        # Also: did the title change? Keycloak sometimes signals
        # "logged in" via a different page title.
        title_m = re.search(r"<title>([^<]+)</title>", post_body, re.IGNORECASE)
        post_title = title_m.group(1).strip() if title_m else ""

        # Save GET and POST HTML to disk for manual inspection — the
        # user can then send the diff/snippet back to us instead of
        # us trying to truncate it usefully into the log.
        try:
            log_dir = os.path.dirname(log_path) or "."
            with open(os.path.join(log_dir, "kia_probe7_get.html"), "w",
                      encoding="utf-8") as f:
                f.write(get_body)
            with open(os.path.join(log_dir, "kia_probe7_post.html"), "w",
                      encoding="utf-8") as f:
                f.write(post_body)
            _direct_log(
                log_path,
                f"  [Probe 7] saved GET + POST HTML to "
                f"kia_probe7_get.html / kia_probe7_post.html for inspection",
            )
        except OSError:
            pass

        if error_msg:
            _direct_log(
                log_path,
                f"  [Probe 7] Keycloak error: '{error_msg}' (login form re-rendered)",
            )
        else:
            len_diff = len(post_body) - len(get_body)
            _direct_log(
                log_path,
                f"  [Probe 7] login rejected — no extractable error message. "
                f"GET body={len(get_body)} chars, POST body={len(post_body)} chars "
                f"(diff={len_diff:+d}). POST title='{post_title}'.",
            )
        return None

    location = resp.headers.get("Location", "")
    match = re.search(r"[?&]code=([^&]+)", location)
    if not match:
        _direct_log(
            log_path,
            f"  [Probe 7] no code in redirect Location: {_safe_truncate(location, 200)}",
        )
        return None

    auth_code = match.group(1)
    _direct_log(log_path, "  [Probe 7] got auth code from backend Keycloak")

    # ----------------------------------------------------------------
    # Step 4: exchange code at backend token endpoint.
    # ----------------------------------------------------------------
    token_url = f"{realm_url}/protocol/openid-connect/token"
    _direct_log(log_path, f"\n  [Probe 7 — Token exchange] POST {token_url}")
    try:
        resp = s.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": backend_redirect,
                "client_id": backend_client_id,
            },
            timeout=15,
        )
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 7] token exchange network error: {exc}")
        return None
    _log_response(log_path, "Probe 7 token exchange", resp)

    if resp.status_code != 200:
        return None
    try:
        tokens = resp.json()
    except ValueError:
        return None
    if tokens.get("refresh_token") and tokens.get("access_token"):
        _direct_log(
            log_path,
            "  [Probe 7] backend authorization_code flow SUCCEEDED — "
            "tokens issued by backend Keycloak (iss != 'uvo'). "
            "May need translation for HA.",
        )
        return tokens
    return None


# ---------------------------------------------------------------------------
# Probe 8: real-browser automation at the backend Keycloak realm.
#
# The 2026-04-28 v3.7 debug-all run conclusively showed that Probe 7's
# only blocker is Google reCAPTCHA v3 (site key 6Ld2GsMrAAAA…) on the
# backend login form. reCAPTCHA v3 is invisible — no user-facing
# challenge, just JS that scores the browser session and produces a
# Google-signed token. So a *real* Chrome browser executing the page's
# JS naturally generates that token; only headless/scripted requests
# fail because Google flags them as bots.
#
# Probe 8 leverages that: launch undetected-chromedriver against
# eu-account.kia.com (which is NOT behind AWS WAF — confirmed by Probe
# 5 discovery), let it run the page's JS, navigate the multi-step
# Kia login UI (email → Continue → password → Log In), and extract
# the auth code from the final redirect URL.
#
# This is opt-in via `--keycloak-browser` — it isn't part of the
# automatic probe chain because (a) it spawns a Chrome window which
# is interactive UX, (b) it takes ~15-30 seconds vs the REST probes'
# ~3 seconds, (c) tokens come from the backend realm with iss=eu-
# account.kia.com which may need translation for Home Assistant.
#
# This is THE futureproof fallback for the day Probes 0-2 break (i.e.
# Kia adds reCAPTCHA or attestation to the REST signin endpoint too).
# At that point, every browser-based path EXCEPT this one is dead,
# because they're either WAF-blocked (fassade) or reCAPTCHA-blocked
# without a real browser.
# ---------------------------------------------------------------------------
def _probe_keycloak_browser(brand_config, email, password, log_path,
                            headless=False, debug_log_extras=True):
    """
    Drive a real Chrome browser through the backend Keycloak login
    flow, including Google's reCAPTCHA v3 (which Chrome handles
    naturally). Returns a token dict (Keycloak-native, iss=backend
    realm) on success, None on failure.
    """
    try:
        import undetected_chromedriver as uc
    except ImportError as exc:
        raise RuntimeError(
            "Probe 8 (--keycloak-browser) requires undetected-chromedriver. "
            "Install it with: python -m pip install undetected-chromedriver"
        ) from exc

    realm_url = brand_config.get("backend_realm_url")
    backend_client_id = brand_config.get("marketing_client_id")
    backend_redirect = brand_config.get("marketing_redirect_uri")
    if not realm_url or not backend_client_id or not backend_redirect:
        _direct_log(log_path, "  [Probe 8] backend_realm_url / marketing_* not configured, skipping.")
        return None

    auth_url = (
        f"{realm_url}/protocol/openid-connect/auth"
        f"?client_id={backend_client_id}"
        "&response_type=code"
        f"&redirect_uri={backend_redirect}"
        "&state=ccsp"
        "&scope=openid"
    )

    _direct_log(log_path, f"\n=== Probe 8: real-browser Keycloak login ===")
    _direct_log(log_path, f"  auth URL: {auth_url}")
    _direct_log(log_path, f"  headless: {headless}")

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Real-looking UA — uc sets one by default but we override to a
    # current desktop Chrome to match what reCAPTCHA expects.
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        print("[Probe 8] Starting undetected Chrome — first run downloads "
              "ChromeDriver, this can take 10-30 seconds...")
        driver = uc.Chrome(
            options=options,
            version_main=_chrome_major_version(),
            use_subprocess=True,
            headless=headless,
        )
        driver.set_page_load_timeout(60)

        # Step 1: navigate to backend Keycloak login
        _direct_log(log_path, "\n  [Probe 8] Loading login page...")
        driver.get(auth_url)

        wait = WebDriverWait(driver, 30)

        # Step 2: fill email, click Continue
        # Kia's custom Keycloak theme has a multi-step UI:
        #   step 2: email field visible (#FormEmail) + button "Continue"
        #   step 3: password field visible (#FormPassword) + button "Log In"
        _direct_log(log_path, "  [Probe 8] Waiting for email field...")
        email_field = wait.until(
            EC.element_to_be_clickable((By.ID, "FormEmail"))
        )
        email_field.clear()
        email_field.send_keys(email)
        time.sleep(0.5)  # let JS validators settle

        _direct_log(log_path, "  [Probe 8] Clicking Continue...")
        login_btn = wait.until(EC.element_to_be_clickable((By.ID, "BtnLogin")))
        # Use JS click — bypasses any visibility issues with overlays
        driver.execute_script("arguments[0].click();", login_btn)

        # Step 3: wait for password field, fill, click Log In
        _direct_log(log_path, "  [Probe 8] Waiting for password field...")
        pwd_field = wait.until(
            EC.visibility_of_element_located((By.ID, "FormPassword"))
        )
        # Extra wait — JS animation, focus transition, etc.
        time.sleep(1.0)
        pwd_field.clear()
        pwd_field.send_keys(password)
        time.sleep(0.5)

        _direct_log(log_path, "  [Probe 8] Clicking Log In (triggers reCAPTCHA + form submit)...")
        login_btn2 = driver.find_element(By.ID, "BtnLogin")
        driver.execute_script("arguments[0].click();", login_btn2)

        # Step 4: wait for the redirect-with-code OR an error.
        # On success: URL becomes https://www.kia.com/api/bin/oneid/login?code=…
        # On failure: URL stays at eu-account.kia.com with an error in the page,
        #             OR redirects but shows recaptcha_failed_v3 etc.
        _direct_log(log_path, "  [Probe 8] Waiting for redirect with code (up to 60s)...")
        redirect_wait = WebDriverWait(driver, 60)
        try:
            redirect_wait.until(
                lambda d: ("code=" in d.current_url and "kia.com" in d.current_url)
                or "/error" in d.current_url
                or "recaptcha_failed" in (d.page_source or "")
            )
        except TimeoutException:
            _direct_log(log_path, f"  [Probe 8] timed out waiting for redirect; current_url={driver.current_url}")
            if debug_log_extras:
                try:
                    log_dir = os.path.dirname(log_path) or "."
                    with open(os.path.join(log_dir, "kia_probe8_timeout.html"), "w", encoding="utf-8") as f:
                        f.write(driver.page_source or "")
                    _direct_log(log_path, "  [Probe 8] saved page source to kia_probe8_timeout.html")
                except OSError:
                    pass
            return None

        current_url = driver.current_url
        _direct_log(log_path, f"  [Probe 8] post-login URL: {_safe_truncate(current_url, 200)}")

        # Capture cookies from this session for the token-exchange call —
        # Keycloak issues HttpOnly session cookies that the exchange
        # request shouldn't actually need (auth code is enough), but
        # log them for diagnostic purposes.
        if debug_log_extras:
            try:
                cookies = driver.get_cookies()
                _direct_log(log_path, f"  [Probe 8] {len(cookies)} cookies on session")
            except Exception:
                pass

        if "/error" in current_url or "recaptcha_failed" in (driver.page_source or ""):
            page_src = driver.page_source or ""
            err_m = re.search(r'recaptcha_failed_v\d', page_src)
            error_marker = err_m.group(0) if err_m else "(error page)"
            _direct_log(
                log_path,
                f"  [Probe 8] login rejected: {error_marker}. "
                "Google's reCAPTCHA v3 score was below Kia's accept threshold. "
                "Try non-headless mode (drop --keycloak-browser-headless), or "
                "use the same browser profile repeatedly to build trust.",
            )
            return None

        match = re.search(r"[?&]code=([^&]+)", current_url)
        if not match:
            _direct_log(log_path, f"  [Probe 8] no code= in final URL")
            return None
        auth_code = match.group(1)
        _direct_log(log_path, "  [Probe 8] got auth code from real-browser Keycloak login")

    except WebDriverException as exc:
        _direct_log(log_path, f"  [Probe 8] WebDriver error: {exc}")
        return None
    except Exception as exc:
        _direct_log(log_path, f"  [Probe 8] unexpected error: {exc}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    # Step 5: exchange the auth code at the BACKEND token endpoint
    # (not the fassade's). Plain `requests` is fine — the backend
    # token endpoint isn't WAF-protected.
    token_url = f"{realm_url}/protocol/openid-connect/token"
    _direct_log(log_path, f"\n  [Probe 8 — Token exchange] POST {token_url}")
    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": backend_redirect,
                "client_id": backend_client_id,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        _direct_log(log_path, f"  [Probe 8 token exchange] network error: {exc}")
        return None
    _log_response(log_path, "Probe 8 token exchange", resp)
    if resp.status_code != 200:
        return None
    try:
        tokens = resp.json()
    except ValueError:
        return None
    if tokens.get("refresh_token") and tokens.get("access_token"):
        _direct_log(
            log_path,
            "  [Probe 8] real-browser Keycloak login SUCCEEDED — "
            "Keycloak-native tokens (iss = backend realm).",
        )
        return tokens
    return None


# ---------------------------------------------------------------------------
# Probe 0: plain `requests` + plaintext signin (the v3.0.0 method)
#
# This is the first thing we try, because it is the same code path
# that demonstrably worked end-to-end against a real Kia EU account
# (commit 2eed503). It uses the stdlib HTTP stack — no curl_cffi, no
# RSA, no cookie priming — so it is immune to packaging weirdness
# (e.g. the Windows wheel of curl_cffi 0.15.0 not containing the
# `_android` impersonation profiles). If Kia hardens the signin
# endpoint to require encryptedPassword=true or stricter TLS, this
# probe is the first to break and the curl_cffi-based probes 1-5
# pick up.
# ---------------------------------------------------------------------------
def _probe_plain_signin(brand_config, email, password, log_path):
    """
    Probe 0: plain stdlib requests, plaintext signin at
    /auth/account/signin with the CCSP client_id. Returns a token
    dict (already validated) on success, None on failure.
    """
    s = requests.Session()
    s.headers.update({
        "Accept-Encoding": "gzip",
        "User-Agent": random.choice(BROWSER_UA_POOL),
    })

    code = _form_signin_legacy(s, brand_config, email, password, log_path)
    if not code:
        return None
    _direct_log(log_path, "  [Probe 0] got code, exchanging for tokens…")
    tokens = _exchange_code_for_tokens(s, code, brand_config, log_path)
    if not (tokens and tokens.get("refresh_token") and tokens.get("access_token")):
        return None
    if _validate_refresh_token(tokens["refresh_token"], brand_config, log_path):
        _direct_log(log_path, "  [JACKPOT] Probe 0 tokens validated.")
    else:
        _direct_log(
            log_path,
            "  [WARN] Probe 0 got tokens but validation failed — "
            "returning anyway (may still work in Home Assistant).",
        )
    return tokens


def _create_curl_cffi_session(log_path):
    """
    Create a curl_cffi Session with TLS impersonation, trying the
    preferred profiles in random order and falling back to no-
    impersonation if none work on this build. Returns (session,
    profile_name).

    Some curl_cffi builds (notably the Windows wheel of 0.15.0)
    only ship a subset of impersonation profiles. To detect which
    profiles work without spending a real network round-trip, we
    use the fact that `Session(impersonate=...)` itself accepts
    any name but the underlying request raises only on first use.
    So we issue a tiny throwaway HEAD against a known-up host
    (kia.com, which is unrelated to the IdP and won't itself flag
    anything) before returning.
    """
    from curl_cffi import requests as curl_requests

    profiles = list(TLS_IMPERSONATE_POOL)
    random.shuffle(profiles)
    profiles.append(None)  # last-resort: no impersonation

    for profile in profiles:
        try:
            if profile is None:
                s = curl_requests.Session()
            else:
                s = curl_requests.Session(impersonate=profile)
            # Validate the profile actually works on this build.
            s.head("https://www.kia.com/", timeout=10, allow_redirects=False)
            label = profile or "(none)"
            _direct_log(log_path, f"TLS profile (active): {label}")
            return s, label
        except Exception as exc:
            err = str(exc)
            if "Impersonating" in err and "not supported" in err:
                _direct_log(log_path, f"  TLS profile {profile} not supported on this build, trying next")
                continue
            # Any other error (DNS, transient network) — the profile
            # is fine, the network blip is unrelated. Use this session.
            label = profile or "(none)"
            _direct_log(
                log_path,
                f"TLS profile (active): {label}  "
                f"(probe HEAD got {err[:80]} — that's fine, profile works)",
            )
            return s, label

    raise RuntimeError(
        "Could not create any curl_cffi session — every impersonation "
        "profile rejected by this curl_cffi build."
    )


def _validate_refresh_token(refresh_token, brand_config, log_path):
    """
    Confirm the freshly-minted refresh_token actually mints a new
    access_token. Catches the case where signin returned a code that
    exchanged successfully but the resulting token isn't usable.
    Plain `requests` is fine here — token endpoints aren't WAF-
    protected and don't need TLS impersonation.
    """
    url = brand_config["token_url"]
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": brand_config["client_id"],
        "client_secret": brand_config["client_secret"],
    }
    _direct_log(log_path, f"\n  [Token validation] POST {url}")
    try:
        resp = requests.post(url, data=data, timeout=30)
    except requests.RequestException as exc:
        _direct_log(log_path, f"  [Token validation] network error: {exc}")
        return False
    _log_response(log_path, "Token validation", resp)
    if resp.status_code != 200:
        return False
    try:
        body = resp.json()
        return bool(body.get("access_token"))
    except ValueError:
        return False


def _finalize_tokens(tokens, name, brand_config, log_path):
    """Validate tokens; return them on success, None otherwise."""
    if not (tokens and tokens.get("refresh_token") and tokens.get("access_token")):
        return None
    if _validate_refresh_token(tokens["refresh_token"], brand_config, log_path):
        _direct_log(log_path, f"  [JACKPOT] {name} tokens validated.")
        return tokens
    _direct_log(
        log_path,
        f"  [WARN] {name} got tokens but validation failed — "
        "returning anyway (may still work in Home Assistant).",
    )
    return tokens


def _finalize_code_to_tokens(s, code, name, brand_config, log_path):
    """Code → token exchange → validation. Returns tokens or None."""
    if not code:
        return None
    _direct_log(log_path, f"  [{name}] got code, exchanging for tokens…")
    tokens = _exchange_code_for_tokens(s, code, brand_config, log_path)
    return _finalize_tokens(tokens, name, brand_config, log_path)


# ---------------------------------------------------------------------------
# Per-probe runners. Each returns tokens-or-None and is independently
# callable. Used both by the chained eu_direct_probe (early-return on
# first success) and the debug-all mode (run them all in isolation).
# ---------------------------------------------------------------------------
PROBE_RUNNERS = [
    (
        0,
        "Plain stdlib signin (v3.0 method)",
        "no_curl",
        lambda _s, bc, em, pw, lp: _probe_plain_signin(bc, em, pw, lp),
    ),
    (
        1,
        "App-flow (curl_cffi + RSA-encrypted password)",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_code_to_tokens(
            s, _form_signin_app_flow(s, bc, em, pw, lp), "Probe 1 / App-flow", bc, lp
        ),
    ),
    (
        2,
        "Legacy (curl_cffi + plaintext signin)",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_code_to_tokens(
            s, _form_signin_legacy(s, bc, em, pw, lp), "Probe 2 / Legacy", bc, lp
        ),
    ),
    (
        3,
        "Marketing → CCSP via cookie reuse",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_code_to_tokens(
            s,
            _probe_marketing_to_ccsp(s, bc, em, pw, lp),
            "Probe 3 / Marketing→CCSP",
            bc,
            lp,
        ),
    ),
    (
        4,
        "OIDC discovery + ROPC",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_tokens(
            _probe_oidc_discovery(s, bc, em, pw, lp),
            "Probe 4 / OIDC discovery",
            bc,
            lp,
        ),
    ),
    (
        5,
        "Backend Keycloak realm (eu-account.*) direct ROPC sweep",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_tokens(
            _probe_backend_realm(s, bc, em, pw, lp),
            "Probe 5 / Backend realm",
            bc,
            lp,
        ),
    ),
    (
        6,
        "Device flow at backend realm (discovery only — interactive via --device-flow)",
        "curl",
        # Probe 6 in the chain is DISCOVERY ONLY. Device flow needs the
        # user to open a verification URL in a browser and log in there
        # — that's interactive, can't run blocking inside the chain. So
        # this lambda just sweeps candidate client_ids at the backend's
        # device_authorization_endpoint, logs what's reachable, and
        # always returns None. To actually use device flow, run the
        # script with --device-flow.
        lambda s, bc, em, pw, lp: (_probe_device_flow_discover(s, bc, lp), None)[1],
    ),
    (
        7,
        "Backend Keycloak realm authorization_code flow (form-based)",
        "curl",
        lambda s, bc, em, pw, lp: _finalize_tokens(
            _probe_backend_auth_code(s, bc, em, pw, lp),
            "Probe 7 / Backend auth_code",
            bc,
            lp,
        ),
    ),
]


def _make_curl_cffi_session_with_ua(log_path):
    """Create a curl_cffi session and set headers. Returns session or None on setup failure."""
    try:
        s, _ = _create_curl_cffi_session(log_path)
    except RuntimeError as exc:
        _direct_log(log_path, f"  [curl_cffi setup] {exc}")
        return None
    s.headers.update({
        "Accept-Encoding": "gzip",
        "User-Agent": random.choice(BROWSER_UA_POOL),
    })
    return s


def eu_direct_probe(email, password, brand_config, log_path, debug_all=False):
    """
    Browserless login for Kia or Hyundai EU.

    Normal mode (debug_all=False): runs probes 0-5 in order, returns
    the first success. The fallback chain is intact — same behavior
    as v3.2.x.

    Debug mode (debug_all=True): runs every probe regardless of
    success, each in its own isolated curl_cffi session (probe 0 is
    plain requests as always). Returns the first probe's tokens for
    the user, but logs and prints which probes succeeded vs failed
    so the user can verify the fallback chain is intact.

    See PROBE_RUNNERS for the list of probes.
    """
    try:
        from curl_cffi import requests as curl_requests  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "EU direct mode requires curl_cffi for TLS impersonation. "
            "Install it with: python -m pip install curl_cffi"
        ) from exc

    _direct_log(
        log_path,
        f"\n=== {brand_config['name']} Direct API Probe — "
        f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} ===",
    )
    _direct_log(log_path, f"Email: {email}")
    if debug_all:
        _direct_log(
            log_path,
            "*** DEBUG-ALL mode: running every probe in isolation ***",
        )

    results = {}  # probe_idx -> tokens or None

    # In normal mode, probes 1-5 share a single curl_cffi session so
    # cookies persist (Probe 3 specifically benefits from that).
    # In debug mode, each probe gets a fresh session for fair
    # isolation — otherwise Probe 1 leftover cookies could pollute
    # Probe 3's cookie-reuse experiment.
    shared_curl_session = None

    for idx, name, kind, runner in PROBE_RUNNERS:
        _direct_log(log_path, f"\n--- Probe {idx}: {name} ---")
        if kind == "no_curl":
            session = None  # probe 0 doesn't use curl_cffi
        else:
            if debug_all:
                session = _make_curl_cffi_session_with_ua(log_path)
            else:
                if shared_curl_session is None:
                    shared_curl_session = _make_curl_cffi_session_with_ua(log_path)
                session = shared_curl_session
            if session is None:
                _direct_log(log_path, f"  [Probe {idx}] curl_cffi unavailable, skipping.")
                results[idx] = None
                continue
        try:
            tokens = runner(session, brand_config, email, password, log_path)
        except Exception as exc:
            _direct_log(log_path, f"  [Probe {idx}] unexpected error: {exc}")
            tokens = None
        results[idx] = tokens

        if tokens and not debug_all:
            return tokens

    # Debug mode: print summary
    if debug_all:
        _direct_log(log_path, "\n=== DEBUG-ALL SUMMARY ===")
        for idx, name, _kind, _runner in PROBE_RUNNERS:
            status = "PASS" if results.get(idx) else "FAIL"
            _direct_log(log_path, f"  Probe {idx}: [{status}]  {name}")

        print()
        print("=" * 60)
        print("DEBUG-ALL probe results")
        print("=" * 60)
        for idx, name, _kind, _runner in PROBE_RUNNERS:
            status = "[PASS]" if results.get(idx) else "[FAIL]"
            print(f"  Probe {idx}: {status}  {name}")
        print("=" * 60)
        print()

        # Return the first successful probe's tokens for the user.
        for idx, _name, _kind, _runner in PROBE_RUNNERS:
            if results.get(idx):
                return results[idx]
        return None

    _direct_log(log_path, "\n=== All probes exhausted, no token obtained ===\n")
    return None


# Backwards-compatible alias for callers that import the old name.
def kia_eu_direct_probe(email, password, log_path):
    """Deprecated alias for eu_direct_probe(..., KIA_EU_BRAND_CONFIG, ...)."""
    return eu_direct_probe(email, password, KIA_EU_BRAND_CONFIG, log_path)


def _run_eu_direct(region, brand, brand_config, debug_all=False):
    """
    Browserless direct-API path for Kia/Hyundai EU. Prompts for
    credentials. If both direct-API paths fail, automatically falls
    back to the marketing-client browser flow as last resort, so the
    user always gets at least one chance to recover.

    debug_all=True runs all probes regardless of success and prints
    a summary table — useful for verifying that fallback paths are
    actually still working (and not silently broken until the
    primary fails).
    """
    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    try:
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write(
                f"{brand_config['name']} direct-API debug log — "
                f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            )
    except OSError:
        pass

    host_short = brand_config["host"].replace("https://", "")
    redirect_short = brand_config["redirect_uri"].replace("https://", "").split("/")[0]

    print(f"Logging into {brand['name']} ({region['name']}) — no browser needed.\n")
    if debug_all:
        print("*** DEBUG-ALL mode: every probe will run, even after one succeeds.")
        print("    Takes ~30-60s. A summary table prints at the end.")
        print()
    print(f"Your credentials are sent only to {brand['name']}'s own endpoints")
    print(f"({host_short}, {redirect_short}), never to a third party,")
    print("never written to disk in plaintext. The password prompt below")
    print("is hidden as you type.\n")
    email = input("Email:    ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("[ERROR] Email or password is empty. Aborting.")
        return

    if debug_all:
        print("\nRunning all 6 probes — this takes a while...\n")
    else:
        print("\nFetching token (typically 5–15 seconds)...\n")
    try:
        tokens = eu_direct_probe(
            email, password, brand_config, debug_log_path, debug_all=debug_all
        )
    except RuntimeError as exc:
        # Friendly message for missing curl_cffi / pycryptodome.
        print(f"[ERROR] {exc}")
        print("Re-run the Quick Start to install all dependencies, then retry.")
        return

    if tokens and tokens.get("refresh_token") and tokens.get("access_token"):
        print(
            f"[OK] Your tokens are:\n\n"
            f"- Refresh Token: {tokens['refresh_token']}\n"
            f"- Access Token:  {tokens['access_token']}"
        )
        return

    # ----------------------------------------------------------------
    # Direct path failed. Walk the user through the browser fallback.
    # The browser flow uses the marketing-client login (proven UX for
    # solving any captcha) and then attempts the CCSP authorize
    # handoff. The handoff is currently anti-bot-blocked for many EU
    # users, but if the user's IP/account isn't on the block list (or
    # if Kia has loosened the rule), this is their automatic recovery.
    # ----------------------------------------------------------------
    print("[ERROR] Could not obtain tokens via the direct API. Reasons in")
    print("order of likelihood:")
    print("  - Wrong email or password (most common — re-check)")
    print(f"  - {brand['name']} changed an endpoint (rare)")
    print(f"\nDiagnostic log: {debug_log_path}")
    print("(Passwords are not logged.)\n")

    print("=" * 60)
    print("FALLBACK: trying the browser-based flow as a last resort.")
    print("This will open Chrome and let you log in there. Useful if")
    print("the typo theory is wrong and an endpoint changed. Press")
    print("Ctrl+C now to skip the browser fallback.")
    print("=" * 60)
    try:
        for remaining in (5, 4, 3, 2, 1):
            print(f"  Opening Chrome in {remaining}s...", end="\r", flush=True)
            time.sleep(1)
        print(" " * 40, end="\r")  # clear the countdown line
    except KeyboardInterrupt:
        print("\n\nFallback skipped. Run the script again to retry.")
        return

    _run_browser_flow(region, brand)


def _run_browser_flow(region, brand):
    """Browser-based OAuth flow for non-Kia-EU regions."""
    user_agent = brand.get("user_agent", DEFAULT_USER_AGENT)

    driver = None
    try:
        driver = create_driver(user_agent)

        print(f"Opening {brand['name']} ({region['name']}) login page...")
        driver.get(brand["login_url"])

        print("\n" + "=" * 50)
        print("Please log in manually in the browser window.")

        # --- Step 1: wait for the user to complete login ---------------
        if brand.get("success_selector"):
            print("The script will detect your login automatically.")
            print("=" * 50 + "\n")
            try:
                wait = WebDriverWait(driver, 300)
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, brand["success_selector"])
                ))
            except TimeoutException:
                raise Exception(
                    "Timed out after 5 minutes. Login was not completed "
                    "or the success element was not found."
                )
            print("[OK] Login successful!")
        else:
            # Check if the redirect already happened while the user was
            # still in the browser (code= already in the URL).
            if "code=" in driver.current_url:
                print("[OK] Authorization code already detected!")
            else:
                print("Press ENTER in this terminal after you have logged in.")
                print("")
                print("If the page does not show a login form, this region")
                print("may not support browser-based login yet.")
                print("Please open an issue on GitHub if that is the case.")
                print("=" * 50 + "\n")
                input(">> Press ENTER to continue after login... ")
                print("[OK] Continuing...")

        # --- Step 2: obtain the authorization code ---------------------
        if brand.get("redirect_url"):
            # EU-style: navigate to a separate authorize URL to trigger
            # the OAuth redirect that carries the authorization code.
            driver.get(brand["redirect_url"])
            try:
                wait = WebDriverWait(driver, 20)
                wait.until(
                    lambda d: "code=" in d.current_url or "error=" in d.current_url
                )
            except TimeoutException:
                raise Exception(
                    "Timed out waiting for OAuth redirect. "
                    "The authorization server did not return a code."
                )
        elif "code=" not in driver.current_url:
            # Standard: the login page already redirected (or will
            # redirect) to redirect_url_final?code=...
            try:
                wait = WebDriverWait(driver, 60)
                wait.until(
                    lambda d: "code=" in d.current_url or "error=" in d.current_url
                )
            except TimeoutException:
                raise Exception(
                    "Timed out waiting for redirect with authorization code. "
                    "The login page did not redirect as expected."
                )

        current_url = driver.current_url

        if "error=" in current_url and "code=" not in current_url:
            raise Exception(f"OAuth error. Redirect URL: {current_url}")

        match = re.search(r"[?&]code=([^&]+)", current_url)
        if not match:
            raise Exception("Authorization code not found in redirect URL.")

        code = match.group(1)
        print("[OK] Authorization code found.")

        # --- Step 3: exchange the code for tokens ----------------------
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": brand["redirect_url_final"],
            "client_id": brand["client_id"],
            "client_secret": brand["client_secret"],
        }
        response = session.post(brand["token_url"], data=data, timeout=30)
        if response.status_code == 200:
            tokens = response.json()
            refresh_token = tokens.get("refresh_token")
            access_token = tokens.get("access_token")
            if refresh_token and access_token:
                print(
                    f"\n[OK] Your tokens are:\n\n"
                    f"- Refresh Token: {refresh_token}\n"
                    f"- Access Token:  {access_token}"
                )
            else:
                print(
                    f"\n[ERROR] Token response did not contain expected fields:\n"
                    f"{tokens}"
                )
        else:
            print(
                f"\n[ERROR] Error getting tokens from the API!\n"
                f"Status: {response.status_code}\n{response.text}"
            )

    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted by user.")
    except WebDriverException:
        print("[ERROR] Browser was closed. Please do not close Chrome manually.")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        if driver:
            print("Cleaning up and closing the browser.")
            try:
                driver.quit()
            except Exception:
                pass


def _run_device_flow(region, brand, brand_config):
    """
    Interactive device-flow login at the backend Keycloak realm.
    Triggered explicitly via --device-flow; doesn't go through the
    automatic probe chain. The user opens a verification URI on
    any browser, logs in there, this script polls for tokens.
    No password is sent from this script in this mode (the user
    enters it on Kia's official Keycloak page).
    """
    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    try:
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write(
                f"{brand_config['name']} device-flow log — "
                f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            )
    except OSError:
        pass

    print(f"Device flow login for {brand['name']} ({region['name']}).")
    print("This is an experimental path. You will log in on a verification")
    print("URL in any browser (your phone is fine), and this script will")
    print("pick up the tokens once you're done — no password is sent from")
    print("this script.\n")

    try:
        from curl_cffi import requests as curl_requests  # noqa: F401
    except ImportError as exc:
        print(f"[ERROR] {exc}")
        print("Re-run pip install -r requirements.txt and try again.")
        return

    s = _make_curl_cffi_session_with_ua(debug_log_path)
    if s is None:
        print("[ERROR] curl_cffi session could not be set up. See debug log.")
        return

    findings = _probe_device_flow_discover(s, brand_config, debug_log_path)
    if not findings:
        print("[ERROR] No client_id at the backend realm accepted device-flow")
        print("initialization. The chain has no usable device-flow path right")
        print("now. See debug log for what each candidate client returned.")
        print(f"\nDebug log: {debug_log_path}")
        return

    # Use the first usable finding. (Could prompt user to pick if there
    # are multiple, but in practice there'll be at most one.)
    finding = findings[0]
    print(f"[OK] device-flow init succeeded with client_id={finding['client_id']}.")
    tokens = _interactive_device_flow_complete(s, finding, debug_log_path)
    if not tokens:
        return
    if tokens.get("refresh_token") and tokens.get("access_token"):
        print(
            f"\n[OK] Your tokens (Keycloak-native — may need translation for HA):\n\n"
            f"- Refresh Token: {tokens['refresh_token']}\n"
            f"- Access Token:  {tokens['access_token']}\n"
        )
        print("NOTE: tokens issued by the backend Keycloak realm have")
        print(f"      iss = {brand_config['backend_realm_url']}")
        print("      whereas the CCSP API expects iss = 'uvo'. Test these")
        print("      in Home Assistant; if they don't work, that's the")
        print("      reason and we'd need a token-translation step.")


def _run_keycloak_browser(region, brand, brand_config, headless=False):
    """
    Probe 8 entry point: drive a real Chrome browser through the
    backend Keycloak login form (which has Google reCAPTCHA v3).
    Triggered explicitly via --keycloak-browser; doesn't go through
    the automatic probe chain. Tokens are Keycloak-native (iss=
    backend realm), may need translation for Home Assistant.
    """
    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    try:
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write(
                f"{brand_config['name']} keycloak-browser log — "
                f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            )
    except OSError:
        pass

    print(f"Real-browser Keycloak login for {brand['name']} ({region['name']}).")
    print("EXPERIMENTAL: this is the futureproof fallback for the day Kia")
    print("locks down the REST API used by the regular probe chain.")
    print()
    print("How it works: Chrome will open and log in at Kia's backend")
    print("Keycloak server. Google's reCAPTCHA v3 runs invisibly — your")
    print("browser session is scored, and if it looks human enough, the")
    print("login goes through. No password is shown anywhere; you type")
    print("it once into this terminal and the script types it into the")
    print("browser for you.")
    print()
    if headless:
        print("Mode: HEADLESS (no Chrome window will appear). Higher risk")
        print("of reCAPTCHA blocking; if it fails, retry without --headless.")
    else:
        print("Mode: VISIBLE (a Chrome window will appear). Don't close it")
        print("manually — the script will close it after login.")
    print()
    email = input("Email:    ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("[ERROR] Email or password is empty. Aborting.")
        return

    print(f"\nStarting Chrome and navigating to {brand_config['backend_realm_url']}...\n")
    try:
        tokens = _probe_keycloak_browser(
            brand_config, email, password, debug_log_path, headless=headless
        )
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        print("Re-run pip install -r requirements.txt and try again.")
        return

    if tokens and tokens.get("refresh_token") and tokens.get("access_token"):
        print(
            f"\n[OK] Your tokens (Keycloak-native — may need translation for HA):\n\n"
            f"- Refresh Token: {tokens['refresh_token']}\n"
            f"- Access Token:  {tokens['access_token']}\n"
        )
        print("NOTE: tokens issued by the backend Keycloak realm have")
        print(f"      iss = {brand_config['backend_realm_url']}")
        print("      whereas the CCSP API expects iss = 'uvo'. Test these")
        print("      in Home Assistant; if they don't work, see CHANGELOG")
        print("      v3.9.0 for the architectural reason and possible")
        print("      translation step.")
    else:
        print("[ERROR] Could not obtain tokens via real-browser login.")
        print("Possible reasons:")
        print("  - Wrong email or password")
        print("  - Google reCAPTCHA v3 scored the browser session too low")
        print(f"    (try without --keycloak-browser-headless for higher score)")
        print("  - Kia changed the form structure")
        print(f"\nDiagnostic log: {debug_log_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Get a Kia or Hyundai OAuth2 refresh token.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--debug-all-probes",
        action="store_true",
        help=(
            "Diagnostic mode for Kia/Hyundai EU. Runs every probe in the "
            "fallback chain (0..6) in isolation, regardless of which one "
            "succeeds, and prints a PASS/FAIL summary at the end. Use this "
            "to verify that fallback paths still work (and aren't silently "
            "broken until the primary fails). Takes ~30-60 seconds and "
            "uses your credentials for every probe — may trigger Kia's "
            "rate limits if run too often."
        ),
    )
    parser.add_argument(
        "--device-flow",
        action="store_true",
        help=(
            "EXPERIMENTAL Kia/Hyundai EU only: skip the regular probe chain "
            "and try OAuth Device Flow at the backend Keycloak realm. "
            "Sweeps candidate client_ids until one accepts a device-code "
            "request, then prompts you to open the verification URL in any "
            "browser and log in there. No password is sent from this "
            "script in this mode. Tokens come from the backend realm "
            "directly (Keycloak-native iss, may need translation for HA — "
            "see CHANGELOG)."
        ),
    )
    parser.add_argument(
        "--keycloak-browser",
        action="store_true",
        help=(
            "EXPERIMENTAL Kia/Hyundai EU only: launch a real Chrome browser "
            "(via undetected-chromedriver), navigate the backend Keycloak "
            "login form, and let Google's reCAPTCHA v3 run naturally in "
            "the browser. This is the futureproof fallback for the day "
            "Probes 0/1/2 (the REST API path) get locked down. Slow (~15-30s) "
            "and visible by default — use --keycloak-browser-headless for "
            "headless mode (higher risk of reCAPTCHA blocking). Tokens are "
            "Keycloak-native (iss=backend realm), may need translation for HA."
        ),
    )
    parser.add_argument(
        "--keycloak-browser-headless",
        action="store_true",
        help=(
            "Implies --keycloak-browser and runs Chrome in headless mode. "
            "More automation-friendly, but Google's reCAPTCHA v3 is more "
            "likely to score a headless browser too low and reject the "
            "login. Try this first; fall back to --keycloak-browser "
            "(visible) if it fails."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"KiaHyundaiToken {__version__}",
    )
    args = parser.parse_args()

    # --keycloak-browser-headless implies --keycloak-browser.
    if args.keycloak_browser_headless:
        args.keycloak_browser = True

    try:
        region, brand = select_region_and_brand()

        # --keycloak-browser short-circuits the probe chain entirely.
        if args.keycloak_browser:
            if region["name"] != "Europe" or brand["name"] not in ("Kia", "Hyundai"):
                print("[NOTE] --keycloak-browser is only implemented for Kia/Hyundai EU.")
                return
            brand_cfg = (
                KIA_EU_BRAND_CONFIG if brand["name"] == "Kia"
                else HYUNDAI_EU_BRAND_CONFIG
            )
            _run_keycloak_browser(
                region, brand, brand_cfg,
                headless=args.keycloak_browser_headless,
            )
            return

        # --device-flow short-circuits the probe chain entirely.
        if args.device_flow:
            if region["name"] != "Europe" or brand["name"] not in ("Kia", "Hyundai"):
                print("[NOTE] --device-flow is only implemented for Kia/Hyundai EU.")
                return
            brand_cfg = (
                KIA_EU_BRAND_CONFIG if brand["name"] == "Kia"
                else HYUNDAI_EU_BRAND_CONFIG
            )
            _run_device_flow(region, brand, brand_cfg)
            return

        # Kia EU and Hyundai EU both go through the browserless
        # direct-API path. Other regions still use the browser flow
        # (we don't have validated app constants for them yet, and
        # they don't seem to sit behind the same anti-bot protection).
        if region["name"] == "Europe" and brand["name"] == "Kia":
            _run_eu_direct(region, brand, KIA_EU_BRAND_CONFIG, debug_all=args.debug_all_probes)
        elif region["name"] == "Europe" and brand["name"] == "Hyundai":
            _run_eu_direct(region, brand, HYUNDAI_EU_BRAND_CONFIG, debug_all=args.debug_all_probes)
        else:
            if args.debug_all_probes:
                print("[NOTE] --debug-all-probes only applies to Kia/Hyundai EU. Ignoring.")
            _run_browser_flow(region, brand)
    except KeyboardInterrupt:
        # Catches Ctrl+C during select prompts, email input, or the
        # direct probe — keeps the terminal output clean instead of
        # dumping a traceback. The browser flow has its own
        # KeyboardInterrupt handler that also runs driver.quit().
        print("\n[ERROR] Interrupted by user.")


if __name__ == "__main__":
    main()
