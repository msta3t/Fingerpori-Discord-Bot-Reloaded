from dataclasses import dataclass
from dotenv import load_dotenv
import imagehash
import io
import os
from PIL import Image
import requests
import sqlite3
from typing import Optional

@dataclass
class Comic:
    date: str
    img_hash: str
    url: str
    path: str
    content: bytes = b""
    message_id: Optional[int] = None


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
            raise Exception(f"image download failed with status: {img.status_code}")

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
                print(f"comic {date} saved to db")
            else:
                print(f"comic {date} is already in db")
                return None
        except sqlite3.Error as e:
            print(f"db error: {e}")
            return None
        except Exception as e:
            print(f"saving comic failed: {e}")
            return None
        return Comic(date, image_hash, url, path, img_content)

    def update_message_id(self, comic: Comic):
        try:
            if not comic.message_id:
                raise Exception("comic missing message_id")
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE fingerpori SET MESSAGE_ID = ? WHERE hash = ?",
                (comic.message_id, comic.img_hash),
            )
            self.conn.commit()

            if cursor.rowcount == 0:
                raise Exception(
                    f"update message_id failed: no rows found for {comic.message_id}"
                )
            else:
                print(f"message id updated: {comic.date}, {comic.message_id}")
        except Exception as e:
            print(f"error updating message_id: {e}")

    def update_reactions(self, comic: Comic, ratings: list):
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE fingerpori SET rating_0 = ?, rating_1 = ?, rating_2 = ?, rating_3 = ?, rating_4 = ?, rating_5 = ? WHERE hash = ?",
                (
                    ratings[0],
                    ratings[1],
                    ratings[2],
                    ratings[3],
                    ratings[4],
                    ratings[5],
                    comic.img_hash,
                ),
            )
            self.conn.commit()
        except Exception as e:
            print(f"error syncing reactions: {e}")

    def get_past_n_comics(self, count: int):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT date, hash, url, path, message_id FROM fingerpori ORDER BY date DESC LIMIT ?",
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
                )
                for row in rows
            ]
            if rows
            else []
        )

    def close(self):
        self.conn.close()
