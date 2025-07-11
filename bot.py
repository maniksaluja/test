import undetected_chromedriver as uc
import time

def bypass_vplink(url):
    options = uc.ChromeOptions()
    
    # ⚠️ HEADLESS OFF for manual interaction
    # options.add_argument("--headless=new")  ❌ HATA DIYA
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")

    # ✅ subprocess mode to avoid session errors
    driver = uc.Chrome(options=options, use_subprocess=True)

    try:
        driver.get(url)
        print("🕐 Waiting for you to solve CAPTCHA...")

        timeout = 180  # 3 minutes max
        start = time.time()

        while "vplink.in" in driver.current_url:
            if time.time() - start > timeout:
                print("❌ Timed out waiting for manual solve!")
                return None
            time.sleep(2)

        print("✅ Redirect complete!")
        return driver.current_url

    finally:
        driver.quit()

# ▶️ Run
short_url = "https://vplink.in/7qQve"
final = bypass_vplink(short_url)
print("👉 Final Link:", final)
