# 계산 함수 모음. DB 없이 값만 받아서 계산한다 (규칙은 docs/rules.md)
import calendar
import itertools
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


def goes_on(day, r):
    # R3-2 그날 가는 곳인지: 요일이 맞고 시작일~끝나는 날 안
    if day.weekday() not in r["weekdays"]:
        return False
    if r["start_date"] is not None and day < r["start_date"]:
        return False
    if r["end_date"] is not None and day > r["end_date"]:
        return False
    return True


def min_living_on(day, routines):
    # R3 그날 최소 생활비: 그날 가는 곳마다 끼니값 + 왕복 교통비
    total = 0
    for r in routines:
        if goes_on(day, r):
            total += r["meals_out"] * r["meal_price"] + r["round_trip_fare"]
    return total


def max_fare(routines):
    # 루틴 왕복 교통비 중 가장 큰 값. 루틴이 없으면 0
    return max((r["round_trip_fare"] for r in routines), default=0)


def transport_default(day, routines):
    # R9 약속 교통비 기본값: 그날 가는 곳이 있으면 0(끔), 없으면 max_fare
    if any(goes_on(day, r) for r in routines):
        return 0
    return max_fare(routines)


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


def incomes_sum(start, end, incomes):
    # R2 기간 안에 들어올 수입. 주 수입도 기간 첫날에 들어오므로 포함한다
    return monthly_sum(start, end, incomes)


def appointments_sum(start, end, appointments):
    # 남은 약속 합 (교통비 포함)
    return sum(a["amount"] + a["transport_fare"]
               for a in appointments if start <= a["appt_date"] <= end)


def free_money(balance, incomes_sum, fixed_sum, appt_sum, min_living_sum, repay=0, items_out=0):
    # R2 쓸 수 있는 돈 = 잔액 + 남은 날 안에 들어올 수입, R5 여유 돈
    # items_out: 산 물건 값(반품 뺀 것)과 살 계획을 잡은 물건 값
    available = balance + incomes_sum
    return available - fixed_sum - appt_sum - min_living_sum - repay - items_out


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


def estimate_balance(balance, start, end, routines, fixed, appts, incomes, items=(), loans=()):
    # start~end 동안 수입·빌린 돈은 더하고 고정지출·약속·최소 생활비·산 물건 값은 뺀 잔액
    # (안 적은 날은 최소 생활비와 약속만큼 썼다고 본다, R10). start > end면 그대로
    if start > end:
        return balance
    return (balance
            + incomes_sum(start, end, incomes)
            + loans_sum(start, end, loans)
            - monthly_sum(start, end, fixed)
            - appointments_sum(start, end, appts)
            - min_living(start, end, routines)
            - purchases_sum(start, end, items))


def spent_money(prev_balance, income_in, fixed_out, bought, balance):
    # R10 쓴 돈 = 지난 잔액 + 들어온 돈 - 빠져나간 고정지출 - 기록한 구매 - 지금 잔액
    return prev_balance + income_in - fixed_out - bought - balance


def preview(free, days_left, price_sum, comfort):
    # R11 미리보기: 여유 돈에서 물건 값 합을 빼고 R6, R8을 다시 계산한다
    # (하루 여유, 단계, 모자라는 돈)을 돌려준다. 남은 날이 0이면 None
    if days_left <= 0:
        return None
    after = free - price_sum
    daily = daily_margin(after, days_left)
    short = -after if after < 0 else 0
    return daily, stage(daily, comfort), short


def work_hours(price_sum, wage):
    # 알바 시간 = 물건 값 ÷ 시급, 0.5 올림 (파이썬 round()는 2.5를 2로 만들어서 정수로 계산)
    if wage <= 0:
        return None
    return (price_sum * 2 + wage) // (2 * wage)


def split_plan(items, periods, comfort):
    # R13 나눠 사기: items는 (이름, 가격, 필요한 날 또는 None), periods는 이번·다음·그다음 기간의
    # (시작일, 여유 돈, 남은 날). 물건마다 세 기간 중 하나에 넣는 경우를 모두 본다.
    # ① 하루 여유가 0 미만인 기간이 없고, 필요한 날 전(같은 날 포함)에 사는 것만 남긴다
    # ②~④ 정렬: ② 모든 기간이 홀쭉 이상인 쪽 -> ③ 기다리는 기간 수의 합이 작은 쪽
    #       -> ④ 세 기간 하루 여유 중 가장 작은 값이 큰 쪽 (같으면 먼저 나온 것)
    # 돌려주는 값: 기간 세 개의 {"items": [...], "daily": 하루 여유, "stage": 단계}. 해답이 없으면 None
    best = None
    best_key = None
    for combo in itertools.product(range(3), repeat=len(items)):
        sums = [0, 0, 0]
        ok = True
        for item, p in zip(items, combo):
            sums[p] += item[1]
            if item[2] is not None and periods[p][0] > item[2]:
                ok = False  # 필요한 날보다 늦게 사게 됨
                break
        if not ok:
            continue

        dailies = [daily_margin(periods[p][1] - sums[p], periods[p][2]) for p in range(3)]
        if any(d is None or d < 0 for d in dailies):
            continue

        stages = [stage(d, comfort) for d in dailies]
        key = (
            0 if all(s in ("빵빵", "든든", "홀쭉") for s in stages) else 1,
            sum(combo),
            -min(dailies),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = [{"items": [it for it, p in zip(items, combo) if p == k],
                     "daily": dailies[k], "stage": stages[k]} for k in range(3)]
    return best


def purchases_sum(start, end, items):
    # start~end에 산 물건 값 합 - start~end에 반품한 물건 값 합 (status와 상관없이 날짜로)
    total = 0
    for it in items:
        if it["bought_date"] is not None and start <= it["bought_date"] <= end:
            total += it["price"]
        if it["returned_date"] is not None and start <= it["returned_date"] <= end:
            total -= it["price"]
    return total


def planned_sum(start, end, items):
    # 살 계획(planned)을 잡은 날이 start~end인 물건 값 합. 약속처럼 여유 돈에서 뺀다
    return sum(it["price"] for it in items
               if it["status"] == "planned" and it["planned_date"] is not None
               and start <= it["planned_date"] <= end)


def loans_sum(start, end, loans):
    # start~end에 비상금에서 빌린 돈 합. 빌린 날 수입처럼 들어온다
    return sum(l["amount"] for l in loans if start <= l["borrowed_on"] <= end)


def replan_proposal(short, appts, fund):
    # R14 다시 짜기: 모자란 돈 short를 약속 줄이기 -> 비상금 순으로 메운다
    # appts는 날짜순 약속 목록. 약속마다 금액의 1/3(천 원 아래 버림)을 제안하되 모자란 돈을 넘지 않게
    # (약속별 줄일 금액 목록, 비상금에서 빌릴 돈, 그래도 남는 돈)을 돌려준다
    left = max(short, 0)
    cuts = []
    for a in appts:
        cut = min(a["amount"] // 3 // 1000 * 1000, left)
        cuts.append(cut)
        left -= cut
    borrow = min(left, fund)
    return cuts, borrow, left - borrow


def can_return(bought_date, day):
    # R14-0 반품은 산 날 빼고 7일 안
    return 0 <= (day - bought_date).days <= 7
