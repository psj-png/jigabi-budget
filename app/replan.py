# 다시 짜기(R14): 산 뒤 여유 돈이 모자라면 반품 -> 약속 줄이기 -> 비상금 순으로 메운다
from datetime import timedelta

from app import calc, queries
from app.home import make_home


def _appts_to_cut(conn, user_id, today, h):
    # 줄일 수 있는 약속: 이번 기간의 오늘 이후 (밤 잔액을 적었으면 내일부터), 날짜순
    first = today + timedelta(days=1) if h["logged"] else today
    return [a for a in queries.get_appointments(conn, user_id)
            if first <= a["appt_date"] <= h["end"]]


def make_replan(conn, user_id, today):
    h = make_home(conn, user_id, today)
    if not h["ready"]:
        return {"ready": False}

    user = queries.get_user(conn, user_id)
    short = -h["free"] if h["free"] < 0 else 0
    appts = _appts_to_cut(conn, user_id, today, h)
    cuts, borrow, left = calc.replan_proposal(short, appts, user["emergency_fund"])

    items = queries.get_items(conn, user_id)
    returnable = [i for i in items if i["status"] == "bought" and calc.can_return(i["bought_date"], today)]
    rows = [{"appt": a, "cut": c} for a, c in zip(appts, cuts)]
    hours = calc.work_hours(left, user["hourly_wage"]) if left > 0 else None
    return {"ready": True, "short": short, "returnable": returnable, "rows": rows,
            "fund": user["emergency_fund"], "borrow": borrow, "left": left, "hours": hours}


def save_replan(conn, user_id, today, cuts):
    # cuts: {appt_id: 줄일 금액} (적용 체크한 것만). 저장하면 None, 못 하면 이유(문장)
    # 비상금에서 빌릴 돈은 여기서 다시 계산한다 (사용자가 칸을 고쳤을 수 있다)
    h = make_home(conn, user_id, today)
    if not h["ready"] or h["free"] >= 0:
        return "모자라지 않아요"

    mine = {a["appt_id"]: a for a in _appts_to_cut(conn, user_id, today, h)}
    for appt_id, cut in cuts.items():
        if appt_id not in mine:
            return "줄일 수 없는 약속이에요"
        if cut < 0 or cut > mine[appt_id]["amount"]:
            return "줄일 금액은 0원 이상, 약속 금액 이하여야 해요"

    user = queries.get_user(conn, user_id)
    left = max(-h["free"] - sum(cuts.values()), 0)
    borrow = min(left, user["emergency_fund"])
    try:
        for appt_id, cut in cuts.items():
            if cut > 0:
                queries.update_appointment_amount(conn, user_id, appt_id, mine[appt_id]["amount"] - cut)
        if borrow > 0:
            queries.insert_loan(conn, user_id, today, borrow)
            queries.add_emergency_fund(conn, user_id, -borrow)
            # 오늘 밤 잔액을 이미 적었으면 옮겨 온 돈만큼 더한다 (산 것을 뺀 것과 같은 방식)
            if queries.get_balance_log(conn, user_id, today) is not None:
                queries.adjust_balance_log(conn, user_id, today, borrow)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return None
