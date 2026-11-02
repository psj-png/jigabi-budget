from datetime import date, timedelta

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import balance as balance_page
from app import calc, cart, queries, setup, split
from app.db import get_conn
from app.home import make_home

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

COOKIE_NAME = "jigabi_id"
# db/seed.sql 예시 사람의 public_id
SEED_PUBLIC_ID = "3f6b2a1c-7d4e-4b8a-9c2d-1e5f6a7b8c9d"


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


@app.get("/start")
def start(request: Request, today: str = None):
    return templates.TemplateResponse(request, "start.html", {"today_q": today})


@app.get("/demo")
def demo(today: str = None):
    # 예시 사람으로 둘러보기: 쿠키를 심고 홈으로
    response = RedirectResponse("/" + (f"?today={today}" if today else ""), status_code=303)
    set_login_cookie(response, SEED_PUBLIC_ID)
    return response


def set_login_cookie(response, public_id):
    response.set_cookie(COOKIE_NAME, public_id, httponly=True, samesite="lax",
                        max_age=365 * 24 * 3600)


# ---- 첫 설정 ----
def step1_values(form):
    # 1단계 칸에 채울 값. 처음엔 빈 칸, 검사에 걸려 다시 그릴 땐 적었던 값 그대로
    def at(name, i):
        items = form.getlist(name) if form else []
        return items[i] if i < len(items) else ""

    def one(name, default):
        return form.get(name, default) if form else default

    return {
        "balance": one("balance", ""),
        "incomes": [{"name": at("inc_name", i), "day": at("inc_day", i), "amount": at("inc_amount", i)}
                    for i in range(setup.INCOME_ROWS)],
        "main": one("main", ""),
        "fixed": [{"name": at("fix_name", i), "day": at("fix_day", i), "amount": at("fix_amount", i)}
                  for i in range(setup.FIXED_ROWS)],
        "comfort_daily": one("comfort_daily", "10000"),
        "hourly_wage": one("hourly_wage", "10320"),
        "emergency_fund": one("emergency_fund", "0"),
    }


def render_step1(request, form, today, error):
    return templates.TemplateResponse(request, "setup1.html", {
        "v": step1_values(form), "today_q": today, "error": error,
    })


def render_step2(request, form, data, now, today, error):
    def at(name, i):
        items = form.getlist(name)
        return items[i] if i < len(items) else ""

    rows = [{"name": at("r_name", i), "wds": form.getlist(f"r_wd_{i}"), "meals": at("r_meals", i),
             "price": at("r_price", i), "fare": at("r_fare", i), "start": at("r_start", i),
             "end": at("r_end", i)} for i in range(setup.ROUTINE_ROWS)]
    # 1단계 값은 hidden으로 다시 넣는다
    hidden = [(k, v) for k, v in form.multi_items() if k in setup.STEP1_FIELDS]
    return templates.TemplateResponse(request, "setup2.html", {
        "s": setup.summary(data, now), "rows": rows, "hidden": hidden,
        "today_q": today, "error": error,
    })


@app.get("/setup")
def setup_get(request: Request, today: str = None):
    parse_date(today, date.today())
    return render_step1(request, None, today, None)


@app.post("/setup/next")
async def setup_next(request: Request):
    form = await request.form()
    today = form.get("today") or None
    now = parse_date(today, date.today())
    try:
        data = setup.parse_step1(form)
    except setup.FormError as e:
        return render_step1(request, form, today, str(e))
    return render_step2(request, form, data, now, today, None)


@app.post("/setup/done")
async def setup_done(request: Request):
    form = await request.form()
    today = form.get("today") or None
    now = parse_date(today, date.today())
    # 두 단계를 다시 검사한다
    try:
        data = setup.parse_step1(form)
    except setup.FormError as e:
        return render_step1(request, form, today, str(e))
    try:
        data["routines"] = setup.parse_step2(form)
    except setup.FormError as e:
        return render_step2(request, form, data, now, today, str(e))

    conn = get_conn()
    try:
        user_id, public_id, code = setup.create_account(conn, data, now)
    finally:
        conn.close()
    # 복구 코드는 이 화면에서 한 번만 보여준다 (redirect 안 함)
    response = templates.TemplateResponse(request, "setup_done.html", {
        "code": code, "today_q": today,
    })
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


