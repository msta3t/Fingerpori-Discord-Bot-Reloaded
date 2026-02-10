from datetime import datetime
from dotenv import load_dotenv
import logging
from playwright.async_api import async_playwright
import re
import time

load_dotenv()

TARGET_URL = "https://www.hs.fi/sarjakuvat/fingerpori/"
IMAGE_PATH = "images/"

logger = logging.getLogger("fingerpori_scraper")

def get_year(comic_month: int):
    now = datetime.now()
    year = now.year

    if now.month == 1 and comic_month == 12:
        year -= 1
    return year


async def get_latest_fingerpori() -> dict[str,(str | bytes | None)] | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await page.goto(TARGET_URL, wait_until="networkidle")
        await page.mouse.wheel(0, 500)
        time.sleep(2)

        article = page.locator("article")
        if await article.count() == 0:
            return None

        img_locator = article.get_by_alt_text(re.compile(r"Pertti Jarla"))
        date_locator = article.locator("span.timestamp-label")

        if await img_locator.count() > 0:
            img_url = await img_locator.get_attribute("src")
            if not img_url:
                logger.critical("image url not found!")
                return None
            if "468.jpg" in img_url:
                img_url = img_url.replace("468.jpg", "978.jpg")
            
            response = await page.request.get(img_url)
            if response.status == 200:
                img_bytes = await response.body()
            else:
                img_bytes = None
                logger.critical(f"failed to download image with code: {response.status}")

            raw_date = await date_locator.inner_text() if await date_locator.count() > 0 else ""
            match = re.search(r"(\d{1,2}\.\d{1,2}\.)", raw_date)
            if match:
                date_str = match.group(1)
                date_str += str(get_year(int(date_str.split(".")[1])))
                date = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
            else:
                date = datetime.now().strftime("%Y-%m-%d")
    
            return {
                "date": date,
                "url": img_url,
                "bytes": img_bytes
            }
    
        return None
