import os
import re
import shutil
import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import requests
import chromedriver_autoinstaller

session = requests.Session()

BRANDS = {
    "1": {
        "name": "Kia",
        "client_id": "fdc85c00-0a2f-4c64-bcb4-2cfb1500730a",
        "client_secret": "secret",
        "base_url": "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/",
        "login_url": (
            "https://idpconnect-eu.kia.com/auth/api/v2/user/oauth2/authorize"
            "?ui_locales=de&scope=openid%20profile%20email%20phone&response_type=code"
            "&client_id=peukiaidm-online-sales"
            "&redirect_uri=https://www.kia.com/api/bin/oneid/login"
            "&state=aHR0cHM6Ly93d3cua2lhLmNvbTo0NDMvZGUvP21zb2NraWQ9MjM1NDU0ODBm"
            "NmUyNjg5NDIwMmU0MDBjZjc2OTY5NWQmX3RtPTE3NTYzMTg3MjY1OTImX3RtPTE3"
            "NTYzMjQyMTcxMjY=_default"
        ),
        "success_selector": "a[class='logout user']",
        "redirect_url_final": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/redirect",
    },
    "2": {
        "name": "Hyundai",
        "client_id": "6d477c38-3ca4-4cf3-9557-2a1929a94654",
        "client_secret": "KUy49XxPzLpLuoK0xhBC77W6VXhmtQR9iQhmIFjjoY4IpxsV",
        "base_url": "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/",
        "login_url": (
            "https://idpconnect-eu.hyundai.com/auth/api/v2/user/oauth2/authorize"
            "?client_id=peuhyundaiidm-ctb"
            "&redirect_uri=https%3A%2F%2Fctbapi.hyundai-europe.com%2Fapi%2Fauth"
            "&nonce=&state=EN_&scope=openid+profile+email+phone&response_type=code"
            "&connector_client_id=peuhyundaiidm-ctb"
            "&connector_scope=&connector_session_key=&country=&captcha=1"
            "&ui_locales=en-US&lang=en"
        ),
        "success_selector": "button.mail_check",
        "redirect_url_final": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36_CCS_APP_AOS"
)


def install_chromedriver():
    """Install a matching chromedriver, exit if Chrome is not found."""
    try:
        chromedriver_autoinstaller.get_chrome_version()
    except Exception:
        print(
            "[ERROR] Google Chrome not found. "
            "Please install Google Chrome and try again."
        )
        sys.exit(1)
    try:
        return chromedriver_autoinstaller.install()
    except Exception as e:
        print(f"[ERROR] Failed to install chromedriver: {e}")
        sys.exit(1)


def create_driver():
    """
    Install chromedriver and start Chrome with anti-detection flags.
    Retries once with a clean reinstall if the first attempt fails.
    """
    driver_path = install_chromedriver()

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    chrome_options.add_argument("--window-size=1000,800")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service(driver_path)
        return webdriver.Chrome(service=service, options=chrome_options)
    except WebDriverException:
        # Clean up broken install and retry once
        try:
            driver_dir = os.path.dirname(driver_path)
            if os.path.exists(driver_dir):
                shutil.rmtree(driver_dir, ignore_errors=True)
        except Exception:
            pass

        try:
            driver_path = chromedriver_autoinstaller.install()
            service = Service(driver_path)
            return webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            print(f"[ERROR] Could not start Chrome after reinstall: {e}")
            sys.exit(1)


def select_brand():
    print("Select your brand:\n")
    print("  1) Kia (EU)")
    print("  2) Hyundai (EU) -- experimental, needs community validation")
    print()
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice in BRANDS:
            brand = BRANDS[choice]
            print(f"\n-> {brand['name']} selected.\n")
            return brand
        print("Invalid choice. Please enter 1 or 2.")


def main():
    brand = select_brand()

    base_url = brand["base_url"]
    redirect_url = (
        f"{base_url}authorize?response_type=code"
        f"&client_id={brand['client_id']}"
        f"&redirect_uri={brand['redirect_url_final']}"
        f"&lang=de&state=ccsp"
    )
    token_url = f"{base_url}token"

    driver = create_driver()

    print(f"Opening {brand['name']} login page...")
    driver.get(brand["login_url"])

    print("\n" + "=" * 50)
    print("Please log in manually in the browser window.")
    print("The script will wait for you to complete the login...")
    print("=" * 50 + "\n")

    try:
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
        driver.get(redirect_url)

        try:
            wait = WebDriverWait(driver, 20)
            wait.until(
                lambda d: "code=" in d.current_url or "error" in d.current_url
            )
        except TimeoutException:
            raise Exception(
                "Timed out waiting for OAuth redirect. "
                "The authorization server did not return a code."
            )

        current_url = driver.current_url

        match = re.search(r"[?&]code=([^&]+)", current_url)
        if not match:
            raise Exception("Authorization code not found in redirect URL.")

        code = match.group(1)
        print("[OK] Authorization code found.")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": brand["redirect_url_final"],
            "client_id": brand["client_id"],
            "client_secret": brand["client_secret"],
        }
        response = session.post(token_url, data=data)
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

    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        print("Cleaning up and closing the browser.")
        driver.quit()


if __name__ == "__main__":
    main()
