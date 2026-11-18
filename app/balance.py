# 밤 잔액 화면에 필요한 값을 모으고 저장한다: queries와 calc를 잇는다
from datetime import timedelta

from app import calc, queries
from app.home import ensure_period, make_home


def _blocked(conn, user_id, today, day):
    # 오늘 기록이 이미 있으면 어제는 못 적는다
    if day != today and queries.get_balance_log(conn, user_id, today) is not None:
        return "오늘 밤 잔액을 이미 적어서 어제는 못 적어요"
    return None


def _context(conn, user_id, day):
    # day가 속한 기간 기준으로 지난 잔액과 그 뒤 범위(start~day)를 정한다
    per = ensure_period(conn, user_id, day)  # 기간이 없으면 만든다
    if per is None:
        return None

    prev = queries.get_latest_balance_log(conn, user_id, day - timedelta(days=1))
    if prev is not None and prev["log_date"] >= per["start_date"]:
        prev_balance = prev["balance"]
        start = prev["log_date"] + timedelta(days=1)
    else:
        prev_balance = per["opening_balance"]
        start = per["start_date"]

    incomes = queries.get_incomes(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    items = queries.get_items(conn, user_id)
    loans = queries.get_loans(conn, user_id)
    # 기간 첫날이 범위에 있으면 그날 갚은 돈(repay_amount)도 빠져나간 돈이다
    repay = per["repay_amount"] if start == per["start_date"] else 0
    return {
        "prev_balance": prev_balance,
        "start": start,
        "income_plan": calc.incomes_sum(start, day, incomes) + calc.loans_sum(start, day, loans),
        "fixed_out": calc.monthly_sum(start, day, fixed) + repay,
        "bought": calc.purchases_sum(start, day, items),  # 그 사이 산 값 - 반품한 값
    }


NO_PERIOD = "앱을 시작하기 전 날짜라 적을 수 없어요"


def get_form(conn, user_id, today, day):
    # message가 있으면 폼 대신 그 문장을 보여준다
    form = {"day": day, "message": None, "show_income": False, "income_plan": 0,
            "prev_balance": None}
    ctx = _context(conn, user_id, day)
    if ctx is None:
        form["message"] = NO_PERIOD
        return form
    form["message"] = _blocked(conn, user_id, today, day)
    # 범위에 예정 수입이 있을 때만 '들어온 돈' 칸을 보여준다
    form["income_plan"] = ctx["income_plan"]
    form["prev_balance"] = ctx["prev_balance"]
    form["show_income"] = ctx["income_plan"] > 0
    return form


def save(conn, user_id, today, day, balance, income_in):
    # 저장하면 None, 못 저장하면 이유(문장)를 돌려준다
    ctx = _context(conn, user_id, day)
    if ctx is None:
        return NO_PERIOD
    message = _blocked(conn, user_id, today, day)
    if message:
        return message

    spent = calc.spent_money(ctx["prev_balance"], income_in, ctx["fixed_out"], ctx["bought"], balance)
    queries.save_balance_log(conn, user_id, day, balance, income_in, spent)

    # 다음 날 시작하는 기간이 이미 있으면 그 시작 잔액을 적은 잔액으로 고친다
    next_day = day + timedelta(days=1)
    nxt = queries.get_period(conn, user_id, next_day)
    if nxt is not None and nxt["start_date"] == next_day:
        queries.update_opening_balance(conn, user_id, next_day, balance)
    return None


def make_result(before, after, spent, day):
    # 저장 결과 카드 값: before는 저장 전 make_home(오늘 쓸 수 있던 돈), after는 저장 후(내일 쓸 수 있는 돈)
    # 새 계산은 없다. 두 값의 차이만 구한다
    r = {"spent": spent, "day": day, "next_day": day + timedelta(days=1),
         "before_budget": before["budget"], "stage_before": before["stage"],
         "stage_after": after["stage"] or before["stage"],
         "after_budget": after["budget"], "ended": after["budget"] is None,
         "left": None, "diff": None}
    if before["budget"] is not None:
        r["left"] = before["budget"] - spent  # 0 이상이면 남긴 돈, 0 미만이면 더 쓴 돈
        if after["budget"] is not None:
            r["diff"] = after["budget"] - before["budget"]
    return r


def guess_balance(conn, user_id, day, spent):
    # R10-1 쓴 돈으로 적기: 그날 아침 잔액에서 그날 들어오고 나간 돈과 '쓴 돈'을 빼 잔액을 거꾸로 구한다
    # 그 사이 안 적은 날은 R10대로 최소 생활비와 약속만큼 썼다고 본다. (잔액, 들어온 돈)을 돌려준다
    ctx = _context(conn, user_id, day)
    if ctx is None:
        return None
    usual = 0
    last_missed = day - timedelta(days=1)
    if ctx["start"] <= last_missed:
        routines = queries.get_routines(conn, user_id)
        appts = queries.get_appointments(conn, user_id)
        usual = (calc.min_living(ctx["start"], last_missed, routines)
                 + calc.appointments_sum(ctx["start"], last_missed, appts))
    balance = (ctx["prev_balance"] + ctx["income_plan"] - ctx["fixed_out"] - ctx["bought"]
               - usual - spent)
    return balance, ctx["income_plan"]


def make_card(conn, user_id, today, day, mode=None, guess=None, edit=False, error=None):
    # 홈 맨 아래 밤 잔액 카드 (13~15): 적기 전(input) / 쓴 돈으로(spent) / 맞나요?(confirm) / 적은 뒤(result)
    card = {"day": day, "is_today": day == today, "mode": "input", "form": None,
            "result": None, "guess": guess, "error": error, "other_day": None}
    log = queries.get_balance_log(conn, user_id, day)
    if log is not None and not edit and mode is None and guess is None and error is None:
        # 적은 뒤에는 같은 자리에서 결과로 바뀐다 (14). 저장 전 값은 before_night로 다시 구한다
        before = make_home(conn, user_id, day, before_night=True)
        after = make_home(conn, user_id, day)
        card["mode"] = "result"
        card["result"] = make_result(before, after, log["spent"], day)
        return card
    card["form"] = get_form(conn, user_id, today, day)
    if guess is not None:
        card["mode"] = "confirm"
    elif mode == "spent":
        card["mode"] = "spent"
    # 오늘 기록이 없을 때만 오늘 밤 / 어젯밤을 바꿔 적을 수 있다 (앱을 시작하기 전 날은 빼고)
    if queries.get_balance_log(conn, user_id, today) is None:
        other = today - timedelta(days=1) if day == today else today
        if queries.get_period(conn, user_id, other) is not None:
            card["other_day"] = other
    return card
