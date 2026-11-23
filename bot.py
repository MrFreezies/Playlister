import asyncio
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import discord
from discord import ui
from discord.ext import commands
from dotenv import load_dotenv
import storage

logging.basicConfig(level=logging.INFO)

load_dotenv()
storage.init_db()

# Left highlight colours matched to the emoji artwork:
# browse (1574456458429599764) -> #9e1899
# add    (1574456406113779772) -> #3e46cc
# Users  (1574456302778712084) -> #08b3cd
COLOR_BROWSE = 0x9E1899
COLOR_ADD = 0x3E46CC
COLOR_USERS = 0x08B3CD

FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")
SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)

EMOJI_BROWSE = discord.PartialEmoji(name="browse", id=1574456458429599764)
EMOJI_ADD = discord.PartialEmoji(name="add", id=1574456406113779772)
EMOJI_USERS = discord.PartialEmoji(name="Users", id=1574456302778712084)


def to_small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS)


def header_label(num_str: str, title: str) -> str:
    fw = num_str.translate(FULLWIDTH_DIGITS)
    return f"{fw}｜{to_small_caps(title)}"


def _fetch_spotify_meta_sync(url: str) -> dict:
    result = {"cover": None, "owner": None}
    if "spotify.com" not in url.lower():
        return result

    # 1. Try Spotify oEmbed endpoint
    try:
        oembed_url = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if data.get("thumbnail_url"):
            result["cover"] = data["thumbnail_url"]
        if data.get("author_name"):
            result["owner"] = str(data["author_name"]).strip()
    except Exception as exc:
        logging.debug("Spotify oEmbed lookup failed for %s: %s", url, exc)

    # 2. Fallback to OpenGraph tags on page HTML
    if not result["cover"] or not result["owner"]:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            if not result["cover"]:
                img_match = re.search(
                    r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                    html,
                    re.IGNORECASE,
                )
                if img_match:
                    result["cover"] = img_match.group(1)

            if not result["owner"]:
                desc_match = re.search(
                    r'<meta\s+(?:property|name)=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
                    html,
                    re.IGNORECASE,
                )
                if desc_match:
                    owner_match = re.search(r"Playlist\s*·\s*([^·\n]+)", desc_match.group(1))
                    if owner_match:
                        result["owner"] = owner_match.group(1).strip()
        except Exception as exc:
            logging.debug("Spotify HTML meta lookup failed for %s: %s", url, exc)

    return result


async def fetch_spotify_meta(url: str) -> dict:
    return await asyncio.to_thread(_fetch_spotify_meta_sync, url)


