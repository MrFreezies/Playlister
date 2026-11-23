import os
import discord
from discord import ui
from discord.ext import commands
from dotenv import load_dotenv
import storage

load_dotenv()
storage.init_db()

# Smooth gradient from electric cyan/blue through violet to magenta/pink
GRADIENT_COLORS = [
    0x6366F1,  # 01 Browse (indigo-violet)
    0x8B5CF6,  # 02 Add (violet)
    0xB84AD9,  # 03 Users (purple-magenta)
]


def header_label(num_str: str, title: str) -> str:
    return f"{num_str}｜{' '.join(title.upper())}"


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


class UserSelect(ui.Select):
    def __init__(self, bot_ref: commands.Bot, user_ids: list[int]):
        self.bot_ref = bot_ref
        options = []
        for uid in user_ids[:25]:
            member = bot_ref.get_user(uid)
            display = member.display_name if member else f"User {uid}"
            options.append(
                discord.SelectOption(
                    label=display[:100],
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
            view=PlaylistSelectView(rows, header_text="USER PLAYLISTS"),
            ephemeral=True,
        )


class UserFilterView(ui.LayoutView):
    def __init__(self, bot_ref: commands.Bot, user_ids: list[int]):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=GRADIENT_COLORS[2])
        container.add_item(ui.TextDisplay(header_label("03", "USERS")))
        container.add_item(ui.ActionRow(UserSelect(bot_ref, user_ids)))
        self.add_item(container)


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
    def __init__(self, rows, header_text: str = "BROWSE"):
        super().__init__(timeout=180)
        container = ui.Container(accent_color=GRADIENT_COLORS[0])
        container.add_item(ui.TextDisplay(header_label("01", header_text)))
        container.add_item(ui.ActionRow(PlaylistSelect(rows)))
        self.add_item(container)


class PlaylistLinkView(ui.LayoutView):
    def __init__(self, title: str, url: str, platform: str):
        super().__init__(timeout=180)
        self.pl_url = url
        self.copied = False

        container = ui.Container(accent_color=GRADIENT_COLORS[1])
        container.add_item(ui.TextDisplay(header_label("01", platform)))
        container.add_item(ui.TextDisplay(f"{title}\n```\n{url}\n```"))

        open_btn = ui.Button(
            style=discord.ButtonStyle.link,
            url=url,
            emoji="↗",
        )
        self.copy_btn = ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji="☐",
        )
        self.copy_btn.callback = self.copy_link

        container.add_item(ui.ActionRow(open_btn, self.copy_btn))
        self.add_item(container)

    async def copy_link(self, interaction: discord.Interaction):
        self.copied = not self.copied
        self.copy_btn.emoji = "☑" if self.copied else "☐"
        self.copy_btn.style = (
            discord.ButtonStyle.primary if self.copied else discord.ButtonStyle.secondary
        )
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(self.pl_url, ephemeral=True)


class MainDashboardView(ui.LayoutView):
    def __init__(self, bot_ref: commands.Bot, selected_key: str | None = None):
        super().__init__(timeout=None)
        self.bot_ref = bot_ref
        self.selected_key = selected_key

        # Top header with no surrounding box
        self.add_item(ui.TextDisplay("PLAYLIST SELECTOR"))

        rows_spec = [
            ("01", "BROWSE", "browse", "▸", "▾", GRADIENT_COLORS[0], self.on_browse),
            ("02", "ADD", "add", "＋", "✓", GRADIENT_COLORS[1], self.on_add),
            ("03", "USERS", "users", "▸", "▾", GRADIENT_COLORS[2], self.on_users),
        ]

        for num_str, title, key, idle_icon, active_icon, color, cb in rows_spec:
            is_selected = self.selected_key == key
            btn = ui.Button(
                style=discord.ButtonStyle.primary if is_selected else discord.ButtonStyle.secondary,
                custom_id=f"pl_{key}",
                emoji=active_icon if is_selected else idle_icon,
            )
            btn.callback = cb

            box = ui.Container(accent_color=color)
            box.add_item(
                ui.Section(
                    ui.TextDisplay(header_label(num_str, title)),
                    accessory=btn,
                )
            )
            self.add_item(box)

    async def _set_selected(self, interaction: discord.Interaction, key: str):
        updated = MainDashboardView(self.bot_ref, selected_key=key)
        await interaction.message.edit(view=updated)

    async def on_browse(self, interaction: discord.Interaction):
        await self._set_selected(interaction, "browse")
        rows = storage.get_playlists()
        if not rows:
            await interaction.response.send_message(
                "No playlists saved yet. Use 02｜ADD first.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=PlaylistSelectView(rows, "BROWSE"),
            ephemeral=True,
        )

    async def on_add(self, interaction: discord.Interaction):
        await self._set_selected(interaction, "add")
        await interaction.response.send_modal(AddPlaylistModal())

    async def on_users(self, interaction: discord.Interaction):
        await self._set_selected(interaction, "users")
        rows = storage.get_playlists()
        user_ids = list(dict.fromkeys(r["user_id"] for r in rows))
        if not user_ids:
            await interaction.response.send_message(
                "No users have saved playlists yet.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
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
