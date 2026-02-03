import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import tasks, commands
from dotenv import load_dotenv
import io
import os
from PIL import Image, ImageOps
import sys
from typing import Optional, TYPE_CHECKING, cast
import zoneinfo

import fingerpori_scraper as scraper
from fingerpori_db import DbManager

if TYPE_CHECKING:
    from fingerpori_bot import FingerporiBot

load_dotenv()

TIMEZONE = zoneinfo.ZoneInfo("Europe/Helsinki")
phour, pminute = map(int, os.getenv("POST_TIME", "03:00").split(":"))
post_dt = datetime.now(TIMEZONE).replace(hour=phour, minute=pminute, second=0, microsecond=0)
reaction_dt = post_dt - timedelta(minutes=15)

POST_TIME = post_dt.timetz()
SUB_TIME = reaction_dt.timetz()

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
            await self.add_cog(ReactionCog(self))
        else:
            print(
                "!!! channel id not registered, run /set_channel and restart the bot !!!"
            )

        # sync commands
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)

    async def on_ready(self):
        print(f"logged in as {self.user}")


class PostsCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.send_to_discord.start()

    @tasks.loop(time=POST_TIME)
    async def send_to_discord(self):
        data = await asyncio.to_thread(scraper.get_latest_fingerpori)
        if not self.bot.active_channel:
            print("no active channel")
            return
        if not data:
            print("botti rikki :/")
            await self.bot.active_channel.send("botti rikki :/")
            return

        comic = self.bot.db.save_comic(data["date"], data["url"])

        if not comic:
            print("skipping comic")
            return

        self.bot.latest_image = Image.open(comic.path)
        file = discord.File(comic.path, filename="comic.jpg")
        embed = discord.Embed(
            title=f"Päivän Fingerpori",
            color=discord.Color.lighter_grey(),
        )
        embed.set_image(url=f"attachment://comic.jpg")
        embed.set_footer(
            text=f"Fingerpori {datetime.strptime(comic.date, "%Y-%m-%d").strftime("%d.%m.%Y")}"
        )
        message = await self.bot.active_channel.send(embed=embed, file=file)
        comic.message_id = message.id
        self.bot.db.update_message_id(comic)


class InteractCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.inverted = None

    @app_commands.command(name="invert")
    async def invert(self, interaction: discord.Interaction):
        if not self.bot.active_channel:
            return

        await interaction.response.defer(ephemeral=True)
        if not self.inverted:

            if not self.bot.latest_image:
                comic = self.bot.db.get_past_n_comics(1)
                if not comic:
                    return print("could not get latest comic from db")
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


class ReactionCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot = bot
        self.update_reactions.start()

    @tasks.loop(time=SUB_TIME)
    async def update_reactions(self):
        if not self.bot.active_channel:
            return
        print("syncing reactions to db")

        comics = self.bot.db.get_past_n_comics(7)

        for comic in comics:
            if not comic.message_id:
                print(f"comic {comic.date} message_id missing")
                return
            try:
                message = await self.bot.active_channel.fetch_message(comic.message_id)
                ratings = [0, 0, 0, 0, 0, 0]
                for reaction in message.reactions:
                    count = reaction.count
                    match str(reaction.emoji):
                        case "0️⃣":
                            ratings[0] = count
                        case "1️⃣":
                            ratings[1] = count
                        case "2️⃣":
                            ratings[2] = count
                        case "3️⃣":
                            ratings[3] = count
                        case "4️⃣":
                            ratings[4] = count
                        case "5️⃣":
                            ratings[5] = count
                        case _:
                            pass
                self.bot.db.update_reactions(comic, ratings)
            except discord.NotFound:
                print(f"message {comic.message_id} not found")
                return
            except Exception as e:
                print(f"error syncing {comic.message_id}: {e}")
                return
        print("reactions synced")


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

        channel_id = str(interaction.channel_id)
        self.bot.db.set_config("channel_id", channel_id)
        await interaction.response.send_message(
            f"Update channel set to <#{channel_id}>"
        )


if __name__ == "__main__":
    db = DbManager()
    bot = FingerporiBot(db=db)
    bot.run(TOKEN)
