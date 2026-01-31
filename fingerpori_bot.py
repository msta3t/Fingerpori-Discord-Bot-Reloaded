import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
TARGET_URL = "https://www.hs.fi/sarjakuvat/fingerpori/"
DB = "fpori.db"
IMAGE_PATH = "images/"

def init_db(db):
    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fingerpori (
                id INTEGER PRIMARY KEY,
                date TEXT,
                url TEXT,
                path TEXT
                rating_0 INTEGER DEFAULT 0,
                rating_1 INTEGER DEFAULT 0,
                rating_2 INTEGER DEFAULT 0,
                rating_3 INTEGER DEFAULT 0,
                rating_4 INTEGER DEFAULT 0,
                rating_5 INTEGER DEFAULT 0
                )
        ''')

        conn.commit()
        return conn
    except sqlite3.Error as e:
        print(f"sqlite error: {e}")
        if conn:
            conn.rollback()
        return None
    except Exception as e:
        print(f"other error: {e}")
        return None
    
def save_db(conn, img_url, today):
    fname = img_url.split('/')[3]
    path = IMAGE_PATH + fname + ".jpg"
    img = requests.get(img_url)
    if img.status_code == 200:
        if not os.path.exists(IMAGE_PATH):
            os.makedirs(IMAGE_PATH)
        with open(path, "wb") as f:
            f.write(img.content)
    
    cursor = conn.cursor()
    cursor.execute('INSERT INTO fingerpori (date, url, path) VALUES (?, ?, ?)',
                   (today, img_url, path))


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
            img_tag = article.find('img', alt=lambda x: x and "Pertti Jarla" in x) # type: ignore
            if img_tag:
                img_url = img_tag.get('src')
                if "468.jpg" in img_url: # type: ignore
                    img_url = img_url.replace("468.jpg", "978.jpg") # type: ignore
                return img_url
        return None

def send_to_discord(img_url):
    # Get current date in Finnish format (e.g., 26.1.2026)
    today = datetime.now().strftime("%d.%m.%Y")

    conn = init_db(DB)

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
    
    save_db(conn, img_url, today)

    r = requests.post(WEBHOOK_URL, json=payload) # type: ignore
    if r.status_code != 204:
        print(f"Error: {r.text}")

if __name__ == "__main__":
    url = get_latest_fingerpori()
    if url:
        send_to_discord(url)
    else:
        print("Could not find comic.")
