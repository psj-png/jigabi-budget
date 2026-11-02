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
    free = calc.free_money(balance, calc.incomes_sum(f, end, incomes),
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
    # 밤 기록이 있으면 내일(10/31 토) 쓸 수 있는 돈 = 3,100 + 8,900
    assert h["logged"] and h["budget"] == 12000 and h["missed_days"] == 0

    # 여유 돈이 나온 과정 (네 칸)
    assert (h["available"], h["fixed"], h["appt"], h["min_living"], h["repay"]) ==         (534200, 43900, 30000, 236200, 0)
    assert h["available"] - h["fixed"] - h["appt"] - h["min_living"] - h["repay"] == h["free"]

    # 11/3: 마지막 기록이 10/30이라 사이 3일(10/31~11/2)을 최소 생활비만큼 쓴 것으로 계산
    h = make_home(conn, USER_ID, date(2026, 11, 3))
    assert h["missed_days"] == 3
    assert (h["days_left"], h["free"], h["daily"], h["stage"]) == (22, 224100, 10100, "빵빵")


def test_홈_화면_기록이_하나도_없을_때(conn):
    from app.home import make_home

    # seed의 10/30 밤 기록을 빼고 계산 (끝나면 되돌림)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM balance_logs WHERE user_id = %s", (USER_ID,))
    try:
        h = make_home(conn, USER_ID, date(2026, 11, 3))
    finally:
        conn.rollback()
    # 기간 시작(10/30)부터 4일을 안 적은 것으로 본다
    assert h["missed_days"] == 4
    assert (h["days_left"], h["free"], h["daily"], h["stage"]) == (22, 229900, 10400, "빵빵")


def test_새_기간_만들기(conn):
    from app.home import make_home

    # 11/25 홈: 그날을 덮는 기간이 없어서 만든다. 마지막 기록은 10/30 밤 284,200
    try:
        h = make_home(conn, USER_ID, date(2026, 11, 25))
        per = queries.get_period(conn, USER_ID, date(2026, 11, 25))
    finally:
        # periods에 넣은 행을 지워서 다른 테스트와 seed에 영향이 없게 한다
        with conn.cursor() as cur:
            cur.execute("DELETE FROM periods WHERE user_id = %s AND start_date = %s",
                        (USER_ID, date(2026, 11, 25)))
        conn.commit()

    assert h["ready"]
    assert (per["start_date"], per["end_date"], per["opening_balance"]) ==         (date(2026, 11, 25), date(2026, 12, 24), 224100)
    assert (h["days_left"], h["free"], h["daily"], h["stage"]) == (30, 614000, 20400, "빵빵")
    assert h["budget"] == 35500  # 수요일: 학교 15,100 + 하루 여유 20,400
    assert h["missed_days"] == 25


# ---- 밤 잔액 적기 (DB에 저장하므로 끝나면 seed 상태로 되돌린다) ----
from app import balance as balance_page


@pytest.fixture
def clean(conn):
    yield
    # 테스트에서 넣은 balance_logs·periods 행을 지운다 (seed는 10/30 기록과 첫 기간만)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM balance_logs WHERE user_id = %s AND log_date <> %s",
                    (USER_ID, date(2026, 10, 30)))
        cur.execute("DELETE FROM periods WHERE user_id = %s AND start_date <> %s",
                    (USER_ID, date(2026, 10, 30)))
        cur.execute("UPDATE periods SET opening_balance = 290000 WHERE user_id = %s", (USER_ID,))
    conn.commit()


def test_밤_잔액_어제_저장(conn, clean):
    from app.home import make_home

    # today=11/1에 어제(10/31) 280,000 저장: 지난 잔액 284,200 -> 쓴 돈 4,200
    assert balance_page.save(conn, USER_ID, date(2026, 11, 1), date(2026, 10, 31), 280000, 0) is None
    log = queries.get_balance_log(conn, USER_ID, date(2026, 10, 31))
    assert (log["balance"], log["spent"]) == (280000, 4200)

    h = make_home(conn, USER_ID, date(2026, 11, 1))
    assert (h["days_left"], h["free"], h["daily"], h["stage"]) == (24, 223000, 9200, "든든")
    assert h["budget"] == 12300


def test_밤_잔액_폼에_예정_수입(conn, clean):
    # 11/1을 적으려면 그 사이 11/1 용돈 250,000이 있어서 들어온 돈 칸이 채워진다
    f = balance_page.get_form(conn, USER_ID, date(2026, 11, 1), date(2026, 11, 1))
    assert f["show_income"] and f["income_plan"] == 250000
    # 10/31만 적는 폼에는 예정 수입이 없어서 칸을 숨긴다
    f = balance_page.get_form(conn, USER_ID, date(2026, 11, 1), date(2026, 10, 31))
    assert not f["show_income"]


