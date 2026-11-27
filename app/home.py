# 홈 화면에 보여줄 값을 모은다: DB에서 읽고(queries) calc로 계산한다
from datetime import date, timedelta

from app import calc, queries


# 지갑이 단계별 한마디
STAGE_LINES = {
    "빵빵": "오늘은 좀 써도 돼요",
    "든든": "이대로면 괜찮아요",
    "홀쭉": "조금씩 아껴볼까요?",
    "텅텅": "최소 생활비만 남았어요",
    "나방": "다시 짜보자…",
}


def ensure_period(conn, user_id, day):
    # day를 덮는 기간을 돌려준다. 없으면 지금 만든다 (R1-2)
    # 그 전 기록이 아예 없어서 못 만들면 None
    per = queries.get_period(conn, user_id, day)
    if per is not None:
        return per

    incomes = queries.get_incomes(conn, user_id)
    main = [i for i in incomes if i["is_main"]]
    if not main:
        return None
    new_start, new_end, _ = calc.period(day, main[0]["day_of_month"])
    # 기간 기준을 바꾼 뒤에는 앞 기간과 겹치지 않게, 앞 기간 다음 날부터 시작한다 (R15)
    last = queries.get_prev_period(conn, user_id, day + timedelta(days=1))
    if last is not None and last["end_date"] >= new_start:
        new_start = last["end_date"] + timedelta(days=1)
    before = queries.get_latest_balance_log(conn, user_id, new_start - timedelta(days=1))
    if before is None:
        return None

    routines = money_routines(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    appts = queries.get_appointments(conn, user_id)
    items = queries.get_items(conn, user_id)
    loans = queries.get_loans(conn, user_id)
    # 마지막 밤 잔액에서 시작일 전날까지 안 적은 날을 메운 값이 시작 잔액
    opening = calc.estimate_balance(
        before["balance"], before["log_date"] + timedelta(days=1),
        new_start - timedelta(days=1), routines, fixed, appts, incomes, items, loans)
    # 앞 기간에 빌린 돈은 이 기간에 갚는다 (R14)
    prev = queries.get_prev_period(conn, user_id, new_start)
    repay = 0
    if prev is not None:
        repay = calc.loans_sum(prev["start_date"], new_start - timedelta(days=1), loans)
    queries.insert_period(conn, user_id, new_start, new_end, opening, repay)
    return queries.get_period(conn, user_id, day)


def make_home(conn, user_id, today, before_night=False):
    # before_night: 오늘 밤 잔액 기록이 없는 것처럼 계산한다 (밤 잔액 저장 결과 화면에서 '저장 전' 값을 볼 때)
    user = queries.get_user(conn, user_id)
    incomes = queries.get_incomes(conn, user_id)
    main = [i for i in incomes if i["is_main"]]
    if user is None or not main:
        return {"ready": False}

    per = ensure_period(conn, user_id, today)
    if per is None:
        return {"ready": False}

    # 잔액 고르기: 오늘 밤 기록 > 기간 안의 가장 최근 기록 > 기간 시작 잔액
    # count_from: 수입·고정지출·약속·최소 생활비를 세는 첫날 (잔액 기준일 다음 날)
    logged = False
    today_log = None if before_night else queries.get_balance_log(conn, user_id, today)
    latest = queries.get_latest_balance_log(
        conn, user_id, today - timedelta(days=1) if before_night else today)
    if today_log is not None:
        balance = today_log["balance"]
        logged = True
        count_from = today + timedelta(days=1)
        missed_days = 0
    elif latest is not None and latest["log_date"] >= per["start_date"]:
        balance = latest["balance"]
        count_from = latest["log_date"] + timedelta(days=1)
        missed_days = (today - latest["log_date"]).days - 1
    else:
        balance = per["opening_balance"]
        count_from = per["start_date"]
        if latest is not None:
            # 기간 안에 기록이 없어도 그 전 기록이 있으면 그 기록일부터 센다
            missed_days = (today - latest["log_date"]).days - 1
        else:
            missed_days = (today - per["start_date"]).days

    # 남은 날은 지금처럼 오늘부터(밤 기록이 있으면 내일부터)
    # 끝나는 날은 기간 표의 값: 기간 기준을 설정에서 바꿔도 지금 기간은 그대로 (R15)
    end = per["end_date"]
    days_left = (end - calc.first_day(today, logged)).days + 1  # 마지막 날에 기록했으면 0
    first = count_from  # 안 적은 날은 최소 생활비와 약속만큼 썼다고 보고 여유 돈에서 뺀다 (R10)

    routines = money_routines(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    appts = queries.get_appointments(conn, user_id)
    items = queries.get_items(conn, user_id)
    loans = queries.get_loans(conn, user_id)

    min_living = calc.min_living(first, end, routines)
    # 비상금에서 빌린 돈은 빌린 날 수입처럼 더한다
    incomes_sum = calc.incomes_sum(first, end, incomes) + calc.loans_sum(first, end, loans)
    fixed_sum = calc.monthly_sum(first, end, fixed)
    appt_sum = calc.appointments_sum(first, end, appts)
    # 갚는 돈은 기간 첫날 통장에서 나간다: 첫날 밤 잔액을 적은 뒤에는 잔액에 이미 빠져 있다
    repay = per["repay_amount"] if first <= per["start_date"] else 0
    # 산 물건(반품 뺀 것)과 살 계획을 잡은 물건은 약속처럼 여유 돈에서 뺀다
    # 계획한 물건은 사거나 취소할 때까지 빼니까 지난 날짜도 센다 (date.min부터)
    items_out = calc.purchases_sum(first, today, items) + calc.planned_sum(date.min, end, items)
    free = calc.free_money(balance, incomes_sum, fixed_sum, appt_sum, min_living, repay, items_out)
    # 지갑이와 바꾼 계획 (R22): 이번 기간에 모아 두기로 한 돈은 여유 돈에서 뺀다 (도시락 날은 routines에 이미 들어 있다)
    changes = [c for c in queries.get_plan_changes(conn, user_id)
               if (c["kind"] == "save" and per["start_date"] <= c["day"] <= end)
               or (c["kind"] == "meal" and today <= c["day"] <= end)]
    saved = sum(c["amount"] for c in changes if c["kind"] == "save")
    free -= saved
    daily = calc.daily_margin(free, days_left)

    # 사기로 한 날이 오늘이거나 지났는데 아직 안 산 물건
    due_items = [it["name"] for it in items
                 if it["status"] == "planned" and it["planned_date"] is not None
                 and it["planned_date"] <= today]

    home = {
        "ready": True,
        "today": today,
        "end": end,
        "days_left": days_left,
        "free": free,
        # 여유 돈이 나온 과정 (네 칸)
        "available": balance + incomes_sum,
        "fixed": fixed_sum,
        "appt": appt_sum,
        "min_living": min_living,
        "repay": repay,
        "items_out": items_out,
        "saved": saved,
        "changes": changes,
        "daily": daily,
        "stage": None,
        "budget": None,
        "logged": logged,
        "missed_days": missed_days,
        "due_items": due_items,
        "today_min": None,
        "today_appt": None,
        "stage_line": None,
        # 남은 기간 막대 제목의 첫날: 오늘 밤 잔액을 적었으면 내일 (기간 마지막 날 밤은 오늘)
        "bar_from": today + timedelta(days=1) if logged and days_left > 0 else today,
        # 기간 끝 카드(18)와 가는 곳 안내(17)에 쓰는 값
        "period_start": per["start_date"],
        "no_places": not any(r["routine_id"] is not None and (r["end_date"] is None or r["end_date"] >= today)
                             for r in routines),
    }
    # 남은 기간 막대 (R7-1): 안 적은 날이 있으면 그날들을 R10대로 메운 '오늘 아침 예상 잔액'부터 센다
    # 여유 돈·하루 여유는 그대로이고, 칸을 모두 빼면 여유 돈과 같다
    if not logged and first < today:
        est = calc.estimate_balance(balance, first, today - timedelta(days=1),
                                    routines, fixed, appts, incomes, items, loans)
        home["available"] = est + calc.incomes_sum(today, end, incomes) + calc.loans_sum(today, end, loans)
        home["fixed"] = calc.monthly_sum(today, end, fixed)
        home["appt"] = calc.appointments_sum(today, end, appts)
        home["min_living"] = calc.min_living(today, end, routines)
        home["items_out"] = calc.purchases_sum(today, today, items) + calc.planned_sum(date.min, end, items)
    if daily is not None:
        home["stage"] = calc.stage(daily, user["comfort_daily"])
        # 밤 잔액을 적었으면 내일 날짜로 R7을 계산한다
        budget_day = today + timedelta(days=1) if logged else today
        home["budget"] = calc.today_budget(budget_day, routines, appts, daily)
        # 오늘 쓸 수 있는 돈 카드에 보여줄 그날 최소 생활비 (카드와 같은 날)
        home["today_min"] = calc.min_living_on(budget_day, routines)
        home["today_appt"] = calc.appointments_sum(budget_day, budget_day, appts)
        home["stage_line"] = STAGE_LINES[home["stage"]]
    return home


def money_routines(conn, user_id):
    # 돈 계산용 가는 곳: 지갑이와 바꾼 도시락 날(R22)은 그날만 점심값 하나가 빠지는 줄로 더한다
    routines = queries.get_routines(conn, user_id)
    for c in queries.get_plan_changes(conn, user_id):
        if c["kind"] == "meal":
            routines.append({"routine_id": None, "weekdays": [c["day"].weekday()],
                             "start_date": c["day"], "end_date": c["day"],
                             "meals_out": -1, "meal_price": c["amount"], "round_trip_fare": 0})
    return routines
