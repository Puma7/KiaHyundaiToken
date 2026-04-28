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

__version__ = "3.1.1"

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
}

# Pool of Android/iOS TLS impersonation profiles for curl_cffi. Picked
# at random per run so consecutive script runs don't all share the
# same TLS fingerprint at the IdP. Only mobile profiles — that's what
# the official Connect app sends, so it's what the IdP expects.
TLS_IMPERSONATE_POOL = [
    "chrome131_android",
    "chrome124_android",
    "chrome120_android",
    "safari17_2_ios",
    "safari17_0_ios",
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


def eu_direct_probe(email, password, brand_config, log_path):
    """
    Browserless login for Kia or Hyundai EU. Returns a token dict
    (with refresh_token + access_token) on success, None on failure.

    Strategy:
      1. App-flow with cookie priming + RSA-encrypted password (what
         the official mobile app does — most app-like, future-proof
         against `encryptedPassword=true` ever becoming required).
      2. Legacy un-encrypted signin as a defensive fallback (still
         works today; first to break if Kia tightens).

    Both paths share the same code-extraction → token-exchange →
    validation pipeline.
    """
    try:
        from curl_cffi import requests as curl_requests
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

    # Per-run randomization across two axes:
    # - Browser User-Agent (15 plausible UAs)
    # - TLS impersonation profile (5 mobile-app-shaped profiles)
    # Different per-run combinations stop trivial cluster-fingerprinting
    # of "all requests from this tool look identical".
    chosen_ua = random.choice(BROWSER_UA_POOL)
    chosen_tls = random.choice(TLS_IMPERSONATE_POOL)
    _direct_log(log_path, f"User-Agent:  {chosen_ua}")
    _direct_log(log_path, f"TLS profile: {chosen_tls}")

    s = curl_requests.Session(impersonate=chosen_tls)
    s.headers.update({
        "Accept-Encoding": "gzip",
        "User-Agent": chosen_ua,
    })

    def _try_path(path_name, code_getter):
        code = code_getter()
        if not code:
            return None
        _direct_log(log_path, f"  [{path_name}] got code, exchanging for tokens…")
        tokens = _exchange_code_for_tokens(s, code, brand_config, log_path)
        if not (tokens and tokens.get("refresh_token") and tokens.get("access_token")):
            return None
        if _validate_refresh_token(tokens["refresh_token"], brand_config, log_path):
            _direct_log(log_path, f"  [JACKPOT] {path_name} tokens validated.")
            return tokens
        _direct_log(
            log_path,
            f"  [WARN] {path_name} got tokens but validation failed — "
            "returning anyway (may still work in Home Assistant).",
        )
        return tokens

    # Path 1: app-flow (modern, RSA-encrypted)
    result = _try_path(
        "App-flow",
        lambda: _form_signin_app_flow(s, brand_config, email, password, log_path),
    )
    if result:
        return result

    # Path 2: legacy un-encrypted signin (defensive fallback)
    _direct_log(log_path, "\n  Falling back to legacy un-encrypted signin path.")
    result = _try_path(
        "Legacy",
        lambda: _form_signin_legacy(s, brand_config, email, password, log_path),
    )
    if result:
        return result

    _direct_log(log_path, "\n=== All paths exhausted, no token obtained ===\n")
    return None


# Backwards-compatible alias for callers that import the old name.
def kia_eu_direct_probe(email, password, log_path):
    """Deprecated alias for eu_direct_probe(..., KIA_EU_BRAND_CONFIG, ...)."""
    return eu_direct_probe(email, password, KIA_EU_BRAND_CONFIG, log_path)


def _run_eu_direct(region, brand, brand_config):
    """
    Browserless direct-API path for Kia/Hyundai EU. Prompts for
    credentials. If both direct-API paths fail, automatically falls
    back to the marketing-client browser flow as last resort, so the
    user always gets at least one chance to recover.
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
    print(f"Your credentials are sent only to {brand['name']}'s own endpoints")
    print(f"({host_short}, {redirect_short}), never to a third party,")
    print("never written to disk in plaintext. The password prompt below")
    print("is hidden as you type.\n")
    email = input("Email:    ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("[ERROR] Email or password is empty. Aborting.")
        return

    print("\nFetching token (typically 5–15 seconds)...\n")
    try:
        tokens = eu_direct_probe(email, password, brand_config, debug_log_path)
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


def main():
    try:
        region, brand = select_region_and_brand()

        # Kia EU and Hyundai EU both go through the browserless
        # direct-API path. Other regions still use the browser flow
        # (we don't have validated app constants for them yet, and
        # they don't seem to sit behind the same anti-bot protection).
        if region["name"] == "Europe" and brand["name"] == "Kia":
            _run_eu_direct(region, brand, KIA_EU_BRAND_CONFIG)
        elif region["name"] == "Europe" and brand["name"] == "Hyundai":
            _run_eu_direct(region, brand, HYUNDAI_EU_BRAND_CONFIG)
        else:
            _run_browser_flow(region, brand)
    except KeyboardInterrupt:
        # Catches Ctrl+C during select prompts, email input, or the
        # direct probe — keeps the terminal output clean instead of
        # dumping a traceback. The browser flow has its own
        # KeyboardInterrupt handler that also runs driver.quit().
        print("\n[ERROR] Interrupted by user.")


if __name__ == "__main__":
    main()
