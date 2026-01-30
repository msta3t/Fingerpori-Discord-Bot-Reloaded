import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

WEBHOOK_URL = "xxx"
TARGET_URL = "https://www.hs.fi/sarjakuvat/fingerpori/"

def get_latest_fingerpori():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        page.goto(TARGET_URL, wait_until="networkidle")
        page.mouse.wheel(0, 500)
        time.sleep(2)

        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        browser.close()

        article = soup.find('article')
        if article:
            img_tag = article.find('img', alt=lambda x: x and "Pertti Jarla" in x)
            if img_tag:
                img_url = img_tag.get('src')
                if "468.jpg" in img_url:
                    img_url = img_url.replace("468.jpg", "978.jpg")
                return img_url
        return None

def send_to_discord(img_url):
    # Get current date in Finnish format (e.g., 26.1.2026)
    today = datetime.now().strftime("%d.%m.%Y")

    payload = {
        "embeds": [
            {
                "title": "Päivän Fingerpori",
                "color": 5814783,  # A nice blue color
                "image": {
                    "url": img_url
                },
                "footer": {
                    "text": f"Fingerpori {today}"
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        ]
    }

    r = requests.post(WEBHOOK_URL, json=payload)
    if r.status_code != 204:
        print(f"Error: {r.text}")

if __name__ == "__main__":
    url = get_latest_fingerpori()
    if url:
        send_to_discord(url)
    else:
        print("Could not find comic.")
