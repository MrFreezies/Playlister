import asyncio
import html
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

ADMIN_ROLE_NAME = "bill overbeck"

FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")
SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)

EMOJI_BROWSE = discord.PartialEmoji(name="browse", id=1574456458429599764)
EMOJI_ADD = discord.PartialEmoji(name="add", id=1574456406113779772)
EMOJI_USERS = discord.PartialEmoji(name="Users", id=1574456302778712084)


def is_admin_user(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(role.name.lower() == ADMIN_ROLE_NAME for role in interaction.user.roles)


def to_small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS)


def top_header_label(num_str: str, playlist_title: str) -> str:
    fw = num_str.translate(FULLWIDTH_DIGITS)
    return f"### {fw}｜{to_small_caps(playlist_title)}"


async def resolve_user_labels(
    bot_ref: commands.Bot, guild: discord.Guild | None, user_ids: list[int]
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for uid in user_ids[:25]:
        if guild:
            member = guild.get_member(uid)
            if member:
                labels[uid] = member.display_name
                continue
        cached = bot_ref.get_user(uid)
        if cached:
            labels[uid] = cached.display_name
            continue
        try:
            fetched = await bot_ref.fetch_user(uid)
            labels[uid] = fetched.display_name
        except Exception:
            labels[uid] = f"User {uid}"
    return labels


def _parse_stats_from_text(text: str) -> str | None:
    parts = []
    tracks_match = re.search(r"(\d[\d,]*)\s*(?:songs?|tracks?)", text, re.IGNORECASE)
    if tracks_match:
        parts.append(f"{tracks_match.group(1)} tracks")

    dur_parts = []
    hr_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hr|hrs|hour|hours)", text, re.IGNORECASE)
    min_match = re.search(r"(\d+)\s*(?:min|mins|minute|minutes)", text, re.IGNORECASE)
    if hr_match:
        dur_parts.append(f"{hr_match.group(1)}h")
    if min_match:
        dur_parts.append(f"{min_match.group(1)}m")
    if dur_parts:
        parts.append(" ".join(dur_parts))

    return " · ".join(parts) if parts else None


def _fetch_spotify_meta_sync(url: str) -> dict:
    result = {"cover": None, "owner": None, "stats": None}
    if "spotify.com" not in url.lower():
        return result

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
        logging.debug("Spotify oEmbed failed for %s: %s", url, exc)

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
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")

        if not result["cover"]:
            img_match = re.search(
                r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                raw_html,
                re.IGNORECASE,
            )
            if img_match:
                result["cover"] = html.unescape(img_match.group(1))

        desc_match = re.search(
            r'<meta\s+(?:property|name)=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
            raw_html,
            re.IGNORECASE,
        )
        desc_text = html.unescape(desc_match.group(1)) if desc_match else ""

        if not result["owner"] and desc_text:
            owner_match = re.search(
                r"(?:Playlist|Listen to .*? on Spotify)\s*[·|•-]\s*([^·|•\n]+)",
                desc_text,
            )
            if owner_match:
                result["owner"] = owner_match.group(1).strip()

        result["stats"] = _parse_stats_from_text(desc_text) or _parse_stats_from_text(
            html.unescape(re.sub(r"<[^>]+>", " ", raw_html))
        )
    except Exception as exc:
        logging.debug("Spotify page lookup failed for %s: %s", url, exc)

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
        await interaction.response.edit_message(view=MainDashboardView(bot))


class EditPlaylistModal(ui.Modal, title="Edit Playlist"):
    def __init__(
        self,
        playlist_id: int,
        current_title: str,
        current_url: str,
        current_tags: str,
        can_delete: bool = False,
    ):
        super().__init__()
        self.playlist_id = playlist_id
        self.can_delete = can_delete
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
        meta = await fetch_spotify_meta(url)
        await interaction.response.edit_message(
            view=PlaylistLinkView(
                playlist_id=self.playlist_id,
                title=title,
                url=url,
                platform=platform,
                tags=tags,
                cover_url=meta["cover"],
                owner_name=meta["owner"],
                stats_text=meta["stats"],
                can_delete=self.can_delete or is_admin_user(interaction),
            )
        )


class UserSelect(ui.Select):
    def __init__(self, user_labels: dict[int, str], user_ids: list[int], can_delete: bool = False):
        self.can_delete = can_delete
        options = []
        for uid in user_ids[:25]:
            display = user_labels.get(uid) or f"User {uid}"
            options.append(
                discord.SelectOption(
                    label=display[:40],
                    value=str(uid),
                )
            )
        super().__init__(
            placeholder="User...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        rows = storage.get_playlists(user_id=uid)
        if not rows:
            await interaction.response.edit_message(
                view=UserFilterView({uid: "No playlists"}, [uid], can_delete=self.can_delete)
            )
            return
        await interaction.response.edit_message(
            view=PlaylistSelectView(rows, header_text="ᴜꜱᴇʀꜱ", can_delete=self.can_delete),
        )


class UserFilterView(ui.LayoutView):
    def __init__(self, user_labels: dict[int, str], user_ids: list[int], can_delete: bool = False):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=COLOR_USERS)
        container.add_item(ui.TextDisplay("ᴜꜱᴇʀꜱ"))
        container.add_item(ui.ActionRow(UserSelect(user_labels, user_ids, can_delete=can_delete)))
        self.add_item(container)


