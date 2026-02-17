import io
import logging
import os
import sys
import zoneinfo
from datetime import datetime, timedelta
from typing import Any, override

import discord
from discord import TextChannel, app_commands
from discord.ext import commands, tasks
from discord.user import User
from discord.utils import _ColourFormatter  # pyright: ignore[reportPrivateUsage]
from dotenv import load_dotenv
from PIL import Image, ImageOps

import fingerpori_scraper as scraper
from fingerpori_db import DbManager, RatingMode

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
user_id = os.getenv("USER_ID")
if user_id is None:
    sys.exit("no user id provided")
USER_ID = int(user_id)
TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    sys.exit("no token provided")


def is_owner():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == USER_ID

    return app_commands.check(predicate)


class PostView(discord.ui.View):
    def __init__(self, comic_id: int):
        super().__init__(timeout=None)
        self.comic_id: int = comic_id

        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.grey,
                label="0",
                custom_id=f"fpori:{self.comic_id}:1",
                row=0,
                emoji="1️⃣",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.grey,
                label="0",
                custom_id=f"fpori:{self.comic_id}:2",
                row=0,
                emoji="2️⃣",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.grey,
                label="0",
                custom_id=f"fpori:{self.comic_id}:3",
                row=0,
                emoji="3️⃣",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.grey,
                label="0",
                custom_id=f"fpori:{self.comic_id}:4",
                row=0,
                emoji="4️⃣",
            )
        )
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.grey,
                label="0",
                custom_id=f"fpori:{self.comic_id}:5",
                row=0,
                emoji="5️⃣",
            )
        )


class FingerporiBot(commands.Bot):
    def __init__(self, db: DbManager, *args: Any, **kwargs: Any):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_reactions = True
        intents.polls = True
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)

        self.db: DbManager = db

        self.active_comics: set[int] = set[int]()
        self.latest_image: Image.Image | None = None
        self.snitch_cache: dict[int, set[int]] = {}

    @override
    async def setup_hook(self):
        await self.db.connect()
        await self.add_cog(AdminCog(self))
        await self.add_cog(GuildCog(self))
        await self.add_cog(PostsCog(self))
        await self.add_cog(InteractCog(self))
        await self.add_cog(VoteCog(self))
        self.active_comics.clear()
        self.active_comics.update(await self.db.get_active_comic_ids())

    async def on_ready(self):
        logger.info(f"logged in as {self.user}")


class GuildCog(commands.Cog):
    def __init__(self, bot: FingerporiBot):
        self.bot: FingerporiBot = bot

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logger.info(f"joining into new guild {guild.id}")
        channel = guild.system_channel or None
        if not channel or not channel.permissions_for(guild.me).send_messages:
            channel = next(
                (
                    chan
                    for chan in guild.text_channels
                    if chan.permissions_for(guild.me).send_messages
                ),
                None,
            )
        channel_id = channel.id if channel else None
        if not await self.bot.db.new_guild(guild.id, channel_id):
            logger.critical(f"inserting guild to db failed! {guild.id}")
        logger.info(f"joined to guild: {guild.name} ({guild.id})")
        if channel:
            await channel.send(
                f"Tervetuloa {guild.name}. Vaihda kannua ajamalla /set_channel"
            )
            return

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        logger.info(f"left guild: {guild.name} ({guild.id})")


