import aiosqlite

DATABASE = "database.db"
DB_VERSION = 3


async def table_exists(
    db: aiosqlite.Connection,
    table_name: str,
) -> bool:
    """
    Vérifie si une table existe déjà dans la base SQLite.
    """

    cursor = await db.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = ?
        """,
        (table_name,),
    )

    row = await cursor.fetchone()
    return row is not None


async def column_exists(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    """
    Vérifie si une colonne existe déjà dans une table SQLite.
    Utile quand la base existe déjà sur Railway.
    """

    if not await table_exists(db, table_name):
        return False

    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    columns = await cursor.fetchall()
    return column_name in [column[1] for column in columns]


async def ensure_column(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    """
    Ajoute une colonne seulement si elle n'existe pas déjà.
    Exemple : await ensure_column(db, "registrations", "deck", "TEXT")
    """

    if not await table_exists(db, table_name):
        return

    if not await column_exists(db, table_name, column_name):
        await db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


async def ensure_no_checkin_needed(
    db: aiosqlite.Connection,
) -> None:
    """
    Rend tous les joueurs inscrits automatiquement disponibles.
    Le check-in n'est plus nécessaire : si un joueur est inscrit, il est considéré disponible.
    On garde la colonne checked_in pour éviter de casser l'ancienne base.
    """

    if await column_exists(db, "registrations", "checked_in"):
        await db.execute("""
            UPDATE registrations
            SET checked_in = 1
            WHERE checked_in IS NULL OR checked_in = 0
        """)


async def run_migrations(
    db: aiosqlite.Connection,
) -> None:
    """
    Met à jour les anciennes bases déjà créées.
    CREATE TABLE IF NOT EXISTS ne modifie pas les tables existantes,
    donc on ajoute ici les colonnes manquantes proprement.
    """

    # ==========================================================
    # MIGRATIONS TOURNOIS
    # ==========================================================

    await ensure_column(db, "tournaments", "current_round", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "tournaments", "total_rounds", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "tournaments", "winner_id", "TEXT")
    await ensure_column(db, "tournaments", "winner_name", "TEXT")
    await ensure_column(db, "tournaments", "bracket_message_id", "TEXT")
    await ensure_column(db, "tournaments", "started_at", "TIMESTAMP")
    await ensure_column(db, "tournaments", "finished_at", "TIMESTAMP")

    # ==========================================================
    # MIGRATIONS JOUEURS
    # ==========================================================

    await ensure_column(db, "players", "display_name", "TEXT")
    await ensure_column(db, "players", "avatar_url", "TEXT")
    await ensure_column(db, "players", "wins", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "players", "losses", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "players", "tournaments_played", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "players", "tournaments_won", "INTEGER NOT NULL DEFAULT 0")

    # ==========================================================
    # MIGRATIONS INSCRIPTIONS
    # ==========================================================

    await ensure_column(db, "registrations", "deck", "TEXT")
    await ensure_column(db, "registrations", "seed", "INTEGER")
    await ensure_column(db, "registrations", "checked_in", "INTEGER NOT NULL DEFAULT 1")
    await ensure_column(db, "registrations", "dropped", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "registrations", "disqualified", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "registrations", "final_rank", "INTEGER")

    # ==========================================================
    # MIGRATIONS MATCHS BRACKET
    # ==========================================================

    await ensure_column(db, "matches", "match_number", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "matches", "bracket_position", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "matches", "next_match_id", "INTEGER")
    await ensure_column(db, "matches", "next_slot", "INTEGER")
    await ensure_column(db, "matches", "player1_score", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "matches", "player2_score", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "matches", "winner_id", "TEXT")
    await ensure_column(db, "matches", "winner_name", "TEXT")
    await ensure_column(db, "matches", "score", "TEXT")
    await ensure_column(db, "matches", "reported_by", "TEXT")
    await ensure_column(db, "matches", "validated_by", "TEXT")
    await ensure_column(db, "matches", "reported_at", "TIMESTAMP")
    await ensure_column(db, "matches", "validated_at", "TIMESTAMP")
    await ensure_column(db, "matches", "is_bye", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "matches", "notes", "TEXT")
    await ensure_column(db, "matches", "created_at", "TIMESTAMP")

    # ==========================================================
    # MIGRATIONS RONDES SUISSES - MATCHS
    # ==========================================================

    await ensure_column(db, "swiss_matches", "is_double_loss", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_matches", "result", "TEXT NOT NULL DEFAULT 'none'")
    await ensure_column(db, "swiss_matches", "finished_at", "TIMESTAMP")

    # ==========================================================
    # MIGRATIONS RONDES SUISSES - CLASSEMENT
    # ==========================================================

    await ensure_column(db, "swiss_standings", "points", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "wins", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "losses", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "double_losses", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "byes", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "matches_played", "INTEGER NOT NULL DEFAULT 0")
    await ensure_column(db, "swiss_standings", "updated_at", "TIMESTAMP")


async def init_db() -> None:
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
        # MATCHS BRACKET
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            round INTEGER NOT NULL,
            match_number INTEGER NOT NULL DEFAULT 0,
            bracket_position INTEGER NOT NULL DEFAULT 0,
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
            is_double_loss INTEGER NOT NULL DEFAULT 0,
            is_bye INTEGER NOT NULL DEFAULT 0,
            result TEXT NOT NULL DEFAULT 'none',
            status TEXT NOT NULL DEFAULT 'pending',
            reported_by TEXT,
            reported_at TIMESTAMP,
            finished_at TIMESTAMP,
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
            ),
            CHECK (
                result IN (
                    'none',
                    'player1',
                    'player2',
                    'draw',
                    'double_loss'
                )
            )
        )
        """)

        # ==========================================================
        # RONDES SUISSES - CLASSEMENT
        # ==========================================================

        await db.execute("""
        CREATE TABLE IF NOT EXISTS swiss_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            discord_id TEXT NOT NULL,
            username TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            double_losses INTEGER NOT NULL DEFAULT 0,
            byes INTEGER NOT NULL DEFAULT 0,
            matches_played INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
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
        # MIGRATIONS POUR ANCIENNE BASE
        # ==========================================================

        await run_migrations(db)

        # ==========================================================
        # INDEXES TOURNOIS / JOUEURS / INSCRIPTIONS
        # ==========================================================

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament_guild
        ON tournaments(guild_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament_code
        ON tournaments(code)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tournament_status
        ON tournaments(status)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_players_guild
        ON players(guild_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_registration_tournament
        ON registrations(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_registration_discord
        ON registrations(discord_id)
        """)

        # ==========================================================
        # INDEXES MATCHS BRACKET
        # ==========================================================

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

        # ==========================================================
        # INDEXES RONDES SUISSES
        # ==========================================================

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

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_result
        ON swiss_matches(result)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_match_double_loss
        ON swiss_matches(is_double_loss)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_standings_tournament
        ON swiss_standings(tournament_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_standings_player
        ON swiss_standings(discord_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_swiss_standings_rank
        ON swiss_standings(
            tournament_id,
            points DESC,
            double_losses ASC,
            wins DESC,
            losses ASC
        )
        """)

        # ==========================================================
        # PLUS DE CHECK-IN OBLIGATOIRE
        # ==========================================================

        await ensure_no_checkin_needed(db)

        # ==========================================================
        # VERSION DB
        # ==========================================================

        await db.execute("""
        UPDATE metadata
        SET value = ?
        WHERE key = 'db_version'
        """, (str(DB_VERSION),))

        await db.commit()

    print("✅ Base de données Hamtaro initialisée.")
