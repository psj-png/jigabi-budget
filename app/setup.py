# 첫 설정: 폼 값 검사, 복구 코드 만들기, 저장. home.py·balance.py처럼 화면과 DB를 잇는다
import hashlib
import secrets
import uuid
from datetime import date

from app import calc, queries

INCOME_ROWS = 3   # 돈 들어오는 날 줄 수
FIXED_ROWS = 4    # 고정비 줄 수
ROUTINE_ROWS = 3  # 가는 곳 줄 수
MAX_MONEY = 1_000_000_000

# 1단계 폼 칸 이름. 2단계로 넘어갈 때 hidden으로 다시 넣는다
STEP1_FIELDS = ["balance", "inc_name", "inc_day", "inc_amount", "main",
                "fix_name", "fix_day", "fix_amount",
                "comfort_daily", "hourly_wage", "emergency_fund"]

NO_INCOME = "돈 들어오는 날을 하나 이상 넣고, 기간 기준을 골라 주세요"


class FormError(Exception):
    # 화면에 그대로 보여줄 문장을 들고 있다
    pass


def to_int(text, label, default=None, low=0):
    text = (text or "").strip()
    if text == "":
        if default is None:
            raise FormError(f"{label}을(를) 적어 주세요")
        return default
    try:
        value = int(text)
    except ValueError:
        raise FormError(f"{label}은(는) 숫자로 적어 주세요")
    if value < low or value > MAX_MONEY:
        raise FormError(f"{label} 값이 너무 크거나 작아요")
    return value


def clean_name(text, label):
    text = (text or "").strip()
    if text == "":
        raise FormError(f"{label}의 이름을 적어 주세요")
    if len(text) > 20:
        raise FormError(f"{label}의 이름은 20자까지예요")
    return text


def parse_day(text):
    day = to_int(text, "매달 며칠", low=1)
    if day > 31:
        raise FormError("매달 며칠은 1~31로 적어 주세요")
    return day


def parse_step1(form):
    # 검사를 통과하면 dict, 아니면 FormError
    balance = to_int(form.get("balance"), "지금 잔액", low=-MAX_MONEY)

    incomes = []
    main = form.get("main")
    names, days, amounts = form.getlist("inc_name"), form.getlist("inc_day"), form.getlist("inc_amount")
    for i in range(INCOME_ROWS):
        amount = to_int(amounts[i] if i < len(amounts) else "", "돈 들어오는 날의 금액", default=0)
        if amount == 0:
            continue  # 금액이 비었거나 0이면 빈 줄
        incomes.append({
            "name": clean_name(names[i] if i < len(names) else "", "돈 들어오는 날"),
            "day_of_month": parse_day(days[i] if i < len(days) else ""),
            "amount": amount,
            "is_main": main == str(i),
        })
    if not incomes or not any(i["is_main"] for i in incomes):
        raise FormError(NO_INCOME)

    fixed = []
    names, days, amounts = form.getlist("fix_name"), form.getlist("fix_day"), form.getlist("fix_amount")
    for i in range(FIXED_ROWS):
        amount = to_int(amounts[i] if i < len(amounts) else "", "고정비 금액", default=0)
        if amount == 0:
            continue
        fixed.append({
            "name": clean_name(names[i] if i < len(names) else "", "고정비"),
            "day_of_month": parse_day(days[i] if i < len(days) else ""),
            "amount": amount,
        })

    return {
        "balance": balance,
        "incomes": incomes,
        "fixed": fixed,
        "comfort_daily": to_int(form.get("comfort_daily"), "넉넉 기준", default=10000),
        "hourly_wage": to_int(form.get("hourly_wage"), "시급", default=10320),
        "emergency_fund": to_int(form.get("emergency_fund"), "비상금", default=0),
    }


def parse_date_or_none(text, label):
    text = (text or "").strip()
    if text == "":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise FormError(f"{label}은(는) 날짜 모양이어야 해요")


def parse_step2(form):
    # 가는 곳 목록. 이름이 비었거나 요일을 하나도 안 고른 줄은 무시
    names = form.getlist("r_name")
    meals, prices, fares = form.getlist("r_meals"), form.getlist("r_price"), form.getlist("r_fare")
    starts, ends = form.getlist("r_start"), form.getlist("r_end")

    def at(items, i):
        return items[i] if i < len(items) else ""

    routines = []
    for i in range(ROUTINE_ROWS):
        name = at(names, i).strip()
        weekdays = sorted({int(w) for w in form.getlist(f"r_wd_{i}") if w in list("0123456")})
        if name == "" or not weekdays:
            continue
        if len(name) > 20:
            raise FormError("가는 곳의 이름은 20자까지예요")
        meals_out = to_int(at(meals, i), "밖에서 먹는 끼니 수", default=0)
        if meals_out > 10:
            raise FormError("밖에서 먹는 끼니 수는 10까지예요")
        start = parse_date_or_none(at(starts, i), "시작일")
        end = parse_date_or_none(at(ends, i), "끝나는 날")
        if start and end and end < start:
            raise FormError("끝나는 날이 시작일보다 앞이에요")
        routines.append({
            "name": name,
            "weekdays": weekdays,
            "meals_out": meals_out,
            "meal_price": to_int(at(prices, i), "끼니 가격", default=0),
            "round_trip_fare": to_int(at(fares, i), "왕복 교통비", default=0),
            "start_date": start,
            "end_date": end,
        })
    return routines


def first_period(data, today):
    # 첫 기간: 시작일은 오늘(앱 시작일), 끝은 주 수입일 기준
    main = [i for i in data["incomes"] if i["is_main"]][0]
    start, end, _ = calc.period(today, main["day_of_month"], app_start=today)
    return start, end


def summary(data, today):
    # 2단계 맨 위: 이번 기간 쓸 수 있는 돈 = 잔액 + 기간 안 수입 (R2)
    start, end = first_period(data, today)
    return {"start": start, "end": end,
            "available": data["balance"] + calc.incomes_sum(start, end, data["incomes"])}


def new_recovery_code():
    # 사람이 옮겨 적기 쉽게: 헷갈리는 글자(0 O 1 I L)를 빼고 4자씩 끊는다
    letters = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(letters) for _ in range(12))
    return "-".join([code[0:4], code[4:8], code[8:12]])


def create_account(conn, data, today):
    # 한 트랜잭션으로 저장하고 (user_id, public_id, 복구 코드)를 돌려준다
    public_id = str(uuid.uuid4())
    code = new_recovery_code()
    recovery_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    start, end = first_period(data, today)
    user_id = queries.create_account(conn, data, public_id, recovery_hash, start, end)
    return user_id, public_id, code
