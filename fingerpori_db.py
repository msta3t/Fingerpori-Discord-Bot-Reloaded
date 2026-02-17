import io
import logging
import os
from dataclasses import dataclass
from enum import IntEnum
from typing import override

import aiosqlite
import imagehash
from dotenv import load_dotenv
from PIL import Image

logger = logging.getLogger("fingerpori_db")


class RatingMode(IntEnum):
    NONE = 0
    VIEW = 1
    SNOOP = 2

    @classmethod
    @override
    def _missing_(cls, value: object) -> "RatingMode":
        return cls.VIEW


@dataclass
class Comic:
    id: int
    date: str
    img_hash: str
    url: str
    path: str
    content: bytes = b""
    poll_closed: bool = False


@dataclass
class ComicMessage:
    guild_id: int
    comic_id: int
    message_id: int
    channel_id: int


@dataclass
class GuildData:
    guild_id: int
    channel_id: int
    rating_mode: RatingMode


if not load_dotenv():
    logger.critical("could not load .env !!")

DB = os.getenv("DB") or "fpori.db"
IMAGE_PATH = "images/"


class DbManager:
    def __init__(self):
        self.db: str = DB
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db)
        await self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = aiosqlite.Row
        await self._create_tables()
        return self

    @property
    def connection(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("DbManager.connect() was never called")
        return self.conn

    async def _create_tables(self):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS comic (
                    comic_id INTEGER PRIMARY KEY,
                    date TEXT UNIQUE NOT NULL,
                    hash TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    path TEXT NOT NULL,
                    poll_closed INTEGER DEFAULT 0,
                    scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
            """
            )
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS guild (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    rating_mode INTEGER DEFAULT 1 CHECK (rating_mode BETWEEN 0 AND 3) -- 0 = none, 1 = view, 2 = reaction, 3 = poll
                    )
            """
            )
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS message (
                    guild_id INTEGER,
                    comic_id INTEGER,
                    message_id INTEGER UNIQUE NOT NULL,
                    channel_id INTEGER NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, comic_id),
                    FOREIGN KEY (guild_id) REFERENCES guild(guild_id),
                    FOREIGN KEY (comic_id) REFERENCES comic(comic_id)
                    )
            """
            )
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS vote (
                    comic_id INTEGER,
                    user_id INTEGER,
                    rating INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (comic_id, user_id),
                    FOREIGN KEY (comic_id) REFERENCES comic(comic_id),
                    FOREIGN KEY (message_id) REFERENCES message(message_id)
                )
            """
            )
            await self.connection.commit()

    async def new_guild(self, guild_id: int, channel_id: int | None):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "INSERT OR IGNORE INTO guild (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id),
            )
            logger.debug(f"Added {cursor.rowcount} rows in table: guild")
            if cursor.rowcount == 0:
                logger.error(
                    f"adding guild failed!!\nguild_id: {guild_id}\tchannel_id: {channel_id}"
                )
                return None
            await self.connection.commit()
            return True

    async def set_active_channel(self, guild_id: int, channel_id: int):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE guild SET channel_id = ? WHERE guild_id = ?",
                (channel_id, guild_id),
            )
            if cursor.rowcount == 0:
                logger.error(
                    f"setting active channel failed!!\nguild_id: {guild_id}\tchannel_id: {channel_id}"
                )
                return None
            await self.connection.commit()
            return True

    async def set_rating_mode(self, guild_id: int, rating_mode: int):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE guild SET rating_mode = ? WHERE guild_id = ?",
                (rating_mode, guild_id),
            )
            if cursor.rowcount == 0:
                logger.error(
                    f"setting rating mode failed!!\nguild_id: {guild_id}\tchannel_id: {rating_mode}"
                )
                return None
            await self.connection.commit()
            return True

    async def get_guilds(self) -> list[GuildData] | None:
        async with self.connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM guild")
            rows = await cursor.fetchall()
            return (
                [
                    GuildData(
                        guild_id=row[0],
                        channel_id=row[1],
                        rating_mode=RatingMode(row[2]),
                    )
                    for row in rows
                ]
                if rows
                else []
            )

    async def save_comic(self, date: str, url: str, bytes: bytes | None):
        fname = url.split("/")[3]
        path = (
            f"{IMAGE_PATH}{date}_{fname}.jpg"  # images/yyyy-mm-dd-1234567890abcdef.jpg
        )
        if not bytes:
            raise Exception("no image provided")
        img_content = bytes
        with Image.open(io.BytesIO(img_content)) as img:
            image_hash = str(imagehash.phash(img))

        try:
            async with self.connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT OR IGNORE INTO comic (date, hash, url, path) VALUES (?, ?, ?, ?) RETURNING comic_id",
                    (date, image_hash, url, path),
                )
                row = await cursor.fetchone()
                if row is None:
                    logger.info(f"comic is already in db: \ndate:\t{date}\nhash:\t")
                    return None
                if not os.path.exists(IMAGE_PATH):
                    os.makedirs(IMAGE_PATH)
                with open(path, "wb") as f:
                    f.write(img_content)
                    logger.debug(f"comic stored in db: \ndate:\t{date}\nhash:\t")

                comic_id = row[0]
                if not isinstance(comic_id, int):
                    logger.critical(f"malformed comic id {comic_id}")

                await self.connection.commit()
        except aiosqlite.Error as e:
            logger.error(f"db error: {e}")
            await self.connection.rollback()
            return None
        except Exception as e:
            logger.error(f"saving comic failed: {e}")
            return None
        return Comic(comic_id, date, image_hash, url, path, img_content)

    async def new_message(
        self, guild_id: int, comic_id: int, message_id: int, channel_id: int
    ):
        try:
            async with self.connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT OR IGNORE INTO message (guild_id, comic_id, message_id, channel_id) VALUES (?,?,?,?)",
                    (guild_id, comic_id, message_id, channel_id),
                )
                if cursor.rowcount == 0:
                    logger.error(
                        f"inserting message failed!\nguild_id: {guild_id}\tcomic_id: {comic_id}\tmessage_id: {message_id}"
                    )
                    return None
                await self.connection.commit()
                return True
        except aiosqlite.Error as e:
            logger.error(f"db error {e}")
        except Exception as e:
            logger.error(f"error saving message: {e}")

    async def get_message_ids_by_comic_id(self, comic_id: int):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "SELECT message_id FROM message WHERE comic_id = ?", (comic_id,)
            )
            rows = await cursor.fetchall()
            messages = [row[0] for row in rows]
            return messages

    async def get_active_comic_ids(self) -> set[int]:
        async with self.connection.cursor() as cursor:
            await cursor.execute("SELECT comic_id FROM comic WHERE poll_closed = 0")
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def get_active_messages(self):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT message.message_id, message.channel_id, guild.guild_id, comic.comic_id, guild.rating_mode 
                FROM message
                JOIN comic ON message.comic_id = comic.comic_id
                JOIN guild ON message.guild_id = guild.guild_id
                WHERE comic.poll_closed = 0
                """
            )
            rows = await cursor.fetchall()
            return (
                [
                    (
                        row["message_id"],
                        row["channel_id"],
                        row["guild_id"],
                        row["comic_id"],
                        row["rating_mode"],
                    )
                    for row in rows
                ]
                if rows
                else []
            )

    async def close_polls(self, comic_ids: set[int]):
        placeholder = ", ".join(["?"] * len(comic_ids))
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                f"UPDATE comic SET poll_closed = 1 WHERE comic_id IN ({placeholder})",
                list(comic_ids),
            )
            await self.connection.commit()

    async def get_past_n_comics(self, count: int):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                "SELECT comic_id, date, hash, url, path, poll_closed FROM comic ORDER BY date DESC LIMIT ?",
                (count,),
            )
            rows = await cursor.fetchall()
            return (
                [
                    Comic(
                        id=row[0],
                        date=row[1],
                        img_hash=row[2],
                        url=row[3],
                        path=row[4],
                        poll_closed=row[5],
                    )
                    for row in rows
                ]
                if rows
                else []
            )

    async def save_vote(
        self, comic_id: int, user_id: int, rating: int, message_id: int
    ):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                """INSERT INTO vote (comic_id, user_id, rating, message_id) 
               VALUES (?, ?, ?, ?)
               ON CONFLICT(comic_id, user_id) DO UPDATE SET 
               rating = excluded.rating, 
               timestamp = CURRENT_TIMESTAMP""",
                (
                    comic_id,
                    user_id,
                    rating,
                    message_id,
                ),
            )
            await self.connection.commit()

    async def get_votes(self, guild_id: int, comic_id: int):
        async with self.connection.cursor() as cursor:
            await cursor.execute(
                """SELECT 
                    rating,
                    COUNT(*) FILTER (WHERE message_id IN (SELECT message_id FROM message WHERE guild_id = ?)) as local_count,
                    COUNT(*) as global_count
                FROM vote
                WHERE comic_id = ?
                GROUP BY rating""",
                (guild_id, comic_id),
            )
            rows = await cursor.fetchall()
            return {
                row[0]: (row[1], row[2]) for row in rows
            }  # {rating: (local, global)}

    async def get_guild_user_votes(self, guild_id:int, comic_id:int) -> list[dict[str, int]]:
        """
        Gets local user ratings for a specific comic in a guild

        Args:
            guild_id (int): Discord ID of the guild to filter by
            comic_id (int): Internal comic ID

        Returns:
            A list of dicts sorted by rating descending {user_id, rating}

        Raises:
            sqlite3.Error: If query fails
        """
        try:
            async with self.connection.cursor() as cursor:
                await cursor.execute("""
                    SELECT vote.user_id, vote.rating
                    FROM vote
                    JOIN message ON vote.message_id = message.message_id
                    WHERE vote.comic_id = ? AND message.guild_id = ?
                    ORDER BY vote.rating DESC
                """,
                    (comic_id, guild_id),
                )
                rows = await cursor.fetchall()
                return [{"user_id": row[0], "rating": row[1]} for row in rows]
        except aiosqlite.Error as e:
            logger.critical(f"DB error when getting ratings for guild id {guild_id}: {e}")
            raise

    async def close(self):
        await self.connection.close()