def test_밤_잔액_기간_시작_전날을_적으면_시작_잔액을_고친다(conn, clean):
    from app.home import make_home

    today = date(2026, 11, 25)
    make_home(conn, USER_ID, today)  # 11/25 기간을 먼저 만든다

    # 어제(11/24) 100,000, 들어온 돈 250,000: 284,200 + 250,000 - 43,900 - 100,000 = 390,300
    assert balance_page.save(conn, USER_ID, today, date(2026, 11, 24), 100000, 250000) is None
    log = queries.get_balance_log(conn, USER_ID, date(2026, 11, 24))
    assert log["spent"] == 390300
    assert queries.get_period(conn, USER_ID, today)["opening_balance"] == 100000

    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"], h["stage"]) == (489900, 16300, "빵빵")
    assert h["budget"] == 31400 and h["missed_days"] == 0


def test_밤_잔액_오늘_기록이_있으면_어제는_못_적는다(conn, clean):
    from app.home import make_home

    today = date(2026, 11, 25)
    make_home(conn, USER_ID, today)
    assert balance_page.save(conn, USER_ID, today, today, 200000, 0) is None

    message = balance_page.save(conn, USER_ID, today, date(2026, 11, 24), 100000, 0)
    assert message == "오늘 밤 잔액을 이미 적어서 어제는 못 적어요"
    assert queries.get_balance_log(conn, USER_ID, date(2026, 11, 24)) is None
    assert balance_page.get_form(conn, USER_ID, today, date(2026, 11, 24))["message"] == message


def test_밤_잔액_기간이_없어도_폼부터_열_수_있다(conn, clean):
    # 홈을 열지 않고 11/25 폼부터: 11/25 기간이 생기고 시작 잔액은 224,100
    today = date(2026, 11, 25)
    f = balance_page.get_form(conn, USER_ID, today, today)
    assert f["message"] is None and f["show_income"] and f["income_plan"] == 420000
    assert queries.get_period(conn, USER_ID, today)["opening_balance"] == 224100

    # 오늘 잔액 600,000: 224,100 + 420,000 - 0 - 600,000 = 44,100
    assert balance_page.save(conn, USER_ID, today, today, 600000, 420000) is None
    assert queries.get_balance_log(conn, USER_ID, today)["spent"] == 44100


def test_밤_잔액_앱_시작_전_날짜는_못_적는다(conn, clean):
    today, day = date(2026, 10, 30), date(2026, 10, 29)
    message = "앱을 시작하기 전 날짜라 적을 수 없어요"
    assert balance_page.get_form(conn, USER_ID, today, day)["message"] == message
    assert balance_page.save(conn, USER_ID, today, day, 100000, 0) == message
    assert queries.get_balance_log(conn, USER_ID, day) is None
    assert queries.get_period(conn, USER_ID, day) is None


# ---- 약속 (DB에 넣으므로 끝나면 지운다) ----
@pytest.fixture
def clean_appts(conn):
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM appointments WHERE user_id = %s AND appt_date = %s",
                    (USER_ID, date(2026, 11, 13)))
    conn.commit()


def test_약속_추가하고_지우기(conn, clean_appts):
    from app.home import make_home

    today = date(2026, 10, 31)  # 10/30 밤 기록 다음 날
    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"], h["budget"]) == (224100, 8900, 12000)

    # 11/13 약속 50,000 + 교통 3,100 -> 여유 돈 171,000, 하루 여유 6,800, 오늘 3,100 + 6,800
    queries.insert_appointment(conn, USER_ID, date(2026, 11, 13), "테스트 약속", 50000, 3100)
    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"], h["stage"], h["budget"]) == (171000, 6800, "든든", 9900)

    # 지우면 원래대로
    appt = [a for a in queries.get_appointments(conn, USER_ID) if a["title"] == "테스트 약속"][0]
    queries.delete_appointment(conn, USER_ID, appt["appt_id"])
    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"], h["budget"]) == (224100, 8900, 12000)


def test_get_user_id(conn):
    assert queries.get_user_id(conn, "3f6b2a1c-7d4e-4b8a-9c2d-1e5f6a7b8c9d") == USER_ID
    assert queries.get_user_id(conn, "없는-아이디") is None


