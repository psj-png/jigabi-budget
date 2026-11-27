# 합성 데이터 만들기 (인덱스 실험용): 사람 100명 + 채팅 + 약속
# random.seed(42)라 언제 돌려도 같은 데이터가 나온다. jigabi_bench에만 넣는다
import os
import random
import sys
import uuid
from datetime import date, timedelta

import pymysql
from pymysql.constants import CLIENT

BENCH_DB = "jigabi_bench"
PEOPLE = 100
SEMESTER = (date(2026, 9, 1), date(2026, 12, 18))  # 109일
FOUR_YEARS = (date(2022, 12, 19), date(2026, 12, 18))  # 1,461일


def connect(db=None):
    # db를 안 주면 DB 없이 접속 (DB를 만들고 지울 때)
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=db,
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def insert_many(cur, sql, rows):
    # 한 번에 너무 많이 보내지 않게 나눠서 넣는다
    for i in range(0, len(rows), 5000):
        cur.executemany(sql, rows[i:i + 5000])


def make(conn, start, end):
    random.seed(42)
    cur = conn.cursor()

    # 사람 100명: 채팅 쓰는 날 확률은 60명 0.1, 30명 0.4, 10명 0.9
    for _ in range(PEOPLE):
        cur.execute("INSERT INTO users (public_id) VALUES (%s)", (str(uuid.UUID(int=random.getrandbits(128))),))
    cur.execute("SELECT user_id FROM users ORDER BY user_id")
    ids = [r["user_id"] for r in cur.fetchall()]
    chance = [0.1] * 60 + [0.4] * 30 + [0.9] * 10
    random.shuffle(chance)

    # 채팅: 쓰는 날엔 보내는 말 1~20개, 말마다 user 행 + assistant 행. 날짜 순서로 넣는다
    chat_sql = "INSERT INTO chat_messages (user_id, chat_day, role, mode, content) VALUES (%s, %s, %s, %s, %s)"
    chats = []
    for d in range((end - start).days + 1):
        day = start + timedelta(days=d)
        for user_id, p in zip(ids, chance):
            if random.random() < p:
                for _ in range(random.randint(1, 20)):
                    mode = random.choice(["shop", "plan"])
                    chats.append((user_id, day, "user", mode, "겨울에 입을 코트 찾아 줘"))
                    chats.append((user_id, day, "assistant", mode, "이런 상품은 어때요?"))
        if len(chats) >= 50000:
            insert_many(cur, chat_sql, chats)
            chats = []
    insert_many(cur, chat_sql, chats)

    # 약속: 주마다 1~3개, 날짜는 그 주 안에서 아무 날, 금액은 10,000~50,000원(천 원 단위)
    appts = []
    for user_id in ids:
        week = start
        while week <= end:
            days_in_week = min(7, (end - week).days + 1)
            for _ in range(random.randint(1, 3)):
                day = week + timedelta(days=random.randint(0, days_in_week - 1))
                appts.append((user_id, day, "약속", random.randint(10, 50) * 1000))
            week += timedelta(days=7)
    random.shuffle(appts)  # 약속은 날짜 순서대로 적지 않으니 넣는 순서도 섞는다
    insert_many(cur, "INSERT INTO appointments (user_id, appt_date, title, amount) VALUES (%s, %s, %s, %s)", appts)


if __name__ == "__main__":
    # python db/make_synth.py 학기   (또는 4년): schema.sql로 만들어 둔 jigabi_bench에 넣는다
    start, end = FOUR_YEARS if sys.argv[1:] == ["4년"] else SEMESTER
    make(connect(BENCH_DB), start, end)
