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
            "SELECT appt_id, appt_date, title, amount, transport_fare FROM appointments "
            "WHERE user_id = %s ORDER BY appt_date, appt_id",
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
            "SELECT comfort_daily, emergency_fund, hourly_wage FROM users WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchone()


def insert_period(conn, user_id, start, end, opening_balance):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO periods (user_id, start_date, end_date, opening_balance) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, start, end, opening_balance),
        )
    conn.commit()


def save_balance_log(conn, user_id, log_date, balance, income_in, spent):
    # 같은 날을 다시 적으면 덮어쓴다 (uq_user_date)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO balance_logs (user_id, log_date, balance, income_in, spent) "
            "VALUES (%s, %s, %s, %s, %s) AS new "
            "ON DUPLICATE KEY UPDATE balance = new.balance, income_in = new.income_in, "
            "spent = new.spent",
            (user_id, log_date, balance, income_in, spent),
        )
    conn.commit()


def update_opening_balance(conn, user_id, start_date, opening_balance):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE periods SET opening_balance = %s WHERE user_id = %s AND start_date = %s",
            (opening_balance, user_id, start_date),
        )
    conn.commit()


def insert_appointment(conn, user_id, appt_date, title, amount, transport_fare):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO appointments (user_id, appt_date, title, amount, transport_fare) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, appt_date, title, amount, transport_fare),
        )
    conn.commit()


def delete_appointment(conn, user_id, appt_id):
    # 남의 약속은 못 지우게 user_id도 같이 건다
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM appointments WHERE appt_id = %s AND user_id = %s",
            (appt_id, user_id),
        )
    conn.commit()


def get_user_id(conn, public_id):
    # 쿠키의 public_id로 user_id를 찾는다. 모르는 ID면 None
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE public_id = %s", (public_id,))
        row = cur.fetchone()
    return row["user_id"] if row else None


def create_account(conn, data, public_id, recovery_hash, start, end):
    # 첫 설정 저장: users -> incomes -> fixed_costs -> routines·routine_days -> periods
    # 한 트랜잭션이라 중간에 실패하면 전부 되돌린다
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (public_id, recovery_hash, comfort_daily, hourly_wage, "
                "emergency_fund) VALUES (%s, %s, %s, %s, %s)",
                (public_id, recovery_hash, data["comfort_daily"], data["hourly_wage"],
                 data["emergency_fund"]),
            )
            user_id = cur.lastrowid

            for i in data["incomes"]:
                cur.execute(
                    "INSERT INTO incomes (user_id, name, day_of_month, amount, is_main) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_id, i["name"], i["day_of_month"], i["amount"], i["is_main"]),
                )
            for f in data["fixed"]:
                cur.execute(
                    "INSERT INTO fixed_costs (user_id, name, day_of_month, amount) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, f["name"], f["day_of_month"], f["amount"]),
                )
            for r in data["routines"]:
                cur.execute(
                    "INSERT INTO routines (user_id, name, round_trip_fare, meals_out, "
                    "meal_price, start_date, end_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, r["name"], r["round_trip_fare"], r["meals_out"],
                     r["meal_price"], r["start_date"], r["end_date"]),
                )
                routine_id = cur.lastrowid
                for weekday in r["weekdays"]:
                    cur.execute(
                        "INSERT INTO routine_days (routine_id, weekday) VALUES (%s, %s)",
                        (routine_id, weekday),
                    )
            cur.execute(
                "INSERT INTO periods (user_id, start_date, end_date, opening_balance) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, start, end, data["balance"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return user_id


def get_wish_items(conn, user_id):
    # 아직 안 산 것(wish)만
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, name, price, need_by FROM wish_items "
            "WHERE user_id = %s AND status = 'wish' ORDER BY item_id",
            (user_id,),
        )
        return cur.fetchall()


def insert_wish_item(conn, user_id, name, price, need_by):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wish_items (user_id, name, price, need_by) VALUES (%s, %s, %s, %s)",
            (user_id, name, price, need_by),
        )
    conn.commit()
