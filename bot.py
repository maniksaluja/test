import undetected_chromedriver as uc
import time

def bypass_vplink(url):
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")  # IMPORTANT for headless
    options.add_argument("--no-sandbox")    # IMPORTANT
    options.add_argument("--disable-dev-shm-usage")  # For VPS memory issues
    options.add_argument("--disable-gpu")   # GPU disable
    options.add_argument("--disable-blink-features=AutomationControlled")  # Less detectable

    driver = uc.Chrome(options=options, use_subprocess=True)

    try:
        driver.get(url)
        print("🕐 Waiting for redirect...")
        timeout = 120
        start = time.time()

        while "vplink.in" in driver.current_url:
            if time.time() - start > timeout:
                print("❌ Timed out!")
                return None
            time.sleep(2)

        return driver.current_url

    finally:
        driver.quit()

# Run it
short_url = "https://vplink.in/7qQve"
final = bypass_vplink(short_url)
print("👉 Final Link:", final)
