# DB에서 읽어서 calc.py가 받는 모양(dict 리스트)으로 돌려준다
# 모든 함수는 conn(get_conn())과 user_id를 받는다


def get_routines(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT routine_id, name, round_trip_fare, meals_out, meal_price, start_date, end_date "
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
            "SELECT name, day_of_month, amount, is_main FROM incomes WHERE user_id = %s",
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


def get_prev_period(conn, user_id, before):
    # before보다 앞서 시작한 가장 가까운 기간. 없으면 None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT start_date, end_date FROM periods "
            "WHERE user_id = %s AND start_date < %s ORDER BY start_date DESC LIMIT 1",
            (user_id, before),
        )
        return cur.fetchone()


def insert_period(conn, user_id, start, end, opening_balance, repay_amount=0):
    # 갚을 돈(repay_amount)은 비상금으로 돌려놓은 것으로 보고 같이 더한다
    # 같은 기간이 이미 있으면 IGNORE로 넘어가고(줄 수 0), 그땐 갚은 돈도 다시 더하지 않는다
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO periods (user_id, start_date, end_date, opening_balance, repay_amount) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, start, end, opening_balance, repay_amount),
            )
            if repay_amount and cur.rowcount:
                cur.execute(
                    "UPDATE users SET emergency_fund = emergency_fund + %s WHERE user_id = %s",
                    (repay_amount, user_id),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_loans(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT loan_id, borrowed_on, amount FROM loans WHERE user_id = %s ORDER BY loan_id",
            (user_id,),
        )
        return cur.fetchall()


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


def create_account(conn, data, public_id, start, end):
    # 첫 설정 저장: users -> incomes -> fixed_costs -> routines·routine_days -> periods
    # 한 트랜잭션이라 중간에 실패하면 전부 되돌린다
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (public_id, comfort_daily, hourly_wage, emergency_fund) "
                "VALUES (%s, %s, %s, %s)",
                (public_id, data["comfort_daily"], data["hourly_wage"], data["emergency_fund"]),
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
            "SELECT item_id, name, price, need_by, url FROM wish_items "
            "WHERE user_id = %s AND status = 'wish' ORDER BY item_id",
            (user_id,),
        )
        return cur.fetchall()


def insert_wish_item(conn, user_id, name, price, need_by, url=None):
    # url: 채팅에서 담은 무신사 상품 링크 (없으면 NULL)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wish_items (user_id, name, price, need_by, url) VALUES (%s, %s, %s, %s, %s)",
            (user_id, name, price, need_by, url),
        )
    conn.commit()


def get_items(conn, user_id):
    # 상태와 날짜까지 모두 (산 것, 계획한 것, 반품한 것 포함)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, name, price, need_by, status, planned_date, bought_date, "
            "received_date, returned_date FROM wish_items WHERE user_id = %s ORDER BY item_id",
            (user_id,),
        )
        return cur.fetchall()


# 아래 네 함수는 commit을 하지 않는다. 부르는 쪽(purchase.py)이 한 트랜잭션으로 묶어 commit한다
def buy_items(conn, user_id, item_ids, day):
    # 아직 안 산 것(wish·planned)만 산 것으로 기록 (받은 날 = 산 날). 산 물건 목록을 돌려준다
    if not item_ids:
        return []
    marks = ", ".join(["%s"] * len(item_ids))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, price FROM wish_items WHERE user_id = %s "
            f"AND status IN ('wish', 'planned') AND item_id IN ({marks})",
            (user_id, *item_ids),
        )
        rows = cur.fetchall()
        for r in rows:
            cur.execute(
                "UPDATE wish_items SET status = 'bought', bought_date = %s, received_date = %s "
                "WHERE item_id = %s AND user_id = %s",
                (day, day, r["item_id"], user_id),
            )
    return rows


def plan_item(conn, user_id, item_id, planned_date):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wish_items SET status = 'planned', planned_date = %s "
            "WHERE item_id = %s AND user_id = %s AND status IN ('wish', 'planned')",
            (planned_date, item_id, user_id),
        )
        return cur.rowcount


