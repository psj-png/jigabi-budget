# 테스트는 개발 DB(jigabi)가 아니라 jigabi_test를 쓴다.
# 세션이 시작될 때 한 번 jigabi_test를 지우고 schema.sql + seed.sql로 새로 만든다.
import os
from pathlib import Path

TEST_DB = "jigabi_test"
DB_DIR = Path(__file__).resolve().parent.parent / "db"


def pytest_sessionstart(session):
    # app/db.py의 get_conn은 호출할 때마다 DB_NAME을 읽으니 환경변수만 바꾸면 된다
    os.environ["DB_NAME"] = TEST_DB

    try:
        import pymysql
        from pymysql.constants import CLIENT

        # DB 이름 없이 접속 (여러 문장을 한 번에 실행할 수 있게 MULTI_STATEMENTS)
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            charset="utf8mb4",
            client_flag=CLIENT.MULTI_STATEMENTS,
            connect_timeout=3,
        )
    except Exception:
        return  # DB에 못 붙으면 DB 테스트는 conn 픽스처에서 skip

    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            for name in ["schema.sql", "seed.sql"]:
                sql = (DB_DIR / name).read_text(encoding="utf-8")
                sql = sql.replace("CREATE DATABASE IF NOT EXISTS jigabi ",
                                  f"CREATE DATABASE IF NOT EXISTS {TEST_DB} ")
                sql = sql.replace("USE jigabi;", f"USE {TEST_DB};")
                cur.execute(sql)
                while cur.nextset():  # 여러 문장의 결과를 모두 비운다
                    pass
        conn.commit()
    finally:
        conn.close()
