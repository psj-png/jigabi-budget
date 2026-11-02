import os

import pymysql


def get_conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "jigabi"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