def unplan_item(conn, user_id, item_id):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wish_items SET status = 'wish', planned_date = NULL "
            "WHERE item_id = %s AND user_id = %s AND status = 'planned'",
            (item_id, user_id),
        )
        return cur.rowcount


def return_item(conn, user_id, item_id, day):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wish_items SET status = 'returned', returned_date = %s "
            "WHERE item_id = %s AND user_id = %s AND status = 'bought'",
            (day, item_id, user_id),
        )
        return cur.rowcount


def adjust_balance_log(conn, user_id, log_date, delta):
    # 그날 밤 잔액을 delta만큼 고친다 (산 것은 음수, 반품은 양수)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE balance_logs SET balance = balance + %s WHERE user_id = %s AND log_date = %s",
            (delta, user_id, log_date),
        )


# 아래 세 함수도 commit을 하지 않는다. replan.py가 한 트랜잭션으로 묶어 commit한다
def update_appointment_amount(conn, user_id, appt_id, amount):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE appointments SET amount = %s WHERE appt_id = %s AND user_id = %s",
            (amount, appt_id, user_id),
        )


def insert_loan(conn, user_id, borrowed_on, amount):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO loans (user_id, borrowed_on, amount) VALUES (%s, %s, %s)",
            (user_id, borrowed_on, amount),
        )


def add_emergency_fund(conn, user_id, delta):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET emergency_fund = emergency_fund + %s WHERE user_id = %s",
            (delta, user_id),
        )


# ---- 되돌리기 (19, 22): commit 안 함, purchase.py가 묶는다 ----
def unbuy_items(conn, user_id, item_ids, day):
    # 그날 산 것만 사기 전으로: 계획에서 산 것이면 계획으로, 아니면 담은 것으로. 되돌린 물건 목록
    if not item_ids:
        return []
    marks = ", ".join(["%s"] * len(item_ids))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT item_id, price FROM wish_items WHERE user_id = %s AND status = 'bought' "
            f"AND bought_date = %s AND item_id IN ({marks})",
            (user_id, day, *item_ids),
        )
        rows = cur.fetchall()
        for r in rows:
            cur.execute(
                "UPDATE wish_items SET status = IF(planned_date IS NULL, 'wish', 'planned'), "
                "bought_date = NULL, received_date = NULL WHERE item_id = %s AND user_id = %s",
                (r["item_id"], user_id),
            )
    return rows


def unreturn_item(conn, user_id, item_id, day):
    # 그날 반품한 것만 다시 산 것으로
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wish_items SET status = 'bought', returned_date = NULL "
            "WHERE item_id = %s AND user_id = %s AND status = 'returned' AND returned_date = %s",
            (item_id, user_id, day),
        )
        return cur.rowcount


# ---- 설정 (흐름 6): 돈 들어오는 날·고정비는 한 줄씩 바로 저장한다 ----
def list_incomes(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT income_id, name, day_of_month, amount, is_main FROM incomes "
            "WHERE user_id = %s ORDER BY is_main DESC, day_of_month, income_id",
            (user_id,),
        )
        rows = cur.fetchall()
    for r in rows:
        r["is_main"] = bool(r["is_main"])
    return rows


def insert_income(conn, user_id, name, day_of_month, amount):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO incomes (user_id, name, day_of_month, amount) VALUES (%s, %s, %s, %s)",
            (user_id, name, day_of_month, amount),
        )
    conn.commit()


def update_income(conn, user_id, income_id, name, day_of_month, amount):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE incomes SET name = %s, day_of_month = %s, amount = %s "
            "WHERE income_id = %s AND user_id = %s",
            (name, day_of_month, amount, income_id, user_id),
        )
    conn.commit()


