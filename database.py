import aiosqlite

DATABASE = "database.db"


async def init_db():

    async with aiosqlite.connect(DATABASE) as db:

        # Active les clés étrangères
        await db.execute("PRAGMA foreign_keys = ON;")

        # ==========================================
        # TOURNOIS
        # ==========================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (

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

        # ==========================================
        # JOUEURS
        # ==========================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS players (

            discord_id TEXT NOT NULL,

            guild_id TEXT NOT NULL,

            username TEXT NOT NULL,

            PRIMARY KEY (discord_id, guild_id)

        )
        """)

        # ==========================================
        # INSCRIPTIONS
        # ==========================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS registrations (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            discord_id TEXT NOT NULL,

            username TEXT NOT NULL,

            deck TEXT,

            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(tournament_id, discord_id),

            FOREIGN KEY(tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE

        )
        """)

        # ==========================================
        # MATCHS
        # ==========================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS matches (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            round INTEGER NOT NULL,

            match_number INTEGER NOT NULL,

            player1_id TEXT,

            player2_id TEXT,

            winner_id TEXT,

            score TEXT,

            status TEXT NOT NULL,

            FOREIGN KEY(tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE

        )
        """)

        # ==========================================
        # INDEX
        # ==========================================

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournaments_guild
        ON tournaments(guild_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_registrations_tournament
        ON registrations(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_matches_tournament
        ON matches(tournament_id)
        """)

        await db.commit()

    print("✅ Base de données initialisée.")
