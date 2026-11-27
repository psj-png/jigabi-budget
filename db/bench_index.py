# 인덱스 전후 재기 (DB 보고서 Evaluation). jigabi_bench에서만 돌리고, 결과는 docs/bench.md에 저장한다
# 순서: schema.sql 그대로(A 후, B 전)를 재고 -> 인덱스를 바꿔서(A 전, B 후) 다시 잰다
import re
import statistics
import time
from datetime import date
from pathlib import Path

import make_synth

DB_DIR = Path(__file__).resolve().parent
OUT = DB_DIR.parent / "docs" / "bench.md"
LAST_DAY = date(2026, 12, 18)
RUNS = 20

# app/queries.py의 쿼리 그대로
Q_CHAT = "SELECT COUNT(*) FROM chat_messages WHERE user_id = %s AND chat_day = %s AND role = 'user'"
Q_APPT = ("SELECT appt_id, appt_date, title, amount, transport_fare FROM appointments "
          "WHERE user_id = %s ORDER BY appt_date, appt_id")
# 참고용: 날짜 조건을 붙인 것 (코드에는 넣지 않았다)
Q_APPT_NEW = ("SELECT appt_id, appt_date, title, amount, transport_fare FROM appointments "
              "WHERE user_id = %s AND appt_date >= '2026-12-01' ORDER BY appt_date, appt_id")


def rebuild():
    # jigabi_bench를 schema.sql로 새로 만든다 (jigabi, jigabi_test는 건드리지 않는다)
    cur = make_synth.connect().cursor()
    cur.execute("DROP DATABASE IF EXISTS jigabi_bench")
    sql = (DB_DIR / "schema.sql").read_text(encoding="utf-8")
    sql = sql.replace("CREATE DATABASE IF NOT EXISTS jigabi ", "CREATE DATABASE IF NOT EXISTS jigabi_bench ")
    sql = sql.replace("USE jigabi;", "USE jigabi_bench;")
    assert "USE jigabi_bench;" in sql and "USE jigabi;" not in sql
    cur.execute(sql)
    while cur.nextset():
        pass


def measure(cur, sql, params):
    # 예열 1번 + 20번 중앙값(ms), EXPLAIN, EXPLAIN ANALYZE, Handler 값
    cur.execute(sql, params)
    cur.fetchall()
    times = []
    for _ in range(RUNS):
        t = time.perf_counter()
        cur.execute(sql, params)
        cur.fetchall()
        times.append((time.perf_counter() - t) * 1000)

    cur.execute("EXPLAIN " + sql, params)
    plan = cur.fetchone()
    cur.execute("EXPLAIN ANALYZE " + sql, params)
    text = cur.fetchone()["EXPLAIN"]
    last = text.strip().split("\n")[-1]  # 맨 아래 줄이 실제로 읽는 곳
    rows = int(re.search(r"actual time=\S+ rows=(\d+)", last).group(1))

    cur.execute("FLUSH STATUS")
    cur.execute(sql, params)
    cur.fetchall()
    cur.execute("SHOW SESSION STATUS LIKE 'Handler_read_%'")
    handler = {r["Variable_name"]: int(r["Value"]) for r in cur.fetchall()}
    return {"ms": statistics.median(times), "rows": rows, "type": plan["type"], "key": plan["key"],
            "extra": plan["Extra"] or "-", "sort": "Sort:" in text,
            "next": handler["Handler_read_next"], "key_reads": handler["Handler_read_key"]}


def index_names(cur, table):
    cur.execute("SELECT DISTINCT INDEX_NAME AS n FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = 'jigabi_bench' AND TABLE_NAME = %s ORDER BY n", (table,))
    return ", ".join(r["n"] for r in cur.fetchall())


def one(cur, sql):
    cur.execute(sql)
    return list(cur.fetchone().values())[0]


