from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
import os
from playwright.sync_api import sync_playwright
import re
import requests
import time

from fingerpori_db import DbManager

load_dotenv()

TARGET_URL = "https://www.hs.fi/sarjakuvat/fingerpori/"
IMAGE_PATH = "images/"


def get_year(comic_month: int):
    now = datetime.now()
    year = now.year

    if now.month == 1 and comic_month == 12:
        year -= 1
    return year


def get_latest_fingerpori():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        page.goto(TARGET_URL, wait_until="networkidle")
        page.mouse.wheel(0, 500)
        time.sleep(2)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        browser.close()

        article = soup.find("article")
        if article:
            img_tag = article.find("img", alt=lambda x: x and "Pertti Jarla" in x)  
            date = article.find("span", class_=lambda x: x and "timestamp-label" in x).getText()  

            match = re.search(r"(\d{1,2}\.\d{1,2}\.)", date)
            if match:
                date = match.group(1)
                date += str(get_year(int(date.split(".")[1])))
                date = datetime.strptime(date, "%d.%m.%Y").strftime("%Y-%m-%d")
            else:
                date = datetime.now().strftime("%Y-%m-%d")

            if img_tag:
                img_url = img_tag.get("src")
                if "468.jpg" in img_url:  
                    img_url = img_url.replace("468.jpg", "978.jpg")  
                return {"date": date, "url": img_url}
        return None


def send_to_webhook(comic):
    if comic:
        date = comic["date"]
        url = comic["url"]

        datef = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
        payload = {
            "embeds": [
                {
                    "title": "Päivän Fingerpori",
                    "color": 5814783,  # A nice blue color
                    "image": {"url": url},
                    "footer": {"text": f"Fingerpori {datef}"},
                }
            ]
        }
        if conn:
            db.save_comic(date, url)
        else:
            print("could not save comic to db")
    else:
        payload = {"content": "botti rikki :/"}
    r = requests.post(WEBHOOK_URL, json=payload)  
    if r.status_code != 204:
        print(f"Error: {r.text}")


if __name__ == "__main__":
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    db = DbManager()
    conn = db.conn

    comic = get_latest_fingerpori()
    send_to_webhook(comic)
