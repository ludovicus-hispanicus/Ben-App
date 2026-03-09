"""
Database client for CuReD desktop app.
Uses local JSON-based storage instead of MongoDB for simplicity.
"""
from mongo.local_db_client import LocalDBClient, LocalCollection, MongoCursor


class MongoClient:
    """Compatibility wrapper that uses LocalDBClient for storage."""
    DB_NAME = "local"

    TEXTS_COLLECTION = "texts"
    NEW_TEXTS_COLLECTION = "new_texts"
    USERS_COLLECTION = "users"

    _db = None
    _connected = True  # Always "connected" since we use local storage

    @classmethod
    def get_db(cls):
        if cls._db is None:
            cls._db = LocalDBClient.get_db()
        return cls._db

    @classmethod
    def is_connected(cls):
        return cls._connected
