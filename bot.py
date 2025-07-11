from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

def bypass_short_url_selenium(short_url, timeout=20):
    try:
        # Configure headless Chrome
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popups")
        
        # Initialize driver with Chromium
        driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
        driver.get(short_url)
        
        # Wait for page to load or redirect
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Wait for potential redirects
        time.sleep(5)  # Adjust if redirects take longer
        final_url = driver.current_url
        
        # Check for CAPTCHA
        try:
            captcha = driver.find_element(By.CLASS_NAME, "g-recaptcha")
            print("CAPTCHA detected. Manual intervention may be required.")
        except:
            print("No CAPTCHA detected. Proceeding to final URL.")
        
        driver.quit()
        return final_url
    except Exception as e:
        if 'driver' in locals():
            driver.quit()
        return f"Error: {e}"

# Example usage
short_url = "https://vplink.in/7qQve"
final_url = bypass_short_url_selenium(short_url)
print(f"Final URL: {final_url}")
