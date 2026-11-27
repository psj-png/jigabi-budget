import json
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import balance as balance_page
from app import ai, calc, cart, plan, purchase, queries, replan, settings, setup, shop, split
from app.db import get_conn
from app.home import make_home

COOKIE_NAME = "jigabi_id"
# db/seed.sql 예시 사람의 public_id
SEED_PUBLIC_ID = "3f6b2a1c-7d4e-4b8a-9c2d-1e5f6a7b8c9d"
# 예시 사람은 이 날로 고정해서 보여준다 (R16): seed 기간 10/30~11/24의 둘째 날
DEMO_TODAY = date(2026, 10, 31)


def is_demo(request):
    return request.cookies.get(COOKIE_NAME) == SEED_PUBLIC_ID


def drop_params(path, query, names):
    # 주소에서 몇몇 파라미터를 뺀다 (시트·띠를 닫을 때)
    keep = [p for p in query.split("&") if p and p.split("=")[0] not in names]
    return path + ("?" + "&".join(keep) if keep else "")


def page_extras(request):
    # 모든 화면 공통 값 (base.html): 예시로 보는 중 띠, '내 걸로 시작할까요?' 시트, 되돌리기 띠
    params = request.query_params
    url = request.url
    extras = {"demo": is_demo(request), "sheet_close": None, "toast": None,
              "toast_today": params.get("today")}
    if params.get("sheet") == "demo":
        extras["sheet_close"] = drop_params(url.path, url.query, ["sheet"])
    ids = [int(x) for x in params.get("ids", "").split(",") if x.isdigit()]
    back = drop_params(url.path, url.query, ["toast", "ids", "sheet"])
    kind = params.get("toast")
    if kind == "bought" and ids:
        extras["toast"] = {"text": "샀어요", "undo": "/cart/unbuy", "ids": ids, "back": back}
    elif kind == "returned" and ids:
        extras["toast"] = {"text": "반품했어요", "undo": f"/cart/{ids[0]}/unreturn", "ids": [], "back": back}
    elif kind == "saved":
        extras["toast"] = {"text": "저장했어요", "undo": None, "ids": [], "back": back}
    elif kind == "ready":
        extras["toast"] = {"text": "준비 끝! 기록은 이 기기에 저장돼요", "undo": None, "ids": [], "back": back}
    elif kind == "added":
        extras["toast"] = {"text": "장바구니에 담았어요", "undo": None, "ids": [], "back": back}
    elif kind == "planned":
        extras["toast"] = {"text": "계획을 바꿨어요. 홈과 장바구니에도 반영돼요", "undo": None, "ids": [], "back": back}
    elif kind == "undone":
        extras["toast"] = {"text": "계획을 되돌렸어요", "undo": None, "ids": [], "back": back}
    return extras


app = FastAPI()
templates = Jinja2Templates(directory="app/templates", context_processors=[page_extras])
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def current_user(request):
    # 쿠키의 public_id로 user_id를 찾는다. 쿠키가 없거나 모르는 ID면 None
    public_id = request.cookies.get(COOKIE_NAME)
    if not public_id:
        return None
    conn = get_conn()
    try:
        return queries.get_user_id(conn, public_id)
    finally:
        conn.close()


def to_start():
    return RedirectResponse("/start", status_code=303)


def demo_stop(request):
    # R16 예시 사람은 저장하지 않는다: 보던 화면으로 돌아가 '내 걸로 시작할까요?' 시트를 띄운다
    if not is_demo(request):
        return None
    ref = urlsplit(request.headers.get("referer", ""))
    path = ref.path if ref.path.startswith("/") and not ref.path.startswith("//") else "/"
    back = drop_params(path, ref.query, ["sheet", "toast", "ids"])
    return RedirectResponse(back + ("&" if "?" in back else "?") + "sheet=demo", status_code=303)


def safe_back(back, default):
    # 되돌아갈 주소는 이 사이트 안의 경로만
    if back and back.startswith("/") and not back.startswith("//"):
        return back
    return default


def url_with(path, today, **params):
    # 돌아갈 주소에 today와 다른 값을 붙인다 (None인 값은 뺀다)
    pairs = [f"today={today}"] if today else []
    pairs += [f"{k}={v}" for k, v in params.items() if v is not None]
    return path + ("?" + "&".join(pairs) if pairs else "")