class AddPlaylistModal(ui.Modal, title="Add a Playlist"):
    pl_title = ui.TextInput(
        label="Playlist Name",
        placeholder="Late night synthwave",
        max_length=80,
    )
    pl_url = ui.TextInput(
        label="Playlist URL",
        placeholder="https://open.spotify.com/playlist/...",
        max_length=250,
    )
    pl_tags = ui.TextInput(
        label="Tags / Genre (Optional)",
        placeholder="synthwave, chill, heavy",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.pl_url.value.strip()
        lower_url = url.lower()
        if "spotify.com" in lower_url:
            platform = "Spotify"
        elif "youtube.com" in lower_url or "youtu.be" in lower_url:
            platform = "YouTube"
        else:
            platform = "Other"

        storage.add_playlist(
            interaction.user.id,
            self.pl_title.value,
            url,
            platform,
            self.pl_tags.value,
        )
        await interaction.response.send_message(
            f"Saved {self.pl_title.value.strip()} ({platform}).",
            ephemeral=True,
        )


class EditPlaylistModal(ui.Modal, title="Edit Playlist"):
    def __init__(self, playlist_id: int, current_title: str, current_url: str, current_tags: str):
        super().__init__()
        self.playlist_id = playlist_id
        self.pl_title = ui.TextInput(
            label="Playlist Name",
            default=current_title[:80],
            max_length=80,
        )
        self.pl_url = ui.TextInput(
            label="Playlist URL",
            default=current_url[:250],
            max_length=250,
        )
        self.pl_tags = ui.TextInput(
            label="Tags / Genre (Optional)",
            default=(current_tags or "")[:100],
            required=False,
            max_length=100,
        )
        self.add_item(self.pl_title)
        self.add_item(self.pl_url)
        self.add_item(self.pl_tags)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.pl_url.value.strip()
        lower_url = url.lower()
        if "spotify.com" in lower_url:
            platform = "Spotify"
        elif "youtube.com" in lower_url or "youtu.be" in lower_url:
            platform = "YouTube"
        else:
            platform = "Other"

        title = self.pl_title.value.strip()
        tags = self.pl_tags.value.strip()
        storage.update_playlist(self.playlist_id, title, url, platform, tags)
        await interaction.response.send_message(
            f"Updated {title} ({platform}).",
            ephemeral=True,
        )


class UserSelect(ui.Select):
    def __init__(self, bot_ref: commands.Bot, user_ids: list[int]):
        self.bot_ref = bot_ref
        options = []
        for uid in user_ids[:25]:
            member = bot_ref.get_user(uid)
            display = member.display_name if member else f"User {uid}"
            options.append(
                discord.SelectOption(
                    label=(display or f"User {uid}")[:100],
                    value=str(uid),
                    description=f"ID: {uid}"[:100],
                )
            )
        super().__init__(
            placeholder="Pick a user...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        rows = storage.get_playlists(user_id=uid)
        if not rows:
            await interaction.response.send_message(
                "No playlists found for that user.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=PlaylistSelectView(rows, header_text="ᴜꜱᴇʀꜱ"),
            ephemeral=True,
        )


class UserFilterView(ui.LayoutView):
    def __init__(self, bot_ref: commands.Bot, user_ids: list[int]):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=COLOR_USERS)
        container.add_item(ui.TextDisplay("ᴜꜱᴇʀꜱ"))
        container.add_item(ui.ActionRow(UserSelect(bot_ref, user_ids)))
        self.add_item(container)


class PlaylistSelect(ui.Select):
    def __init__(self, rows):
        self.rows_map = {str(r["id"]): r for r in rows}
        options = []
        for r in rows[:25]:
            title = (r["title"] or "Untitled")[:100]
            plat = r["platform"] or "Other"
            tags = r["tags"] or "No tags"
            options.append(
                discord.SelectOption(
                    label=title,
                    value=str(r["id"]),
                    description=f"{plat} | {tags}"[:100],
                )
            )
        super().__init__(
            placeholder="Choose a playlist...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        row = self.rows_map[self.values[0]]
        meta = await fetch_spotify_meta(row["url"])
        await interaction.followup.send(
            view=PlaylistLinkView(
                playlist_id=row["id"],
                title=row["title"],
                url=row["url"],
                platform=row["platform"],
                tags=row["tags"] or "",
                cover_url=meta["cover"],
                owner_name=meta["owner"],
            ),
            ephemeral=True,
        )


class PlaylistSelectView(ui.LayoutView):
    def __init__(self, rows, header_text: str = "ʙʀᴏᴡꜱᴇ"):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=COLOR_BROWSE)
        container.add_item(ui.TextDisplay(header_text))
        container.add_item(ui.ActionRow(PlaylistSelect(rows)))
        self.add_item(container)


class PlaylistLinkView(ui.LayoutView):
    def __init__(
        self,
        playlist_id: int,
        title: str,
        url: str,
        platform: str,
        tags: str = "",
        cover_url: str | None = None,
        owner_name: str | None = None,
    ):
        super().__init__(timeout=180)
        self.playlist_id = playlist_id
        self.pl_title = title
        self.pl_url = url
        self.pl_tags = tags
        self.copied = False

        owner_sc = to_small_caps(owner_name) if owner_name else None
        platform_sc = to_small_caps(platform)

        lines = [title]
        if owner_sc:
            lines.append(owner_sc)
        lines.append(platform_sc)
        lines.append(f"```\n{url}\n```")
        info_display = ui.TextDisplay("\n".join(lines))

        container = ui.Container(accent_color=COLOR_ADD)
        container.add_item(ui.TextDisplay(header_label("01", platform)))

        if cover_url:
            container.add_item(
                ui.Section(
                    info_display,
                    accessory=ui.Thumbnail(url=cover_url),
                )
            )
        else:
            container.add_item(info_display)

        open_btn = ui.Button(
            style=discord.ButtonStyle.link,
            url=url,
            emoji="🔗",
        )
        self.copy_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji="▫️",
        )
        self.copy_btn.callback = self.copy_link

        edit_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            label="ᴇᴅɪᴛ",
        )
        edit_btn.callback = self.edit_playlist

        delete_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            label="ᴅᴇʟᴇᴛᴇ",
        )
        delete_btn.callback = self.delete_playlist

        container.add_item(ui.ActionRow(open_btn, self.copy_btn, edit_btn, delete_btn))
        self.add_item(container)

    async def copy_link(self, interaction: discord.Interaction):
        self.copied = not self.copied
        self.copy_btn.emoji = "▪️" if self.copied else "▫️"
        self.copy_btn.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(self.pl_url, ephemeral=True)

    async def edit_playlist(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            EditPlaylistModal(
                playlist_id=self.playlist_id,
                current_title=self.pl_title,
                current_url=self.pl_url,
                current_tags=self.pl_tags,
            )
        )

    async def delete_playlist(self, interaction: discord.Interaction):
        storage.delete_playlist(self.playlist_id)
        await interaction.response.send_message(
            f"Deleted {self.pl_title}.",
            ephemeral=True,
        )


