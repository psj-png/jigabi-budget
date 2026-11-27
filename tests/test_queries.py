# DB에서 읽은 값으로 계산이 맞는지 확인한다. DB에 못 붙으면 건너뜀
# 접속 정보는 app/db.py와 같은 환경변수 (docker compose를 띄운 상태라면
# DB_HOST=127.0.0.1 DB_PORT=3317 DB_PASSWORD=<.env의 MYSQL_ROOT_PASSWORD>)
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


def test_홈_남은_기간_막대는_오늘부터_센다(conn):
    from app.home import make_home

    def parts(h):
        return (h["available"], h["fixed"], h["appt"], h["min_living"], h["free"])

    # 10/30 밤 기록 뒤라 막대 제목은 내일(10/31)부터
    assert make_home(conn, USER_ID, TODAY)["bar_from"] == date(2026, 10, 31)

    # 11/3: 10/31~11/2를 R10대로 메운 예상 잔액 512,900부터. 11/5·11/12 고정지출과 11/7 약속은 아직 남았다
    h = make_home(conn, USER_ID, date(2026, 11, 3))
    assert parts(h) == (512900, 43900, 30000, 214900, 224100)
    assert h["bar_from"] == date(2026, 11, 3)

    # 11/16: 고정지출·약속은 이미 지나서 0, 남은 9일 최소 생활비 96,800 (예전엔 10/31부터 세서 534,200)
    h = make_home(conn, USER_ID, date(2026, 11, 16))
    assert h["missed_days"] == 16
    assert parts(h) == (320900, 0, 0, 96800, 224100)
    assert (h["days_left"], h["daily"], h["stage"]) == (9, 24900, "빵빵")
    for h in [make_home(conn, USER_ID, date(2026, 11, d)) for d in (3, 16)]:
        assert h["available"] - h["fixed"] - h["appt"] - h["min_living"] - h["repay"] - h["items_out"] == h["free"]


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
    user_id, public_id = setup.create_account(conn, SEED_LIKE, today)
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

        # d) 쿠키에 넣는 public_id로 다시 찾는다
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
    assert [it[0] for it in plan[0]["items"]] == ["니트", "목도리", "부츠"]
    assert (plan[0]["daily"], plan[0]["stage"]) == (1000, "홀쭉")
    assert [it[0] for it in plan[1]["items"]] == ["롱패딩"]
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


# ---- 산 것·반품·나눠 사기 저장 (끝나면 seed 상태로 되돌린다) ----
from app import purchase


@pytest.fixture
def clean_purchases(conn):
    yield
    with conn.cursor() as cur:
        cur.execute("UPDATE wish_items SET status = 'wish', planned_date = NULL, bought_date = NULL, "
                    "received_date = NULL, returned_date = NULL WHERE user_id = %s", (USER_ID,))
        cur.execute("DELETE FROM balance_logs WHERE user_id = %s AND log_date <> %s",
                    (USER_ID, date(2026, 10, 30)))
        cur.execute("UPDATE balance_logs SET balance = 284200 WHERE user_id = %s AND log_date = %s",
                    (USER_ID, date(2026, 10, 30)))
        cur.execute("DELETE FROM periods WHERE user_id = %s AND start_date <> %s",
                    (USER_ID, date(2026, 10, 30)))
    conn.commit()


def item_ids(conn):
    return {w["name"]: w["item_id"] for w in queries.get_wish_items(conn, USER_ID)}


def test_산_것과_반품(conn, clean_purchases):
    from app.home import make_home

    ids = item_ids(conn)

    # a) 10/31에 니트 49,000을 사면 여유 돈 224,100 -> 175,100, 하루 여유 7,000
    assert purchase.buy_now(conn, USER_ID, [ids["니트"]], date(2026, 10, 31)) == 1
    h = make_home(conn, USER_ID, date(2026, 10, 31))
    assert (h["free"], h["daily"]) == (175100, 7000)
    assert h["items_out"] == 49000

    # b) 이어서 10/31 밤 잔액 232,100: 지난 잔액 284,200 - 산 것 49,000 - 232,100 = 쓴 돈 3,100
    assert balance_page.save(conn, USER_ID, date(2026, 10, 31), date(2026, 10, 31), 232100, 0) is None
    assert queries.get_balance_log(conn, USER_ID, date(2026, 10, 31))["spent"] == 3100

    # c) 11/1에 니트를 반품하면 환불 49,000이 11/1에 들어온 것: 여유 돈 224,100, 하루 여유 9,300
    assert purchase.return_item(conn, USER_ID, ids["니트"], date(2026, 11, 1)) is True
    h = make_home(conn, USER_ID, date(2026, 11, 1))
    assert (h["free"], h["daily"]) == (224100, 9300)
    # 이미 반품한 것은 다시 반품할 수 없다
    assert purchase.return_item(conn, USER_ID, ids["니트"], date(2026, 11, 1)) is False


