# 산 것·반품·나눠 사기 저장: queries(commit 없음)를 한 트랜잭션으로 묶는다 (R14-0)
from app import calc, queries, split


def _buy(conn, user_id, item_ids, day):
    # 산 물건 수를 돌려준다. 그날 밤 잔액을 이미 적었으면 그 잔액에서 값만큼 뺀다
    rows = queries.buy_items(conn, user_id, item_ids, day)
    total = sum(r["price"] for r in rows)
    if total and queries.get_balance_log(conn, user_id, day) is not None:
        queries.adjust_balance_log(conn, user_id, day, -total)
    return len(rows)


def buy_now(conn, user_id, item_ids, day):
    try:
        count = _buy(conn, user_id, item_ids, day)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return count


def return_item(conn, user_id, item_id, day):
    # 산 날 빼고 7일 안의 산 것만 반품한다. 못 하면 False (남의 물건이어도 False)
    mine = [i for i in queries.get_items(conn, user_id) if i["item_id"] == item_id]
    if not mine or mine[0]["status"] != "bought" or not calc.can_return(mine[0]["bought_date"], day):
        return False
    try:
        done = queries.return_item(conn, user_id, item_id, day)
        # 반품한 날 밤 잔액을 이미 적었으면 환불받은 만큼 더한다
        if done and queries.get_balance_log(conn, user_id, day) is not None:
            queries.adjust_balance_log(conn, user_id, day, mine[0]["price"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return bool(done)


def save_split(conn, user_id, today, selected):
    # 나눠 사기 계획을 서버에서 다시 계산해 저장한다: '지금' 칸은 산 것, 나머지는 그 기간 시작일로 계획
    s = split.make_split(conn, user_id, today, selected)
    plan = s.get("plan")
    if plan is None:
        return False
    try:
        _buy(conn, user_id, [it[3] for it in plan[0]["items"]], today)
        for k in (1, 2):
            for it in plan[k]["items"]:
                queries.plan_item(conn, user_id, it[3], plan[k]["start"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True