def run_scale(name, start, end):
    print(name, "데이터 만드는 중...", flush=True)
    rebuild()
    conn = make_synth.connect("jigabi_bench")
    cur = conn.cursor()
    make_synth.make(conn, start, end)
    cur.execute("ANALYZE TABLE users, chat_messages, appointments")
    cur.fetchall()

    # 대상: 채팅이 가장 많은 사람, 가운데 사람 / 약속이 가장 많은 사람
    cur.execute("SELECT user_id, COUNT(*) AS n FROM chat_messages GROUP BY user_id ORDER BY n DESC, user_id")
    by_chat = cur.fetchall()
    for r in by_chat:
        r["n"] = int(r["n"])
    top, mid = by_chat[0], by_chat[len(by_chat) // 2]
    cur.execute("SELECT user_id, COUNT(*) AS n FROM appointments GROUP BY user_id ORDER BY n DESC, user_id LIMIT 1")
    appt = cur.fetchone()
    info = {"people": one(cur, "SELECT COUNT(*) FROM users"),
            "chats": one(cur, "SELECT COUNT(*) FROM chat_messages"),
            "appts": one(cur, "SELECT COUNT(*) FROM appointments"),
            "top": top, "mid": mid, "appt": appt,
            "days": (end - start).days + 1,
            "top_last": one(cur, f"SELECT COUNT(*) FROM chat_messages WHERE user_id={top['user_id']} AND chat_day='{LAST_DAY}' AND role='user'"),
            "mid_last": one(cur, f"SELECT COUNT(*) FROM chat_messages WHERE user_id={mid['user_id']} AND chat_day='{LAST_DAY}' AND role='user'"),
            "appt_new": one(cur, f"SELECT COUNT(*) FROM appointments WHERE user_id={appt['user_id']} AND appt_date >= '2026-12-01'")}

    res = {}
    print(name, "재는 중 (스키마 그대로)...", flush=True)
    info["idx_chat_now"] = index_names(cur, "chat_messages")
    info["idx_appt_now"] = index_names(cur, "appointments")
    res["A후 최다"] = measure(cur, Q_CHAT, (top["user_id"], LAST_DAY))
    res["A후 중간"] = measure(cur, Q_CHAT, (mid["user_id"], LAST_DAY))
    res["B전 전체"] = measure(cur, Q_APPT, (appt["user_id"],))
    res["B전 12월"] = measure(cur, Q_APPT_NEW, (appt["user_id"],))

    # A 전: FK용 user_id 인덱스를 먼저 만들고 (user_id, chat_day)를 뺀다 / B 후: (user_id, appt_date) 추가
    print(name, "인덱스 바꾸는 중...", flush=True)
    cur.execute("ALTER TABLE chat_messages ADD KEY idx_chat_user (user_id)")
    cur.execute("ALTER TABLE chat_messages DROP KEY idx_chat_user_day")
    cur.execute("ALTER TABLE appointments ADD KEY idx_appt_user_date (user_id, appt_date)")
    cur.execute("ANALYZE TABLE chat_messages, appointments")
    cur.fetchall()
    info["idx_chat_alt"] = index_names(cur, "chat_messages")
    info["idx_appt_alt"] = index_names(cur, "appointments")
    print(name, "재는 중 (바꾼 뒤)...", flush=True)
    res["A전 최다"] = measure(cur, Q_CHAT, (top["user_id"], LAST_DAY))
    res["A전 중간"] = measure(cur, Q_CHAT, (mid["user_id"], LAST_DAY))
    res["B후 전체"] = measure(cur, Q_APPT, (appt["user_id"],))
    res["B후 12월"] = measure(cur, Q_APPT_NEW, (appt["user_id"],))
    return info, res


def line(who, when, r):
    sort = "예" if r["sort"] else "아니오"
    return (f"| {who} | {when} | {r['ms']:.2f} | {r['rows']:,} | {r['type']} / {r['key']} | {r['extra']} | "
            f"{sort} | {r['next']:,} | {r['key_reads']:,} |")


HEAD = ("| 대상 | 전/후 | 중앙값(ms) | 읽은 행 | type / 쓴 인덱스 | Extra | 정렬 단계 | Handler_read_next | Handler_read_key |\n"
        "|---|---|---|---|---|---|---|---|---|")


def section(name, info, res):
    top, mid, appt = info["top"], info["mid"], info["appt"]
    out = [f"## {name} ({info['days']:,}일)", "",
           f"- 사람 {info['people']:,}명, 채팅 {info['chats']:,}행, 약속 {info['appts']:,}행",
           f"- 채팅 가장 많은 사람: user_id {top['user_id']}, {top['n']:,}행 (마지막 날 12/18에 보낸 말 {info['top_last']}개)",
           f"- 채팅 가운데 사람: user_id {mid['user_id']}, {mid['n']:,}행 (마지막 날 12/18에 보낸 말 {info['mid_last']}개)",
           f"- 약속 가장 많은 사람: user_id {appt['user_id']}, {appt['n']:,}행 (12/1 이후 {info['appt_new']}행)",
           f"- 인덱스: chat_messages 스키마 그대로 [{info['idx_chat_now']}] / 바꾼 뒤 [{info['idx_chat_alt']}], "
           f"appointments 스키마 그대로 [{info['idx_appt_now']}] / 바꾼 뒤 [{info['idx_appt_alt']}]", "",
           "### 실험 A: 채팅 하루 제한 (`count_chat_today`, chat_day = 12/18)", "", HEAD,
           line("가장 많은 사람", "전", res["A전 최다"]), line("가장 많은 사람", "후", res["A후 최다"]),
           line("가운데 사람", "전", res["A전 중간"]), line("가운데 사람", "후", res["A후 중간"]), "",
           "### 실험 B: 약속 목록 (`get_appointments`, 약속이 가장 많은 사람)", "", HEAD,
           line("전체 목록", "전", res["B전 전체"]), line("전체 목록", "후", res["B후 전체"]),
           line("12/1 이후만 (참고)", "전", res["B전 12월"]), line("12/1 이후만 (참고)", "후", res["B후 12월"]), ""]
    return "\n".join(out)


def main():
    conn = make_synth.connect()
    version = one(conn.cursor(), "SELECT VERSION()")
    parts = []
    for name, (start, end) in [("학기", make_synth.SEMESTER), ("4년", make_synth.FOUR_YEARS)]:
        info, res = run_scale(name, start, end)
        parts.append(section(name, info, res))
    text = ["# 인덱스 실험 결과 (DB 보고서 Evaluation)", "",
            f"- MySQL {version}, 새 DB `jigabi_bench`(schema.sql 그대로), 합성 데이터 `db/make_synth.py` (seed 42)",
            f"- 쿼리마다 예열 1번 뒤 {RUNS}번 돌린 시간의 중앙값. 읽은 행은 EXPLAIN ANALYZE 맨 아래(실제로 읽는 곳)의 실제 행 수",
            "- Handler_read_*는 FLUSH STATUS 뒤 쿼리를 한 번 돌린 값", "",
            "```sql", Q_CHAT.replace("%s", "?"), Q_APPT.replace("%s", "?"), Q_APPT_NEW.replace("%s", "?") + "  -- 참고용", "```", ""]
    OUT.write_text("\n".join(text + parts), encoding="utf-8")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