def test_밤_잔액을_적은_날_사면_적은_잔액에서_뺀다(conn, clean_purchases):
    from app.home import make_home

    ids = item_ids(conn)
    # d) 10/30 밤 기록(284,200)이 있는 날 목도리 29,000을 사면 그 잔액이 255,200
    purchase.buy_now(conn, USER_ID, [ids["목도리"]], date(2026, 10, 30))
    assert queries.get_balance_log(conn, USER_ID, date(2026, 10, 30))["balance"] == 255200
    h = make_home(conn, USER_ID, date(2026, 10, 30))
    assert (h["free"], h["daily"]) == (195100, 7800)

    # 그날 반품하면 다시 더해진다
    assert purchase.return_item(conn, USER_ID, ids["목도리"], date(2026, 10, 30)) is True
    assert queries.get_balance_log(conn, USER_ID, date(2026, 10, 30))["balance"] == 284200


def test_나눠_사기_저장(conn, clean_purchases):
    from app.home import make_home

    ids = item_ids(conn)
    today = date(2026, 10, 31)
    assert purchase.save_split(conn, USER_ID, today, list(ids.values())) is True

    # e) 니트·목도리·부츠는 산 것, 롱패딩은 11/25에 사기로 함
    status = {i["name"]: (i["status"], i["planned_date"], i["bought_date"])
              for i in queries.get_items(conn, USER_ID)}
    assert status["니트"] == ("bought", None, today)
    assert status["목도리"] == ("bought", None, today)
    assert status["부츠"] == ("bought", None, today)
    assert status["롱패딩"] == ("planned", date(2026, 11, 25), None)
    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"]) == (27100, 1000)

    # f) 11/25: 새 기간 시작 잔액 27,100, 롱패딩 189,000은 그날 계획이라 여유 돈에서 빠진다
    h = make_home(conn, USER_ID, date(2026, 11, 25))
    assert queries.get_period(conn, USER_ID, date(2026, 11, 25))["opening_balance"] == 27100
    assert (h["free"], h["daily"], h["stage"]) == (228000, 7600, "든든")

    # 계획한 물건은 장바구니(wish) 목록에서 빠진다
    assert "롱패딩" not in item_ids(conn)


def test_계획한_물건은_날짜가_지나도_사거나_취소할_때까지_뺀다(conn, clean_purchases):
    from app.home import make_home

    ids = item_ids(conn)
    롱패딩 = ids["롱패딩"]
    purchase.save_split(conn, USER_ID, date(2026, 10, 31), list(ids.values()))
    make_home(conn, USER_ID, date(2026, 11, 25))  # 새 기간 만들기

    # g) 11/26 밤 잔액 416,900 = 27,100 + 알바비 420,000 - 학교 15,100 x 2
    assert balance_page.save(conn, USER_ID, date(2026, 11, 26), date(2026, 11, 26), 416900, 0) is None

    # 11/27: count_from이 11/26 뒤로 넘어가도 안 산 롱패딩 189,000은 계속 뺀다
    h = make_home(conn, USER_ID, date(2026, 11, 27))
    assert (h["free"], h["daily"], h["stage"], h["days_left"]) == (228000, 8100, "든든", 28)
    assert h["due_items"] == ["롱패딩"]  # 사기로 한 날(11/25)이 지났다

    # [계획 취소]: 다시 wish, 여유 돈 417,000
    assert purchase.unplan_item(conn, USER_ID, 롱패딩) is True
    it = [i for i in queries.get_items(conn, USER_ID) if i["item_id"] == 롱패딩][0]
    assert (it["status"], it["planned_date"]) == ("wish", None)
    h = make_home(conn, USER_ID, date(2026, 11, 27))
    assert h["free"] == 417000 and h["due_items"] == []

    # 11/27에 롱패딩을 사면 다시 228,000
    purchase.buy_now(conn, USER_ID, [롱패딩], date(2026, 11, 27))
    assert make_home(conn, USER_ID, date(2026, 11, 27))["free"] == 228000


