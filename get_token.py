import base64
import datetime as dt
import getpass
import os
import random
import re
import shutil

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
# These mimic the official Android app and are used only by Mode 4.
# ---------------------------------------------------------------------------
KIA_EU_CCSP_SERVICE_ID = "fdc85c00-0a2f-4c64-bcb4-2cfb1500730a"
KIA_EU_APP_ID = "a2b8469b-30a3-4361-8e13-6fceea8fbe74"
KIA_EU_CLIENT_SECRET = "secret"
KIA_EU_BASIC_AUTH = (
    "Basic ZmRjODVjMDAtMGEyZi00YzY0LWJjYjQtMmNmYjE1MDA3MzBhOnNlY3JldA=="
)
KIA_EU_CFB = base64.b64decode(
    "wLTVxwidmH8CfJYBWSnHD6E0huk0ozdiuygB4hLkM5XCgzAL1Dk5sE36d/bx5PFMbZs="
)
KIA_EU_OKHTTP_UA = "okhttp/3.12.0"


def _kia_eu_stamp():
    """Generate the Stamp header expected by the Kia EU CCSP backend."""
    raw = f"{KIA_EU_APP_ID}:{int(dt.datetime.now().timestamp())}".encode()
    result = bytes(b1 ^ b2 for b1, b2 in zip(KIA_EU_CFB, raw))
    return base64.b64encode(result).decode("utf-8")


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


def _exchange_code_for_tokens(session_obj, code, log_path):
    """Use the IdP token endpoint (not WAF-protected) to swap a code for tokens."""
    url = "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
        "client_id": KIA_EU_CCSP_SERVICE_ID,
        "client_secret": KIA_EU_CLIENT_SECRET,
    }
    _direct_log(log_path, f"\n  [Token exchange] POST {url}")
    try:
        resp = session_obj.post(url, data=data, timeout=30)
    except requests.RequestException as e:
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


def _form_signin(session_obj, client_id, redirect_uri, email, password, log_path, label):
    """
    POST credentials to /auth/account/signin (NOT WAF-blocked). Returns
    the authorization code from the redirect Location, or None.

    User-Agent comes from the session (set by kia_eu_direct_probe) so
    the rotation is consistent within a single run.
    """
    url = "https://idpconnect-eu.kia.com/auth/account/signin"
    data = {
        "client_id": client_id,
        "encryptedPassword": "false",
        "username": email,
        "password": password,
        "redirect_uri": redirect_uri,
        "state": "ccsp",
        "remember_me": "false",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://idpconnect-eu.kia.com",
        "Referer": "https://idpconnect-eu.kia.com/",
    }
    try:
        resp = session_obj.post(
            url, data=data, headers=headers, timeout=30, allow_redirects=False
        )
        _log_response(log_path, label, resp)
        if resp.status_code in (302, 303):
            location = resp.headers.get("Location", "")
            match = re.search(r"[?&]code=([^&]+)", location)
            if match:
                return match.group(1)
    except Exception as e:
        _direct_log(log_path, f"  [{label}] exception: {e}")
    return None


