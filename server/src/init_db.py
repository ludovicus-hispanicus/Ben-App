from common.global_handlers import global_users_handler
from entities.text import Text, Uploader
from common.env_vars import STORAGE_PATH
from entities.user import UserRole
from mongo.mongo_client import MongoClient
import os
import logging

users = [
    {
        "fullname": "Lord Lalazar",
        "email": "roeylalazar@gmail.com",
        "password": "EEUc2uzX2a"
    },
    {
        "fullname": "Dr. Shai G",
        "email": "shygordin@gmail.com",
        "password": "INtbKVqiNP"
    },
    {
        "fullname": "Lady Romach",
        "email": "lond12lance@gmail.com",
        "password": "azG3C8p08d"
    },
    {
        "fullname": "Senior Luis",
        "email": "luissaenzs@gmail.com",
        "password": "ImUyCYmWun"
    },
    {
        "fullname": "Mister Ireman",
        "email": "ireman.br@gmail.com",
        "password": "LmZryGcgAl"
    },
    {
        "fullname": "Dr. Moni S",
        "email": "monishahar@gmail.com",
        "password": "j17Qqz9GwM"
    },
    {
        "fullname": "Dr. Ethan F",
        "email": "ethanfetaya@gmail.com",
        "password": "z2IuKgnFrW"
    },
    {
        "fullname": "Morris Alper",
        "email": "morrisalper@mail.tau.ac.il",
        "password": "3k8ANfk40f6"
    },
    {
        "fullname": "Samuel Clark",
        "email": "clark.samuel@gmail.com",
        "password": "q5IOKfnFRw"
    }
]


def init_the_db():
    logging.info("init db...")
    print("init db called")
    db = MongoClient.get_db()
    logging.info("found db...")
    add_users()
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


def add_users():
    # global_users_handler.add_user(full_name="Or Lewenstein", email="or.lewenstein@mail.huji.ac.il",
    #                               password="a35Abm9DDs3",
    #                               role=UserRole.ADMIN)

    if global_users_handler.count() > 0:
        return

    for user in users:
        print(f"adding  {user}")
        global_users_handler.add_user(full_name=user["fullname"], email=user["email"], password=user["password"],
                                      role=UserRole.ADMIN)