def test_계획한_물건은_장바구니에서_바로_산다(conn, clean_purchases):
    # 사기로 한 날이 지나면 홈이 '장바구니에서 [살게요]'라고 안내한다: 계획 취소 없이 바로 살 수 있어야 한다
    from jinja2 import Environment, FileSystemLoader
    from app.home import make_home

    ids = item_ids(conn)
    롱패딩 = ids["롱패딩"]
    purchase.save_split(conn, USER_ID, date(2026, 10, 31), list(ids.values()))
    make_home(conn, USER_ID, date(2026, 11, 25))  # 새 기간 만들기
    assert balance_page.save(conn, USER_ID, date(2026, 11, 26), date(2026, 11, 26), 416900, 0) is None
    today = date(2026, 11, 27)

    # '살 계획' 줄에 [살게요] 폼이 있다 (아무것도 체크 안 했으니 /cart/buy 폼은 이것뿐)
    cart_html = Environment(loader=FileSystemLoader("app/templates")).get_template("cart.html")
    html = cart_html.render(c=cart.make_cart(conn, USER_ID, today, []), stages=cart.STAGES, today_q="2026-11-27")
    assert html.count('action="/cart/buy"') == 1
    assert f'<input type="hidden" name="item" value="{롱패딩}">' in html

    # 계획한 그대로 산다: 여유 돈은 계획일 때와 같은 228,000, 사기로 한 날 안내는 사라진다
    assert purchase.buy_now(conn, USER_ID, [롱패딩], today) == 1
    it = [i for i in queries.get_items(conn, USER_ID) if i["item_id"] == 롱패딩][0]
    assert (it["status"], it["bought_date"]) == ("bought", today)
    h = make_home(conn, USER_ID, today)
    assert h["free"] == 228000 and h["due_items"] == []


def test_반품은_산_날_빼고_7일_안(conn, clean_purchases):
    ids = item_ids(conn)
    purchase.buy_now(conn, USER_ID, [ids["니트"]], date(2026, 10, 31))
    assert purchase.return_item(conn, USER_ID, ids["니트"], date(2026, 11, 8)) is False   # 8일째
    assert queries.get_items(conn, USER_ID)[1]["status"] == "bought"
    assert purchase.return_item(conn, USER_ID, ids["니트"], date(2026, 11, 7)) is True     # 7일째


def test_남의_물건은_사거나_반품할_수_없다(conn, clean_purchases):
    ids = item_ids(conn)
    other, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        # 다른 사용자가 seed 사용자의 item_id로 사려고 해도 아무것도 안 바뀐다
        assert purchase.buy_now(conn, other, list(ids.values()), date(2026, 10, 31)) == 0
        assert all(i["status"] == "wish" for i in queries.get_items(conn, USER_ID))

        # seed 사용자가 산 것을 다른 사용자가 반품하려 해도 안 된다
        purchase.buy_now(conn, USER_ID, [ids["니트"]], date(2026, 10, 31))
        assert purchase.return_item(conn, other, ids["니트"], date(2026, 11, 1)) is False
        assert queries.get_items(conn, USER_ID)[1]["status"] == "bought"
        # 계획 잡기도 마찬가지
        with conn.cursor() as cur:
            assert queries.plan_item(conn, other, ids["부츠"], date(2026, 11, 25)) == 0
        conn.rollback()
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (other,))
        conn.commit()


# ---- 다시 짜기 (끝나면 seed 상태로 되돌린다) ----
from app import replan


@pytest.fixture
def clean_replan(conn, clean_purchases):
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM loans WHERE user_id = %s", (USER_ID,))
        cur.execute("UPDATE users SET emergency_fund = 100000 WHERE user_id = %s", (USER_ID,))
        cur.execute("UPDATE appointments SET amount = 30000 WHERE user_id = %s", (USER_ID,))
    conn.commit()


def buy_three(conn):
    # 롱패딩·니트·목도리 267,000을 10/31에 산다
    ids = item_ids(conn)
    purchase.buy_now(conn, USER_ID, [ids["롱패딩"], ids["니트"], ids["목도리"]], date(2026, 10, 31))