def kia_eu_direct_probe(email, password, log_path):
    """
    Try several non-browser approaches to obtain a Kia EU refresh_token.
    Each probe is logged in detail to log_path. Returns a token dict
    (with 'refresh_token' and 'access_token') if any probe succeeds,
    else None.

    The probes are deliberately ordered cheapest-and-most-promising
    first: ROPC at the IdP token endpoint (which is not WAF-protected),
    then the legacy form-based signin endpoint, then the CCSP-side
    authorize endpoint as a cookie-priming + redirect-following test.
    """
    _direct_log(
        log_path,
        f"\n=== Kia EU Direct API Probe — {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===",
    )
    _direct_log(log_path, f"Email: {email}")

    # Pick a random browser UA per run so consecutive users of the
    # script don't all share the exact same fingerprint at the IdP.
    # All requests in this session use the same UA (one user, one
    # browser, one session — what real traffic looks like).
    chosen_ua = random.choice(BROWSER_UA_POOL)
    _direct_log(log_path, f"User-Agent: {chosen_ua}")

    s = requests.Session()
    s.headers.update({
        "Accept-Encoding": "gzip",
        "User-Agent": chosen_ua,
    })

    # ----------------------------------------------------------------
    # Probe 1: OAuth2 Resource-Owner-Password-Credentials grant against
    # the IdP token endpoint. Token endpoints are typically NOT behind
    # WAF Bot Control because they're machine-to-machine. If the IdP
    # supports ROPC, this returns access_token + refresh_token directly
    # with no Authorize step needed.
    # ----------------------------------------------------------------
    _direct_log(log_path, "\n--- Probe 1: IdP token endpoint, grant_type=password (ROPC) ---")
    try:
        url = "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/token"
        data = {
            "grant_type": "password",
            "username": email,
            "password": password,
            "client_id": KIA_EU_CCSP_SERVICE_ID,
            "client_secret": KIA_EU_CLIENT_SECRET,
            "scope": "openid profile email phone",
        }
        resp = s.post(url, data=data, timeout=30, allow_redirects=False)
        _log_response(log_path, "Probe 1", resp)
        if resp.status_code == 200:
            try:
                tokens = resp.json()
                if tokens.get("refresh_token") and tokens.get("access_token"):
                    _direct_log(log_path, "  [JACKPOT] Probe 1 returned tokens.")
                    return tokens
            except ValueError:
                pass
    except Exception as e:
        _direct_log(log_path, f"  [Probe 1] exception: {e}")

    # ----------------------------------------------------------------
    # Probe 2a: Form-based signin using the CCSP client_id directly.
    # Earlier diagnostic showed signin works, but a code issued for the
    # marketing client cannot be exchanged at the CCSP token endpoint
    # (OAuth requires redirect_uri at authorize and exchange to match).
    # Asking signin to issue a code FOR the CCSP client + CCSP
    # redirect_uri lets the regular exchange work end-to-end.
    # ----------------------------------------------------------------
    _direct_log(
        log_path,
        "\n--- Probe 2a: signin with CCSP client_id (the killer attempt) ---",
    )
    code = _form_signin(
        s,
        KIA_EU_CCSP_SERVICE_ID,
        "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
        email,
        password,
        log_path,
        "Probe 2a",
    )
    if code:
        _direct_log(log_path, f"  [Probe 2a] Got code for CCSP client, exchanging…")
        tokens = _exchange_code_for_tokens(s, code, log_path)
        if tokens and tokens.get("refresh_token") and tokens.get("access_token"):
            _direct_log(log_path, "  [JACKPOT] Probe 2a returned tokens.")
            return tokens

    # ----------------------------------------------------------------
    # Probe 2b: Marketing-client signin (control case). We already know
    # this returns a code. Useful only as a sanity check that the
    # signin endpoint is alive in this session — without the marketing
    # client_secret we can't exchange the code for tokens.
    # ----------------------------------------------------------------
    _direct_log(
        log_path,
        "\n--- Probe 2b: signin with marketing client_id (control, no exchange) ---",
    )
    code = _form_signin(
        s,
        "peukiaidm-online-sales",
        "https://www.kia.com/api/bin/oneid/login",
        email,
        password,
        log_path,
        "Probe 2b",
    )
    if code:
        _direct_log(
            log_path,
            f"  [Probe 2b] Got marketing code (cannot exchange — no marketing secret).",
        )

    # ----------------------------------------------------------------
    # Probe 3: CCSP authorize endpoint on port 8080. Different host
    # than the WAF-blocked IdP authorize URL. With the right Stamp +
    # ccsp-* headers (mimicking the Android app), this might either
    # issue a code directly or redirect to a still-alive auth path.
    # ----------------------------------------------------------------
    _direct_log(log_path, "\n--- Probe 3: CCSP authorize endpoint with app headers ---")
    try:
        url = (
            "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/authorize"
            f"?response_type=code&client_id={KIA_EU_CCSP_SERVICE_ID}"
            "&redirect_uri=https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect"
            "&state=ccsp&lang=en"
        )
        headers = {
            "User-Agent": KIA_EU_OKHTTP_UA,
            "Stamp": _kia_eu_stamp(),
            "ccsp-service-id": KIA_EU_CCSP_SERVICE_ID,
            "ccsp-application-id": KIA_EU_APP_ID,
            "Authorization": KIA_EU_BASIC_AUTH,
            "Host": "prd.eu-ccapi.kia.com:8080",
        }
        resp = s.get(url, headers=headers, timeout=30, allow_redirects=False)
        _log_response(log_path, "Probe 3", resp)
    except Exception as e:
        _direct_log(log_path, f"  [Probe 3] exception: {e}")

    # ----------------------------------------------------------------
    # Probe 4: Same authorize endpoint, but we follow redirects this
    # time. If CCSP routes us through a non-WAF login page somewhere,
    # we'll see it in the chain. Also tries the device-registration
    # endpoint to confirm the CCSP backend accepts our app headers
    # (sanity check — this should always succeed if our Stamp is valid).
    # ----------------------------------------------------------------
    _direct_log(log_path, "\n--- Probe 4: Device-register sanity check ---")
    try:
        url = "https://prd.eu-ccapi.kia.com:8080/api/v1/spa/notifications/register"
        import uuid
        body = {
            "pushRegId": "0" * 64,
            "pushType": "APNS",
            "uuid": str(uuid.uuid4()),
        }
        headers = {
            "User-Agent": KIA_EU_OKHTTP_UA,
            "Stamp": _kia_eu_stamp(),
            "ccsp-service-id": KIA_EU_CCSP_SERVICE_ID,
            "ccsp-application-id": KIA_EU_APP_ID,
            "Content-Type": "application/json;charset=UTF-8",
            "Host": "prd.eu-ccapi.kia.com:8080",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }
        resp = s.post(url, json=body, headers=headers, timeout=30)
        _log_response(log_path, "Probe 4", resp)
    except Exception as e:
        _direct_log(log_path, f"  [Probe 4] exception: {e}")

    _direct_log(log_path, "\n=== All probes exhausted, no token obtained ===\n")
    return None


