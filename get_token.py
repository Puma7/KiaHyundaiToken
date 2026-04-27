import base64
import datetime as dt
import getpass
import json
import os
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

# Mobile UA used by Maximum mode — matches the platform suggested by
# the _CCS_APP_AOS suffix (Android), so the User-Agent is internally
# consistent instead of a desktop browser claiming to be the mobile app.
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Mobile Safari/537.36_CCS_APP_AOS"
)

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


def _chrome_major_version():
    """Return the installed Chrome major version (e.g. 125), or None."""
    try:
        full = chromedriver_autoinstaller.get_chrome_version()
        # Returns a string like "125.0.6422.78"
        return int(full.split(".")[0])
    except Exception:
        return None


def _create_stealth_driver(user_agent):
    """
    Stealth path using undetected-chromedriver. Patches the chromedriver
    binary at runtime to drop cdc_ markers, hides navigator.webdriver,
    and strips automation switches that the standard path can only mask.

    Use this when the standard path fails with anti-bot detection
    (e.g. Kia EU IdP "abusing request" 400).
    """
    try:
        import undetected_chromedriver as uc
    except ImportError as e:
        raise RuntimeError(
            "Stealth mode requires the 'undetected-chromedriver' package. "
            "Install it with: python -m pip install undetected-chromedriver"
        ) from e

    # Build options via uc.ChromeOptions — uc handles excludeSwitches,
    # useAutomationExtension and navigator.webdriver internally, so we
    # only set the user agent here. --start-maximized is more reliable
    # than driver.maximize_window() with uc on Windows.
    options = uc.ChromeOptions()
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--start-maximized")

    print(
        "[Stealth] Starting undetected Chrome — first run downloads and "
        "patches its own ChromeDriver, this can take 10–30 seconds..."
    )
    try:
        driver = uc.Chrome(
            options=options,
            version_main=_chrome_major_version(),
            use_subprocess=True,
        )
        try:
            driver.maximize_window()
        except WebDriverException:
            # Some uc + Windows combinations fail silently here; the
            # --start-maximized flag is the real safeguard.
            pass
        return driver
    except Exception as e:
        raise RuntimeError(
            f"Could not start Chrome in stealth mode: {e}"
        ) from e


def _create_maximum_driver(user_agent):
    """
    Maximum-stealth + diagnostic path. uc + mobile UA + Chrome
    performance logging so the redirect chain that ends in the abuse
    page can be reconstructed from the network log.
    """
    try:
        import undetected_chromedriver as uc
    except ImportError as e:
        raise RuntimeError(
            "Maximum mode requires the 'undetected-chromedriver' package. "
            "Install it with: python -m pip install undetected-chromedriver"
        ) from e

    options = uc.ChromeOptions()
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--start-maximized")
    # Capture every network event so _dump_debug_info can replay the
    # redirect chain after the run.
    options.set_capability(
        "goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"}
    )

    print(
        "[Maximum] Starting undetected Chrome with mobile UA + network "
        "logging — first run downloads chromedriver, this can take "
        "10–30 seconds..."
    )
    try:
        driver = uc.Chrome(
            options=options,
            version_main=_chrome_major_version(),
            use_subprocess=True,
        )
        try:
            driver.maximize_window()
        except WebDriverException:
            pass
        # Enable Network domain via CDP as a belt-and-braces alongside
        # goog:loggingPrefs. Either source feeds the performance log.
        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except WebDriverException:
            pass
        return driver
    except Exception as e:
        raise RuntimeError(
            f"Could not start Chrome in maximum mode: {e}"
        ) from e


def _navigate_via_click(driver, url):
    """
    Navigate to url by injecting an <a> tag and clicking it. The
    resulting request carries a Referer header pointing to the current
    page, instead of the empty Referer that driver.get() produces.
    Some IdPs use a missing/synthetic Referer as an abuse signal.
    """
    script = (
        "const a = document.createElement('a');"
        "a.href = arguments[0];"
        "a.rel = 'noopener';"
        "a.style.display = 'none';"
        "document.body.appendChild(a);"
        "a.click();"
    )
    driver.execute_script(script, url)