def test_다시_짜기(conn, clean_replan):
    from app.home import make_home

    today = date(2026, 10, 31)
    buy_three(conn)
    h = make_home(conn, USER_ID, today)
    assert h["free"] == -42900

    # 제안: 술자리 30,000 -> 10,000 줄이기, 비상금 32,900
    r = replan.make_replan(conn, USER_ID, today)
    assert r["short"] == 42900
    assert [(x["appt"]["title"], x["cut"]) for x in r["rows"]] == [("동기 술자리", 10000)]
    assert (r["borrow"], r["left"]) == (32900, 0)
    appt_id = r["rows"][0]["appt"]["appt_id"]

    # 저장하면 여유 돈 0, 하루 여유 0 텅텅, 약속 20,000, 비상금 67,100, loans 1행
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 10000}) is None
    h = make_home(conn, USER_ID, today)
    assert (h["free"], h["daily"], h["stage"]) == (0, 0, "텅텅")
    assert queries.get_appointments(conn, USER_ID)[0]["amount"] == 20000
    assert queries.get_user(conn, USER_ID)["emergency_fund"] == 67100
    loans = queries.get_loans(conn, USER_ID)
    assert [(l["borrowed_on"], l["amount"]) for l in loans] == [(today, 32900)]
    # 이제 모자라지 않으니 다시 저장할 수 없다
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 1000}) == "모자라지 않아요"

    # 그날 밤 '들어온 돈' 미리 채우기 32,900, 밤 잔액 47,000 -> 쓴 돈 3,100
    assert balance_page.get_form(conn, USER_ID, today, today)["income_plan"] == 32900
    assert balance_page.save(conn, USER_ID, today, today, 47000, 32900) is None
    assert queries.get_balance_log(conn, USER_ID, today)["spent"] == 3100

    # 11/25: 새 기간 시작 잔액 0, 갚을 돈 32,900, 비상금은 100,000으로 돌아옴
    h = make_home(conn, USER_ID, date(2026, 11, 25))
    per = queries.get_period(conn, USER_ID, date(2026, 11, 25))
    assert (per["opening_balance"], per["repay_amount"]) == (0, 32900)
    assert queries.get_user(conn, USER_ID)["emergency_fund"] == 100000
    assert (h["free"], h["daily"], h["stage"]) == (357000, 11900, "빵빵")


def test_다시_짜기_줄일_금액은_고친_대로_비상금을_다시_계산(conn, clean_replan):
    today = date(2026, 10, 31)
    buy_three(conn)
    r = replan.make_replan(conn, USER_ID, today)
    appt_id = r["rows"][0]["appt"]["appt_id"]
    # 30,000을 다 줄이면 비상금에서는 12,900만 빌린다
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 30000}) is None
    assert queries.get_user(conn, USER_ID)["emergency_fund"] == 87100
    assert queries.get_loans(conn, USER_ID)[0]["amount"] == 12900


def test_다시_짜기_범위_밖의_금액과_남의_약속은_막는다(conn, clean_replan):
    today = date(2026, 10, 31)
    buy_three(conn)
    appt_id = replan.make_replan(conn, USER_ID, today)["rows"][0]["appt"]["appt_id"]
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 30001}) is not None   # 약속 금액 초과
    assert replan.save_replan(conn, USER_ID, today, {appt_id: -1}) is not None      # 음수

    other, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        queries.insert_appointment(conn, other, date(2026, 11, 7), "남의 약속", 30000, 0)
        other_appt = queries.get_appointments(conn, other)[0]["appt_id"]
        assert replan.save_replan(conn, USER_ID, today, {other_appt: 10000}) == "줄일 수 없는 약속이에요"
        assert queries.get_appointments(conn, other)[0]["amount"] == 30000
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (other,))
        conn.commit()
    # 아무것도 안 바뀌었다
    assert queries.get_appointments(conn, USER_ID)[0]["amount"] == 30000
    assert len(queries.get_loans(conn, USER_ID)) == 0
    assert queries.get_user(conn, USER_ID)["emergency_fund"] == 100000


