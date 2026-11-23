import sqlite3

DB_PATH = "playlists.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                platform TEXT NOT NULL,
                tags TEXT
            )
            """
        )


def add_playlist(user_id: int, title: str, url: str, platform: str, tags: str = "") -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO playlists (user_id, title, url, platform, tags) VALUES (?, ?, ?, ?, ?)",
            (user_id, title.strip(), url.strip(), platform.strip(), tags.strip()),
        )


def get_playlists(user_id: int | None = None, query: str | None = None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM playlists WHERE 1=1"
        params = []
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        if query:
            sql += " AND (title LIKE ? OR tags LIKE ? OR platform LIKE ?)"
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY id DESC LIMIT 25"
        return conn.execute(sql, params).fetchall()


def update_playlist(playlist_id: int, title: str, url: str, platform: str, tags: str = "") -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE playlists
            SET title = ?, url = ?, platform = ?, tags = ?
            WHERE id = ?
            """,
            (title.strip(), url.strip(), platform.strip(), tags.strip(), playlist_id),
        )


def delete_playlist(playlist_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