def _safe_truncate(value, limit=80):
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _dump_debug_info(driver, log_path, label):
    """
    Append a snapshot (URL, cookies, performance log) to log_path.
    Best-effort: never raises, so it can be safely called from
    finally blocks.
    """
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== [{label}] {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            try:
                f.write(f"Current URL: {driver.current_url}\n")
            except Exception as e:
                f.write(f"(current_url failed: {e})\n")
            try:
                f.write(f"Title: {driver.title}\n")
            except Exception as e:
                f.write(f"(title failed: {e})\n")

            f.write("\n--- Cookies ---\n")
            try:
                for cookie in driver.get_cookies():
                    domain = cookie.get("domain", "?")
                    name = cookie.get("name", "?")
                    value = _safe_truncate(cookie.get("value"), 40)
                    f.write(f"{domain}\t{name}={value}\n")
            except Exception as e:
                f.write(f"(get_cookies failed: {e})\n")

            f.write("\n--- Network log (last 100 events) ---\n")
            try:
                logs = driver.get_log("performance")[-100:]
                for entry in logs:
                    try:
                        msg = json.loads(entry["message"])["message"]
                    except (KeyError, ValueError):
                        continue
                    method = msg.get("method", "")
                    params = msg.get("params", {}) or {}
                    if method == "Network.requestWillBeSent":
                        req = params.get("request", {})
                        f.write(
                            f"REQ  {req.get('method', '')} "
                            f"{_safe_truncate(req.get('url'), 200)}\n"
                        )
                    elif method == "Network.responseReceived":
                        resp = params.get("response", {})
                        f.write(
                            f"RESP {resp.get('status', '')} "
                            f"{_safe_truncate(resp.get('url'), 200)}\n"
                        )
                    elif method == "Network.requestWillBeSentExtraInfo":
                        # Shows actual headers Chrome will send (incl. Referer)
                        headers = params.get("headers", {}) or {}
                        ref = headers.get("Referer") or headers.get("referer")
                        if ref:
                            f.write(f"  Referer: {_safe_truncate(ref, 200)}\n")
            except Exception as e:
                f.write(f"(performance log unavailable: {e})\n")

            f.write("\n")
    except Exception:
        # Last-resort: never let debug logging break the main flow.
        pass


def create_driver(user_agent, mode="standard"):
    """
    Install chromedriver and start Chrome with anti-detection flags.

    mode: "standard" (default), "stealth", or "maximum".
    Raises RuntimeError if Chrome cannot be started.
    """
    if mode == "maximum":
        return _create_maximum_driver(user_agent)
    if mode == "stealth":
        return _create_stealth_driver(user_agent)
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
    resp = session_obj.post(url, data=data, timeout=30)
    _log_response(log_path, "Token exchange", resp)
    if resp.status_code == 200:
        return resp.json()
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
        f"\n=== Kia EU Direct API Probe — {time.strftime('%Y-%m-%d %H:%M:%S')} ===",
    )
    _direct_log(log_path, f"Email: {email}")

    s = requests.Session()
    s.headers.update({"Accept-Encoding": "gzip"})

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
    # Probe 2: Legacy form-based signin against /auth/account/signin.
    # This is the URL the marketing-site browser flow ultimately POSTs
    # to behind the scenes after reCAPTCHA. If WAF only protects the
    # /auth/api/v2/* paths and not /auth/account/*, this might still
    # accept credentials directly.
    # ----------------------------------------------------------------
    _direct_log(log_path, "\n--- Probe 2: IdP form signin /auth/account/signin ---")
    try:
        url = "https://idpconnect-eu.kia.com/auth/account/signin"
        data = {
            "client_id": "peukiaidm-online-sales",
            "encryptedPassword": "false",
            "username": email,
            "password": password,
            "redirect_uri": "https://www.kia.com/api/bin/oneid/login",
            "state": "ccsp",
            "remember_me": "false",
        }
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://idpconnect-eu.kia.com",
            "Referer": "https://idpconnect-eu.kia.com/",
        }
        resp = s.post(url, data=data, headers=headers, timeout=30, allow_redirects=False)
        _log_response(log_path, "Probe 2", resp)
        # If credentials are accepted, the IdP redirects with code= or
        # to the marketing site. Either way, a 302 with Location is
        # the success indicator.
        if resp.status_code in (302, 303):
            location = resp.headers.get("Location", "")
            match = re.search(r"[?&]code=([^&]+)", location)
            if match:
                code = match.group(1)
                _direct_log(log_path, f"  [Probe 2] Got code, exchanging…")
                tokens = _exchange_code_for_tokens(s, code, log_path)
                if tokens and tokens.get("refresh_token"):
                    return tokens
    except Exception as e:
        _direct_log(log_path, f"  [Probe 2] exception: {e}")

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