def test_나눠_사기는_이번_기간에_빌린_돈을_다음_기간에서_뺀다(conn, clean_replan):
    today = date(2026, 10, 31)
    buy_three(conn)
    appt_id = replan.make_replan(conn, USER_ID, today)["rows"][0]["appt"]["appt_id"]
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 10000}) is None  # 비상금 32,900

    # 부츠 하나: 이번 기간은 안 되고 다음 기간에 하루 여유 7,900 든든
    boots = item_ids(conn)["부츠"]
    plan = split.make_split(conn, USER_ID, today, [boots])["plan"]
    assert plan[0]["items"] == []
    assert [it[0] for it in plan[1]["items"]] == ["부츠"]
    assert plan[1]["free"] == 389900 - 32900   # 다음 기간 여유 돈 (갚을 돈을 뺌, 부츠 값은 아직)
    assert (plan[1]["daily"], plan[1]["stage"]) == (7900, "든든")   # (389,900 − 32,900 − 119,000) ÷ 30


def test_홈에_모자라면_다시_짜기_링크가_보인다(conn, clean_replan):
    from jinja2 import Environment, FileSystemLoader
    from app.home import make_home

    home_html = Environment(loader=FileSystemLoader("app/templates")).get_template("home.html")
    today = date(2026, 10, 31)

    # 세 개를 샀지만 다시 짜기를 안 했다: 42,900원 모자라요 + 링크
    buy_three(conn)
    html = home_html.render(h=make_home(conn, USER_ID, today), today_q="2026-10-31")
    assert "최소 생활비가 42,900원 모자라요" in html
    assert 'href="/replan?today=2026-10-31"' in html

    # 다시 짜기를 저장하면 여유 돈 0: 링크가 안 보인다
    appt_id = replan.make_replan(conn, USER_ID, today)["rows"][0]["appt"]["appt_id"]
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 10000}) is None
    html = home_html.render(h=make_home(conn, USER_ID, today), today_q="2026-10-31")
    assert "모자라요" not in html


def test_다시_짜기_비상금을_이미_빌렸으면_그렇게_보여준다(conn, clean_replan):
    from jinja2 import Environment, FileSystemLoader

    replan_html = Environment(loader=FileSystemLoader("app/templates")).get_template("replan.html")
    today = date(2026, 10, 31)
    purchase.buy_now(conn, USER_ID, list(item_ids(conn).values()), today)  # 4개 386,000

    # 처음: 161,900 모자람 -> 술자리 10,000 줄이고 비상금 100,000을 빌려도 51,900 모자람
    r = replan.make_replan(conn, USER_ID, today)
    assert (r["short"], r["borrow"], r["borrowed"], r["left"]) == (161900, 100000, 0, 51900)
    html = replan_html.render(r=r, today_q="2026-10-31", now=today)
    assert "남은 100,000원</b>을 비상금(100,000원)에서 빌리고 11/25부터 갚아요" in html
    assert "이렇게 메워도 최소 생활비가 51,900원 모자라요" in html
    assert "최소 생활비는 지켜요" not in html  # 아직 모자란데 지킨다고 하지 않는다

    # 저장한 뒤 다시 열면 비상금은 0원: '남은 0원을 비상금(0원)에서' 대신 이미 빌린 돈을 보여준다
    appt_id = r["rows"][0]["appt"]["appt_id"]
    assert replan.save_replan(conn, USER_ID, today, {appt_id: 10000}) is None
    r = replan.make_replan(conn, USER_ID, today)
    assert (r["short"], r["fund"], r["borrow"], r["borrowed"]) == (51900, 0, 0, 100000)
    html = replan_html.render(r=r, today_q="2026-10-31", now=today)
    assert "비상금에서 이미 100,000원 빌렸어요 · 11/25부터 갚아요" in html
    assert "남은 0원" not in html



# ---- 흐름 2·3·4·6 ----
def test_첫_설정_확인_숫자는_첫날_홈과_같다(conn):
    # R17: 5/5 확인 화면의 숫자 = 계정을 만든 첫날 홈
    from app.home import make_home

    look = setup.preview(SEED_LIKE, date(2026, 10, 30))
    assert (look["free"], look["daily"], look["stage"], look["budget"]) == (259900, 9900, "든든", 9900)
    user_id, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        h = make_home(conn, user_id, date(2026, 10, 30))
        assert (look["free"], look["daily"], look["stage"], look["budget"], look["days_left"], look["end"]) == (
            h["free"], h["daily"], h["stage"], h["budget"], h["days_left"], h["end"])
        # 첫날에는 '어젯밤' 칸이 없다 (앱을 시작하기 전 날)
        assert balance_page.make_card(conn, user_id, date(2026, 10, 30), date(2026, 10, 30))["other_day"] is None
    finally:
        queries.delete_user(conn, user_id)