def delete_income(conn, user_id, income_id):
    # 기간 기준인 돈은 지우지 않는다. 지운 줄 수를 돌려준다
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM incomes WHERE income_id = %s AND user_id = %s AND is_main = FALSE",
            (income_id, user_id),
        )
        count = cur.rowcount
    conn.commit()
    return count


def set_main_income(conn, user_id, income_id):
    # 기간 기준은 하나만: 모두 끄고 고른 것만 켠다 (한 트랜잭션). 내 것이 아니면 False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT income_id FROM incomes WHERE income_id = %s AND user_id = %s",
                        (income_id, user_id))
            if cur.fetchone() is None:
                conn.rollback()
                return False
            cur.execute("UPDATE incomes SET is_main = FALSE WHERE user_id = %s", (user_id,))
            cur.execute("UPDATE incomes SET is_main = TRUE WHERE income_id = %s AND user_id = %s",
                        (income_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def list_fixed(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fixed_id, name, day_of_month, amount FROM fixed_costs "
            "WHERE user_id = %s ORDER BY day_of_month, fixed_id",
            (user_id,),
        )
        return cur.fetchall()


def insert_fixed(conn, user_id, name, day_of_month, amount):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO fixed_costs (user_id, name, day_of_month, amount) VALUES (%s, %s, %s, %s)",
            (user_id, name, day_of_month, amount),
        )
    conn.commit()


def update_fixed(conn, user_id, fixed_id, name, day_of_month, amount):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fixed_costs SET name = %s, day_of_month = %s, amount = %s "
            "WHERE fixed_id = %s AND user_id = %s",
            (name, day_of_month, amount, fixed_id, user_id),
        )
    conn.commit()


def delete_fixed(conn, user_id, fixed_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fixed_costs WHERE fixed_id = %s AND user_id = %s", (fixed_id, user_id))
    conn.commit()


# ---- 설정: 가는 곳. 아래 셋은 commit 안 함 (settings.py가 묶는다) ----
def list_routines(conn, user_id):
    # get_routines에 이름까지 (설정 화면용)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT routine_id, name, round_trip_fare, meals_out, meal_price, start_date, end_date "
            "FROM routines WHERE user_id = %s ORDER BY routine_id",
            (user_id,),
        )
        routines = cur.fetchall()
        cur.execute(
            "SELECT d.routine_id, d.weekday FROM routine_days d "
            "JOIN routines r ON r.routine_id = d.routine_id WHERE r.user_id = %s ORDER BY d.weekday",
            (user_id,),
        )
        days = cur.fetchall()
    for r in routines:
        r["weekdays"] = [d["weekday"] for d in days if d["routine_id"] == r["routine_id"]]
    return routines


def insert_routine(conn, user_id, r):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO routines (user_id, name, round_trip_fare, meals_out, meal_price, "
            "start_date, end_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, r["name"], r["round_trip_fare"], r["meals_out"], r["meal_price"],
             r["start_date"], r["end_date"]),
        )
        routine_id = cur.lastrowid
        for weekday in r["weekdays"]:
            cur.execute("INSERT INTO routine_days (routine_id, weekday) VALUES (%s, %s)",
                        (routine_id, weekday))
    return routine_id


def end_routine(conn, user_id, routine_id, end_date):
    with conn.cursor() as cur:
        cur.execute("UPDATE routines SET end_date = %s WHERE routine_id = %s AND user_id = %s",
                    (end_date, routine_id, user_id))


def delete_routine(conn, user_id, routine_id):
    # routine_days는 ON DELETE CASCADE로 같이 지워진다
    with conn.cursor() as cur:
        cur.execute("DELETE FROM routines WHERE routine_id = %s AND user_id = %s", (routine_id, user_id))


# ---- 설정: 숫자, 지우기 ----
def update_user_numbers(conn, user_id, comfort_daily, hourly_wage, emergency_fund):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET comfort_daily = %s, hourly_wage = %s, emergency_fund = %s "
            "WHERE user_id = %s",
            (comfort_daily, hourly_wage, emergency_fund, user_id),
        )
    conn.commit()