def check_day(target, now):
    # 밤 잔액은 오늘 또는 어제만 적을 수 있다
    if target not in (now, now - timedelta(days=1)):
        raise HTTPException(status_code=400, detail="오늘이나 어제만 적을 수 있어요")


@app.get("/")
def home(request: Request, today: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    # ?today=2026-10-30 으로 오늘 날짜를 고정할 수 있다 (없으면 진짜 오늘)
    day = parse_date(today, date.today())

    conn = get_conn()
    try:
        data = make_home(conn, user_id, day)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "home.html", {"h": data, "today_q": today})


def balance_view(request, form, now, today_q, error):
    return templates.TemplateResponse(request, "balance.html", {
        "f": form, "today": now, "yesterday": now - timedelta(days=1),
        "today_q": today_q, "today_q_and": f"&today={today_q}" if today_q else "",
        "error": error,
    })


@app.get("/balance")
def balance_get(request: Request, today: str = None, day: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        form = balance_page.get_form(conn, user_id, now, target)
    finally:
        conn.close()
    return balance_view(request, form, now, today, None)


@app.post("/balance")
def balance_post(request: Request, day: str = Form(), balance: int = Form(),
                 income_in: int = Form(0), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        message = balance_page.save(conn, user_id, now, target, balance, income_in)
        form = balance_page.get_form(conn, user_id, now, target) if message else None
    finally:
        conn.close()
    if message:
        return balance_view(request, form, now, today, message)
    # 저장하고 같은 today로 홈에 간다
    return RedirectResponse("/" + (f"?today={today}" if today else ""), status_code=303)


@app.get("/appointments")
def appointments_get(request: Request, today: str = None, day: str = None):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())
    target = parse_date(day, None)
    if target is not None and target < now:
        raise HTTPException(status_code=400, detail="오늘보다 앞선 날짜는 안 돼요")

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
    finally:
        conn.close()
    return templates.TemplateResponse(request, "appointments.html", {
        "appts": appts, "day": target, "fare": fare, "max_fare": max_fare,
        "today_q": today, "now": now,
    })


@app.post("/appointments")
def appointments_post(request: Request, day: str = Form(), title: str = Form(min_length=1, max_length=40),
                      amount: int = Form(ge=0), transport: str = Form(None),
                      transport_fare: int = Form(0, ge=0), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())
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
    return RedirectResponse("/appointments" + (f"?today={today}" if today else ""), status_code=303)


@app.post("/appointments/{appt_id}/delete")
def appointments_delete(request: Request, appt_id: int, today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    conn = get_conn()
    try:
        queries.delete_appointment(conn, user_id, appt_id)
    finally:
        conn.close()
    return RedirectResponse("/appointments" + (f"?today={today}" if today else ""), status_code=303)


@app.get("/cart")
def cart_get(request: Request, today: str = None, item: list[int] = Query(default=[])):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())

    conn = get_conn()
    try:
        data = cart.make_cart(conn, user_id, now, item)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "cart.html", {
        "c": data, "stages": cart.STAGES, "today_q": today,
    })


@app.post("/cart/items")
def cart_items_post(request: Request, name: str = Form(min_length=1, max_length=60),
                    price: int = Form(ge=1), need_by: str = Form(None), today: str = Form(None)):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())
    # 필요한 날은 오늘 이후거나 빈칸
    need = parse_date(need_by, None)
    if need is not None and need < now:
        raise HTTPException(status_code=400, detail="필요한 날은 오늘 이후여야 해요")

    conn = get_conn()
    try:
        queries.insert_wish_item(conn, user_id, name, price, need)
    finally:
        conn.close()
    return RedirectResponse("/cart" + (f"?today={today}" if today else ""), status_code=303)


@app.get("/split")
def split_get(request: Request, today: str = None, item: list[int] = Query(default=[])):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    now = parse_date(today, date.today())

    conn = get_conn()
    try:
        data = split.make_split(conn, user_id, now, item)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "split.html", {
        "s": data, "items": item, "today_q": today,
    })