def test_쓴_돈으로_적기(conn, clean_purchases):
    # R10-1: 10/30은 시작 잔액 290,000에서 5,800원 → seed 10/30 밤 잔액과 같다
    assert balance_page.guess_balance(conn, USER_ID, date(2026, 10, 30), 5800) == (284200, 0)
    # 11/3: 10/31~11/2는 R10대로 21,300원, 11/1 용돈 250,000은 들어왔다고 본다
    assert balance_page.guess_balance(conn, USER_ID, date(2026, 11, 3), 10000) == (502900, 250000)
    # 그대로 저장하면 그날 쓴 돈은 안 적은 날 몫까지 합친 31,300
    assert balance_page.save(conn, USER_ID, date(2026, 11, 3), date(2026, 11, 3), 502900, 250000) is None
    assert queries.get_balance_log(conn, USER_ID, date(2026, 11, 3))["spent"] == 31300


def test_밤_잔액_카드(conn, clean_purchases):
    # 14: 10/30은 이미 적어서 결과. 10/31은 아직이라 적기 전이고, 어젯밤(10/30)으로 바꿔 적을 수 있다
    card = balance_page.make_card(conn, USER_ID, date(2026, 10, 30), date(2026, 10, 30))
    assert card["mode"] == "result"
    assert (card["result"]["left"], card["result"]["after_budget"], card["result"]["stage_after"]) == (3000, 12000, "든든")
    card = balance_page.make_card(conn, USER_ID, date(2026, 10, 31), date(2026, 10, 31))
    assert (card["mode"], card["other_day"]) == ("input", date(2026, 10, 30))
    assert balance_page.make_card(conn, USER_ID, date(2026, 10, 31), date(2026, 10, 31), guess=284200)["mode"] == "confirm"
    assert balance_page.make_card(conn, USER_ID, date(2026, 10, 30), date(2026, 10, 30), edit=True)["mode"] == "input"


def test_산_것과_반품을_되돌린다(conn, clean_purchases):
    # R18
    from app.home import make_home

    ids = item_ids(conn)
    today = date(2026, 10, 31)
    purchase.buy_now(conn, USER_ID, [ids["니트"]], today)
    assert make_home(conn, USER_ID, today)["free"] == 224100 - 49000
    assert purchase.unbuy_items(conn, USER_ID, [ids["니트"]], today) == 1
    assert make_home(conn, USER_ID, today)["free"] == 224100
    knit = [i for i in queries.get_items(conn, USER_ID) if i["item_id"] == ids["니트"]][0]
    assert (knit["status"], knit["bought_date"]) == ("wish", None)

    # 다른 날 산 것은 되돌리지 않는다
    purchase.buy_now(conn, USER_ID, [ids["목도리"]], today)
    assert purchase.unbuy_items(conn, USER_ID, [ids["목도리"]], date(2026, 11, 1)) == 0
    # 반품 되돌리기: 그날 반품한 것만
    assert purchase.return_item(conn, USER_ID, ids["목도리"], today)
    assert purchase.unreturn_item(conn, USER_ID, ids["목도리"], today)
    assert make_home(conn, USER_ID, today)["free"] == 224100 - 29000
    assert not purchase.unreturn_item(conn, USER_ID, ids["목도리"], today)  # 이미 산 것


def test_설정에서_돈_들어오는_날_바꾸기(conn):
    # R15: 기간 기준을 바꿔도 지금 기간은 그대로, 다음 기간은 앞 기간 다음 날부터 새 날짜로
    from app.home import make_home

    user_id, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        rows = queries.list_incomes(conn, user_id)
        main = [r for r in rows if r["is_main"]][0]
        pocket = [r for r in rows if not r["is_main"]][0]
        assert queries.delete_income(conn, user_id, main["income_id"]) == 0  # 기간 기준은 못 뺀다
        queries.update_income(conn, user_id, pocket["income_id"], "용돈", 1, 300000)
        queries.insert_income(conn, user_id, "장학금", 10, 100000)
        assert [(r["name"], r["amount"]) for r in queries.list_incomes(conn, user_id)] == [
            ("알바비", 420000), ("용돈", 300000), ("장학금", 100000)]

        assert queries.set_main_income(conn, user_id, pocket["income_id"])
        assert make_home(conn, user_id, date(2026, 10, 30))["end"] == date(2026, 11, 24)
        assert balance_page.save(conn, user_id, date(2026, 11, 24), date(2026, 11, 24), 100000, 0) is None
        h = make_home(conn, user_id, date(2026, 11, 25))
        assert (h["end"], h["days_left"]) == (date(2026, 11, 30), 6)
        assert queries.delete_income(conn, user_id, main["income_id"]) == 1  # 이제 기준이 아니라 뺄 수 있다
    finally:
        queries.delete_user(conn, user_id)


