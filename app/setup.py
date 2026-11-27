# 첫 설정: 폼 값 검사와 저장. home.py·balance.py처럼 화면과 DB를 잇는다
import json
import uuid
from datetime import date

from app import calc, queries

# 화면에서 [+ 하나 더]로 늘릴 수 있는 최대 줄 수
INCOME_ROWS = 5   # 돈 들어오는 날
FIXED_ROWS = 6    # 고정비
ROUTINE_ROWS = 4  # 가는 곳
MAX_MONEY = 1_000_000_000

NO_INCOME = "돈 들어오는 날을 하나 이상 넣어 주세요"


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
    rows = []  # incomes[k]가 화면의 몇 번째 줄이었는지
    main = form.get("main")  # 직접 고른 줄 번호. 비어 있으면 앱이 정한다
    names, days, amounts = form.getlist("inc_name"), form.getlist("inc_day"), form.getlist("inc_amount")
    for i in range(INCOME_ROWS):
        amount = to_int(amounts[i] if i < len(amounts) else "", "돈 들어오는 날의 금액", default=0)
        if amount == 0:
            continue  # 금액이 비었거나 0이면 빈 줄
        incomes.append({
            "name": clean_name(names[i] if i < len(names) else "", "돈 들어오는 날"),
            "day_of_month": parse_day(days[i] if i < len(days) else ""),
            "amount": amount,
            "is_main": False,
            "row": i,
        })
        rows.append(i)
    if not incomes:
        raise FormError(NO_INCOME)
    # 기간 시작일: 직접 고른 줄이 없으면 금액이 가장 큰 수입의 날 (같으면 위에 적은 줄)
    if main in [str(i) for i in rows]:
        k = rows.index(int(main))
    else:
        k = max(range(len(incomes)), key=lambda n: incomes[n]["amount"])
    incomes[k]["is_main"] = True

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
    income = calc.incomes_sum(start, end, data["incomes"])
    return {"start": start, "end": end, "balance": data["balance"], "income": income,
            "available": data["balance"] + income}


def create_account(conn, data, today):
    # 한 트랜잭션으로 저장하고 (user_id, public_id)를 돌려준다. public_id는 쿠키에 넣는 익명 ID (R19)
    public_id = str(uuid.uuid4())
    start, end = first_period(data, today)
    user_id = queries.create_account(conn, data, public_id, start, end)
    return user_id, public_id


# ---- 첫 설정 다섯 단계 (흐름 2): 묻지 말고 채워 놓고, 고치게 한다 ----
# 단계 사이 값은 화면의 숨은 칸(draft, JSON)으로 넘기고, 끝에서 parse_step1·parse_step2로 다시 검사한다
LAST_STEP = 5
EXAMPLE_INCOMES = [{"name": "알바비", "day": "25", "amount": "500000"},
                   {"name": "용돈", "day": "1", "amount": "250000"}]
EXAMPLE_FIXED = [{"name": "통신비", "day": "5", "amount": "30000"}]
SCHOOL = {"name": "학교", "wds": ["0", "1", "2", "3", "4"], "meals": "2", "price": "6000",
          "fare": "3100", "start": "", "end": ""}
WEEKDAYS = "월화수목금토일"


def new_draft():
    return {"balance": "", "incomes": [dict(r) for r in EXAMPLE_INCOMES], "main": "",
            "fixed": [dict(r) for r in EXAMPLE_FIXED], "routines": [dict(SCHOOL, wds=list(SCHOOL["wds"]))],
            "comfort_daily": "10000", "hourly_wage": "10320", "emergency_fund": "0"}


def load_draft(text):
    # 화면에서 돌아온 JSON. 깨졌거나 모양이 다르면 그 부분은 처음 값으로
    base = new_draft()
    try:
        got = json.loads(text or "")
    except ValueError:
        return base
    if not isinstance(got, dict):
        return base
    for key in base:
        if key in ("incomes", "fixed", "routines"):
            rows = got.get(key)
            if isinstance(rows, list) and all(isinstance(r, dict) for r in rows):
                base[key] = rows
        elif isinstance(got.get(key), str):
            base[key] = got[key]
    return base


class DraftForm:
    # parse_step1·parse_step2가 읽는 request.form() 모양 (get, getlist)
    def __init__(self, pairs):
        self.pairs = pairs

    def get(self, name, default=None):
        for k, v in self.pairs:
            if k == name:
                return v
        return default

    def getlist(self, name):
        return [v for k, v in self.pairs if k == name]


def draft_to_form(d):
    pairs = [("balance", d["balance"]), ("main", d["main"]), ("comfort_daily", d["comfort_daily"]),
             ("hourly_wage", d["hourly_wage"]), ("emergency_fund", d["emergency_fund"])]
    for r in d["incomes"]:
        pairs += [("inc_name", r.get("name", "")), ("inc_day", r.get("day", "")),
                  ("inc_amount", r.get("amount", ""))]
    for r in d["fixed"]:
        pairs += [("fix_name", r.get("name", "")), ("fix_day", r.get("day", "")),
                  ("fix_amount", r.get("amount", ""))]
    for i, r in enumerate(d["routines"]):
        pairs += [("r_name", r.get("name", "")), ("r_meals", r.get("meals", "")),
                  ("r_price", r.get("price", "")), ("r_fare", r.get("fare", "")),
                  ("r_start", r.get("start", "")), ("r_end", r.get("end", ""))]
        pairs += [(f"r_wd_{i}", str(w)) for w in r.get("wds", [])]
    return DraftForm(pairs)


