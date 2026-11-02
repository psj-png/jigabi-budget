# 홈 화면에 보여줄 값을 모은다: DB에서 읽고(queries) calc로 계산한다
from datetime import timedelta

from app import calc, queries


def make_home(conn, user_id, today):
    user = queries.get_user(conn, user_id)
    per = queries.get_period(conn, user_id, today)
    incomes = queries.get_incomes(conn, user_id)
    main = [i for i in incomes if i["is_main"]]
    if user is None or per is None or not main:
        return {"ready": False}

    # 기간 기준 수입일은 주 수입의 날짜
    income_day = main[0]["day_of_month"]

    # 잔액 고르기: 오늘 밤 기록 > 기간 안의 가장 최근 기록 > 기간 시작 잔액
    # count_from: 수입·고정지출·약속·최소 생활비를 세는 첫날 (잔액 기준일 다음 날)
    logged = False
    today_log = queries.get_balance_log(conn, user_id, today)
    latest = queries.get_latest_balance_log(conn, user_id, today)
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
        missed_days = (today - per["start_date"]).days

    # 남은 날은 지금처럼 오늘부터(밤 기록이 있으면 내일부터)
    start, end, days_left = calc.period(today, income_day, app_start=per["start_date"],
                                        logged_tonight=logged)
    first = count_from  # 안 적은 날은 최소 생활비와 약속만큼 썼다고 보고 여유 돈에서 뺀다 (R10)

    routines = queries.get_routines(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    appts = queries.get_appointments(conn, user_id)

    min_living = calc.min_living(first, end, routines)
    incomes_sum = calc.other_incomes_sum(first, end, incomes)
    fixed_sum = calc.monthly_sum(first, end, fixed)
    appt_sum = calc.appointments_sum(first, end, appts)
    repay = per["repay_amount"]
    free = calc.free_money(balance, incomes_sum, fixed_sum, appt_sum, min_living, repay)
    daily = calc.daily_margin(free, days_left)

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
        "daily": daily,
        "stage": None,
        "budget": None,
        "logged": logged,
        "missed_days": missed_days,
    }
    if daily is not None:
        home["stage"] = calc.stage(daily, user["comfort_daily"])
        # 밤 잔액을 적었으면 내일 날짜로 R7을 계산한다
        budget_day = today + timedelta(days=1) if logged else today
        home["budget"] = calc.today_budget(budget_day, routines, appts, daily)
    return home
