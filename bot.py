import undetected_chromedriver as uc
import time

def bypass_vplink(url):
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Don't headless if CAPTCHA needs manual solve
    # options.headless = True

    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        print("🕐 Waiting to redirect or solve CAPTCHA...")
        timeout = 120
        start = time.time()

        while True:
            if "vplink.in" not in driver.current_url:
                break
            if time.time() - start > timeout:
                print("❌ Timed out.")
                break
            time.sleep(2)

        return driver.current_url

    finally:
        driver.quit()

# Example
short_url = "https://vplink.in/7qQve"
final = bypass_vplink(short_url)
print("👉 Final Link:", final)