def _rows(form, prefix):
    names = form.getlist(f"{prefix}_name")
    days, amounts = form.getlist(f"{prefix}_day"), form.getlist(f"{prefix}_amount")
    return [{"name": names[i], "day": days[i] if i < len(days) else "",
             "amount": amounts[i] if i < len(amounts) else ""} for i in range(len(names))]


def take_step(d, form, step, editing):
    # 지금 단계 화면에 있던 칸을 draft로 옮긴다 (가는 곳은 고치는 화면일 때만 칸이 있다)
    if step == 1:
        d["balance"] = (form.get("balance") or "").strip()
    elif step == 2:
        d["incomes"] = _rows(form, "inc")
    elif step == 3:
        d["fixed"] = _rows(form, "fix")
    elif step == 4 and editing:
        names = form.getlist("r_name")
        meals, prices, fares = form.getlist("r_meals"), form.getlist("r_price"), form.getlist("r_fare")
        starts, ends = form.getlist("r_start"), form.getlist("r_end")

        def at(items, i):
            return items[i] if i < len(items) else ""

        d["routines"] = [{"name": names[i], "wds": form.getlist(f"r_wd_{i}"), "meals": at(meals, i),
                          "price": at(prices, i), "fare": at(fares, i), "start": at(starts, i),
                          "end": at(ends, i)} for i in range(len(names))]
    return d


def apply_op(d, op):
    # 줄 더하기·빼기, 없어요 같은 버튼. 처리했으면 True
    kind, _, arg = op.partition(":")
    index = int(arg) if arg.isdigit() else -1
    if kind == "add_income" and len(d["incomes"]) < INCOME_ROWS:
        d["incomes"].append({"name": "", "day": "", "amount": ""})
    elif kind == "del_income" and 0 <= index < len(d["incomes"]):
        del d["incomes"][index]
        main = int(d["main"]) if d["main"].isdigit() else -1
        if main == index:
            d["main"] = ""  # 고른 줄을 빼면 다시 앱이 정한다
        elif main > index:
            d["main"] = str(main - 1)
    elif kind == "add_fixed" and len(d["fixed"]) < FIXED_ROWS:
        d["fixed"].append({"name": "", "day": "", "amount": ""})
    elif kind == "del_fixed" and 0 <= index < len(d["fixed"]):
        del d["fixed"][index]
    elif kind == "no_fixed":
        d["fixed"] = []
    elif kind == "add_routine" and len(d["routines"]) < ROUTINE_ROWS:
        d["routines"].append({"name": "", "wds": [], "meals": "0", "price": "0", "fare": "0",
                              "start": "", "end": ""})
    elif kind == "del_routine" and 0 <= index < len(d["routines"]):
        del d["routines"][index]
    elif kind == "no_routine":
        d["routines"] = []
    else:
        return False
    return True


def check_step(d, step):
    # [다음]을 누르기 전 검사. 문제가 있으면 FormError
    if step == 1:
        to_int(d["balance"], "지금 잔액", low=-MAX_MONEY)
    elif step in (2, 3):
        parse_step1(draft_to_form(d))
    elif step == 4:
        parse_step2(draft_to_form(d))


def draft_data(d):
    # create_account가 받는 모양 (다섯 단계 값을 한 번 더 검사한다)
    form = draft_to_form(d)
    data = parse_step1(form)
    data["routines"] = parse_step2(form)
    return data


def example_left(d):
    # 5/5에서 알려 줄 '아직 예시 값' 줄 이름 (금액까지 예시와 똑같이 남은 줄)
    names = [r.get("name") for r in d["incomes"] if r in EXAMPLE_INCOMES]
    return names + [r.get("name") for r in d["fixed"] if r in EXAMPLE_FIXED]


def iga(name):
    # 이름 뒤에 붙일 '이/가' (받침이 없으면 가)
    last = name[-1]
    return "가" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 0 else "이"


def period_text(day):
    # 기간이 이 날부터 시작한다는 날짜 범위: 25 -> '25일 ~ 다음 달 24일'
    return "1일 ~ 그달 말일" if day == 1 else f"{day}일 ~ 다음 달 {day - 1}일"


def preview(data, today):
    # 5/5 확인 화면 (R17): 기록이 없는 새 사람의 첫날 홈과 같은 계산 (R2~R8)
    start, end = first_period(data, today)
    main = [i for i in data["incomes"] if i["is_main"]][0]
    choices = [{"row": i.get("row", k), "name": i["name"], "range": period_text(i["day_of_month"]),
                "main": i["is_main"]} for k, i in enumerate(data["incomes"])]
    days_left = (end - today).days + 1
    income = calc.incomes_sum(today, end, data["incomes"])
    fixed = calc.monthly_sum(today, end, data["fixed"])
    min_living = calc.min_living(today, end, data["routines"])
    free = calc.free_money(data["balance"], income, fixed, 0, min_living)
    daily = calc.daily_margin(free, days_left)
    return {"start": start, "end": end, "days_left": days_left, "balance": data["balance"],
            "main": main, "main_iga": iga(main["name"]), "choices": choices,
            "income": income, "fixed": fixed, "min_living": min_living, "free": free,
            "daily": daily, "stage": calc.stage(daily, data["comfort_daily"]),
            "budget": calc.today_budget(today, data["routines"], [], daily)}


def weekday_text(wds):
    # [0,1,2,3,4] -> 월~금, [5,6] -> 토·일, [0,2,4] -> 월·수·금
    days = sorted({int(w) for w in wds if str(w).isdigit() and int(w) < 7})
    if not days:
        return "요일 없음"
    if len(days) >= 3 and days == list(range(days[0], days[-1] + 1)):
        return f"{WEEKDAYS[days[0]]}~{WEEKDAYS[days[-1]]}"
    return "·".join(WEEKDAYS[x] for x in days)