class PostsCog(commands.Cog):
    def __init__(self, bot: FingerporiBot):
        self.bot: FingerporiBot = bot
        self.send_to_discord.start()

    @tasks.loop(time=POST_TIME)
    async def send_to_discord(self):
        data = await scraper.get_latest_fingerpori()
        if not data:
            logger.error("botti rikki :/")
            user: User | None = self.bot.get_user(USER_ID)
            if isinstance(user, User):
                await user.send("botti rikki :/")
            return

        img_date, img_url, img_bytes = data["date"], data["url"], data["bytes"]

        comic = await self.bot.db.save_comic(
            img_date, img_url, img_bytes  # pyright: ignore[reportArgumentType]
        )

        if not comic:
            logger.info("skipping comic")
            return

        embed = discord.Embed(
            title="Päivän Fingerpori", color=discord.Color.light_grey()
        )
        embed.set_image(url=data["url"])
        embed.set_footer(
            text=f'{datetime.strptime(comic.date, "%Y-%m-%d").strftime("%d.%m.%Y")}'
        )
        guilds = await self.bot.db.get_guilds()
        if not guilds:
            logger.warning("no guilds found")
            return
        for guild in guilds:
            if not self.bot.get_guild(guild.guild_id):
                logger.info(f"skipping {guild.guild_id}: bot is no longer a member")
            channel = self.bot.get_channel(guild.channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(guild.channel_id)
                except (discord.NotFound, discord.Forbidden):
                    logger.warning(
                        f"guild {guild.guild_id} channel {guild.channel_id} missing"
                    )
                    continue
            rating_mode = RatingMode(guild.rating_mode)

            if not isinstance(channel, TextChannel):
                logger.warning(f"{guild.guild_id} channel not found or not messageable")
                continue
            try:
                if rating_mode == RatingMode.VIEW:
                    message = await channel.send(embed=embed, view=PostView(comic.id))
                else:
                    message = await channel.send(embed=embed)

                if not await self.bot.db.new_message(
                    guild.guild_id, comic.id, message.id, channel.id
                ):
                    logger.error("message insert failed")
                    await message.delete()
            except discord.Forbidden:
                logger.error(f"missing permissions to send in {channel.id}")
            except discord.HTTPException as e:
                logger.error(f"failed to send message: {e}")
        self.bot.active_comics.add(comic.id)

    @send_to_discord.before_loop
    async def before_send_to_discord(self):
        await self.bot.wait_until_ready()


class VoteCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot: FingerporiBot = bot
        self.close_polls.start()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.data or not interaction.message or not interaction.guild_id:
            return
        custom_id = interaction.data.get("custom_id")
        if not custom_id or not custom_id.startswith("fpori:"):
            return
        try:
            parts = custom_id.split(":")
            comic_id = int(parts[1])
            rating = int(parts[2])
        except (IndexError, ValueError):
            return
        if int(comic_id) not in self.bot.active_comics:
            return
        await self.bot.db.save_vote(
            comic_id, interaction.user.id, rating, interaction.message.id
        )

        votes = await self.bot.db.get_votes(interaction.guild_id, comic_id)

        view = discord.ui.View.from_message(interaction.message)
        for item in view.children:
            if isinstance(item, discord.ui.Button) and item.custom_id:
                rating = int(item.custom_id.split(":")[2])
                localvotes, globalvotes = votes.get( # pyright: ignore[reportUnusedVariable]
                    rating, (0, 0)
                )  
                item.label = f"{localvotes}"
                # item.label = f"{localvotes} ({globalvotes})"
        await interaction.response.edit_message(view=view)

    @tasks.loop(time=SUB_TIME)
    async def close_polls(self):
        messages = await self.bot.db.get_active_messages()
        closed: set[int] = set()

        for row in messages:
            message_id, channel_id, guild_id, comic_id, rating_mode = row
            rating_mode = RatingMode(rating_mode)
            if rating_mode == RatingMode.NONE:
                continue

            votes = await self.bot.db.get_votes(guild_id, comic_id)

            local_sum = 0
            local_count = 0
            global_sum = 0
            global_count = 0
            for score, (local, glob) in votes.items():
                local_sum += score * local
                local_count += local
                global_sum += score * glob
                global_count += glob
            local_avg = local_sum / local_count if local_count > 0 else 0
            global_avg = global_sum / global_count if global_count > 0 else 0

            try:
                channel = self.bot.get_channel(
                    channel_id
                ) or await self.bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                message = await channel.fetch_message(message_id)
                if not isinstance(message, discord.Message):
                    continue

                view = discord.ui.View.from_message(message)
                for item in view.children:
                    if isinstance(item, discord.ui.Button) and item.custom_id:
                        item.disabled = True
                        item.style = discord.ButtonStyle.grey

                        rating = int(item.custom_id.split(":")[2])
                        localvotes, globalvotes = votes.get(rating, (0, 0))
                        item.label = f"{localvotes}   ({globalvotes})"

                guild_name = message.guild.name if message.guild else "guild"

                embed = message.embeds[0].copy()
                embed2 = discord.Embed(
                    title="Tulokset", color=discord.Color.light_grey()
                )
                embed2.add_field(
                    name=guild_name, value=f"📍 **{local_avg:.1f}**", inline=True
                )
                embed2.add_field(
                    name="Kaikki servut", value=f"🇫🇮 **{global_avg:.1f}**", inline=True
                )

                await message.edit(embeds=[embed, embed2], view=view)
            except discord.NotFound:
                logger.warning(f"message {message_id} not found")
            except Exception as e:
                logger.warning(f"failed to close poll for {message_id}: {e}")
            closed.add(comic_id)
        await self.bot.db.close_polls(closed)
        self.bot.active_comics -= closed

    @close_polls.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


class InteractCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot: FingerporiBot = bot
        self.inverted: Image.Image | None = None

    @app_commands.command(name="black")
    async def invert(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.inverted:
            if not self.bot.latest_image:
                comic = await self.bot.db.get_past_n_comics(1)
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
            embed.set_image(url="attachment://inverted.png")
            if isinstance(interaction.channel, TextChannel):
                await interaction.channel.send(embed=embed, file=file)
        await interaction.delete_original_response()

    @app_commands.command(name="tiiraile")
    async def snoop(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True)

        comic = await self.bot.db.get_past_n_comics(1)
        if not comic:
            await interaction.response.send_message("Ei fingerporia.", ephemeral=True)
            return
        comic_id = comic[0].id

        ratings: list[dict[str, Any]] = await self.bot.db.get_guild_user_votes(
            interaction.guild.id, comic_id
        )
        if not ratings:
            await interaction.followup.send("Tämähän on tyhjää täynnä")
            return

        EMOJI_MAP = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣"}

        lines: list[str] = []

        for item in ratings:
            member = interaction.guild.get_member(item["user_id"])
            name = member.display_name if member else None
            rating = item["rating"]
            if name and rating in EMOJI_MAP:
                lines.append(f"{EMOJI_MAP[rating]}  {name}")

        vote_list = "\n".join(lines)
        content = f"###Arvosanat: \n\n{vote_list}"

        self.bot.snitch_cache.setdefault(interaction.guild.id, set()).add(
            interaction.user.id
        )

        await interaction.followup.send(content)

    @app_commands.command(name="vasikoi")
    async def snitch(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True)

        users = self.bot.snitch_cache.get(interaction.guild.id)

        if not users:
            await interaction.followup.send("Ei tiirailijoita")
            return

        names: list[str] = []

        for id in users:
            member = interaction.guild.get_member(id)
            if member:
                names.append(member.display_name)
        names.sort()
        user_list = "\n".join(names)
        content = f"### Tiirailijat: \n\n{user_list}"
        await interaction.followup.send(content=content, ephemeral=True)


class AdminCog(commands.Cog):
    def __init__(self, bot: "FingerporiBot"):
        self.bot: FingerporiBot = bot

    @app_commands.command(
        name="set_channel", description="set current channel as active channel"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction):

        channel_id = interaction.channel_id
        guild_id = interaction.guild_id
        if not channel_id or not guild_id:
            logger.error(
                f"no guild or channel id found\nguild_id: {guild_id}\tchannel_id: {channel_id}"
            )
            return
        await self.bot.db.set_active_channel(guild_id, channel_id)

        await interaction.response.send_message(
            f"Active channel set to <#{channel_id}>"
        )
        logger.info(f"Update channel for guild {guild_id} set to #{channel_id}.")

    @commands.command(hidden=True)
    @commands.dm_only()
    @commands.is_owner()
    async def scrape(self, ctx: commands.Context[FingerporiBot]):
        posts_cog = self.bot.get_cog("PostsCog")
        if isinstance(posts_cog, PostsCog):
            await ctx.send("Manual scrape started")
            await posts_cog.send_to_discord()
            await ctx.send("scraping done")
        else:
            await ctx.send("error: PostsCog not loaded.")

    @commands.command(hidden=True)
    @commands.dm_only()
    @commands.is_owner()
    async def sync(self, ctx: commands.Context[FingerporiBot]):
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"synced {len(synced)} global commands")
        except Exception as e:
            await ctx.send(f"error syncing {e}")

    @commands.command(hidden=True)
    @commands.dm_only()
    @commands.is_owner()
    async def closepolls(self, ctx: commands.Context[FingerporiBot]):
        vote_cog = self.bot.get_cog("VoteCog")
        if isinstance(vote_cog, VoteCog):
            await ctx.send("Closing polls")
            await vote_cog.close_polls()
            await ctx.send("Polls closed")
        else:
            await ctx.send("error: VoteCog not loaded")


if __name__ == "__main__":
    db = DbManager()
    bot = FingerporiBot(db=db)
    bot.run(TOKEN)
