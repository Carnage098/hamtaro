import aiosqlite

DATABASE = "database.db"

DB_VERSION = 2


async def init_db():

    async with aiosqlite.connect(DATABASE) as db:

        # ==========================================================
        # SQLITE
        # ==========================================================

        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA synchronous = NORMAL;")

        # ==========================================================
        # META
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS metadata (

            key TEXT PRIMARY KEY,

            value TEXT NOT NULL

        )
        """)

        await db.execute("""
        INSERT OR IGNORE INTO metadata(
            key,
            value
        )
        VALUES(
            'db_version',
            ?
        )
        """, (str(DB_VERSION),))

        # ==========================================================
        # TOURNOIS
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tournaments (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id TEXT NOT NULL,

            code TEXT NOT NULL UNIQUE,

            name TEXT NOT NULL,

            format TEXT NOT NULL,

            max_players INTEGER NOT NULL,

            status TEXT NOT NULL DEFAULT 'registration',

            current_round INTEGER NOT NULL DEFAULT 0,

            total_rounds INTEGER NOT NULL DEFAULT 0,

            winner_id TEXT,

            winner_name TEXT,

            bracket_message_id TEXT,

            created_by TEXT NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            started_at TIMESTAMP,

            finished_at TIMESTAMP

        )
        """)

        # ==========================================================
        # JOUEURS
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS players (

            discord_id TEXT NOT NULL,

            guild_id TEXT NOT NULL,

            username TEXT NOT NULL,

            display_name TEXT,

            avatar_url TEXT,

            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            wins INTEGER NOT NULL DEFAULT 0,

            losses INTEGER NOT NULL DEFAULT 0,

            tournaments_played INTEGER NOT NULL DEFAULT 0,

            tournaments_won INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY (
                discord_id,
                guild_id
            )

        )
        """)

        # ==========================================================
        # INSCRIPTIONS
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS registrations (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            discord_id TEXT NOT NULL,

            username TEXT NOT NULL,

            deck TEXT,

            seed INTEGER,

            checked_in INTEGER NOT NULL DEFAULT 1,

            dropped INTEGER NOT NULL DEFAULT 0,

            disqualified INTEGER NOT NULL DEFAULT 0,

            final_rank INTEGER,

            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                tournament_id,
                discord_id
            ),

            FOREIGN KEY (tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE

        )
        """)

        # ==========================================================
        # MATCHS
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS matches (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            round INTEGER NOT NULL,

            match_number INTEGER NOT NULL,

            bracket_position INTEGER NOT NULL,

            next_match_id INTEGER,

            next_slot INTEGER,

            player1_id TEXT,
            player2_id TEXT,

            player1_name TEXT,
            player2_name TEXT,

            player1_score INTEGER NOT NULL DEFAULT 0,
            player2_score INTEGER NOT NULL DEFAULT 0,

            winner_id TEXT,
            winner_name TEXT,

            score TEXT,

            reported_by TEXT,
            validated_by TEXT,

            reported_at TIMESTAMP,
            validated_at TIMESTAMP,

            status TEXT NOT NULL DEFAULT 'waiting',

            is_bye INTEGER NOT NULL DEFAULT 0,

            notes TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE,

            FOREIGN KEY (next_match_id)
                REFERENCES matches(id)
                ON DELETE SET NULL,

            CHECK (
                next_slot IS NULL
                OR next_slot IN (1, 2)
            ),

            CHECK (
                status IN (
                    'waiting',
                    'playing',
                    'reported',
                    'validated',
                    'completed',
                    'cancelled'
                )
            )

        )
        """)
        # ==========================================================
        # RONDES SUISSES - PARAMÈTRES
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS swiss_settings (

            tournament_id INTEGER PRIMARY KEY,

            total_rounds INTEGER NOT NULL,

            current_round INTEGER NOT NULL DEFAULT 0,

            status TEXT NOT NULL DEFAULT 'running',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            finished_at TIMESTAMP,

            FOREIGN KEY (tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE,

            CHECK (
                status IN (
                    'running',
                    'finished',
                    'cancelled'
                )
            )

        )
        """)

        # ==========================================================
        # RONDES SUISSES - MATCHS
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS swiss_matches (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tournament_id INTEGER NOT NULL,

            round_number INTEGER NOT NULL,

            table_number INTEGER NOT NULL,

            player1_id TEXT NOT NULL,
            player1_name TEXT NOT NULL,

            player2_id TEXT,
            player2_name TEXT,

            player1_score INTEGER NOT NULL DEFAULT 0,
            player2_score INTEGER NOT NULL DEFAULT 0,

            winner_id TEXT,
            winner_name TEXT,

            is_draw INTEGER NOT NULL DEFAULT 0,

            is_bye INTEGER NOT NULL DEFAULT 0,

            status TEXT NOT NULL DEFAULT 'pending',

            reported_by TEXT,

            reported_at TIMESTAMP,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (
                tournament_id,
                round_number,
                table_number
            ),

            FOREIGN KEY (tournament_id)
                REFERENCES tournaments(id)
                ON DELETE CASCADE,

            CHECK (
                status IN (
                    'pending',
                    'completed',
                    'cancelled'
                )
            )

        )
        """)
        # ==========================================================
        # INDEXES
        # ==========================================================

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament_guild
        ON tournaments(guild_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament_status
        ON tournaments(status)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_registration_tournament
        ON registrations(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_registration_discord
        ON registrations(discord_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_tournament
        ON matches(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_round
        ON matches(tournament_id, round)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_status
        ON matches(status)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_next
        ON matches(next_match_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_players
        ON matches(player1_id, player2_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_winner
        ON matches(winner_id)
        """)
        
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_settings_tournament
        ON swiss_settings(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_tournament
        ON swiss_matches(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_round
        ON swiss_matches(tournament_id, round_number)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_players
        ON swiss_matches(player1_id, player2_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_status
        ON swiss_matches(status)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_winner
        ON swiss_matches(winner_id)
        """)

        # ==========================================================
        # FIN
        # ==========================================================
        
    CREATE TABLE IF NOT EXISTS swiss_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
       
        await db.commit()

    print("✅ Base de données Hamtaro initialisée.")


