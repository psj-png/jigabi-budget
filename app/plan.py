# 지갑이 계획 도우미 (R22): 다음 돈 들어오는 날까지 어떻게 쓸지 같이 짜고, 고른 것만 계획에 넣는다
# 바꿀 수 있는 건 두 가지: 도시락 날(그날 점심값 하나가 최소 생활비에서 빠짐), 모아 두기(이번 기간 여유 돈에서 뺌)
import json
from datetime import date, timedelta

from app import ai, calc, queries, shop
from app.home import make_home

DAYS = "월화수목금토일"
MAX_MEAL_DAYS = 14
STARTERS = ["알바비 날까지 어떻게 쓸까?", "이번 주 아껴 쓰는 법 알려 줘", "3만 원은 모아 두고 싶어"]


def options(conn, user_id, today):
    # AI에게 보낼 지갑 상태와 고를 수 있는 선택지 (숫자는 모두 앱이 계산). 기간이 끝났으면 None
    h = make_home(conn, user_id, today)
    if not h["ready"] or h["daily"] is None:
        return None, h
    comfort = queries.get_user(conn, user_id)["comfort_daily"]
    first = calc.first_day(today, h["logged"])
    routines = queries.get_routines(conn, user_id)
    swapped = {c["day"] for c in queries.get_plan_changes(conn, user_id) if c["kind"] == "meal"}
    meals = []
    day = first
    while day <= h["end"] and len(meals) < MAX_MEAL_DAYS:
        prices = [r["meal_price"] for r in routines if r["meals_out"] > 0 and calc.goes_on(day, r)]
        if prices and max(prices) > 0 and day not in swapped:
            meals.append({"day": day.isoformat(), "label": f"{day.month}/{day.day}({DAYS[day.weekday()]})",
                          "amount": max(prices)})
        day += timedelta(days=1)
    # 모아 둘 수 있는 최대: 모아 둬도 든든(넉넉 기준의 절반)이 남는 만큼
    max_save = max((h["free"] - (comfort // 2) * h["days_left"]) // 1000 * 1000, 0)
    next_day = h["end"] + timedelta(days=1)
    appts = [a for a in queries.get_appointments(conn, user_id) if first <= a["appt_date"] <= h["end"]]
    context = {
        "오늘": today.isoformat(), "기간 끝": h["end"].isoformat(), "남은 날": h["days_left"],
        "여유 돈": h["free"], "하루 여유": h["daily"], "지갑이 단계": h["stage"], "넉넉 기준": comfort,
        "오늘 쓸 수 있는 돈": h["budget"], "다음 돈 들어오는 날": next_day.isoformat(),
        "그날 들어올 돈": calc.incomes_sum(next_day, next_day, queries.get_incomes(conn, user_id)),
        "다가오는 약속": [{"날": a["appt_date"].isoformat(), "이름": a["title"],
                         "금액": a["amount"] + a["transport_fare"]} for a in appts],
        "도시락으로 바꿀 수 있는 날": [{"날": m["day"], "아끼는 돈": m["amount"]} for m in meals],
        "모아 둘 수 있는 최대": max_save,
    }
    return {"context": context, "meals": meals, "max_save": max_save, "comfort": comfort}, h


def choose(opts, picked):
    # AI가 고른 것 중 선택지에 있는 것만 남긴다. 바꿀 게 없으면 None
    allowed = {m["day"]: m for m in opts["meals"]}
    meals = [allowed[d] for d in dict.fromkeys(picked.get("meal_days") or []) if d in allowed]
    save = min(max(picked.get("save") or 0, 0), opts["max_save"]) // 1000 * 1000
    if not meals and not save:
        return None
    return {"meals": meals, "save": save}


def preview(h, proposal, comfort):
    # 제안대로 하면 하루 여유가 어떻게 되나 (도시락 날은 아직 안 지난 날만 센다)
    first = calc.first_day(h["today"], h["logged"])
    gain = sum(m["amount"] for m in proposal["meals"] if date.fromisoformat(m["day"]) >= first)
    daily = calc.daily_margin(h["free"] + gain - proposal["save"], h["days_left"])
    return {"before": h["daily"], "before_stage": h["stage"], "after": daily, "after_stage": calc.stage(daily, comfort)}


def ask(conn, user_id, today, text, call=None):
    # 사용자 말을 저장하고, 지갑 상태로 계획을 물어 제안을 저장한다. 오류 키 또는 None
    text = " ".join((text or "").split())[:300]
    if not text:
        return "empty"
    if queries.count_chat_today(conn, user_id, today) >= shop.DAILY_LIMIT:
        return "limit"
    opts, h = options(conn, user_id, today)
    queries.insert_chat(conn, user_id, today, "user", text, mode="plan")
    if opts is None:
        queries.insert_chat(conn, user_id, today, "assistant", "이번 기간이 끝났어요. 새 기간에 같이 짜 봐요.", mode="plan")
        return None
    reply, picked, error = ai.plan_reply(opts["context"], text, call)
    if error:
        queries.insert_chat(conn, user_id, today, "assistant", ai.ERRORS[error], mode="plan")
        return error
    proposal = choose(opts, picked)
    queries.insert_chat(conn, user_id, today, "assistant", reply or "이렇게 바꿔 볼까요?", mode="plan",
                        plan_json=json.dumps(proposal, ensure_ascii=False) if proposal else None)
    return None


def apply(conn, user_id, today, message_id):
    # [이대로 적용]: 제안을 계획에 넣는다. 그새 지난 날·이미 바꾼 날은 빼고, 모아 두기는 지금 최대 안에서
    msg = queries.get_chat_message(conn, user_id, message_id)
    if msg is None or not msg["plan_json"] or msg["applied"]:
        return False
    proposal = json.loads(msg["plan_json"])
    opts, h = options(conn, user_id, today)
    if opts is None:
        return False
    allowed = {m["day"] for m in opts["meals"]}
    try:
        for m in proposal["meals"]:
            if m["day"] in allowed:
                queries.add_plan_change(conn, user_id, date.fromisoformat(m["day"]), "meal", m["amount"],
                                        f"{m['label']} 점심 도시락")
        save = min(proposal["save"], opts["max_save"])
        if save > 0:
            queries.add_plan_change(conn, user_id, h["end"], "save", save, "다음 돈 들어오는 날까지 모아 두기")
        queries.mark_applied(conn, user_id, message_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True
