from datetime import date, timedelta

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import balance as balance_page
from app.db import get_conn
from app.home import make_home

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


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
    # ?today=2026-10-30 으로 오늘 날짜를 고정할 수 있다 (없으면 진짜 오늘)
    day = parse_date(today, date.today())

    # 지금은 예시 사람(1번)만 보여줌
    conn = get_conn()
    try:
        data = make_home(conn, 1, day)
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
    now = parse_date(today, date.today())
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        form = balance_page.get_form(conn, 1, now, target)
    finally:
        conn.close()
    return balance_view(request, form, now, today, None)


@app.post("/balance")
def balance_post(request: Request, day: str = Form(), balance: int = Form(),
                 income_in: int = Form(0), today: str = Form(None)):
    now = parse_date(today, date.today())
    target = parse_date(day, now)
    check_day(target, now)

    conn = get_conn()
    try:
        message = balance_page.save(conn, 1, now, target, balance, income_in)
        form = balance_page.get_form(conn, 1, now, target) if message else None
    finally:
        conn.close()
    if message:
        return balance_view(request, form, now, today, message)
    # 저장하고 같은 today로 홈에 간다
    return RedirectResponse("/" + (f"?today={today}" if today else ""), status_code=303)


@app.get("/wishes")
def wishes(request: Request):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, price, need_by FROM wish_items WHERE user_id = %s", (1,))
            items = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "index.html", {"items": items})