class PlaylistSelect(ui.Select):
    def __init__(self, rows, can_delete: bool = False):
        self.rows_map = {str(r["id"]): r for r in rows}
        self.can_delete = can_delete
        options = []
        for r in rows[:25]:
            title = (r["title"] or "Untitled")[:40]
            options.append(
                discord.SelectOption(
                    label=title,
                    value=str(r["id"]),
                )
            )
        super().__init__(
            placeholder="Playlist...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        row = self.rows_map[self.values[0]]
        meta = await fetch_spotify_meta(row["url"])
        await interaction.response.edit_message(
            view=PlaylistLinkView(
                playlist_id=row["id"],
                title=row["title"],
                url=row["url"],
                platform=row["platform"],
                tags=row["tags"] or "",
                cover_url=meta["cover"],
                owner_name=meta["owner"],
                stats_text=meta["stats"],
                can_delete=self.can_delete or is_admin_user(interaction),
            )
        )


class PlaylistSelectView(ui.LayoutView):
    def __init__(self, rows, header_text: str = "ʙʀᴏᴡꜱᴇ", can_delete: bool = False):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=COLOR_BROWSE)
        container.add_item(ui.TextDisplay(header_text))
        container.add_item(ui.ActionRow(PlaylistSelect(rows, can_delete=can_delete)))
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
        stats_text: str | None = None,
        can_delete: bool = False,
    ):
        super().__init__(timeout=180)
        self.playlist_id = playlist_id
        self.pl_title = title
        self.pl_url = url
        self.pl_platform = platform
        self.pl_tags = tags
        self.cover_url = cover_url
        self.owner_name = owner_name
        self.stats_text = stats_text
        self.can_delete = can_delete

        header_display = ui.TextDisplay(top_header_label("01", title))

        detail_lines = [to_small_caps(platform)]
        if owner_name:
            detail_lines.append(to_small_caps(owner_name))
        if stats_text:
            detail_lines.append(to_small_caps(stats_text))
        detail_display = ui.TextDisplay("\n".join(detail_lines))

        container = ui.Container(accent_color=COLOR_ADD)
        if cover_url:
            container.add_item(
                ui.Section(
                    header_display,
                    detail_display,
                    accessory=ui.Thumbnail(media=cover_url),
                )
            )
        else:
            container.add_item(header_display)
            container.add_item(detail_display)

        open_btn = ui.Button(
            style=discord.ButtonStyle.link,
            label="\u200b",
            url=url,
        )

        self.print_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            label="ᴘʀɪɴᴛ",
        )
        self.print_btn.callback = self.print_link

        edit_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            label="ᴇᴅɪᴛ",
        )
        edit_btn.callback = self.edit_playlist

        buttons = [open_btn, self.print_btn, edit_btn]
        if self.can_delete:
            delete_btn = ui.Button(
                style=discord.ButtonStyle.secondary,
                label="ᴅᴇʟᴇᴛᴇ",
            )
            delete_btn.callback = self.delete_playlist
            buttons.append(delete_btn)

        container.add_item(ui.ActionRow(*buttons))
        self.add_item(container)

    async def print_link(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.pl_url, ephemeral=True)

    async def edit_playlist(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            EditPlaylistModal(
                playlist_id=self.playlist_id,
                current_title=self.pl_title,
                current_url=self.pl_url,
                current_tags=self.pl_tags,
                can_delete=self.can_delete,
            )
        )

    async def delete_playlist(self, interaction: discord.Interaction):
        if not (self.can_delete or is_admin_user(interaction)):
            await interaction.response.edit_message(view=self)
            return
        storage.delete_playlist(self.playlist_id)
        rows = storage.get_playlists()
        if rows:
            await interaction.response.edit_message(
                view=PlaylistSelectView(rows, "ʙʀᴏᴡꜱᴇ", can_delete=self.can_delete)
            )
        else:
            await interaction.response.edit_message(view=MainDashboardView(bot))


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
        can_del = is_admin_user(interaction)
        rows = storage.get_playlists()
        if not rows:
            await interaction.response.edit_message(view=MainDashboardView(self.bot_ref, selected_key="browse"))
            return
        await interaction.response.edit_message(
            view=PlaylistSelectView(rows, "ʙʀᴏᴡꜱᴇ", can_delete=can_del),
        )

    async def on_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddPlaylistModal())

    async def on_users(self, interaction: discord.Interaction):
        can_del = is_admin_user(interaction)
        rows = storage.get_playlists()
        user_ids = list(dict.fromkeys(r["user_id"] for r in rows))
        if not user_ids:
            await interaction.response.edit_message(view=MainDashboardView(self.bot_ref, selected_key="users"))
            return
        user_labels = await resolve_user_labels(self.bot_ref, interaction.guild, user_ids)
        await interaction.response.edit_message(
            view=UserFilterView(user_labels, user_ids, can_delete=can_del),
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
