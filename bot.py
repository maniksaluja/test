from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def manual_bypass_vplink(url):
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    # chrome_options.add_argument("--headless")  # Don't use headless if CAPTCHA needs manual solve

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(url)
        print("🕐 Waiting for you to solve CAPTCHA...")

        # Wait for user to solve CAPTCHA and redirect (max 2 mins)
        timeout = 120
        start = time.time()

        while True:
            current_url = driver.current_url
            if "vplink.in" not in current_url:
                print("✅ Final Link Found!")
                break

            if time.time() - start > timeout:
                print("⛔ Timeout waiting for CAPTCHA.")
                break

            time.sleep(3)

        final_url = driver.current_url
        return final_url

    finally:
        driver.quit()

# Example
short_url = "https://vplink.in/7qQve"
link = manual_bypass_vplink(short_url)
print("👉 Final Link:", link)
