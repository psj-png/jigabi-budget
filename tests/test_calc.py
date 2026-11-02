from datetime import date

from app.calc import (appointments_sum, daily_margin, first_day, free_money,
                      min_living, monthly_sum, incomes_sum, period, stage,
                      today_budget)


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
ROUTINES = [
    {"weekdays": [0, 1, 2, 3], "round_trip_fare": 3100, "meals_out": 2,
     "meal_price": 6000, "start_date": date(2026, 9, 1), "end_date": date(2026, 12, 18)},
    {"weekdays": [5, 6], "round_trip_fare": 3100, "meals_out": 0,
     "meal_price": 0, "start_date": None, "end_date": None},
]
INCOMES = [{"day_of_month": 25, "amount": 420000, "is_main": True},
           {"day_of_month": 1, "amount": 250000, "is_main": False}]
FIXED = [{"day_of_month": 5, "amount": 33000}, {"day_of_month": 12, "amount": 10900}]
APPTS = [{"appt_date": date(2026, 11, 7), "amount": 30000, "transport_fare": 0}]
TODAY = date(2026, 10, 30)


def 계산(today, logged_tonight, balance, app_start=None):
    # 남은 날 범위를 정해 쓸 수 있는 돈~단계까지 계산. 쓸 수 있는 돈도 같이 돌려줌
    start, end, days_left = period(today, 25, app_start=app_start, logged_tonight=logged_tonight)
    f = first_day(today, logged_tonight)
    ml = min_living(f, end, ROUTINES)
    incomes = incomes_sum(f, end, INCOMES)
    free = free_money(balance, incomes, monthly_sum(f, end, FIXED),
                      appointments_sum(f, end, APPTS), ml)
    daily = daily_margin(free, days_left)
    return days_left, ml, balance + incomes, free, daily, stage(daily)


def test_남은_날_기록_전은_오늘부터_기록_후는_내일부터():
    assert period(TODAY, 25, app_start=TODAY)[2] == 26
    assert period(TODAY, 25, app_start=TODAY, logged_tonight=True)[2] == 25


def test_남은_날_마지막_날에_기록했으면_0():
    assert period(date(2026, 11, 24), 25, logged_tonight=True)[2] == 0


def test_기록_전_예시():
    # seed의 10/30 밤 기록은 빼고 계산 (잔액 290,000)
    assert 계산(TODAY, False, 290000, TODAY) == (26, 236200, 540000, 229900, 8800, "든든")


def test_기록_후_예시():
    # 10/30 밤 잔액 284,200 (5,800원 씀), 남은 날은 10/31부터라 25일
    # 최소 생활비는 오늘(금, 가는 곳 없음)이 0원이라 그대로 236,200
    assert 계산(TODAY, True, 284200, TODAY) == (25, 236200, 534200, 224100, 8900, "든든")


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
    end = date(2026, 11, 24)
    assert min_living(date(2026, 11, 2), end, ROUTINES) == 230000
    assert min_living(date(2026, 11, 3), end, ROUTINES) == 214900


def test_R6_남은_날이_0이면_None():
    # 여유 돈이 음수여도 0(텅텅)으로 보이면 안 되므로 None
    assert daily_margin(-5000, 0) is None
    assert daily_margin(5000, 0) is None


def test_다음_기간_예시():
    # 11/25~12/24: 시작 잔액은 11/24 밤 잔액인데 확인용 예시에서는 0으로 본다
    # (rules.md R13 '이번 기간에서 남는 돈은 0으로 봄')
    # 기간 중 수입은 알바비 420,000 + 용돈 250,000 = 670,000
    assert 계산(date(2026, 11, 25), False, 0) == (30, 236200, 670000, 389900, 12900, "빵빵")  # 넉넉 기준 10,000 이상


def test_R7_오늘_쓸_수_있는_돈():
    # 기록 전 하루 여유 8,800 기준
    def 오늘(day):
        return today_budget(day, ROUTINES, APPTS, 8800)

    assert 오늘(date(2026, 10, 30)) == 8800    # 금: 가는 곳 없음
    assert 오늘(date(2026, 10, 31)) == 11900   # 토: 알바 교통비 3,100
    assert 오늘(date(2026, 11, 2)) == 23900    # 월: 학교 15,100
    assert 오늘(date(2026, 11, 7)) == 41900    # 토: 알바 3,100 + 술자리 30,000


def test_R7_약속_교통비도_더한다():
    # 이 약속을 넣으면 하루 여유가 8,800 -> 6,800 (rules.md 확인용 예시)
    appts = [{"appt_date": date(2026, 11, 13), "amount": 50000, "transport_fare": 3100}]
    assert today_budget(date(2026, 11, 13), ROUTINES, appts, 6800) == 59900


def test_R7_하루_여유가_None이면_None():
    assert today_budget(date(2026, 11, 7), ROUTINES, APPTS, None) is None


def test_밤_기록_후_내일_쓸_수_있는_돈():
    # 10/30 밤 기록(잔액 284,200): 남은 날 25, 여유 돈 224,100, 하루 여유 8,900
    # 내일(10/31 토) = 알바 교통비 3,100 + 하루 여유 8,900
    days_left, ml, available, free, daily, _ = 계산(TODAY, True, 284200, TODAY)
    assert (days_left, free, daily) == (25, 224100, 8900)
    assert today_budget(date(2026, 10, 31), ROUTINES, APPTS, daily) == 12000


def test_기간_마지막_날_밤_기록하면_남은_날_0이고_하루_여유_None():
    end_day = date(2026, 11, 24)
    days_left = period(end_day, 25, logged_tonight=True)[2]
    assert days_left == 0
    assert daily_margin(100000, days_left) is None


def test_R2_이번_기간_수입_합은_용돈만():
    # 10/30~11/24: 알바비 25일은 범위 밖이라 11/1 용돈 250,000만
    assert incomes_sum(date(2026, 10, 30), date(2026, 11, 24), INCOMES) == 250000
