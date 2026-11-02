# 장바구니 미리보기: make_home의 여유 돈에서 고른 물건 값을 빼 본다 (R11)
from app import calc, queries
from app.home import make_home

STAGES = ["빵빵", "든든", "홀쭉", "텅텅", "나방"]


def eul_reul(name):
    # 이름 끝 글자에 받침이 있으면 '을', 없으면 '를'
    last = name[-1]
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 == 0:
        return "를"
    return "을"


def make_cart(conn, user_id, today, selected):
    # selected: 체크한 item_id 목록
    h = make_home(conn, user_id, today)
    if not h["ready"]:
        return {"ready": False}

    user = queries.get_user(conn, user_id)
    wishes = queries.get_wish_items(conn, user_id)
    all_items = queries.get_items(conn, user_id)
    ended = h["daily"] is None  # 남은 날 0: 기간 마지막 날 밤

    items = []
    for w in wishes:
        chip = None
        if not ended:
            # 그것 하나만 샀을 때 단계
            chip = calc.preview(h["free"], h["days_left"], w["price"], user["comfort_daily"])[1]
        items.append({"id": w["item_id"], "name": w["name"], "price": w["price"],
                      "need_by": w["need_by"], "chip": chip, "checked": w["item_id"] in selected})

    # 계획한 것(예: 11/25에 사기로 함)과 최근 산 것(반품할 수 있는 것)
    planned = [i for i in all_items if i["status"] == "planned"]
    recent = [i for i in all_items if i["status"] == "bought" and calc.can_return(i["bought_date"], today)]

    cart = {"ready": True, "planned": planned, "recent": recent, "logged": h["logged"], "ended": ended, "items": items, "now": h["stage"], "now_daily": h["daily"], "after": None,
            "hours": None, "shortage": None, "message": None, "hours_text": None}
    if ended:
        cart["message"] = "이번 기간이 끝났어요. 새 기간에 다시 봐요"
        return cart

    chosen = [i for i in items if i["checked"]]
    if not chosen:
        cart["message"] = "담은 걸 체크하면 사면 어떻게 되는지 보여줘요"
        return cart

    price_sum = sum(i["price"] for i in chosen)
    daily, stage, short = calc.preview(h["free"], h["days_left"], price_sum, user["comfort_daily"])
    cart["after"] = {"daily": daily, "stage": stage, "short": short}

    first = chosen[0]["name"]
    if len(chosen) == 1:
        what = f"{first}{eul_reul(first)}"
    else:
        what = f"{first} 외 {len(chosen) - 1}개를"
    cart["message"] = f"지금은 {h['stage']}인데, {what} 사면 {stage}이 나와요"
    if short > 0:
        cart["shortage"] = f"최소 생활비를 {short:,}원 건드려요"

    cart["hours"] = calc.work_hours(price_sum, user["hourly_wage"])
    if cart["hours"] is not None:
        cart["hours_text"] = f"= 알바 약 {cart['hours']}시간"
    return cart
