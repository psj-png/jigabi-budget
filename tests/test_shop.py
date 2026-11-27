# 쇼핑 추천 채팅 (R21): OpenAI는 부르지 않고 가짜 응답으로 확인한다
import json
import urllib.error
from datetime import date

import pymysql
import pytest

from app import ai, cart, queries, setup, shop
from app.db import get_conn
from app.home import make_home

A = "https://www.musinsa.com/products/1111"
B = "https://www.musinsa.com/products/2222"


def answer(items, sources=(A, B), reply="찾아봤어요."):
    # Responses API 모양의 가짜 답: 웹 검색에서 본 주소들과 JSON 답
    return {"output": [
        {"type": "web_search_call", "action": {"type": "search", "sources": [{"type": "url", "url": u} for u in sources]}},
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"reply": reply, "items": items})}]},
    ]}


@pytest.fixture
def conn():
    try:
        c = get_conn()
    except pymysql.err.OperationalError:
        pytest.skip("DB에 연결할 수 없음")
    yield c
    c.close()


def coat(url, price=129000, name="울 블렌드 코트"):
    return {"name": name, "price": price, "url": url, "reason": "울 섞인 기본 코트"}


def new_user(conn):
    d = setup.new_draft()
    d["balance"] = "290000"
    user_id, _ = setup.create_account(conn, setup.draft_data(d), date(2026, 10, 30))
    return user_id


def test_예산은_지갑으로_계산한다(conn):
    # seed 10/31: 여유 돈 224,100, 남은 25일, 넉넉 기준 10,000 → 든든 유지 224,100 − 5,000 × 25
    h = make_home(conn, 1, date(2026, 10, 31))
    b = shop.budget(h, 10000)
    assert b == {"keep_solid": 99100, "no_touch": 224100}
    assert "99,100원까지" in shop.budget_line(b)


def test_검색에서_본_무신사_페이지만_남긴다():
    items = [coat(A), coat(B + "?utm=x", price="89,000원", name="  숏 코트 "),
             coat("https://www.musinsa.com/products/9999"),      # 검색에서 안 본 주소: 지어냈을 수 있다
             coat("https://example.com/products/1"),            # 무신사가 아님
             coat(A, name="")]                                  # 이름 없음
    reply, picks = ai.parse_picks(answer(items))
    assert reply == "찾아봤어요."
    assert [(p["name"], p["price"], p["url"]) for p in picks] == [
        ("울 블렌드 코트", 129000, A), ("숏 코트", 89000, B + "?utm=x")]
    assert ai.is_shop_url("https://store.musinsa.com/x") and not ai.is_shop_url("https://musinsa.com.evil.io/x")


def test_요청_모양(monkeypatch):
    sent = {}

    def fake(payload):
        sent.update(payload)
        return answer([coat(A)])

    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    reply, picks, error = ai.recommend("이런 코트", "든든 유지 99,100원까지", png, call=fake)
    assert error is None and len(picks) == 1
    tool = sent["tools"][0]
    assert tool["type"] == "web_search" and tool["filters"]["allowed_domains"] == ["musinsa.com"]
    assert sent["include"] == ["web_search_call.action.sources"]
    assert sent["text"]["format"]["strict"] is True and "99,100원" in sent["instructions"]
    assert sent["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert "reasoning" not in sent  # 기본 모델(gpt-6.1-terra)에는 reasoning을 보내지 않는다
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")  # gpt-5 계열만 reasoning을 받는다
    ai.recommend("이런 코트", "", png, call=fake)
    assert sent["reasoning"] == {"effort": "low"}
    assert ai.recommend("코트", "", b"not image", call=fake) == (None, [], "type")


def test_대화를_저장하고_하루_횟수를_지킨다(conn, monkeypatch):
    user_id = new_user(conn)
    today = date(2026, 10, 31)
    try:
        assert shop.ask(conn, user_id, today, "  겨울   코트 ", call=lambda p: answer([coat(A)])) is None
        chat = shop.make_chat(conn, user_id, today)
        assert [(m["role"], m["content"]) for m in chat["messages"]] == [("user", "겨울 코트"), ("assistant", "찾아봤어요.")]
        pick = chat["messages"][1]["items"][0]
        assert (pick["url"], pick["price"]) == (A, 129000) and pick["chip"] in ("빵빵", "든든", "홀쭉", "텅텅", "나방")
        assert chat["used"] == 1

        # 고를 게 없으면 다시 말해 달라고 한다
        shop.ask(conn, user_id, today, "코트", call=lambda p: answer([]))
        assert "다르게 말해 볼까요?" in shop.make_chat(conn, user_id, today)["messages"][-1]["content"]

        # 검색이 실패하면 안내 문장을 남긴다
        def down(payload):
            raise urllib.error.URLError("끊김")
        assert shop.ask(conn, user_id, today, "코트", call=down) == "search"
        assert shop.make_chat(conn, user_id, today)["messages"][-1]["content"] == ai.ERRORS["search"]

        # 하루 횟수를 넘으면 OpenAI를 부르지 않는다
        monkeypatch.setattr(shop, "DAILY_LIMIT", 3)
        def boom(payload):
            raise AssertionError("부르면 안 된다")
        assert shop.ask(conn, user_id, today, "코트", call=boom) == "limit"
        assert shop.ask(conn, user_id, date(2026, 11, 1), "코트", call=lambda p: answer([coat(A)])) is None  # 다음 날은 된다
        assert shop.ask(conn, user_id, today, "   ", call=boom) == "empty"
    finally:
        queries.delete_user(conn, user_id)


def test_채팅에서_담으면_링크도_담긴다(conn):
    user_id = new_user(conn)
    try:
        queries.insert_wish_item(conn, user_id, "울 블렌드 코트", 129000, None, A)
        c = cart.make_cart(conn, user_id, date(2026, 10, 31), [])
        assert [(i["name"], i["url"]) for i in c["items"]] == [("울 블렌드 코트", A)]
    finally:
        queries.delete_user(conn, user_id)
