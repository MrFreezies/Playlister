import os
import discord
from discord import ui
from discord.ext import commands
from dotenv import load_dotenv
import storage

load_dotenv()
storage.init_db()

COLOR_HEADER = 0x7B68EE
COLOR_BROWSE = 0x3B82F6
COLOR_SAVE = 0x2DD4BF
COLOR_MINE = 0xA855F7


def spaced(text: str) -> str:
    return " ".join(text.upper())


class SavePlaylistModal(ui.Modal, title="Save a Playlist"):
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
            f"Saved **{self.pl_title.value.strip()}** (`{platform}`).",
            ephemeral=True,
        )


class SearchModal(ui.Modal, title="Search Saved Playlists"):
    query = ui.TextInput(
        label="Search Term",
        placeholder="Title, platform, or tag...",
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction):
        term = self.query.value.strip()
        rows = storage.get_playlists(query=term)
        if not rows:
            await interaction.response.send_message(
                f"No saved playlists matched `{term}`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=PlaylistSelectView(rows, header_text=f"SEARCH: {term}"),
            ephemeral=True,
        )


class PlaylistSelect(ui.Select):
    def __init__(self, rows):
        self.rows_map = {str(r["id"]): r for r in rows}
        options = [
            discord.SelectOption(
                label=r["title"][:100],
                value=str(r["id"]),
                description=f"{r['platform']} | {r['tags'] or 'No tags'}"[:100],
            )
            for r in rows
        ]
        super().__init__(
            placeholder="Choose a playlist...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        row = self.rows_map[self.values[0]]
        await interaction.response.send_message(
            view=PlaylistLinkView(
                title=row["title"],
                url=row["url"],
                platform=row["platform"],
            ),
            ephemeral=True,
        )


class PlaylistSelectView(ui.LayoutView):
    def __init__(self, rows, header_text: str = "BROWSE PLAYLISTS"):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=COLOR_BROWSE)
        container.add_item(ui.TextDisplay(f"### {spaced(header_text)}"))
        container.add_item(ui.ActionRow(PlaylistSelect(rows)))

        search_btn = ui.Button(label="Search", style=discord.ButtonStyle.secondary)
        search_btn.callback = self.open_search
        container.add_item(ui.ActionRow(search_btn))
        self.add_item(container)

    async def open_search(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal())


class PlaylistLinkView(ui.LayoutView):
    def __init__(self, title: str, url: str, platform: str):
        super().__init__(timeout=180)
        self.pl_url = url

        container = ui.Container(accent_color=COLOR_MINE)
        container.add_item(ui.TextDisplay(f"### {spaced(platform)}"))
        container.add_item(ui.TextDisplay(f"**{title}**\n```\n{url}\n```"))

        open_btn = ui.Button(
            label=f"Open {platform}",
            style=discord.ButtonStyle.link,
            url=url,
        )
        copy_btn = ui.Button(
            label="Copy Link",
            style=discord.ButtonStyle.secondary,
        )
        copy_btn.callback = self.copy_link

        container.add_item(ui.ActionRow(open_btn, copy_btn))
        self.add_item(container)

    async def copy_link(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.pl_url, ephemeral=True)


class MainDashboardView(ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)

        c1 = ui.Container(accent_color=COLOR_HEADER)
        c1.add_item(ui.TextDisplay(f"### {spaced('PLAYLIST SELECTION')}"))
        self.add_item(c1)

        c2 = ui.Container(accent_color=COLOR_BROWSE)
        btn_browse = ui.Button(
            label="Browse playlists",
            style=discord.ButtonStyle.secondary,
            custom_id="pl_browse",
        )
        btn_browse.callback = self.on_browse
        c2.add_item(
            ui.Section(
                ui.TextDisplay(f"### {spaced('BROWSE')}"),
                accessory=btn_browse,
            )
        )
        self.add_item(c2)

        c3 = ui.Container(accent_color=COLOR_SAVE)
        btn_save = ui.Button(
            label="Save a playlist",
            style=discord.ButtonStyle.secondary,
            custom_id="pl_save",
        )
        btn_save.callback = self.on_save
        c3.add_item(
            ui.Section(
                ui.TextDisplay(f"### {spaced('SAVE')}"),
                accessory=btn_save,
            )
        )
        self.add_item(c3)

        c4 = ui.Container(accent_color=COLOR_MINE)
        btn_mine = ui.Button(
            label="My playlists",
            style=discord.ButtonStyle.secondary,
            custom_id="pl_mine",
        )
        btn_mine.callback = self.on_mine
        c4.add_item(
            ui.Section(
                ui.TextDisplay(f"### {spaced('MY PLAYLISTS')}"),
                accessory=btn_mine,
            )
        )
        self.add_item(c4)

    async def on_browse(self, interaction: discord.Interaction):
        rows = storage.get_playlists()
        if not rows:
            await interaction.response.send_message(
                "No playlists saved yet. Use **Save a playlist** first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=PlaylistSelectView(rows, "ALL PLAYLISTS"),
            ephemeral=True,
        )

    async def on_save(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SavePlaylistModal())

    async def on_mine(self, interaction: discord.Interaction):
        rows = storage.get_playlists(user_id=interaction.user.id)
        if not rows:
            await interaction.response.send_message(
                "You have not saved any playlists yet.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=PlaylistSelectView(rows, "MY PLAYLISTS"),
            ephemeral=True,
        )


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    bot.add_view(MainDashboardView())
    print(f"Logged in as {bot.user}")


@bot.command(name="PL")
async def pl_command(ctx: commands.Context):
    await ctx.send(view=MainDashboardView())


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Missing DISCORD_TOKEN in environment or .env file.")

bot.run(token)
