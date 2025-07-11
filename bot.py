from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def manual_bypass_vplink(url):
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # Headless remove karo agar manually CAPTCHA solve karna hai
    # chrome_options.add_argument("--headless=new")

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(url)
        print("🕐 Solve the CAPTCHA manually...")
        
        # Wait until redirected
        start = time.time()
        timeout = 120

        while True:
            if "vplink.in" not in driver.current_url:
                break
            if time.time() - start > timeout:
                print("⛔ Timed out!")
                break
            time.sleep(2)

        return driver.current_url

    finally:
        driver.quit()
