# 설정 (흐름 6): 돈 들어오는 날·고정비·가는 곳·숫자 고치기, 지난 기간 돌아보기, 지우기
from datetime import timedelta

from app import calc, queries, setup
from app.home import ensure_period, make_home, money_routines


def make_settings(conn, user_id, today):
    # 설정 첫 화면 (24): 맨 위 이번 기간 최소 생활비와 항목별 한 줄 요약
    per = ensure_period(conn, user_id, today)
    routines = money_routines(conn, user_id)
    places = [r for r in queries.list_routines(conn, user_id)
              if r["end_date"] is None or r["end_date"] >= today]
    return {"per": per, "user": queries.get_user(conn, user_id),
            "min_living": calc.min_living(per["start_date"], per["end_date"], routines) if per else 0,
            "incomes": queries.list_incomes(conn, user_id), "fixed": queries.list_fixed(conn, user_id),
            "places": places,
            # 맨 위 숫자 칸: 이번 기간 남은 날 (오늘 포함)
            "days_left": (per["end_date"] - today).days + 1 if per else 0}


def money_row(form, label):
    # 돈 들어오는 날·고정비 한 줄: 첫 설정과 같은 검사
    return (setup.clean_name(form.get("name"), label), setup.parse_day(form.get("day")),
            setup.to_int(form.get("amount"), "금액", low=1))


def parse_place(form):
    # 가는 곳 한 곳 (첫 설정과 같은 검사). 요일 칸 이름은 wd
    pairs = [("r_name", form.get("name") or ""), ("r_meals", form.get("meals") or ""),
             ("r_price", form.get("price") or ""), ("r_fare", form.get("fare") or ""),
             ("r_start", form.get("start") or ""), ("r_end", form.get("end") or "")]
    pairs += [("r_wd_0", w) for w in form.getlist("wd")]
    places = setup.parse_step2(setup.DraftForm(pairs))
    if not places:
        raise setup.FormError("이름을 적고 요일을 하나 이상 골라 주세요")
    return places[0]


def place_parts(routines, start, end):
    # 이번 기간 최소 생활비 = 곳마다 (가는 날 수 × 하루 비용). 합은 calc.min_living과 같다
    parts = []
    for r in routines:
        days = 0
        day = start
        while day <= end:
            if calc.goes_on(day, r):
                days += 1
            day += timedelta(days=1)
        if days:
            per_day = r["meals_out"] * r["meal_price"] + r["round_trip_fare"]
            parts.append({"name": r["name"], "days": days, "per_day": per_day, "total": days * per_day})
    return parts


def make_places(conn, user_id, today):
    # 가는 곳 관리 (27): 왜 그 숫자인지 식으로 보여준다
    per = ensure_period(conn, user_id, today)
    every = queries.list_routines(conn, user_id)
    total, parts = 0, []
    if per is not None:
        total = calc.min_living(per["start_date"], per["end_date"], every)
        parts = place_parts(every, per["start_date"], per["end_date"])
    places = [r for r in every if r["end_date"] is None or r["end_date"] >= today]
    return {"per": per, "total": total, "parts": parts, "places": places}


def _mine(conn, user_id, routine_id):
    found = [r for r in queries.list_routines(conn, user_id) if r["routine_id"] == routine_id]
    return found[0] if found else None


