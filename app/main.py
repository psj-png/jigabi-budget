from datetime import date, timedelta

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import balance as balance_page
from app import calc, queries
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
    response.set_cookie(COOKIE_NAME, SEED_PUBLIC_ID, httponly=True, samesite="lax",
                        max_age=365 * 24 * 3600)
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


@app.get("/wishes")
def wishes(request: Request):
    user_id = current_user(request)
    if user_id is None:
        return to_start()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, price, need_by FROM wish_items WHERE user_id = %s", (user_id,))
            items = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "index.html", {"items": items})
