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
    logged = False
    missed_days = 0
    today_log = queries.get_balance_log(conn, user_id, today)
    latest = queries.get_latest_balance_log(conn, user_id, today)
    if today_log is not None:
        balance = today_log["balance"]
        logged = True
    elif latest is not None and latest["log_date"] >= per["start_date"]:
        balance = latest["balance"]
        # 어제 밤 기록이 아니면 사이가 빈 날을 센다 (계산으로 메우지는 않음)
        missed_days = (today - latest["log_date"]).days - 1
    else:
        balance = per["opening_balance"]

    start, end, days_left = calc.period(today, income_day, app_start=per["start_date"],
                                        logged_tonight=logged)
    first = calc.first_day(today, logged)

    routines = queries.get_routines(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    appts = queries.get_appointments(conn, user_id)

    min_living = calc.min_living(first, end, routines)
    free = calc.free_money(
        balance,
        calc.other_incomes_sum(first, end, incomes),
        calc.monthly_sum(first, end, fixed),
        calc.appointments_sum(first, end, appts),
        min_living,
        per["repay_amount"],
    )
    daily = calc.daily_margin(free, days_left)

    home = {
        "ready": True,
        "today": today,
        "end": end,
        "days_left": days_left,
        "free": free,
        "daily": daily,
        "stage": None,
        "budget": None,
        "logged": logged,
        "missed_days": missed_days,
    }
    if daily is not None:
        home["stage"] = calc.stage(daily, user["comfort_daily"])
        # 오늘 밤 잔액을 적은 뒤의 R7은 아직 정하지 않아서 보여주지 않는다
        if not logged:
            home["budget"] = calc.today_budget(today, routines, appts, daily)
    return home