def add_place(conn, user_id, r, today):
    # 새로 넣은 곳은 오늘부터 (R15)
    try:
        queries.insert_routine(conn, user_id, dict(r, start_date=max(today, r["start_date"] or today)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def edit_place(conn, user_id, routine_id, r, today):
    # R15 고치면 오늘부터 새 줄: 예전 줄은 그 전날로 끝내서 지난 날 계산은 그대로 둔다
    old = _mine(conn, user_id, routine_id)
    if old is None:
        return False
    start = max(today, r["start_date"] or today)
    try:
        if old["start_date"] is not None and old["start_date"] >= start:
            queries.delete_routine(conn, user_id, routine_id)  # 아직 시작 전인 줄은 통째로 바꾼다
        else:
            queries.end_routine(conn, user_id, routine_id, start - timedelta(days=1))
        queries.insert_routine(conn, user_id, dict(r, start_date=start))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def end_place(conn, user_id, routine_id, today):
    # 이제 안 가는 곳: 어제로 끝낸다. 오늘부터 시작한 줄이면 지운다
    old = _mine(conn, user_id, routine_id)
    if old is None:
        return False
    try:
        if old["start_date"] is not None and old["start_date"] >= today:
            queries.delete_routine(conn, user_id, routine_id)
        else:
            queries.end_routine(conn, user_id, routine_id, today - timedelta(days=1))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def parse_numbers(form):
    # 시급·비상금·넉넉 기준 (28)
    return (setup.to_int(form.get("comfort_daily"), "넉넉 기준", low=1000),
            setup.to_int(form.get("hourly_wage"), "시급", low=1),
            setup.to_int(form.get("emergency_fund"), "비상금"))


def delete_account(conn, user_id):
    queries.delete_user(conn, user_id)


def make_history(conn, user_id, today, pick=None):
    # 지난 기간 돌아보기 (29): 기간마다 적은 밤 수와 쓴 돈, 고른 기간의 날짜별 막대
    items = queries.get_items(conn, user_id)
    loans = queries.get_loans(conn, user_id)
    rows = []
    for p in queries.get_periods(conn, user_id, today):
        last = min(p["end_date"], today)
        logs = queries.get_balance_logs(conn, user_id, p["start_date"], last)
        row = {"start": p["start_date"], "end": p["end_date"], "last": last,
               "current": p["end_date"] >= today, "days": (last - p["start_date"]).days + 1,
               "nights": len(logs), "spent": sum(log["spent"] for log in logs), "logs": logs,
               "bought": [it for it in items if it["bought_date"] is not None
                          and it["status"] in ("bought", "returned")
                          and p["start_date"] <= it["bought_date"] <= last],
               "loans": [x for x in loans if p["start_date"] <= x["borrowed_on"] <= last],
               "end_stage": None}
        if not row["current"]:
            # 끝난 기간은 마지막 날 아침 기준 지갑이 단계
            row["end_stage"] = make_home(conn, user_id, p["end_date"], before_night=True).get("stage")
        rows.append(row)
    if not rows:
        return {"rows": [], "sel": None, "prev": None, "newer": None, "diff": None, "bars": [], "top": None}
    sel = next((r for r in rows if r["start"] == pick), rows[0])
    i = rows.index(sel)
    prev = rows[i + 1] if i + 1 < len(rows) else None
    newer = rows[i - 1] if i > 0 else None
    diff = sel["spent"] - prev["spent"] if prev is not None and prev["nights"] and sel["nights"] else None
    # 날짜별 막대: 기간 끝날까지 칸을 잡고, 적은 날은 쓴 돈, 안 적은 날은 낮은 회색, 아직 안 온 날은 빈칸
    spent_by_day = {log["log_date"]: log["spent"] for log in sel["logs"]}
    top = max([v for v in spent_by_day.values() if v > 0], default=0)
    bars = []
    day = sel["start"]
    while day <= sel["end"]:
        v = spent_by_day.get(day)
        bars.append({"day": day, "spent": v, "future": day > sel["last"],
                     "pct": max(v, 0) * 100 // top if v is not None and top else 0})
        day += timedelta(days=1)
    # 가장 많이 쓴 날 (막대 위 한 줄)
    top_log = max(sel["logs"], key=lambda log: log["spent"], default=None)
    top = top_log if top_log is not None and top_log["spent"] > 0 else None
    return {"rows": rows, "sel": sel, "prev": prev, "newer": newer, "diff": diff, "bars": bars, "top": top}