def select_mode():
    """
    Ask the user which login flow to use.

    Standard: vanilla Selenium with anti-detection flags + CDP overrides.
    Stealth:  undetected-chromedriver, which patches the chromedriver
              binary at runtime. Try this if Standard hits Kia's
              "abusing request" 400 or similar bot-detection blocks.
    Maximum:  Stealth + mobile UA + JS-click navigation (sets Referer)
              + network logging written to kia_debug.log. Use as a
              last resort and to gather diagnostic data.
    Direct:   No browser. Probes several non-browser API endpoints
              (ROPC token-grant, legacy signin form, CCSP authorize)
              with proper app headers. Kia EU only.
    """
    print("Select login mode:\n")
    print("  1) Standard   (default — try this first)")
    print("  2) Stealth    (undetected-chromedriver — try if Standard fails)")
    print("  3) Maximum    (Stealth + mobile UA + click-nav + debug log)")
    print("  4) Direct     (no browser, direct API probes — Kia EU only)")
    print()
    while True:
        choice = input("Enter mode (1-4) [1]: ").strip() or "1"
        if choice in ("1", "2", "3", "4"):
            break
        print("Invalid choice.")

    mode = {"1": "standard", "2": "stealth", "3": "maximum", "4": "direct"}[choice]
    print(f"\n-> {mode.capitalize()} mode selected.\n")
    if mode == "stealth":
        print("=" * 60)
        print("NOTE: Stealth mode uses undetected-chromedriver. It will")
        print("download its own ChromeDriver on first run and may take a")
        print("few extra seconds to start. If it fails to launch, fall")
        print("back to Standard mode.")
        print("=" * 60 + "\n")
    elif mode == "maximum":
        print("=" * 60)
        print("NOTE: Maximum mode bundles every bypass technique we have")
        print("(undetected-chromedriver + Android mobile User-Agent +")
        print("JS-click navigation that sends a real Referer header) and")
        print("writes a detailed network log to:")
        print(f"  {os.path.abspath(DEBUG_LOG_FILE)}")
        print("If this still fails, send the contents of that log so we")
        print("can see exactly which request triggers the abuse page.")
        print("=" * 60 + "\n")
    elif mode == "direct":
        print("=" * 60)
        print("NOTE: Direct mode skips the browser entirely and talks to")
        print("Kia's CCSP backend / IdP token endpoint with the same")
        print("headers the Android app sends (Stamp, ccsp-service-id,")
        print("etc.). It probes several historical endpoints that may")
        print("or may not still be alive. Every request is logged to:")
        print(f"  {os.path.abspath(DEBUG_LOG_FILE)}")
        print("This mode is experimental — the most recent maintainers")
        print("of hyundai_kia_connect_api report direct password login")
        print("is dead due to reCAPTCHA on the IdP form. We're testing")
        print("anyway because the token endpoint itself is not WAF-")
        print("protected and may accept ROPC.")
        print("=" * 60 + "\n")
    return mode