# ---- 첫 설정 저장 (새 사용자를 만들고 끝나면 지운다) ----
import hashlib

from app import setup

SEED_LIKE = {
    "balance": 290000,
    "incomes": [
        {"name": "알바비", "day_of_month": 25, "amount": 420000, "is_main": True},
        {"name": "용돈", "day_of_month": 1, "amount": 250000, "is_main": False},
    ],
    "fixed": [
        {"name": "통신비", "day_of_month": 5, "amount": 33000},
        {"name": "음악 구독", "day_of_month": 12, "amount": 10900},
    ],
    "comfort_daily": 10000, "hourly_wage": 10320, "emergency_fund": 0,
    "routines": [
        {"name": "학교", "weekdays": [0, 1, 2, 3], "meals_out": 2, "meal_price": 6000,
         "round_trip_fare": 3100, "start_date": date(2026, 9, 1), "end_date": date(2026, 12, 18)},
        {"name": "알바", "weekdays": [5, 6], "meals_out": 0, "meal_price": 0,
         "round_trip_fare": 3100, "start_date": None, "end_date": None},
    ],
}


def count(conn, sql, args):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchone().values())[0]


def test_첫_설정_저장(conn):
    from app.home import make_home

    today = date(2026, 10, 30)
    user_id, public_id, code = setup.create_account(conn, SEED_LIKE, today)
    try:
        assert user_id != USER_ID

        # a) 첫 기간
        per = queries.get_period(conn, user_id, today)
        assert (per["start_date"], per["end_date"], per["opening_balance"]) == \
            (date(2026, 10, 30), date(2026, 11, 24), 290000)

        # b) 약속 없이: 259,900 / 26 = 9,996 -> 9,900
        h = make_home(conn, user_id, today)
        assert (h["days_left"], h["min_living"], h["available"]) == (26, 236200, 540000)
        assert (h["daily"], h["stage"]) == (9900, "든든")

        # c) 11/7 약속 30,000 -> rules.md '기록 전' 예시와 같다
        queries.insert_appointment(conn, user_id, date(2026, 11, 7), "술자리", 30000, 0)
        h = make_home(conn, user_id, today)
        assert (h["free"], h["daily"], h["stage"]) == (229900, 8800, "든든")

        # d) 복구 코드의 해시와 public_id
        with conn.cursor() as cur:
            cur.execute("SELECT recovery_hash FROM users WHERE user_id = %s", (user_id,))
            assert cur.fetchone()["recovery_hash"] == hashlib.sha256(code.encode("utf-8")).hexdigest()
        assert queries.get_user_id(conn, public_id) == user_id
        # 다른 사용자의 데이터와 섞이지 않는다
        assert len(queries.get_appointments(conn, user_id)) == 1
        assert len(queries.get_appointments(conn, USER_ID)) == 1  # seed의 술자리
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT routine_id FROM routines WHERE user_id = %s", (user_id,))
            routine_ids = [r["routine_id"] for r in cur.fetchall()]
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()

    # 사용자를 지우면 딸린 행도 CASCADE로 같이 지워진다
    for table in ["incomes", "fixed_costs", "routines", "appointments", "periods"]:
        assert count(conn, f"SELECT COUNT(*) FROM {table} WHERE user_id = %s", (user_id,)) == 0
    assert len(routine_ids) == 2
    assert count(conn, "SELECT COUNT(*) FROM routine_days WHERE routine_id IN (%s, %s)",
                 tuple(routine_ids)) == 0


def test_첫_설정_중간에_실패하면_전부_되돌린다(conn):
    before = count(conn, "SELECT COUNT(*) FROM users", ())
    bad = dict(SEED_LIKE, fixed=[{"name": "x" * 30, "day_of_month": 5, "amount": 1}])  # 이름이 너무 김
    with pytest.raises(Exception):
        setup.create_account(conn, bad, date(2026, 10, 30))
    assert count(conn, "SELECT COUNT(*) FROM users", ()) == before


# ---- 장바구니 미리보기 ----
from app import cart


@pytest.fixture
def clean_wish(conn):
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM wish_items WHERE user_id = %s AND name = %s", (USER_ID, "테스트 물건"))
    conn.commit()


