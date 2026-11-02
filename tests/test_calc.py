from datetime import date

from app.calc import period


def test_R1_예시_10월30일():
    # docs/rules.md 확인용 예시: 오늘 10/30, 알바비 25일 -> 10/30~11/24, 26일
    start, end, days_left = period(date(2026, 10, 30), 25, app_start=date(2026, 10, 30))
    assert start == date(2026, 10, 30)
    assert end == date(2026, 11, 24)
    assert days_left == 26


def test_R1_앱_시작일이_없으면_수입일부터():
    start, end, days_left = period(date(2026, 10, 30), 25)
    assert start == date(2026, 10, 25)
    assert end == date(2026, 11, 24)
    assert days_left == 26


def test_R1_수입일에_새_기간_시작():
    start, end, days_left = period(date(2026, 11, 25), 25)
    assert start == date(2026, 11, 25)
    assert end == date(2026, 12, 24)
    assert days_left == 30


def test_R1_수입일_전날은_남은_날_1():
    start, end, days_left = period(date(2026, 11, 24), 25)
    assert start == date(2026, 10, 25)
    assert end == date(2026, 11, 24)
    assert days_left == 1


def test_R1_수입일_전에_오늘이_있으면_지난달_수입일부터():
    start, end, days_left = period(date(2026, 11, 3), 25)
    assert start == date(2026, 10, 25)
    assert end == date(2026, 11, 24)
    assert days_left == 22


def test_R1_해가_넘어가는_기간():
    start, end, days_left = period(date(2026, 12, 30), 25)
    assert start == date(2026, 12, 25)
    assert end == date(2027, 1, 24)
    assert days_left == 26

    start, end, days_left = period(date(2027, 1, 3), 25)
    assert start == date(2026, 12, 25)
    assert end == date(2027, 1, 24)


def test_R1_수입일이_없는_달은_마지막_날():
    # 수입일 31일: 2월엔 28일
    start, end, days_left = period(date(2026, 2, 10), 31)
    assert start == date(2026, 1, 31)
    assert end == date(2026, 2, 27)
    assert days_left == 18


# ---- 남은 날 / 여유 돈 (docs/rules.md 확인용 예시, seed 기준) ----
from datetime import date as _d

from app.calc import (appointments_sum, daily_margin, first_day, free_money, min_living,
                      monthly_sum, stage)

ROUTINES = [
    {"weekdays": [0, 1, 2, 3], "round_trip_fare": 3100, "meals_out": 2,
     "meal_price": 6000, "start_date": _d(2026, 9, 1), "end_date": _d(2026, 12, 18)},
    {"weekdays": [5, 6], "round_trip_fare": 3100, "meals_out": 0,
     "meal_price": 0, "start_date": None, "end_date": None},
]
INCOMES = [{"day_of_month": 25, "amount": 420000}, {"day_of_month": 1, "amount": 250000}]
FIXED = [{"day_of_month": 5, "amount": 33000}, {"day_of_month": 12, "amount": 10900}]
APPTS = [{"appt_date": _d(2026, 11, 7), "amount": 30000, "transport_fare": 0}]
TODAY = _d(2026, 10, 30)


def 계산(logged_tonight, balance):
    # 10/30 밤 기록 여부에 따라 남은 날 범위를 정해 여유 돈~단계까지 계산
    start, end, days_left = period(TODAY, 25, app_start=TODAY, logged_tonight=logged_tonight)
    f = first_day(TODAY, logged_tonight)
    ml = min_living(f, end, ROUTINES)
    free = free_money(balance, monthly_sum(f, end, INCOMES), monthly_sum(f, end, FIXED),
                      appointments_sum(f, end, APPTS), ml)
    daily = daily_margin(free, days_left)
    return days_left, ml, free, daily, stage(daily)


def test_남은_날_기록_전은_오늘부터_기록_후는_내일부터():
    assert period(TODAY, 25, app_start=TODAY)[2] == 26
    assert period(TODAY, 25, app_start=TODAY, logged_tonight=True)[2] == 25


def test_남은_날_마지막_날에_기록했으면_0():
    assert period(date(2026, 11, 24), 25, logged_tonight=True)[2] == 0


def test_기록_전_예시():
    # seed의 10/30 밤 기록은 빼고 계산 (잔액 290,000)
    assert 계산(False, 290000) == (26, 236200, 229900, 8800, "든든")


def test_기록_후_예시():
    # 10/30 밤 잔액 284,200 (5,800원 씀), 남은 날은 10/31부터라 25일
    # 최소 생활비는 오늘(금, 가는 곳 없음)이 0원이라 그대로 236,200
    assert 계산(True, 284200) == (25, 236200, 224100, 8900, "든든")


def test_밤_기록_때문에_최소_생활비가_두_번_빠지지_않는다():
    # 학교 가는 월요일(11/2)에 기록했다면 그날 15,100원은 남은 날에서 빠진다
    start, end, _ = period(date(2026, 11, 2), 25)
    assert min_living(date(2026, 11, 2), end, ROUTINES) - min_living(date(2026, 11, 3), end, ROUTINES) == 15100


def test_R6_R8_음수는_나방():
    assert daily_margin(-50, 10) == -100
    assert stage(-100) == "나방"
    assert stage(0) == "텅텅"
    assert stage(1000) == "홀쭉"
    assert stage(5000) == "든든"
    assert stage(10000) == "빵빵"


def test_R4_최소_생활비는_범위의_첫날부터_더한다():
    # 11/2(월)부터와 11/3(화)부터의 차이는 학교 하루(끼니 2 x 6,000 + 교통 3,100)
    end = _d(2026, 11, 24)
    assert min_living(_d(2026, 11, 2), end, ROUTINES) == 230000
    assert min_living(_d(2026, 11, 3), end, ROUTINES) == 214900


def test_R6_남은_날이_0이면_None():
    # 여유 돈이 음수여도 0(텅텅)으로 보이면 안 되므로 None
    assert daily_margin(-5000, 0) is None
    assert daily_margin(5000, 0) is None
