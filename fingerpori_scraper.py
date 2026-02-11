import asyncio
import logging
import os
import re
import time
from datetime import datetime

import aiohttp
import discord
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from fingerpori_db import DbManager

load_dotenv()

TARGET_URL = "https://www.hs.fi/sarjakuvat/fingerpori/"
IMAGE_PATH = "images/"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

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

        article = page.locator("article").first
        if await article.count() == 0:
            return None

        img_locator = article.get_by_alt_text(re.compile(r"Pertti Jarla")).first
        date_locator = article.locator("span.timestamp-label").first

        if await img_locator.count() > 0:
            img_url = await img_locator.get_attribute("src")
            if not img_url:
                logger.critical("image url not found!")
                return None
            if "468.jpg" in img_url:
                # img_url = img_url.replace("468.jpg", "978.jpg")
                img_url = img_url.replace("468.jpg", "1920.jpg")
            
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

async def send_to_webhook(comic:dict[str,(str|bytes|None)] | None):
    if not WEBHOOK_URL:
        return logger.critical("no webhook url provided")
    
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        if comic:
            img_date:str = comic["date"] # pyright: ignore[reportAssignmentType]
            img_url:str = comic["url"] # pyright: ignore[reportAssignmentType]
            img_bytes:bytes = comic["bytes"] # pyright: ignore[reportAssignmentType]

            datef = datetime.strptime(img_date, "%Y-%m-%d").strftime("%d.%m.%Y")

            embed = discord.Embed(
                title="Päivän Fingerpori",
                color=5814783,
            )
            embed.set_image(url=img_url)
            embed.set_footer(text=f"Fingerpori {datef}")

            if db.conn:
                await db.save_comic(img_date, img_url, img_bytes)
            else:
                logger.warning(f"could not save comic to db: {img_date} {img_url}")

            await webhook.send(embed=embed)

        else:
            await webhook.send(content="botti rikki :/")

async def main():
    await db.connect()
    comic = await get_latest_fingerpori()
    await send_to_webhook(comic)

if __name__ == "__main__":
    db = DbManager()
    asyncio.run(main())