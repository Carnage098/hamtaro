import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATABASE = BASE_DIR / "database.db"