def test_설정에서_가는_곳을_고치면_오늘부터(conn):
    # R15: 예전 줄은 어제로 끝내고 새 줄은 오늘부터
    from app import settings

    user_id, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        school = [r for r in queries.list_routines(conn, user_id) if r["name"] == "학교"][0]
        alba = [r for r in queries.list_routines(conn, user_id) if r["name"] == "알바"][0]
        p = settings.make_places(conn, user_id, date(2026, 10, 30))
        assert p["total"] == 236200
        assert [(x["name"], x["days"], x["per_day"]) for x in p["parts"]] == [("학교", 14, 15100), ("알바", 8, 3100)]

        today = date(2026, 11, 16)
        assert settings.edit_place(conn, user_id, school["routine_id"], dict(school, meals_out=1), today)
        routines = queries.get_routines(conn, user_id)
        assert calc.min_living(date(2026, 10, 30), date(2026, 11, 15), routines) == 139400
        assert calc.min_living(today, date(2026, 11, 24), routines) == 96800 - 6 * 6000

        assert settings.end_place(conn, user_id, alba["routine_id"], today)  # 알바는 11/15까지
        assert calc.min_living(today, date(2026, 11, 24), queries.get_routines(conn, user_id)) == 54600
        names = [r["name"] for r in settings.make_places(conn, user_id, today)["places"]]
        assert names == ["학교"]
    finally:
        queries.delete_user(conn, user_id)


def test_설정_숫자와_데이터_지우기(conn):
    from app import settings

    user_id, public_id = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    queries.update_user_numbers(conn, user_id, 20000, 11000, 50000)
    assert queries.get_user(conn, user_id) == {"comfort_daily": 20000, "emergency_fund": 50000,
                                               "hourly_wage": 11000}
    settings.delete_account(conn, user_id)
    assert queries.get_user_id(conn, public_id) is None
    assert count(conn, "SELECT COUNT(*) FROM routines WHERE user_id = %s", (user_id,)) == 0


def test_지난_기간_돌아보기(conn):
    from app import settings

    hist = settings.make_history(conn, USER_ID, date(2026, 10, 31))
    assert len(hist["rows"]) == 1
    s = hist["sel"]
    assert (s["start"], s["end"], s["days"], s["nights"], s["spent"]) == (
        date(2026, 10, 30), date(2026, 11, 24), 2, 1, 5800)
    assert [b["spent"] for b in hist["bars"]] == [5800, None]
    assert hist["diff"] is None


def test_같은_기간은_한_번만_들어간다(conn):
    user_id, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        before = queries.get_user(conn, user_id)["emergency_fund"]
        for _ in range(2):  # ensure_period가 겹쳐 불려도 한 줄
            queries.insert_period(conn, user_id, date(2026, 11, 25), date(2026, 12, 24), 100000, 5000)
        sql = "SELECT COUNT(*) FROM periods WHERE user_id = %s AND start_date = %s"
        assert count(conn, sql, (user_id, date(2026, 11, 25))) == 1
        assert queries.get_user(conn, user_id)["emergency_fund"] == before + 5000  # 갚은 돈도 한 번만
    finally:
        queries.delete_user(conn, user_id)


def test_주_수입은_한_사람에_하나만(conn):
    user_id, _ = setup.create_account(conn, SEED_LIKE, date(2026, 10, 30))
    try:
        with pytest.raises(pymysql.err.IntegrityError):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO incomes (user_id, name, day_of_month, amount, is_main) "
                            "VALUES (%s, '또 주 수입', 3, 100000, TRUE)", (user_id,))
        conn.rollback()
        # 주 수입이 아닌 줄은 여러 개여도 된다
        queries.insert_income(conn, user_id, "용돈1", 5, 10000)
        queries.insert_income(conn, user_id, "용돈2", 6, 10000)
    finally:
        queries.delete_user(conn, user_id)
