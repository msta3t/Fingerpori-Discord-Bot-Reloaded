from dataclasses import dataclass
from dotenv import load_dotenv
import imagehash
import io
import logging
import os
from PIL import Image
import requests
import sqlite3
from typing import Optional

logger = logging.getLogger("fingerpori_db")

@dataclass
class Comic:
    date: str
    img_hash: str
    url: str
    path: str
    content: bytes = b""
    message_id: Optional[int] = None
    poll_closed: bool = True


load_dotenv()

DB = os.getenv("DB")
IMAGE_PATH = "images/"


class DbManager:
    def __init__(self):
        db = DB
        self.conn = sqlite3.connect(db)  # type: ignore
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fingerpori (
                date TEXT PRIMARY KEY,
                hash TEXT UNIQUE,
                url TEXT,
                path TEXT,
                message_id INTEGER,
                poll_closed INTEGER DEFAULT 0,
                rating_0 INTEGER DEFAULT 0,
                rating_1 INTEGER DEFAULT 0,
                rating_2 INTEGER DEFAULT 0,
                rating_3 INTEGER DEFAULT 0,
                rating_4 INTEGER DEFAULT 0,
                rating_5 INTEGER DEFAULT 0
                )
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
                )
        """
        )
        self.conn.commit()

    def get_config(self, key: str, default=None):
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

    def set_config(self, key: str, value: str):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        self.conn.commit()

    def save_comic(self, date: str, url: str):
        fname = url.split("/")[3]
        path = (
            f"{IMAGE_PATH}{date}_{fname}.jpg"  # images/yyyy-mm-dd-1234567890abcdef.jpg
        )
        img = requests.get(url)
        if img.status_code == 200:
            img_content = img.content
            with Image.open(io.BytesIO(img_content)) as img:
                image_hash = str(imagehash.phash(img))

        else:
            raise Exception(f"image download for comic {date} failed with status: {img.status_code}")

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO fingerpori (date, hash, url, path) VALUES (?, ?, ?, ?)",
                (date, image_hash, url, path),
            )
            self.conn.commit()

            if cursor.rowcount > 0:
                if not os.path.exists(IMAGE_PATH):
                    os.makedirs(IMAGE_PATH)
                with open(path, "wb") as f:
                    f.write(img_content)
                logger.debug(f"comic stored in db: \ndate:\t{date}\nhash:\t")
            else:
                logger.info(f"comic is already in db: \ndate:\t{date}\nhash:\t")
                return None
        except sqlite3.Error as e:
            logger.error(f"db error: {e}")
            return None
        except Exception as e:
            logger.error(f"saving comic failed: {e}")
            return None
        return Comic(date, image_hash, url, path, img_content)

    def update_message_id(self, comic: Comic):
        try:
            if not comic.message_id:
                raise Exception(f"comic {comic.date} missing message_id")
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE fingerpori SET MESSAGE_ID = ? WHERE hash = ?",
                (comic.message_id, comic.img_hash),
            )
            self.conn.commit()

            if cursor.rowcount == 0:
                raise Exception(
                    f"no rows found for {comic.message_id}"
                )
            else:
                logger.debug(f"message id updated: \ndate:\t{comic.date}\nmessage_id:\t{comic.message_id}")
        except Exception as e:
            logger.error(f"error updating message_id: {e}")

    def update_ratings(self, comic: Comic, ratings: list):
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE fingerpori SET poll_closed = 1, rating_0 = ?, rating_1 = ?, rating_2 = ?, rating_3 = ?, rating_4 = ?, rating_5 = ? WHERE date = ?",
                (
                    ratings[0],
                    ratings[1],
                    ratings[2],
                    ratings[3],
                    ratings[4],
                    ratings[5],
                    comic.date,
                ),
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"error updating ratings: {e}")

    def get_past_n_comics(self, count: int):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT date, hash, url, path, message_id, poll_closed FROM fingerpori ORDER BY date DESC LIMIT ?",
            (count,),
        )
        rows = cursor.fetchall()
        return (
            [
                Comic(
                    date=row[0],
                    img_hash=row[1],
                    url=row[2],
                    path=row[3],
                    message_id=row[4],
                    poll_closed=row[5]
                )
                for row in rows
            ]
            if rows
            else []
        )

    def close(self):
        self.conn.close()
