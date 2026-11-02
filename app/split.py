# 나눠 사기 추천: 이번·다음·그다음 기간의 여유 돈을 구해 calc.split_plan에 넘긴다 (R13)
from datetime import timedelta

from app import calc, queries
from app.home import make_home

MAX_ITEMS = 8
PERIOD_NAMES = ["이번 기간", "다음 기간", "그다음 기간"]


def man(amount):
    # 420000 -> '42만', 만 단위로 안 떨어지면 '12,500원'
    if amount % 10000 == 0:
        return f"{amount // 10000}만"
    return f"{amount:,}원"


def md(day):
    return f"{day.month}/{day.day}"


def make_split(conn, user_id, today, selected):
    # selected: 장바구니에서 체크한 item_id 목록
    h = make_home(conn, user_id, today)
    if not h["ready"]:
        return {"ready": False}
    result = {"ready": True, "message": None, "plan": None, "note": None}
    if h["daily"] is None:
        result["message"] = "이번 기간이 끝났어요. 새 기간에 다시 봐요"
        return result

    wishes = queries.get_wish_items(conn, user_id)
    chosen = [w for w in wishes if w["item_id"] in selected]
    if not chosen:
        result["message"] = "장바구니에서 나눠 살 물건을 체크해 주세요"
        return result
    if len(chosen) > MAX_ITEMS:
        result["message"] = f"{MAX_ITEMS}개까지만 나눠 볼 수 있어요"
        return result

    user = queries.get_user(conn, user_id)
    incomes = queries.get_incomes(conn, user_id)
    main = [i for i in incomes if i["is_main"]][0]
    routines = queries.get_routines(conn, user_id)
    fixed = queries.get_fixed_costs(conn, user_id)
    appts = queries.get_appointments(conn, user_id)
    all_items = queries.get_items(conn, user_id)

    # 이번 기간은 지금 여유 돈, 다음·그다음은 이번에서 남는 돈을 0으로 보고 계산
    periods = [(today, h["free"], h["days_left"])]
    spans = [(today, h["end"])]
    start = h["end"] + timedelta(days=1)
    for _ in range(2):
        p_start, p_end, days = calc.period(start, main["day_of_month"])
        free = calc.free_money(
            0,
            calc.incomes_sum(p_start, p_end, incomes),
            calc.monthly_sum(p_start, p_end, fixed),
            calc.appointments_sum(p_start, p_end, appts),
            calc.min_living(p_start, p_end, routines),
            0,
            calc.planned_sum(p_start, p_end, all_items),  # 이미 살 계획을 잡은 물건
        )
        periods.append((p_start, free, days))
        spans.append((p_start, p_end))
        start = p_end + timedelta(days=1)

    # (이름, 가격, 필요한 날, item_id): calc.split_plan은 앞의 세 개만 쓴다
    items = [(w["name"], w["price"], w["need_by"], w["item_id"]) for w in chosen]
    plan = calc.split_plan(items, periods, user["comfort_daily"])
    if plan is None:
        result["message"] = "세 기간에 나눠도 나방이 나와요. 담은 걸 줄여 보세요"
        return result

    labels = [f"지금 · {md(today)}", f"{md(periods[1][0])} {main['name']} 들어온 뒤",
              f"{md(periods[2][0])} 이후"]
    for i, p in enumerate(plan):
        p["label"] = labels[i]
        p["name"] = PERIOD_NAMES[i]
        p["start"] = periods[i][0]
        p["free"] = periods[i][1]
        p["days"] = periods[i][2]

    result["plan"] = plan
    result["message"] = "이렇게 나눠 사면 나방은 안 나와요"
    needs = sorted({w["need_by"] for w in chosen if w["need_by"]})
    if needs:
        result["note"] = f"필요한 날({', '.join(md(d) for d in needs)})도 맞추고, 최소 생활비도 안 건드려요."

    # 다음 기간 예상 수입 안내
    s, e = spans[1]
    parts = [(i["name"], calc.incomes_sum(s, e, [i])) for i in incomes]
    parts = [(n, a) for n, a in parts if a > 0]
    total = sum(a for _, a in parts)
    result["income_note"] = (f"다음 기간은 예상 수입 {man(total)} 원"
                             f"({' + '.join(f'{n} {man(a)}' for n, a in parts)}) 기준이에요.")
    return result