class MainDashboardView(ui.LayoutView):
    def __init__(self, bot_ref: commands.Bot, selected_key: str | None = None):
        super().__init__(timeout=None)
        self.bot_ref = bot_ref
        self.selected_key = selected_key

        self.add_item(ui.TextDisplay("PLAYLIST SELECTOR"))

        rows_spec = [
            ("ʙʀᴏᴡꜱᴇ", "browse", COLOR_BROWSE, EMOJI_BROWSE, self.on_browse),
            ("ᴀᴅᴅ", "add", COLOR_ADD, EMOJI_ADD, self.on_add),
            ("ᴜꜱᴇʀꜱ", "users", COLOR_USERS, EMOJI_USERS, self.on_users),
        ]

        for label_text, key, color, custom_emoji, cb in rows_spec:
            btn = ui.Button(
                style=discord.ButtonStyle.secondary,
                custom_id=f"pl_{key}",
                emoji=custom_emoji,
            )
            btn.callback = cb

            box = ui.Container(accent_color=color)
            box.add_item(
                ui.Section(
                    ui.TextDisplay(label_text),
                    accessory=btn,
                )
            )
            self.add_item(box)

    async def on_browse(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.message:
            await interaction.message.edit(view=MainDashboardView(self.bot_ref, selected_key="browse"))
        rows = storage.get_playlists()
        if not rows:
            await interaction.followup.send(
                "No playlists saved yet. Use ᴀᴅᴅ first.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=PlaylistSelectView(rows, "ʙʀᴏᴡꜱᴇ"),
            ephemeral=True,
        )

    async def on_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddPlaylistModal())
        if interaction.message:
            await interaction.message.edit(view=MainDashboardView(self.bot_ref, selected_key="add"))

    async def on_users(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.message:
            await interaction.message.edit(view=MainDashboardView(self.bot_ref, selected_key="users"))
        rows = storage.get_playlists()
        user_ids = list(dict.fromkeys(r["user_id"] for r in rows))
        if not user_ids:
            await interaction.followup.send(
                "No users have saved playlists yet.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            view=UserFilterView(self.bot_ref, user_ids),
            ephemeral=True,
        )


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    bot.add_view(MainDashboardView(bot))
    print(f"Logged in as {bot.user}")


@bot.command(name="PL")
async def pl_command(ctx: commands.Context):
    await ctx.send(view=MainDashboardView(bot))


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Missing DISCORD_TOKEN in environment or .env file.")

bot.run(token)
