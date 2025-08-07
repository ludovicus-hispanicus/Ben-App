import os

import pymongo

from common.env_vars import MONGODB_DATABASE, MONGODB_HOSTNAME, MONGODB_USERNAME, MONGODB_PASSWORD, APP_ENV
from common.environments import Environment


class MongoCursor:

    def __init__(self):
        pass

    @staticmethod
    def get_next(cursor):
        if cursor and cursor.alive:
            try:
                return next(cursor)
            except Exception as e:
                return None
        return None


class MongoClient:
    DB_NAME = os.environ.get(MONGODB_DATABASE)

    HOST = os.environ.get(MONGODB_HOSTNAME)
    ENV = os.environ.get(APP_ENV)
    USERNAME = os.environ.get(MONGODB_USERNAME)
    PASSWORD = os.environ.get(MONGODB_PASSWORD)

    NEW_TEXTS_COLLECTION = "new_texts"
    USERS_COLLECTION = "users"
    TEXTS_COLLECTION = "texts"

    def __init__(self):
        pass

    @classmethod
    def get_db(cls):
        MongoClient.ENV = os.environ.get(APP_ENV).lower()
        if Environment.DEV.value.lower() == MongoClient.ENV:
            return pymongo.MongoClient(cls.HOST)[cls.DB_NAME]
        elif Environment.PROD.value.lower() == MongoClient.ENV:
            mongo_client = pymongo.MongoClient(cls.HOST, username=MongoClient.USERNAME, password=MongoClient.PASSWORD)
            return mongo_client[cls.DB_NAME]
        else:
            print(f"app environment not recognized: {MongoClient.ENV}")