# ---- 에러 화면: {"detail": ...} JSON 대신 화면으로 보여준다 ----
@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc):
    # 400은 우리가 쓴 한국어 문장 그대로, 그 밖에는 짧은 안내
    if exc.status_code == 400:
        message = exc.detail
    elif exc.status_code == 404:
        message = "없는 화면이에요"
    else:
        message = "요청을 처리하지 못했어요"
    return templates.TemplateResponse(request, "error.html", {"message": message},
                                      status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def form_error(request: Request, exc):
    # 폼 칸이 비었거나 범위를 벗어났을 때 (FastAPI가 Form() 검사에서 막은 것)
    return templates.TemplateResponse(request, "error.html", {"message": "입력한 값을 다시 확인해 주세요"},
                                      status_code=422)


# ---- 처음 (흐름 1) ----
@app.get("/start")
def start(request: Request, today: str = None):
    return templates.TemplateResponse(request, "start.html", {"today_q": today})


@app.get("/demo")
def demo(today: str = None):
    # 예시로 먼저 해 보기: 쿠키를 심고 홈으로 (날짜는 DEMO_TODAY로 고정된다)
    response = RedirectResponse("/" + (f"?today={today}" if today else ""), status_code=303)
    set_login_cookie(response, SEED_PUBLIC_ID)
    return response


def set_login_cookie(response, public_id):
    response.set_cookie(COOKIE_NAME, public_id, httponly=True, samesite="lax",
                        max_age=365 * 24 * 3600)


# ---- 첫 설정 (흐름 2): 다섯 단계, 칸은 예시로 채워 두고 고치게 한다 ----
def render_setup(request, d, step, today, error=None, editing=False):
    look = None
    if step == setup.LAST_STEP:
        try:
            look = setup.preview(setup.draft_data(d), parse_date(today, date.today()))
        except setup.FormError as e:
            return render_setup(request, d, 1, today, str(e))
    return templates.TemplateResponse(request, "setup_step.html", {
        "step": step, "d": d, "draft_json": json.dumps(d, ensure_ascii=False),
        "today_q": today, "error": error, "editing": editing, "look": look,
        "examples": setup.example_left(d), "example_incomes": setup.EXAMPLE_INCOMES,
        "example_fixed": setup.EXAMPLE_FIXED, "weekday_text": setup.weekday_text,
        "has_alba": any(r.get("name") == "알바" for r in d["routines"]),
        "rows_max": {"incomes": setup.INCOME_ROWS, "fixed": setup.FIXED_ROWS,
                     "routines": setup.ROUTINE_ROWS},
    })


@app.get("/setup")
def setup_get(request: Request, today: str = None):
    parse_date(today, date.today())
    return render_setup(request, setup.new_draft(), 1, today)


@app.post("/setup/step")
async def setup_step(request: Request):
    form = await request.form()
    today = form.get("today") or None
    parse_date(today, date.today())
    d = setup.load_draft(form.get("draft"))
    step = int(form.get("step")) if (form.get("step") or "").isdigit() else 1
    step = min(max(step, 1), setup.LAST_STEP)
    editing = form.get("editing") == "1"
    setup.take_step(d, form, step, editing)
    go = form.get("go") or "next"

    if go == "back":
        return render_setup(request, d, max(step - 1, 1), today)
    if go.startswith("to:") and go[3:].isdigit():
        # 5/5 확인 화면의 [고치기]
        return render_setup(request, d, min(max(int(go[3:]), 1), setup.LAST_STEP - 1), today)
    if go == "edit":
        return render_setup(request, d, 4, today, editing=True)
    if go == "no_fixed":
        setup.apply_op(d, go)
        return render_setup(request, d, 4, today)
    if go == "no_routine":
        setup.apply_op(d, go)
        return render_setup(request, d, setup.LAST_STEP, today)
    if go != "next":
        # 줄 더하기·빼기는 같은 단계에 머문다
        setup.apply_op(d, go)
        return render_setup(request, d, step, today, editing=editing or go == "add_routine")
    try:
        setup.check_step(d, step)
    except setup.FormError as e:
        return render_setup(request, d, step, today, str(e), editing)
    return render_setup(request, d, min(step + 1, setup.LAST_STEP), today)


@app.post("/setup/done")
async def setup_done(request: Request):
    form = await request.form()
    today = form.get("today") or None
    now = parse_date(today, date.today())
    d = setup.load_draft(form.get("draft"))
    try:
        data = setup.draft_data(d)
    except setup.FormError as e:
        return render_setup(request, d, 1, today, str(e))

    conn = get_conn()
    try:
        user_id, public_id = setup.create_account(conn, data, now)
    finally:
        conn.close()
    # 완료하면 바로 홈으로 ('준비 끝' 띠). 기록은 이 브라우저 쿠키에만 묶인다 (R19)
    response = RedirectResponse(url_with("/", today, toast="ready"), status_code=303)
    set_login_cookie(response, public_id)
    return response


def parse_date(text, default):
    # 2026-10-30 모양이 아니면 400
    if not text:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜는 2026-10-30 모양이어야 해요")


def pick_now(request, today):
    # ?today=가 있으면 그날, 예시 사람이면 DEMO_TODAY, 아니면 진짜 오늘
    if not today and is_demo(request):
        return DEMO_TODAY
    return parse_date(today, date.today())


def check_day(target, now):
    # 밤 잔액은 오늘 또는 어제만 적을 수 있다
    if target not in (now, now - timedelta(days=1)):
        raise HTTPException(status_code=400, detail="오늘이나 어제만 적을 수 있어요")


# ---- 홈 (흐름 3): 그 자리에서 끝내게 ----
def pick_card_day(conn, user_id, now, day, fixed_day):
    # 밤 잔액 카드가 볼 날: ?day= > 오늘 기록이 있으면 오늘 > 오전에 어젯밤이 비었으면 어젯밤 > 오늘
    if day:
        target = parse_date(day, now)
        check_day(target, now)
        return target
    if queries.get_balance_log(conn, user_id, now) is not None:
        return now
    yesterday = now - timedelta(days=1)
    # 날짜를 고정해 보는 중(?today=, 예시)에는 시각을 따지지 않는다
    if (not fixed_day and datetime.now().hour < 12
            and queries.get_balance_log(conn, user_id, yesterday) is None
            and queries.get_period(conn, user_id, yesterday) is not None):
        return yesterday
    return now


def render_home(request, user_id, now, today, day=None, mode=None, guess=None, edit=False, error=None):
    conn = get_conn()
    try:
        data = make_home(conn, user_id, now)
        card = summary = None
        wish_count = 0
        if data["ready"]:
            target = pick_card_day(conn, user_id, now, day, bool(today) or is_demo(request))
            card = balance_page.make_card(conn, user_id, now, target, mode, guess, edit, error)
            wish_count = len(queries.get_wish_items(conn, user_id))
            if data["end"] == now:
                # 기간 끝 카드 (18): 이번 기간 기록 요약
                logs = queries.get_balance_logs(conn, user_id, data["period_start"], now)
                summary = {"days": (now - data["period_start"]).days + 1, "nights": len(logs),
                           "spent": sum(log["spent"] for log in logs)}
    finally:
        conn.close()
    return templates.TemplateResponse(request, "home.html", {
        "h": data, "card": card, "summary": summary, "wish_count": wish_count, "today_q": today,
        "ai_on": ai.enabled(),
    })


@app.get("/")
def home(request: Request, today: str = None, day: str = None, mode: str = None,
         guess: str = None, edit: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    # ?today=2026-10-30 으로 오늘 날짜를 고정할 수 있다 (없으면 진짜 오늘, 예시 사람은 DEMO_TODAY)
    now = pick_now(request, today)
    guess_value = int(guess) if guess and guess.lstrip("-").isdigit() else None
    return render_home(request, user_id, now, today, day, mode, guess_value, edit == "1")


@app.get("/balance")
def balance_get(today: str = None, day: str = None):
    # 밤 잔액은 홈 맨 아래 카드에서 적는다 (흐름 3)
    return RedirectResponse(url_with("/", today, day=day) + "#tonight", status_code=303)


@app.post("/balance")
def balance_post(request: Request, day: str = Form(), balance: int = Form(),
                 income_in: int = Form(0), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        message = balance_page.save(conn, user_id, now, target, balance, income_in)
    finally:
        conn.close()
    if message:
        return render_home(request, user_id, now, today, str(target), error=message)
    # 결과는 홈 카드가 그 자리에서 보여준다 (14)
    return RedirectResponse(url_with("/", today, day=None if target == now else target) + "#tonight",
                            status_code=303)


@app.post("/balance/spent")
def balance_spent(request: Request, day: str = Form(), spent: int = Form(ge=0),
                  today: str = Form(None)):
    # 잔액을 모를 때 (15): 쓴 돈으로 잔액을 거꾸로 구해 '맞나요?'로 묻는다 (R10-1)
    # 계산만 하고 저장은 안 하니 예시 사람도 해 볼 수 있다
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        guess = balance_page.guess_balance(conn, user_id, target, spent)
    finally:
        conn.close()
    if guess is None:
        raise HTTPException(status_code=400, detail=balance_page.NO_PERIOD)
    return RedirectResponse(url_with("/", today, day=target, guess=guess[0]) + "#tonight", status_code=303)


# ---- 약속 (흐름 5) ----
@app.get("/appointments")
def appointments_get(request: Request, today: str = None, day: str = None, amount: str = None,
                     title: str = "", transport: str = None, transport_fare: str = None,
                     preview: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)
    target = parse_date(day, None)
    if target is not None and target < now:
        raise HTTPException(status_code=400, detail="오늘보다 앞선 날짜는 안 돼요")
    # 미리보기 칸이 빈칸이거나 숫자가 아니면 없는 것으로 본다
    amount = int(amount) if amount and amount.isdigit() else None
    transport_fare = int(transport_fare) if transport_fare and transport_fare.isdigit() else None

    conn = get_conn()
    try:
        appts = [a for a in queries.get_appointments(conn, user_id) if a["appt_date"] >= now]
        # 2단계: 날짜를 고르면 그날 교통비 기본값(R9)을 채워 보여준다
        # 체크는 그날 가는 곳이 없을 때만 켜고, 금액 칸은 항상 가장 큰 왕복 교통비
        fare = None
        max_fare = 0
        if target is not None:
            routines = queries.get_routines(conn, user_id)
            fare = calc.transport_default(target, routines)
            max_fare = calc.max_fare(routines)

        # 금액이 정해졌으면 넣은 뒤 하루 여유를 미리 본다 (R11과 같은 calc.preview)
        # 교통비 체크는 [미리보기]로 온 경우 그 상태, 금액 칩으로 온 경우 기본값
        transport_on = (transport is not None) if preview else (fare is not None and fare > 0)
        fare_amount = (transport_fare if transport_fare is not None else max_fare) if transport_on else 0
        look = None
        if target is not None and amount is not None and amount >= 0:
            h = make_home(conn, user_id, now)
            if h["ready"] and h["daily"] is not None:
                comfort = queries.get_user(conn, user_id)["comfort_daily"]
                first = now + timedelta(days=1) if h["logged"] else now
                # 이번 기간(남은 날) 안의 약속만 이번 여유 돈에서 빠진다
                counted = first <= target <= h["end"]
                if counted:
                    daily, stage, _ = calc.preview(h["free"], h["days_left"], amount + fare_amount, comfort)
                else:
                    daily, stage = h["daily"], h["stage"]
                look = {"now_daily": h["daily"], "now_stage": h["stage"],
                        "daily": daily, "stage": stage, "counted": counted}
    finally:
        conn.close()
    return templates.TemplateResponse(request, "appointments.html", {
        "appts": appts, "day": target, "fare": fare, "max_fare": max_fare,
        "today_q": today, "now": now, "amount": amount, "title": title,
        "transport_on": transport_on, "fare_amount": fare_amount, "look": look,
    })


@app.post("/appointments")
def appointments_post(request: Request, day: str = Form(), title: str = Form(min_length=1, max_length=40),
                      amount: int = Form(ge=0), transport: str = Form(None),
                      transport_fare: int = Form(0, ge=0), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    target = parse_date(day, None)
    if target is None or target < now:
        raise HTTPException(status_code=400, detail="오늘보다 앞선 날짜는 안 돼요")

    # 체크를 끄면 교통비 0
    fare = transport_fare if transport else 0
    conn = get_conn()
    try:
        queries.insert_appointment(conn, user_id, target, title, amount, fare)
    finally:
        conn.close()
    return RedirectResponse(url_with("/appointments", today), status_code=303)


@app.post("/appointments/{appt_id}/delete")
def appointments_delete(request: Request, appt_id: int, today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    conn = get_conn()
    try:
        queries.delete_appointment(conn, user_id, appt_id)
    finally:
        conn.close()
    return RedirectResponse(url_with("/appointments", today), status_code=303)


# ---- 장바구니·나눠 사기·다시 짜기 (흐름 4) ----
@app.get("/cart")
def cart_get(request: Request, today: str = None, item: list[int] = Query(default=[]),
             cap_name: str = None, cap_price: str = None, cap_err: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)

    conn = get_conn()
    try:
        data = cart.make_cart(conn, user_id, now, item)
    finally:
        conn.close()
    # 캡처로 읽은 값 (R20): 추가 칸에 채워 보여주기만 한다
    cap = None
    if cap_name or cap_price or cap_err:
        cap = {"name": (cap_name or "")[:60], "price": cap_price if (cap_price or "").isdigit() else "",
               "error": ai.ERRORS.get(cap_err)}
    return templates.TemplateResponse(request, "cart.html", {
        "c": data, "stages": cart.STAGES, "today_q": today, "now": now,
        "cap": cap, "ai_on": ai.enabled(),
    })


@app.post("/cart/capture")
async def cart_capture(request: Request, shot: UploadFile = File(...), today: str = Form(None)):
    # 캡처로 상품 담기 (R20): AI가 이름·가격을 읽어 추가 칸에 채운다. 저장은 [추가]를 눌러야 해서 예시도 해 볼 수 있다
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    if not ai.enabled():
        raise HTTPException(status_code=404)
    data = await shot.read(ai.MAX_BYTES + 1)
    found, error = ai.read_item(data)
    params = {"today": today} if today else {}
    if error:
        params["cap_err"] = error
    else:
        params.update(cap_name=found["name"] or "", cap_price=found["price"] or "")
    return RedirectResponse("/cart?" + urlencode(params) + "#add", status_code=303)


@app.post("/cart/items")
def cart_items_post(request: Request, name: str = Form(min_length=1, max_length=60),
                    price: int = Form(ge=1), need_by: str = Form(None), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    # 필요한 날은 오늘 이후거나 빈칸
    need = parse_date(need_by, None)
    if need is not None and need < now:
        raise HTTPException(status_code=400, detail="필요한 날은 오늘 이후여야 해요")

    conn = get_conn()
    try:
        queries.insert_wish_item(conn, user_id, name, price, need)
    finally:
        conn.close()
    return RedirectResponse(url_with("/cart", today), status_code=303)


@app.get("/split")
def split_get(request: Request, today: str = None, item: list[int] = Query(default=[])):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)

    conn = get_conn()
    try:
        data = split.make_split(conn, user_id, now, item)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "split.html", {
        "s": data, "items": item, "today_q": today,
    })


@app.post("/cart/buy")
def cart_buy(request: Request, item: list[int] = Form(default=[]), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)

    conn = get_conn()
    try:
        count = purchase.buy_now(conn, user_id, item, now)
        h = make_home(conn, user_id, now)
    finally:
        conn.close()
    # 산 뒤에는 [되돌리기] 띠를 띄운다 (19)
    toast = "bought" if count else None
    ids = ",".join(str(i) for i in item) if count else None
    # 산 뒤 여유 돈이 0 미만이면 다시 짜기로 (R14)
    if h["ready"] and h["free"] < 0:
        return RedirectResponse(url_with("/replan", today, toast=toast, ids=ids), status_code=303)
    return RedirectResponse(url_with("/", today, toast=toast, ids=ids), status_code=303)


@app.post("/cart/unbuy")
def cart_unbuy(request: Request, item: list[int] = Form(default=[]), today: str = Form(None)):
    # 되돌리기 (19): 방금 산 것을 사기 전으로 돌리고 장바구니로
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    conn = get_conn()
    try:
        purchase.unbuy_items(conn, user_id, item, now)
    finally:
        conn.close()
    return RedirectResponse(url_with("/cart", today), status_code=303)


@app.post("/cart/{item_id}/return")
def cart_return(request: Request, item_id: int, today: str = Form(None), back: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)

    conn = get_conn()
    try:
        done = purchase.return_item(conn, user_id, item_id, now)
    finally:
        conn.close()
    if not done:
        raise HTTPException(status_code=400, detail="반품할 수 없어요 (산 날 빼고 7일 안, 산 것만)")
    # 확인 화면 대신 [되돌리기] 띠 (22). 다시 짜기 화면에서 반품했으면 그 화면으로
    page = "/replan" if back == "replan" else "/cart"
    return RedirectResponse(url_with(page, today, toast="returned", ids=item_id), status_code=303)


@app.post("/cart/{item_id}/unreturn")
def cart_unreturn(request: Request, item_id: int, today: str = Form(None), back: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    conn = get_conn()
    try:
        purchase.unreturn_item(conn, user_id, item_id, now)
    finally:
        conn.close()
    return RedirectResponse(safe_back(back, url_with("/cart", today)), status_code=303)


@app.post("/cart/{item_id}/unplan")
def cart_unplan(request: Request, item_id: int, today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop

    conn = get_conn()
    try:
        done = purchase.unplan_item(conn, user_id, item_id)
    finally:
        conn.close()
    if not done:
        raise HTTPException(status_code=400, detail="취소할 계획이 없어요")
    return RedirectResponse(url_with("/cart", today), status_code=303)


@app.get("/replan")
def replan_get(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)

    conn = get_conn()
    try:
        data = replan.make_replan(conn, user_id, now)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "replan.html", {"r": data, "today_q": today, "now": now})


@app.post("/replan")
async def replan_post(request: Request):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    form = await request.form()
    today = form.get("today") or None
    now = pick_now(request, today)

    # cut_<약속 id> 칸 중 '적용'을 체크한 것만 모은다
    cuts = {}
    for key in form.keys():
        if not key.startswith("cut_") or form.get("apply_" + key[4:]) is None:
            continue
        try:
            cuts[int(key[4:])] = int(form.get(key))
        except ValueError:
            raise HTTPException(status_code=400, detail="줄일 금액은 숫자여야 해요")

    conn = get_conn()
    try:
        error = replan.save_replan(conn, user_id, now, cuts)
    finally:
        conn.close()
    if error:
        raise HTTPException(status_code=400, detail=error)
    return RedirectResponse(url_with("/", today), status_code=303)


@app.post("/split/save")
def split_save(request: Request, item: list[int] = Form(default=[]), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)

    conn = get_conn()
    try:
        done = purchase.save_split(conn, user_id, now, item)
    finally:
        conn.close()
    if not done:
        raise HTTPException(status_code=400, detail="저장할 계획이 없어요")
    return RedirectResponse(url_with("/", today), status_code=303)


# ---- 지갑이 채팅: 무신사 쇼핑 추천 (R21). 키가 없으면 없는 화면 ----
@app.get("/chat")
def chat_get(request: Request, today: str = None, mode: str = "shop"):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    if not ai.enabled():
        raise HTTPException(status_code=404)
    now = pick_now(request, today)
    conn = get_conn()
    try:
        data = shop.make_chat(conn, user_id, now)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "chat.html", {
        "chat": data, "today_q": today, "mode": "plan" if mode == "plan" else "shop",
        "plan_starters": plan.STARTERS,
    })


@app.post("/chat")
async def chat_post(request: Request):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    if not ai.enabled():
        raise HTTPException(status_code=404)
    stop = demo_stop(request)  # 예시 사람은 대화를 저장하지 않는다 (R16)
    if stop:
        return stop
    form = await request.form()
    today = form.get("today") or None
    now = pick_now(request, today)
    image = None
    shot = form.get("shot")
    if shot is not None and hasattr(shot, "read"):
        image = await shot.read(ai.MAX_BYTES + 1) or None
    mode = "plan" if form.get("mode") == "plan" else "shop"
    conn = get_conn()
    try:
        if mode == "plan":
            plan.ask(conn, user_id, now, form.get("text"))
        else:
            shop.ask(conn, user_id, now, form.get("text"), image)
    finally:
        conn.close()
    return RedirectResponse(url_with("/chat", today, mode=mode) + "#last", status_code=303)


@app.post("/chat/add")
def chat_add(request: Request, name: str = Form(min_length=1, max_length=60), price: int = Form(ge=1),
             url: str = Form(""), today: str = Form(None)):
    # 추천 카드의 [장바구니에 담기]: 무신사 링크까지 같이 담는다
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    conn = get_conn()
    try:
        queries.insert_wish_item(conn, user_id, name, price, None, url[:500] if ai.is_shop_url(url) else None)
    finally:
        conn.close()
    return RedirectResponse(url_with("/chat", today, toast="added") + "#last", status_code=303)


@app.post("/plan/apply")
def plan_apply(request: Request, message_id: int = Form(), today: str = Form(None)):
    # 계획 도우미 제안의 [이대로 적용] (R22): 저장하면 모든 화면이 같은 계산으로 따라 바뀐다
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    conn = get_conn()
    try:
        done = plan.apply(conn, user_id, now, message_id)
    finally:
        conn.close()
    if not done:
        raise HTTPException(status_code=400, detail="적용할 수 있는 제안이 없어요")
    return RedirectResponse(url_with("/chat", today, mode="plan", toast="planned") + "#last", status_code=303)


@app.post("/plan/changes/{change_id}/delete")
def plan_undo(request: Request, change_id: int, today: str = Form(None)):
    # 홈 '지갑이와 바꾼 계획'의 [되돌리기]
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    conn = get_conn()
    try:
        queries.delete_plan_change(conn, user_id, change_id)
    finally:
        conn.close()
    return RedirectResponse(url_with("/", today, toast="undone"), status_code=303)


# ---- 설정 (흐름 6) ----
MONEY_KINDS = {"incomes": "돈 들어오는 날", "fixed": "고정비"}
NO_MAIN_DELETE = "기간 기준인 돈은 뺄 수 없어요. 다른 걸 기간 기준으로 고른 뒤 빼 주세요"


def saved(path, today):
    # 고친 뒤에는 그 화면으로 돌아가 '저장했어요' 띠를 띄운다
    return RedirectResponse(url_with(path, today, toast="saved"), status_code=303)


@app.get("/settings")
def settings_home(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)
    conn = get_conn()
    try:
        s = settings.make_settings(conn, user_id, now)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "settings.html", {"s": s, "today_q": today})


def money_view(request, user_id, kind, today, error=None):
    conn = get_conn()
    try:
        rows = queries.list_incomes(conn, user_id) if kind == "incomes" else queries.list_fixed(conn, user_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "settings_money.html", {
        "kind": kind, "title": MONEY_KINDS[kind], "rows": rows, "error": error, "today_q": today,
    })


@app.get("/settings/incomes")
def settings_incomes(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    return money_view(request, user_id, "incomes", today)


@app.get("/settings/fixed")
def settings_fixed(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    return money_view(request, user_id, "fixed", today)


@app.post("/settings/money/{kind}/add")
async def money_add(request: Request, kind: str):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    if kind not in MONEY_KINDS:
        raise HTTPException(status_code=404)
    form = await request.form()
    today = form.get("today") or None
    try:
        name, day, amount = settings.money_row(form, MONEY_KINDS[kind])
    except setup.FormError as e:
        return money_view(request, user_id, kind, today, str(e))
    conn = get_conn()
    try:
        if kind == "incomes":
            queries.insert_income(conn, user_id, name, day, amount)
        else:
            queries.insert_fixed(conn, user_id, name, day, amount)
    finally:
        conn.close()
    return saved(f"/settings/{kind}", today)


@app.post("/settings/money/incomes/{row_id}/main")
def money_main(request: Request, row_id: int, today: str = Form(None)):
    # 기간 기준 바꾸기: 지금 기간은 그대로, 다음 기간부터 새 날짜로 끊는다 (R15)
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    conn = get_conn()
    try:
        queries.set_main_income(conn, user_id, row_id)
    finally:
        conn.close()
    return saved("/settings/incomes", today)


@app.post("/settings/money/{kind}/{row_id}/delete")
def money_delete(request: Request, kind: str, row_id: int, today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    if kind not in MONEY_KINDS:
        raise HTTPException(status_code=404)
    conn = get_conn()
    try:
        if kind == "incomes":
            done = queries.delete_income(conn, user_id, row_id)
        else:
            queries.delete_fixed(conn, user_id, row_id)
            done = True
    finally:
        conn.close()
    if not done:
        return money_view(request, user_id, kind, today, NO_MAIN_DELETE)
    return saved(f"/settings/{kind}", today)


@app.post("/settings/money/{kind}/{row_id}")
async def money_update(request: Request, kind: str, row_id: int):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    if kind not in MONEY_KINDS:
        raise HTTPException(status_code=404)
    form = await request.form()
    today = form.get("today") or None
    try:
        name, day, amount = settings.money_row(form, MONEY_KINDS[kind])
    except setup.FormError as e:
        return money_view(request, user_id, kind, today, str(e))
    conn = get_conn()
    try:
        if kind == "incomes":
            queries.update_income(conn, user_id, row_id, name, day, amount)
        else:
            queries.update_fixed(conn, user_id, row_id, name, day, amount)
    finally:
        conn.close()
    return saved(f"/settings/{kind}", today)


def places_view(request, user_id, now, today, error=None):
    conn = get_conn()
    try:
        p = settings.make_places(conn, user_id, now)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "settings_places.html", {
        "p": p, "now": now, "error": error, "today_q": today, "weekday_text": setup.weekday_text,
    })


@app.get("/settings/places")
def settings_places(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    return places_view(request, user_id, pick_now(request, today), today)


@app.post("/settings/places/add")
async def place_add(request: Request):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    form = await request.form()
    today = form.get("today") or None
    now = pick_now(request, today)
    try:
        r = settings.parse_place(form)
    except setup.FormError as e:
        return places_view(request, user_id, now, today, str(e))
    conn = get_conn()
    try:
        settings.add_place(conn, user_id, r, now)
    finally:
        conn.close()
    return saved("/settings/places", today)


@app.post("/settings/places/{routine_id}/end")
def place_end(request: Request, routine_id: int, today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    now = pick_now(request, today)
    conn = get_conn()
    try:
        settings.end_place(conn, user_id, routine_id, now)
    finally:
        conn.close()
    return saved("/settings/places", today)


@app.post("/settings/places/{routine_id}")
async def place_edit(request: Request, routine_id: int):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    form = await request.form()
    today = form.get("today") or None
    now = pick_now(request, today)
    try:
        r = settings.parse_place(form)
    except setup.FormError as e:
        return places_view(request, user_id, now, today, str(e))
    conn = get_conn()
    try:
        settings.edit_place(conn, user_id, routine_id, r, now)
    finally:
        conn.close()
    return saved("/settings/places", today)


@app.get("/settings/numbers")
def settings_numbers(request: Request, today: str = None, error: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    conn = get_conn()
    try:
        user = queries.get_user(conn, user_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "settings_numbers.html", {
        "user": user, "error": None, "today_q": today,
    })


@app.post("/settings/numbers")
async def numbers_post(request: Request):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    form = await request.form()
    today = form.get("today") or None
    conn = get_conn()
    try:
        try:
            comfort, wage, fund = settings.parse_numbers(form)
        except setup.FormError as e:
            return templates.TemplateResponse(request, "settings_numbers.html", {
                "user": queries.get_user(conn, user_id), "error": str(e), "today_q": today,
            })
        queries.update_user_numbers(conn, user_id, comfort, wage, fund)
    finally:
        conn.close()
    return saved("/settings/numbers", today)


@app.get("/settings/history")
def settings_history(request: Request, today: str = None, start: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = pick_now(request, today)
    conn = get_conn()
    try:
        hist = settings.make_history(conn, user_id, now, parse_date(start, None))
    finally:
        conn.close()
    return templates.TemplateResponse(request, "settings_history.html", {"hist": hist, "today_q": today})


@app.get("/settings/delete")
def settings_delete(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    return templates.TemplateResponse(request, "settings_delete.html", {"today_q": today})


@app.post("/settings/delete")
def settings_delete_post(request: Request, today: str = Form(None)):
    # 되돌릴 수 없는 일이라 여기만 확인 화면을 둔다 (30)
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    stop = demo_stop(request)
    if stop:
        return stop
    conn = get_conn()
    try:
        settings.delete_account(conn, user_id)
    finally:
        conn.close()
    response = RedirectResponse(url_with("/start", today), status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
