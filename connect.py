import psycopg2

from config import DB_CONFIG


def get_connection():
    """Open a new PostgreSQL connection using settings from config.py."""
    return psycopg2.connect(**DB_CONFIG)
