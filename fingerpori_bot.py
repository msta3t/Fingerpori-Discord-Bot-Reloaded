import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.utils import _ColourFormatter
from discord.ext import tasks, commands
from dotenv import load_dotenv
import io
import logging
import os
from PIL import Image, ImageOps
import sys
from typing import Optional, TYPE_CHECKING, cast
import zoneinfo

import fingerpori_scraper as scraper
from fingerpori_db import Comic, DbManager

if TYPE_CHECKING:
    from fingerpori_bot import FingerporiBot

load_dotenv()


# logging setup
discord.utils.setup_logging(level=logging.INFO)

root_logger = logging.getLogger()
console_handler = root_logger.handlers[0]

console_formatter = _ColourFormatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)
console_handler.setFormatter(console_formatter)

file_handler = logging.FileHandler("bot.log", encoding="utf-8", mode="w")
file_formatter = logging.Formatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)
file_handler.setFormatter(file_formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("fingerpori_bot")


# post times
TIMEZONE = zoneinfo.ZoneInfo("Europe/Helsinki")
phour, pminute = map(int, os.getenv("POST_TIME", "03:00").split(":"))
post_dt = datetime.now(TIMEZONE).replace(
    hour=phour, minute=pminute, second=0, microsecond=0
)
sub_dt = post_dt - timedelta(minutes=5)

POST_TIME = post_dt.timetz()
SUB_TIME = sub_dt.timetz()


# env
GUILD_ID = os.getenv("GUILD_ID")
TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    sys.exit("no token provided")
if GUILD_ID is None:
    sys.exit("no guild id provided")
GUILD = discord.Object(id=GUILD_ID)


class FingerporiBot(commands.Bot):
    def __init__(self, db: DbManager, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guild_reactions = True
        intents.polls = True
        super().__init__(command_prefix="/", intents=intents)

        self.db = db
        self.channel_id = None
        self.latest_image: Optional[Image.Image] = None

    @property
    def active_channel(self) -> Optional[discord.abc.Messageable]:
        if not self.channel_id:
            return None

        channel = self.get_channel(self.channel_id)
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def setup_hook(self):
        raw_channel_id = self.db.get_config("channel_id")
        if raw_channel_id:
            self.channel_id = int(raw_channel_id)

        await self.add_cog(AdminCog(self))

        if self.channel_id:
            await self.add_cog(PostsCog(self))
            await self.add_cog(InteractCog(self))
            await self.add_cog(RatingsCog(self))
        else:
            logger.critical(
                """
                \033[91m
                ***********************************************************************
                !!! channel id not registered, run /set_channel and restart the bot !!!
                ***********************************************************************
                \033[0m"""
            )

        # sync commands
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)

    async def on_ready(self):
        logger.info(f"logged in as {self.user}")


class PostsCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.send_to_discord.start()

    @tasks.loop(time=POST_TIME)
    async def send_to_discord(self):
        data = await asyncio.to_thread(scraper.get_latest_fingerpori)
        if not self.bot.active_channel:
            logger.critical("no active channel!!!")
            return
        if not data:
            logger.error("botti rikki :/")
            await self.bot.active_channel.send("botti rikki :/")
            return

        comic = self.bot.db.save_comic(data["date"], data["url"])

        if not comic:
            logger.info("skipping comic")
            return

        poll = discord.Poll(
            duration=timedelta(hours=1, minutes=0),
            question=f"Päivän Fingerpori",
            multiple=False,
        )
        poll.add_answer(text="\u2800", emoji="5️⃣")
        poll.add_answer(text="\u2800", emoji="4️⃣")
        poll.add_answer(text="\u2800", emoji="3️⃣")
        poll.add_answer(text="\u2800", emoji="2️⃣")
        poll.add_answer(text="\u2800", emoji="1️⃣")
        poll.add_answer(text="\u2800", emoji="0️⃣")

        embed = discord.Embed(color=discord.Color.light_grey())
        embed.set_image(url=data["url"])
        embed.set_footer(
            text=f'{datetime.strptime(comic.date, "%Y-%m-%d").strftime("%d.%m.%Y")}'
        )

        message = await self.bot.active_channel.send(embed=embed, poll=poll)
        comic.message_id = message.id
        self.bot.db.update_message_id(comic)

    @send_to_discord.before_loop
    async def before_send_to_discord(self):
        await self.bot.wait_until_ready()
        logger.debug("starting PostsCog @task.loop")


class InteractCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.inverted = None

    @app_commands.command(name="invert")
    async def invert(self, interaction: discord.Interaction):
        if not self.bot.active_channel:
            logger.critical("no active channel!!!")
            return

        await interaction.response.defer(ephemeral=True)
        if not self.inverted:

            if not self.bot.latest_image:
                comic = self.bot.db.get_past_n_comics(1)
                if not comic:
                    return logger.error("could not get latest comic from db")
                comic = comic[0]
                self.bot.latest_image = Image.open(comic.path)
            self.inverted = ImageOps.invert(self.bot.latest_image)

        with io.BytesIO() as img_bin:
            self.inverted.save(img_bin, format="PNG")
            img_bin.seek(0)

            file = discord.File(fp=img_bin, filename="inverted.png")
            embed = discord.Embed()
            embed.set_image(url=f"attachment://inverted.png")
            await self.bot.active_channel.send(embed=embed, file=file)
        await interaction.delete_original_response()


class RatingsCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.EMOJI_MAP = {"0️⃣": 0, "1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5}
        self.update_ratings.start()

    @tasks.loop(time=SUB_TIME)
    async def update_ratings(self):
        if not self.bot.active_channel:
            logger.critical("no active channel!!!")
            return

        logger.debug("syncing reactions to db")

        comics = self.bot.db.get_past_n_comics(7)

        for comic in comics:
            if not comic.message_id:
                logger.warning(f"comic {comic.date} message_id missing")
                continue
            if comic.poll_closed:
                logger.debug(f"comic {comic.date} poll already closed")
                continue
            try:
                message = await self.bot.active_channel.fetch_message(comic.message_id)
                if (
                    message.poll
                    and message.poll.answers
                    and message.poll.is_finalised()
                ):
                    ratings = [0, 0, 0, 0, 0, 0]
                    for answer in message.poll.answers:
                        emoji = str(answer.emoji)
                        if emoji in self.EMOJI_MAP:
                            index = self.EMOJI_MAP[emoji]
                            ratings[index] = answer.vote_count
                        else:
                            logger.warning(f"unexpected poll answer: {answer.text}")
                    self.bot.db.update_ratings(comic, ratings)
                else:
                    logger.warning(f"comic {comic.date} poll not found or finalized")
                    continue
            except discord.NotFound:
                logger.warning(f"message {comic.message_id} not found")
                continue
            except Exception as e:
                logger.error(f"error syncing {comic.message_id}: {e}")
                continue
        logger.info("ratings synced")

    @update_ratings.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        logger.debug("starting RatingsCog @task.loop")


class AdminCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = cast("FingerporiBot", bot)

    @app_commands.command(name="scrape")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_scrape(self, interaction: discord.Interaction):
        posts_cog = cast("PostsCog", self.bot.get_cog("PostsCog"))
        if posts_cog:
            await interaction.response.send_message(
                "Manual scrape started", ephemeral=True
            )
            await posts_cog.send_to_discord()
        else:
            await interaction.response.send_message(
                "error: PostsCog not loaded.", ephemeral=True
            )

    @app_commands.command(
        name="set_channel", description="set current channel as active channel"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction):

        channel_id = interaction.channel_id
        self.bot.db.set_config("channel_id", str(channel_id))

        await interaction.response.send_message(
            f"Update channel set to <#{channel_id}>"
        )
        logger.info(
            f"Update channel set to #{channel_id}. Restart bot for changes to take effect"
        )


if __name__ == "__main__":
    db = DbManager()
    bot = FingerporiBot(db=db)
    bot.run(TOKEN)