def test_장바구니_미리보기(conn):
    today = date(2026, 10, 31)  # 기록 후 25일, 여유 돈 224,100
    ids = {w["name"]: w["item_id"] for w in queries.get_wish_items(conn, USER_ID)}
    assert set(ids) == {"롱패딩", "니트", "목도리", "부츠"}

    # 아무것도 안 고르면
    c = cart.make_cart(conn, USER_ID, today, [])
    assert c["now"] == "든든" and c["now_daily"] == 8900 and c["after"] is None
    assert c["message"] == "담은 걸 체크하면 사면 어떻게 되는지 보여줘요"
    assert [i["chip"] for i in c["items"]] == ["홀쭉", "든든", "든든", "홀쭉"]

    # 롱패딩만
    c = cart.make_cart(conn, USER_ID, today, [ids["롱패딩"]])
    assert (c["after"]["daily"], c["after"]["stage"], c["after"]["short"]) == (1400, "홀쭉", 0)
    assert c["hours"] == 18
    assert c["message"] == "지금은 든든인데, 롱패딩을 사면 홀쭉이 나와요"
    assert c["shortage"] is None

    # 4개 다
    c = cart.make_cart(conn, USER_ID, today, list(ids.values()))
    assert (c["after"]["daily"], c["after"]["stage"], c["after"]["short"]) == (-6500, "나방", 161900)
    assert c["hours"] == 37
    assert c["message"] == "지금은 든든인데, 롱패딩 외 3개를 사면 나방이 나와요"
    assert c["shortage"] == "최소 생활비를 161,900원 건드려요"
    assert c["hours_text"] == "= 알바 약 37시간"


def test_장바구니_물건_추가(conn, clean_wish):
    queries.insert_wish_item(conn, USER_ID, "테스트 물건", 12000, None)
    names = [w["name"] for w in queries.get_wish_items(conn, USER_ID)]
    assert "테스트 물건" in names


def test_장바구니_기간_마지막_날_밤이면_미리보기_없음(conn):
    # 11/24 밤 기록 -> 남은 날 0. 기록을 잠깐 넣었다가 지운다
    queries.save_balance_log(conn, USER_ID, date(2026, 11, 24), 100000, 0, 0)
    try:
        c = cart.make_cart(conn, USER_ID, date(2026, 11, 24), [])
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM balance_logs WHERE user_id = %s AND log_date = %s",
                        (USER_ID, date(2026, 11, 24)))
        conn.commit()
    assert c["ended"] and c["message"] == "이번 기간이 끝났어요. 새 기간에 다시 봐요"
    assert all(i["chip"] is None for i in c["items"])


# ---- 나눠 사기 ----
from app import split


@pytest.fixture
def clean_extra_wishes(conn):
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM wish_items WHERE user_id = %s AND name LIKE %s", (USER_ID, "테스트 물건%"))
    conn.commit()


def test_나눠_사기_seed(conn):
    today = date(2026, 10, 31)  # 기록 후 25일, 여유 돈 224,100
    ids = [w["item_id"] for w in queries.get_wish_items(conn, USER_ID)]
    s = split.make_split(conn, USER_ID, today, ids)
    plan = s["plan"]

    # 다음 기간 11/25~12/24, 그다음 12/25~1/24의 여유 돈
    assert (plan[1]["free"], plan[1]["days"]) == (389900, 30)
    assert (plan[2]["free"], plan[2]["days"]) == (595100, 31)

    # calc 테스트 b)와 같은 결과
    assert [n for n, _, _ in plan[0]["items"]] == ["니트", "목도리", "부츠"]
    assert (plan[0]["daily"], plan[0]["stage"]) == (1000, "홀쭉")
    assert [n for n, _, _ in plan[1]["items"]] == ["롱패딩"]
    assert (plan[1]["daily"], plan[1]["stage"]) == (6600, "든든")
    assert s["note"] == "필요한 날(12/1)도 맞추고, 최소 생활비도 안 건드려요."
    assert s["income_note"] == "다음 기간은 예상 수입 67만 원(알바비 42만 + 용돈 25만) 기준이에요."
    assert (plan[0]["label"], plan[1]["label"], plan[2]["label"]) == \
        ("지금 · 10/31", "11/25 알바비 들어온 뒤", "12/25 이후")


def test_나눠_사기_9개부터는_막는다(conn, clean_extra_wishes):
    for n in range(5):
        queries.insert_wish_item(conn, USER_ID, f"테스트 물건{n}", 1000, None)
    ids = [w["item_id"] for w in queries.get_wish_items(conn, USER_ID)]
    assert len(ids) == 9
    s = split.make_split(conn, USER_ID, date(2026, 10, 31), ids)
    assert s["plan"] is None and s["message"] == "8개까지만 나눠 볼 수 있어요"
    # 8개는 계산한다
    s = split.make_split(conn, USER_ID, date(2026, 10, 31), ids[:8])
    assert s["plan"] is not None
