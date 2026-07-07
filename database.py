import aiosqlite

DATABASE = "database.db"


async def init_db():

    async with aiosqlite.connect(DATABASE) as db:

        await db.execute("""

        CREATE TABLE IF NOT EXISTS tournaments(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id TEXT NOT NULL,

            name TEXT NOT NULL,

            format TEXT NOT NULL,

            size INTEGER NOT NULL,

            status TEXT NOT NULL

        )

        """)

        await db.execute("""

        CREATE TABLE IF NOT EXISTS players(

            discord_id TEXT,

            guild_id TEXT,

            username TEXT,

            PRIMARY KEY(discord_id,guild_id)

        )

        """)

        await db.execute("""

        CREATE TABLE IF NOT EXISTS registrations(

            tournament_id INTEGER,

            discord_id TEXT,

            deck TEXT

        )

        """)

        await db.execute("""

        CREATE TABLE IF NOT EXISTS matches(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER,

            round INTEGER,

            player1 TEXT,

            player2 TEXT,

            winner TEXT,

            score TEXT,

            player1_deck TEXT,

            player2_deck TEXT,

            status TEXT

        )

        """)

        await db.commit()
