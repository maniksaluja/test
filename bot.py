from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

def bypass_short_url_selenium(short_url, timeout=20):
    try:
        # Configure headless Chrome
        options = Options()
        options.add_argument("--headless=new")  # New headless mode for better compatibility
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")  # Fix for limited /dev/shm
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popups")
        options.add_argument("--window-size=1920,1080")  # Set window size for stability
        
        # Initialize driver with Service
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.get(short_url)
        
        # Wait for page to load
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Wait for redirects
        time.sleep(5)  # Redirect ke liye wait
        final_url = driver.current_url
        
        # Check for CAPTCHA
        try:
            captcha = driver.find_element(By.CLASS_NAME, "g-recaptcha")
            print("CAPTCHA mila! Manual solve karna padega ya 2Captcha use karo.")
        except:
            print("No CAPTCHA. Final URL mil gaya.")
        
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
