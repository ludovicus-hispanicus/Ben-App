# Auth removed for desktop app - no hardcoded users needed
from entities.text import Text, Uploader
from common.env_vars import STORAGE_PATH
from mongo.mongo_client import MongoClient
import os
import logging


def init_the_db():
    logging.info("init db...")
    print("init db called")
    db = MongoClient.get_db()
    logging.info("found db...")
    # Auth removed - no users needed for desktop app
    logging.info("check if collection exists...")
    collections = db.list_collection_names()
    if len(collections) > 0:
        logging.info("collections exists")
        texts = db[MongoClient.TEXTS_COLLECTION]
        doc_count = texts.count_documents({})
        logging.info(f"{doc_count} records found!")
        return

    return

    logging.info("dropping db...")
    db[MongoClient.TEXTS_COLLECTION].drop()
    logging.info("started loading texts...")

    BASE_PATH = os.environ.get(STORAGE_PATH)
    for i in range(1, 384):
        transliteration = []
        transliteration_path = os.path.join(BASE_PATH, "cyrus_texts", f"{i}.txt")
        with open(transliteration_path, encoding="UTF-8") as file:
            lines = file.readlines()
            for line in lines:
                line = line.replace("\n", "")
                line = line.split(" ")
                transliteration.append(line)
        original_transliteration = []
        original_transliteration_path = os.path.join(BASE_PATH, "cyrus_texts_original", f"{i}.txt")
        with open(original_transliteration_path, encoding="UTF-8") as file:
            lines = file.readlines()
            for line in lines:
                line = line.replace("\n", "")
                original_transliteration.append(line)

        metadata = [
            {"Title": f"Strassmaier, Cyrus {i}"},
            {"Babylonian date": "[o]-vii-Cyr 0"},
            {"Julian date": "octobre 539"},
            {"place of redaction": "(Sippar)"},
            {"archive": "(Ebabbar)"},
            {"type": "tablette"},
            {"language": "babylonien"},
            {"writing system": "cunéiforme"},
            {"edition": "Peiser, KB 4, p. 262"},
            {"remarks": "Weissbach, ZDMG 55, p. 211 "},
            {"summary": "Réception par l'Ebabbar de moutons, avec leur équivalent en argent, fournis par, etc). "},
            {"editor": "Francis Joannès"},
            {"upload date": "19 septembre 2002"},
            {"last update": "NaN"},
            {"material": "NaN"},
        ]
        text = Text(text_id=i,
                    transliteration=transliteration,
                    original_transliteration=original_transliteration,
                    metadata=metadata,
                    origin=Uploader.ADMIN)
        db[MongoClient.TEXTS_COLLECTION].insert_one(text.dict())
    logging.info("started loading texts...DONE")
    logging.info("loaded 384 texts")
