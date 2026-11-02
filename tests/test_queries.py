# DB에서 읽은 값으로 계산이 맞는지 확인한다. DB에 못 붙으면 건너뜀
# 접속 정보는 app/db.py와 같은 환경변수 (docker compose를 띄운 상태라면
# DB_HOST=127.0.0.1 DB_PORT=3307 DB_PASSWORD=<.env의 MYSQL_ROOT_PASSWORD>)
from datetime import date

import pytest

pymysql = pytest.importorskip("pymysql")

from app import calc, queries
from app.db import get_conn

USER_ID = 1  # seed의 예시 사람
TODAY = date(2026, 10, 30)


@pytest.fixture
def conn():
    try:
        c = get_conn()
    except pymysql.err.OperationalError:
        pytest.skip("DB에 연결할 수 없음")
    yield c
    c.close()


def test_seed_기록_후_예시(conn):
    routines = queries.get_routines(conn, USER_ID)
    incomes = queries.get_incomes(conn, USER_ID)
    fixed = queries.get_fixed_costs(conn, USER_ID)
    appts = queries.get_appointments(conn, USER_ID)
    per = queries.get_period(conn, USER_ID, TODAY)
    log = queries.get_latest_balance_log(conn, USER_ID, TODAY)

    # 오늘(10/30) 밤 기록이 있으면 그 잔액으로, 남은 날은 내일부터
    logged = log is not None and log["log_date"] == TODAY
    assert logged
    balance = log["balance"]

    start, end, days_left = calc.period(TODAY, 25, app_start=per["start_date"], logged_tonight=logged)
    f = calc.first_day(TODAY, logged)
    ml = calc.min_living(f, end, routines)
    free = calc.free_money(balance, calc.other_incomes_sum(f, end, incomes),
                           calc.monthly_sum(f, end, fixed),
                           calc.appointments_sum(f, end, appts), ml, per["repay_amount"])
    daily = calc.daily_margin(free, days_left)

    assert (days_left, ml, free, daily) == (25, 236200, 224100, 8900)


def test_가장_최근_밤_잔액(conn):
    # 기록 전 날짜는 None, 기록 뒤 날짜는 마지막 기록(10/30)
    assert queries.get_latest_balance_log(conn, USER_ID, date(2026, 10, 29)) is None
    log = queries.get_latest_balance_log(conn, USER_ID, date(2026, 11, 5))
    assert log["log_date"] == TODAY and log["balance"] == 284200


def test_홈_화면_값(conn):
    from app.home import make_home

    # 10/30 밤 기록이 있는 상태: 남은 날 25, 여유 돈 224,100, 하루 여유 8,900, 든든
    h = make_home(conn, USER_ID, TODAY)
    assert (h["days_left"], h["free"], h["daily"], h["stage"]) == (25, 224100, 8900, "든든")
    assert h["logged"] and h["budget"] is None and h["missed_days"] == 0

    # 기록이 없는 날(기간 시작 전 기록은 안 씀): 10/30 아침 기준 = 기록 전 값
    # 11/3은 10/30 기록이 있고 사이가 3일 비었다
    h = make_home(conn, USER_ID, date(2026, 11, 3))
    assert h["missed_days"] == 3