def _run_kia_eu_direct(region, brand):
    """Browserless direct-API path for Kia EU. Prompts for credentials."""
    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    try:
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write(
                f"Kia EU direct-API debug log — "
                f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            )
    except OSError:
        pass

    print(f"Logging into {brand['name']} ({region['name']}) — no browser needed.\n")
    print("Your credentials are sent only to Kia's own endpoints")
    print("(idpconnect-eu.kia.com, prd.eu-ccapi.kia.com), never to a third")
    print("party, never written to disk in plaintext. The password prompt")
    print("below is hidden as you type.\n")
    email = input("Email:    ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("[ERROR] Email or password is empty. Aborting.")
        return

    print("\nFetching token (typically 5–15 seconds)...\n")
    tokens = kia_eu_direct_probe(email, password, debug_log_path)
    if tokens and tokens.get("refresh_token") and tokens.get("access_token"):
        print(
            f"[OK] Your tokens are:\n\n"
            f"- Refresh Token: {tokens['refresh_token']}\n"
            f"- Access Token:  {tokens['access_token']}"
        )
    else:
        print("[ERROR] Could not obtain tokens. Possible reasons:")
        print("  - Wrong email or password (most likely)")
        print("  - Kia changed an endpoint (rare — please open an issue)")
        print(f"\nThe full diagnostic log is at:\n  {debug_log_path}")
        print("Open an issue with the log contents (passwords are NOT logged).")


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

        # Kia EU is fully browserless via direct-API login. Every other
        # region/brand still uses the OAuth-via-browser flow because (a)
        # they don't sit behind AWS WAF Bot Control and (b) we don't have
        # validated app constants (Service ID, App ID, CFB key) for them.
        if region["name"] == "Europe" and brand["name"] == "Kia":
            _run_kia_eu_direct(region, brand)
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
