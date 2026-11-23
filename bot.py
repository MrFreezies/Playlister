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
        try:
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
        except Exception as exc:
            logging.exception("Failed to open playlist view")
            await interaction.followup.send(f"Error opening playlist: {exc}", ephemeral=True)
