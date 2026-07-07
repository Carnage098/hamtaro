import aiosqlite

DATABASE = "database.db"


async def init_db():

    async with aiosqlite.connect(DATABASE) as db:

        # Active les clés étrangères
        await db.execute("PRAGMA foreign_keys = ON;")

        # ==========================
        # TOURNOIS
        # ==========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tournaments(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id TEXT NOT NULL,

            code TEXT NOT NULL UNIQUE,

            name TEXT NOT NULL,

            format TEXT NOT NULL,

            max_players INTEGER NOT NULL,

            status TEXT NOT NULL,

            current_round INTEGER DEFAULT 0,

            winner_id TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ==========================
        # JOUEURS
        # ==========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS players(

            discord_id TEXT,

            guild_id TEXT,

            username TEXT,

            PRIMARY KEY(discord_id,guild_id)
        )
        """)

        # ==========================
        # INSCRIPTIONS
        # ==========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS registrations(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            discord_id TEXT NOT NULL,

            username TEXT NOT NULL,

            deck TEXT,

            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(tournament_id,discord_id),

            FOREIGN KEY(tournament_id)
            REFERENCES tournaments(id)
            ON DELETE CASCADE
        )
        """)

        # ==========================
        # MATCHS
        # ==========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS matches(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            round INTEGER NOT NULL,

            bracket TEXT DEFAULT 'winner',

            player1_id TEXT,

            player2_id TEXT,

            player1_name TEXT,

            player2_name TEXT,

            player1_deck TEXT,

            player2_deck TEXT,

            score TEXT,

            winner_id TEXT,

            loser_id TEXT,

            status TEXT,

            validated INTEGER DEFAULT 0,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(tournament_id)
            REFERENCES tournaments(id)
            ON DELETE CASCADE
        )
        """)

        # ==========================
        # DECKLISTS
        # ==========================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS decklists(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER,

            discord_id TEXT,

            archetype TEXT,

            ydk TEXT,

            validated INTEGER DEFAULT 0,

            FOREIGN KEY(tournament_id)
            REFERENCES tournaments(id)
            ON DELETE CASCADE
        )
        """)

        # ==========================
        # INDEX SQL
        # ==========================

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament
        ON registrations(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_matches
        ON matches(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_players
        ON players(discord_id)
        """)

        await db.commit()

    print("✅ Base de données initialisée.")
