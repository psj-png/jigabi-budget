# DB에서 읽어서 calc.py가 받는 모양(dict 리스트)으로 돌려준다
# 모든 함수는 conn(get_conn())과 user_id를 받는다


def get_routines(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT routine_id, round_trip_fare, meals_out, meal_price, start_date, end_date "
            "FROM routines WHERE user_id = %s",
            (user_id,),
        )
        routines = cur.fetchall()
        # 요일은 routine_days에 따로 있어서 한 번에 읽어 붙인다
        cur.execute(
            "SELECT d.routine_id, d.weekday FROM routine_days d "
            "JOIN routines r ON r.routine_id = d.routine_id WHERE r.user_id = %s",
            (user_id,),
        )
        days = cur.fetchall()

    for r in routines:
        r["weekdays"] = [d["weekday"] for d in days if d["routine_id"] == r["routine_id"]]
    return routines


def get_incomes(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT day_of_month, amount, is_main FROM incomes WHERE user_id = %s",
            (user_id,),
        )
        incomes = cur.fetchall()
    for i in incomes:
        i["is_main"] = bool(i["is_main"])
    return incomes


def get_fixed_costs(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT day_of_month, amount FROM fixed_costs WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchall()


def get_appointments(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appt_date, amount, transport_fare FROM appointments WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchall()


def get_period(conn, user_id, today):
    # today가 들어 있는 기간. 없으면 None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT start_date, end_date, opening_balance, repay_amount FROM periods "
            "WHERE user_id = %s AND start_date <= %s AND end_date >= %s "
            "ORDER BY start_date DESC LIMIT 1",
            (user_id, today, today),
        )
        return cur.fetchone()


def get_balance_log(conn, user_id, day):
    # 그날 밤 잔액 행. 기록이 없으면 None (있는지만 볼 때는 `is not None`)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT log_date, balance, income_in, spent FROM balance_logs "
            "WHERE user_id = %s AND log_date = %s",
            (user_id, day),
        )
        return cur.fetchone()


def get_latest_balance_log(conn, user_id, today):
    # today 이전(오늘 포함) 기록 중 가장 최근 것. 없으면 None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT log_date, balance, income_in, spent FROM balance_logs "
            "WHERE user_id = %s AND log_date <= %s ORDER BY log_date DESC LIMIT 1",
            (user_id, today),
        )
        return cur.fetchone()


def get_user(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT comfort_daily, emergency_fund FROM users WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchone()