def _run_direct_mode(region, brand):
    """Mode 4 entry point: prompt for credentials and run the probes."""
    if region["name"] != "Europe" or brand["name"] != "Kia":
        print(
            "[ERROR] Direct mode is only implemented for Europe / Kia. "
            "Other regions/brands need their own constants and probe "
            "logic. Aborting."
        )
        return

    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    try:
        with open(debug_log_path, "w", encoding="utf-8") as f:
            f.write(
                f"Kia EU direct-API debug log — "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
    except OSError:
        pass

    print("Direct mode requires your Kia account credentials. They are sent")
    print("only to Kia's own endpoints (idpconnect-eu.kia.com, prd.eu-ccapi.")
    print("kia.com) — never logged to disk in plaintext, never to a third")
    print("party. The password prompt below is hidden as you type.\n")
    email = input("Email:    ").strip()
    password = getpass.getpass("Password: ")
    if not email or not password:
        print("[ERROR] Email or password is empty. Aborting.")
        return

    print("\nProbing endpoints — this typically takes 5–15 seconds...\n")
    tokens = kia_eu_direct_probe(email, password, debug_log_path)
    if tokens and tokens.get("refresh_token") and tokens.get("access_token"):
        print(
            f"\n[OK] Direct mode succeeded! Your tokens are:\n\n"
            f"- Refresh Token: {tokens['refresh_token']}\n"
            f"- Access Token:  {tokens['access_token']}"
        )
    else:
        print("[ERROR] No probe returned valid tokens.")
        print(f"See {debug_log_path} for the full response of every probe —")
        print("the status codes will tell us which endpoints are alive and")
        print("which are WAF-blocked, so we know what to try next.")


def main():
    region, brand = select_region_and_brand()
    mode = select_mode()

    if mode == "direct":
        _run_direct_mode(region, brand)
        return

    # Use the brand's normal UA for Step 1 (login). In Maximum mode we
    # switch to MOBILE_USER_AGENT via CDP just before Step 2, so the
    # login page (which depends on the desktop UA for the
    # success_selector to appear) keeps working.
    user_agent = brand.get("user_agent", DEFAULT_USER_AGENT)

    debug_log_path = os.path.abspath(DEBUG_LOG_FILE)
    if mode == "maximum":
        # Reset the log for this run so it only contains current data.
        try:
            with open(debug_log_path, "w", encoding="utf-8") as f:
                f.write(f"Kia debug log — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Region: {region['name']}, Brand: {brand['name']}\n")
                f.write(f"User-Agent: {user_agent}\n")
        except OSError:
            pass

    driver = None
    try:
        driver = create_driver(user_agent, mode=mode)

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
            # Pause before the handoff: Kia's EU IdP flags fast back-to-back
            # authorize calls as "abusing requests".
            if mode == "maximum":
                # Switch UA to a real Android UA only for Step 2. The
                # IdP's CCSP authorize endpoint is the one that flags
                # "abuse"; making this single request look like the
                # mobile app is the actual experiment.
                try:
                    driver.execute_cdp_cmd(
                        "Network.setUserAgentOverride",
                        {"userAgent": MOBILE_USER_AGENT},
                    )
                except WebDriverException:
                    pass
                _dump_debug_info(driver, debug_log_path, "before-step-2")
            time.sleep(5)
            try:
                if mode == "maximum":
                    # Click-style navigation sends a real Referer header
                    # from the marketing site, which driver.get() omits.
                    _navigate_via_click(driver, brand["redirect_url"])
                else:
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
            finally:
                if mode == "maximum":
                    _dump_debug_info(driver, debug_log_path, "after-step-2")
        elif "code=" not in driver.current_url:
            # Standard: the login page already redirected (or will
            # redirect) to redirect_url_final?code=...
            # Give it a generous timeout in case the redirect is slow.
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


if __name__ == "__main__":
    main()
