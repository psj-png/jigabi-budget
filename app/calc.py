# 계산 함수 모음. DB 없이 값만 받아서 계산한다 (규칙은 docs/rules.md)
import calendar
from datetime import date, timedelta


def income_date(year, month, income_day):
    # 그 달에 수입일이 없으면(예: 31일) 그 달 마지막 날로 본다
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(income_day, last))


def first_day(today, logged_tonight=False):
    # 남은 날의 첫날: 오늘 밤 잔액을 기록했으면 내일부터
    if logged_tonight:
        return today + timedelta(days=1)
    return today


def period(today, income_day, app_start=None, logged_tonight=False):
    # R1 기간: 수입일부터 다음 수입일 전날까지. (시작일, 끝나는 날, 남은 날)을 돌려줌
    this_month = income_date(today.year, today.month, income_day)
    if this_month <= today:
        start = this_month
        year, month = today.year, today.month + 1
    else:
        year, month = today.year, today.month - 1
        if month == 0:
            year, month = year - 1, 12
        start = income_date(year, month, income_day)
        year, month = today.year, today.month
    if month == 13:
        year, month = year + 1, 1
    end = income_date(year, month, income_day) - timedelta(days=1)

    # 첫 기간은 앱을 시작한 날부터
    if app_start is not None and app_start > start:
        start = app_start

    days_left = (end - first_day(today, logged_tonight)).days + 1  # 마지막 날에 기록했으면 0
    return start, end, days_left


def min_living_on(day, routines):
    # R3 그날 최소 생활비: 그날 가는 곳마다 끼니값 + 왕복 교통비
    total = 0
    for r in routines:
        if day.weekday() not in r["weekdays"]:
            continue
        if r["start_date"] is not None and day < r["start_date"]:
            continue
        if r["end_date"] is not None and day > r["end_date"]:
            continue
        total += r["meals_out"] * r["meal_price"] + r["round_trip_fare"]
    return total


def min_living(start, end, routines):
    # R4 최소 생활비: 남은 날(start~end)의 R3 합
    total = 0
    day = start
    while day <= end:
        total += min_living_on(day, routines)
        day += timedelta(days=1)
    return total


def monthly_sum(start, end, items):
    # 매달 day_of_month에 들어오거나 나가는 돈 중 start~end 안에 있는 것의 합
    total = 0
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        for item in items:
            d = income_date(year, month, item["day_of_month"])
            if start <= d <= end:
                total += item["amount"]
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return total


def other_incomes_sum(start, end, incomes):
    # R2 기간 안에 들어올 다른 수입. 기간을 만든 주 수입(is_main)은 시작 잔액에 이미 있어서 뺀다
    return monthly_sum(start, end, [i for i in incomes if not i["is_main"]])


def appointments_sum(start, end, appointments):
    # 남은 약속 합 (교통비 포함)
    return sum(a["amount"] + a["transport_fare"]
               for a in appointments if start <= a["appt_date"] <= end)


def free_money(balance, incomes_sum, fixed_sum, appt_sum, min_living_sum, repay=0):
    # R2 쓸 수 있는 돈 = 잔액 + 남은 날 안에 들어올 수입, R5 여유 돈
    available = balance + incomes_sum
    return available - fixed_sum - appt_sum - min_living_sum - repay


def daily_margin(free, days_left):
    # R6 하루 여유: 100원 아래 버림 (음수는 내림이라 -50은 -100)
    # 남은 날이 0이면 None: 기간 끝이라 호출하는 쪽에서 따로 다룬다
    if days_left <= 0:
        return None
    return free // days_left // 100 * 100


def stage(daily, comfort=10000):
    # R8 지갑이 단계
    if daily >= comfort:
        return "빵빵"
    if daily >= comfort // 2:
        return "든든"
    if daily >= comfort // 10:
        return "홀쭉"
    if daily >= 0:
        return "텅텅"
    return "나방"


def today_budget(day, routines, appointments, daily):
    # R7 오늘 쓸 수 있는 돈 = 오늘의 R3 + 하루 여유 + 오늘 약속 금액(교통비 포함)
    # 하루 여유가 없으면(기간 끝) None
    if daily is None:
        return None
    return min_living_on(day, routines) + daily + appointments_sum(day, day, appointments)
