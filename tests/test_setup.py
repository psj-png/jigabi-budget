# 첫 설정 폼 검사 (DB 없이)
from datetime import date

import pytest

from app import setup


class FormData:
    # request.form()처럼 get, getlist만 흉내 낸 것 (starlette를 따로 설치하지 않아도 되게)
    def __init__(self, items):
        self.items = items

    def get(self, name, default=None):
        for k, v in self.items:
            if k == name:
                return v
        return default

    def getlist(self, name):
        return [v for k, v in self.items if k == name]


def make_form(**fields):
    # make_form(inc_name=["알바비", "", ""]) 처럼 칸 이름 -> 값 목록
    items = []
    for name, values in fields.items():
        if isinstance(values, str):
            values = [values]
        items += [(name, v) for v in values]
    return FormData(items)


# seed와 같은 값
SEED_STEP1 = dict(
    balance="290000",
    inc_name=["알바비", "용돈", ""], inc_day=["25", "1", ""], inc_amount=["420000", "250000", ""],
    main="0",
    fix_name=["통신비", "음악 구독", "", ""], fix_day=["5", "12", "", ""],
    fix_amount=["33000", "10900", "", ""],
    comfort_daily="10000", hourly_wage="10320", emergency_fund="0",
)


def test_seed_값을_읽는다():
    data = setup.parse_step1(make_form(**SEED_STEP1))
    assert data["balance"] == 290000
    assert [(i["name"], i["day_of_month"], i["amount"], i["is_main"]) for i in data["incomes"]] == \
        [("알바비", 25, 420000, True), ("용돈", 1, 250000, False)]
    assert [(f["name"], f["day_of_month"], f["amount"]) for f in data["fixed"]] == \
        [("통신비", 5, 33000), ("음악 구독", 12, 10900)]


def test_빈_줄과_금액_0은_무시한다():
    fields = dict(SEED_STEP1)
    fields["inc_name"] = ["알바비", "용돈", "장학금"]
    fields["inc_day"] = ["25", "1", "15"]
    fields["inc_amount"] = ["420000", "0", ""]   # 0과 빈 값은 무시
    data = setup.parse_step1(make_form(**fields))
    assert [i["name"] for i in data["incomes"]] == ["알바비"]


def test_수입이_없으면_막는다():
    fields = dict(SEED_STEP1)
    fields["inc_amount"] = ["", "", ""]
    with pytest.raises(setup.FormError) as e:
        setup.parse_step1(make_form(**fields))
    assert str(e.value) == "돈 들어오는 날을 하나 이상 넣고, 기간 기준을 골라 주세요"


def test_기간_기준을_안_고르면_막는다():
    fields = dict(SEED_STEP1)
    del fields["main"]
    with pytest.raises(setup.FormError) as e:
        setup.parse_step1(make_form(**fields))
    assert str(e.value) == setup.NO_INCOME

    # 빈 줄(2번째 줄이 아닌 3번째)을 기준으로 골라도 막는다
    fields["main"] = "2"
    with pytest.raises(setup.FormError):
        setup.parse_step1(make_form(**fields))


def test_매달_며칠은_1부터_31():
    for bad in ["0", "32"]:
        fields = dict(SEED_STEP1)
        fields["inc_day"] = [bad, "1", ""]
        with pytest.raises(setup.FormError):
            setup.parse_step1(make_form(**fields))


def test_기준_세_칸은_비우면_기본값():
    fields = dict(SEED_STEP1, comfort_daily="", hourly_wage="", emergency_fund="")
    data = setup.parse_step1(make_form(**fields))
    assert (data["comfort_daily"], data["hourly_wage"], data["emergency_fund"]) == (10000, 10320, 0)


SEED_STEP2 = dict(
    r_name=["학교", "알바", ""],
    r_wd_0=["0", "1", "2", "3"], r_wd_1=["5", "6"],
    r_meals=["2", "0", ""], r_price=["6000", "0", ""], r_fare=["3100", "3100", ""],
    r_start=["2026-09-01", "", ""], r_end=["2026-12-18", "", ""],
)


def test_가는_곳을_읽는다():
    routines = setup.parse_step2(make_form(**SEED_STEP2))
    assert [(r["name"], r["weekdays"], r["meals_out"], r["meal_price"], r["round_trip_fare"])
            for r in routines] == [("학교", [0, 1, 2, 3], 2, 6000, 3100), ("알바", [5, 6], 0, 0, 3100)]
    assert routines[0]["start_date"] == date(2026, 9, 1) and routines[0]["end_date"] == date(2026, 12, 18)
    assert routines[1]["start_date"] is None and routines[1]["end_date"] is None


def test_가는_곳_이름이_없거나_요일이_없으면_무시():
    fields = dict(SEED_STEP2)
    fields["r_name"] = ["", "알바", "스터디"]   # 1번: 이름 없음, 3번: 요일 없음
    routines = setup.parse_step2(make_form(**fields))
    assert [r["name"] for r in routines] == ["알바"]


def test_이번_기간_쓸_수_있는_돈():
    data = setup.parse_step1(make_form(**SEED_STEP1))
    s = setup.summary(data, date(2026, 10, 30))
    assert (s["start"], s["end"], s["available"]) == (date(2026, 10, 30), date(2026, 11, 24), 540000)


def test_복구_코드_모양():
    code = setup.new_recovery_code()
    assert len(code) == 14 and code.count("-") == 2
    assert not set(code) & set("01OIL")
