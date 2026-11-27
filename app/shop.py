# 지갑이 채팅 (R21): 무신사에서 내 지갑에 맞는 상품을 찾아 준다
import json
from datetime import timedelta

from app import ai, calc, queries
from app.home import make_home

DAILY_LIMIT = 20  # 하루에 물어볼 수 있는 횟수 (웹 검색 비용 때문에)
STARTERS = ["겨울 코트 추천해 줘", "롱패딩이랑 비슷한데 더 싼 거", "5만 원 아래 니트 찾아 줘"]


def budget(h, comfort):
    # 사도 되는 가격 상한: 든든을 지키려면 (넉넉 기준의 절반 × 남은 날)을 남긴다, 여유 돈을 넘으면 최소 생활비를 건드린다
    if not h["ready"] or not h["days_left"]:
        return None
    return {"keep_solid": max(h["free"] - (comfort // 2) * h["days_left"], 0),
            "no_touch": max(h["free"], 0)}


def budget_line(b):
    if b is None:
        return "이번 기간이 끝나서 예산은 따지지 않아도 돼요."
    return (f"이번 기간에 지갑이 든든을 지키려면 {b['keep_solid']:,}원까지, "
            f"{b['no_touch']:,}원을 넘으면 최소 생활비를 건드려요.")


def make_chat(conn, user_id, today, mode=None):
    # 채팅 화면: 그 모드의 최근 대화 30개, 상품마다 '사면 단계' 칩은 지금 지갑으로 다시 계산한다 (장바구니 칩과 같은 R11)
    h = make_home(conn, user_id, today)
    comfort = queries.get_user(conn, user_id)["comfort_daily"]
    messages = []
    for m in queries.get_chat(conn, user_id, 30, mode):
        items = json.loads(m["items_json"]) if m["items_json"] else []
        for it in items:
            it["chip"] = None
            if it.get("price") and h["ready"] and h["daily"] is not None:
                it["chip"] = calc.preview(h["free"], h["days_left"], it["price"], comfort)[1]
        proposal = json.loads(m["plan_json"]) if m.get("plan_json") else None
        look = None
        if proposal and h["ready"] and h["daily"] is not None and not m.get("applied"):
            from app import plan  # plan이 shop을 불러서 여기서만 부른다
            look = plan.preview(h, proposal, comfort)
        messages.append({"id": m["message_id"], "role": m["role"], "mode": m.get("mode", "shop"),
                         "content": m["content"], "items": items, "plan": proposal, "look": look,
                         "applied": bool(m.get("applied"))})
    return {"messages": messages, "budget": budget(h, comfort) if h["ready"] else None,
            "used": queries.count_chat_today(conn, user_id, today), "limit": DAILY_LIMIT,
            "starters": STARTERS, "stage": h.get("stage"),
            "next_day": h["end"] + timedelta(days=1) if h["ready"] else None,
            "short": max(-h["free"], 0) if h["ready"] else 0,
            "days_left": h.get("days_left"), "daily": h.get("daily")}


def ask(conn, user_id, today, text, image=None, call=None):
    # 사용자 말을 저장하고 무신사를 찾아 답을 저장한다. 오류 키 또는 None (하루 횟수를 넘으면 묻지 않는다)
    text = " ".join((text or "").split())[:300]
    if not text and image is None:
        return "empty"
    if queries.count_chat_today(conn, user_id, today) >= DAILY_LIMIT:
        return "limit"
    h = make_home(conn, user_id, today)
    b = budget(h, queries.get_user(conn, user_id)["comfort_daily"]) if h["ready"] else None
    queries.insert_chat(conn, user_id, today, "user", text or "(캡처로 비슷한 거 찾기)")
    reply, picks, error = ai.recommend(text or "이 캡처 속 상품과 비슷한 걸 찾아 줘", budget_line(b), image, call)
    if error:
        queries.insert_chat(conn, user_id, today, "assistant", ai.ERRORS[error])
        return error
    if not picks:
        reply = (reply + " " if reply else "") + "무신사에서 딱 맞는 상품을 찾지 못했어요. 다르게 말해 볼까요?"
    queries.insert_chat(conn, user_id, today, "assistant", reply,
                        json.dumps(picks, ensure_ascii=False) if picks else None)
    return None
