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
    assert str(e.value) == "돈 들어오는 날을 하나 이상 넣어 주세요"


def test_기간_시작일은_가장_큰_수입의_날():
    fields = dict(SEED_STEP1)
    del fields["main"]  # 화면에서 고르지 않는다: 앱이 정한다
    fields["inc_name"] = ["용돈", "알바비", "장학금"]
    fields["inc_day"] = ["1", "25", "15"]
    fields["inc_amount"] = ["250000", "400000", "400000"]
    data = setup.parse_step1(make_form(**fields))
    # 금액이 가장 큰 건 알바비·장학금 (같다) -> 위에 적은 알바비
    assert [(i["name"], i["is_main"]) for i in data["incomes"]] == [("용돈", False), ("알바비", True), ("장학금", False)]
    assert setup.first_period(data, date(2026, 11, 27))[1] == date(2026, 12, 24)


def test_직접_고르지_않아도_막지_않는다():
    fields = dict(SEED_STEP1)
    fields["main"] = "2"  # 빈 줄을 가리키면 없는 걸로 보고 앱이 정한다
    data = setup.parse_step1(make_form(**fields))
    assert [i["is_main"] for i in data["incomes"]] == [True, False]


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


# ---- 첫 설정 다섯 단계 (흐름 2) ----
def test_첫_설정_초안은_예시로_채워져_있다():
    d = setup.new_draft()
    d["balance"] = "290000"
    form = setup.draft_to_form(d)
    data = setup.parse_step1(form)
    assert [(i["name"], i["day_of_month"], i["amount"], i["is_main"]) for i in data["incomes"]] == [
        ("알바비", 25, 500000, True), ("용돈", 1, 250000, False)]
    assert [(f["name"], f["amount"]) for f in data["fixed"]] == [("통신비", 30000)]
    routines = setup.parse_step2(form)
    assert [(r["name"], r["weekdays"], r["meals_out"], r["meal_price"], r["round_trip_fare"])
            for r in routines] == [("학교", [0, 1, 2, 3, 4], 2, 6000, 3100)]
    # 금액을 안 바꾼 줄은 확인 화면에서 알려 준다
    assert setup.example_left(d) == ["알바비", "용돈", "통신비"]
    d["incomes"][0]["amount"] = "420000"
    assert setup.example_left(d) == ["용돈", "통신비"]


def test_첫_설정_줄_더하고_빼기():
    d = setup.new_draft()
    assert setup.apply_op(d, "add_income") and len(d["incomes"]) == 3
    d["main"] = "1"
    assert setup.apply_op(d, "del_income:0")  # 기준 줄 앞을 빼면 기준 번호도 당겨진다
    assert d["main"] == "0" and d["incomes"][0]["name"] == "용돈"
    assert setup.apply_op(d, "del_income:0")  # 고른 줄을 빼면 다시 앱이 정한다
    assert d["main"] == "" and len(d["incomes"]) == 1
    assert setup.apply_op(d, "no_fixed") and d["fixed"] == []
    assert setup.apply_op(d, "add_alba") and [r["name"] for r in d["routines"]] == ["학교", "알바"]
    assert setup.apply_op(d, "no_routine") and d["routines"] == []
    assert not setup.apply_op(d, "모르는_버튼")
    # 최대 줄 수를 넘기지 않는다
    for _ in range(10):
        setup.apply_op(d, "add_fixed")
    assert len(d["fixed"]) == setup.FIXED_ROWS


def test_단계마다_검사():
    d = setup.new_draft()
    with pytest.raises(setup.FormError):
        setup.check_step(d, 1)  # 잔액은 비어 있다
    d["balance"] = "290000"
    setup.check_step(d, 1)
    setup.check_step(d, 2)  # 기간 시작일은 앱이 정하니 안 골라도 된다
    d["routines"][0]["wds"] = []  # 요일이 없으면 빈 줄로 본다
    setup.check_step(d, 4)
    assert setup.draft_data(d)["routines"] == []


def test_깨진_초안은_처음부터():
    assert setup.load_draft("{깨짐") == setup.new_draft()
    assert setup.load_draft('{"incomes": "x", "balance": "5"}')["incomes"] == setup.new_draft()["incomes"]
    assert setup.load_draft('{"incomes": "x", "balance": "5"}')["balance"] == "5"


def test_요일_글자():
    assert setup.weekday_text(["0", "1", "2", "3", "4"]) == "월~금"
    assert setup.weekday_text([5, 6]) == "토·일"
    assert setup.weekday_text([0, 2, 4]) == "월·수·금"
    assert setup.weekday_text([]) == "요일 없음"
