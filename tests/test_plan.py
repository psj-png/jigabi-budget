# 계획 도우미 (R22): OpenAI는 부르지 않고 가짜 응답으로 확인한다
import json
from datetime import date

import pymysql
import pytest

from app import calc, cart, plan, queries, setup, shop
from app.db import get_conn
from app.home import make_home

TODAY = date(2026, 10, 31)  # 새 사람(10/30 시작, 학교 월~금 점심 6,000)의 둘째 날, 토요일


@pytest.fixture
def conn():
    try:
        c = get_conn()
    except pymysql.err.OperationalError:
        pytest.skip("DB에 연결할 수 없음")
    yield c
    c.close()


@pytest.fixture
def user(conn):
    d = setup.new_draft()
    d["balance"] = "290000"
    user_id, _ = setup.create_account(conn, setup.draft_data(d), date(2026, 10, 30))
    yield user_id
    queries.delete_user(conn, user_id)


def answer(reply, days, save):
    return lambda payload: {"choices": [{"message": {"content": json.dumps({"reply": reply, "meal_days": days, "save": save})}}]}


def test_선택지는_앱이_계산한다(conn, user):
    opts, h = plan.options(conn, user, TODAY)
    # 학교 가는 날(월~금)만, 앞으로 14일까지, 점심값 6,000
    assert [m["day"] for m in opts["meals"]][:3] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert len(opts["meals"]) == plan.MAX_MEAL_DAYS and {m["amount"] for m in opts["meals"]} == {6000}
    # 모아 둘 수 있는 최대: 여유 돈 − 넉넉 기준의 절반 × 남은 날, 1,000원 단위
    assert opts["max_save"] == (h["free"] - 5000 * h["days_left"]) // 1000 * 1000
    assert opts["context"]["다음 돈 들어오는 날"] == "2026-11-25" and opts["context"]["그날 들어올 돈"] == 500000


def test_선택지_밖은_버린다(conn, user):
    opts, _ = plan.options(conn, user, TODAY)
    got = plan.choose(opts, {"meal_days": ["2026-11-02", "2026-11-01", "2026-11-02", "아무거나"], "save": 999999999})
    assert [m["day"] for m in got["meals"]] == ["2026-11-02"]  # 일요일·중복·이상한 값은 빠진다
    assert got["save"] == opts["max_save"]
    assert plan.choose(opts, {"meal_days": [], "save": 0}) is None


def test_적용하면_모든_화면이_따라_바뀐다(conn, user):
    before = make_home(conn, user, TODAY)
    assert plan.ask(conn, user, TODAY, "알바비 날까지 어떻게 쓸까?",
                    call=answer("월·화 점심을 도시락으로 바꾸고 3만 원은 모아 둬요.", ["2026-11-02", "2026-11-03"], 30000)) is None
    chat = shop.make_chat(conn, user, TODAY)
    card = chat["messages"][-1]
    assert card["mode"] == "plan" and [m["day"] for m in card["plan"]["meals"]] == ["2026-11-02", "2026-11-03"]
    expected = calc.daily_margin(before["free"] + 12000 - 30000, before["days_left"])
    assert (card["look"]["before"], card["look"]["after"]) == (before["daily"], expected)

    assert plan.apply(conn, user, TODAY, card["id"])
    after = make_home(conn, user, TODAY)
    assert (after["free"], after["daily"]) == (before["free"] + 12000 - 30000, expected)  # 카드에서 본 숫자 그대로
    assert after["saved"] == 30000 and len(after["changes"]) == 3
    # 장바구니 칩도 같은 여유 돈으로 계산한다
    assert cart.make_cart(conn, user, TODAY, [])["now_daily"] == expected
    # 도시락 날 아침에는 그날 점심값이 빠진다 (오늘 쓸 수 있는 돈)
    monday = make_home(conn, user, date(2026, 11, 2))
    tuesday_plain = calc.min_living_on(date(2026, 11, 2), queries.get_routines(conn, user))
    assert monday["today_min"] == tuesday_plain - 6000
    # 같은 제안은 두 번 적용하지 않는다
    assert not plan.apply(conn, user, TODAY, card["id"])
    assert shop.make_chat(conn, user, TODAY)["messages"][-1]["applied"]

    # 되돌리면 원래대로
    for ch in after["changes"]:
        queries.delete_plan_change(conn, user, ch["change_id"])
    assert make_home(conn, user, TODAY)["free"] == before["free"]


def test_실패하거나_바꿀_게_없을_때(conn, user):
    import urllib.error

    def down(payload):
        raise urllib.error.URLError("끊김")

    assert plan.ask(conn, user, TODAY, "어떻게 쓸까?", call=down) == "plan"
    assert plan.ask(conn, user, TODAY, "지금 괜찮아?", call=answer("지금처럼 쓰면 돼요.", [], 0)) is None
    last = shop.make_chat(conn, user, TODAY)["messages"][-1]
    assert last["content"] == "지금처럼 쓰면 돼요." and last["plan"] is None
    assert plan.ask(conn, user, TODAY, "   ") == "empty"