def delete_user(conn, user_id):
    # 다른 표는 모두 ON DELETE CASCADE로 같이 지워진다
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    conn.commit()


# ---- 지난 기간 돌아보기 (29) ----
def get_periods(conn, user_id, until):
    # until 날까지 시작한 기간들, 최근 것부터
    with conn.cursor() as cur:
        cur.execute(
            "SELECT start_date, end_date, opening_balance, repay_amount FROM periods "
            "WHERE user_id = %s AND start_date <= %s ORDER BY start_date DESC",
            (user_id, until),
        )
        return cur.fetchall()


def get_balance_logs(conn, user_id, start, end):
    # 범위 안 밤 잔액 기록 (uq_user_date 인덱스를 범위로 탄다)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT log_date, balance, spent FROM balance_logs "
            "WHERE user_id = %s AND log_date BETWEEN %s AND %s ORDER BY log_date",
            (user_id, start, end),
        )
        return cur.fetchall()


# ---- 지갑이 채팅 (R21) ----
def insert_chat(conn, user_id, day, role, content, items_json=None, mode="shop", plan_json=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_messages (user_id, chat_day, role, mode, content, items_json, plan_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, day, role, mode, content, items_json, plan_json),
        )
    conn.commit()


def get_chat(conn, user_id, limit, mode=None):
    # 최근 limit개를 오래된 것부터. mode를 주면 그 대화(계획 짜기/무신사에서 찾기)만
    with conn.cursor() as cur:
        if mode is None:
            cur.execute(
                "SELECT message_id, role, mode, content, items_json, plan_json, applied FROM chat_messages "
                "WHERE user_id = %s ORDER BY message_id DESC LIMIT %s",
                (user_id, limit),
            )
        else:
            cur.execute(
                "SELECT message_id, role, mode, content, items_json, plan_json, applied FROM chat_messages "
                "WHERE user_id = %s AND mode = %s ORDER BY message_id DESC LIMIT %s",
                (user_id, mode, limit),
            )
        rows = cur.fetchall()
    return list(reversed(rows))


def count_chat_today(conn, user_id, day):
    # 그날 사용자가 보낸 말 수 (idx_chat_user_day를 탄다)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE user_id = %s AND chat_day = %s AND role = 'user'",
            (user_id, day),
        )
        return cur.fetchone()["n"]


# ---- 지갑이와 바꾼 계획 (R22) ----
def get_plan_changes(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT change_id, day, kind, amount, note FROM plan_changes "
            "WHERE user_id = %s ORDER BY day, change_id",
            (user_id,),
        )
        return cur.fetchall()


def add_plan_change(conn, user_id, day, kind, amount, note):
    # commit 안 함 (plan.py가 묶는다). 도시락은 그날 한 번만, 모아 두기는 같은 기간이면 더한다
    with conn.cursor() as cur:
        cur.execute("SELECT change_id FROM plan_changes WHERE user_id = %s AND day = %s AND kind = %s",
                    (user_id, day, kind))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO plan_changes (user_id, day, kind, amount, note) VALUES (%s, %s, %s, %s, %s)",
                (user_id, day, kind, amount, note),
            )
        elif kind == "save":
            cur.execute("UPDATE plan_changes SET amount = amount + %s WHERE change_id = %s",
                        (amount, row["change_id"]))


def delete_plan_change(conn, user_id, change_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM plan_changes WHERE change_id = %s AND user_id = %s", (change_id, user_id))
        count = cur.rowcount
    conn.commit()
    return count


def get_chat_message(conn, user_id, message_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT message_id, mode, plan_json, applied FROM chat_messages "
            "WHERE message_id = %s AND user_id = %s",
            (message_id, user_id),
        )
        return cur.fetchone()


def mark_applied(conn, user_id, message_id):
    # commit 안 함
    with conn.cursor() as cur:
        cur.execute("UPDATE chat_messages SET applied = 1 WHERE message_id = %s AND user_id = %s",
                    (message_id, user_id))
