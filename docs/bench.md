# 인덱스 실험 결과 (DB 보고서 Evaluation)

- MySQL 8.4.13, 새 DB `jigabi_bench`(schema.sql 그대로), 합성 데이터 `db/make_synth.py` (seed 42)
- 쿼리마다 예열 1번 뒤 20번 돌린 시간의 중앙값. 읽은 행은 EXPLAIN ANALYZE 맨 아래(실제로 읽는 곳)의 실제 행 수
- Handler_read_*는 FLUSH STATUS 뒤 쿼리를 한 번 돌린 값

```sql
SELECT COUNT(*) FROM chat_messages WHERE user_id = ? AND chat_day = ? AND role = 'user'
SELECT appt_id, appt_date, title, amount, transport_fare FROM appointments WHERE user_id = ? ORDER BY appt_date, appt_id
SELECT appt_id, appt_date, title, amount, transport_fare FROM appointments WHERE user_id = ? AND appt_date >= '2026-12-01' ORDER BY appt_date, appt_id  -- 참고용
```

## 학기 (109일)

- 사람 100명, 채팅 63,276행, 약속 3,223행
- 채팅 가장 많은 사람: user_id 99, 2,276행 (마지막 날 12/18에 보낸 말 5개)
- 채팅 가운데 사람: user_id 92, 298행 (마지막 날 12/18에 보낸 말 16개)
- 약속 가장 많은 사람: user_id 6, 40행 (12/1 이후 8행)
- 인덱스: chat_messages 스키마 그대로 [idx_chat_user_day, PRIMARY] / 바꾼 뒤 [idx_chat_user, PRIMARY], appointments 스키마 그대로 [PRIMARY, user_id] / 바꾼 뒤 [idx_appt_user_date, PRIMARY]

### 실험 A: 채팅 하루 제한 (`count_chat_today`, chat_day = 12/18)

| 대상 | 전/후 | 중앙값(ms) | 읽은 행 | type / 쓴 인덱스 | Extra | 정렬 단계 | Handler_read_next | Handler_read_key |
|---|---|---|---|---|---|---|---|---|
| 가장 많은 사람 | 전 | 4.45 | 2,276 | ref / idx_chat_user | Using where | 아니오 | 2,276 | 1 |
| 가장 많은 사람 | 후 | 1.40 | 10 | ref / idx_chat_user_day | Using where | 아니오 | 10 | 1 |
| 가운데 사람 | 전 | 2.05 | 298 | ref / idx_chat_user | Using where | 아니오 | 298 | 1 |
| 가운데 사람 | 후 | 1.58 | 32 | ref / idx_chat_user_day | Using where | 아니오 | 32 | 1 |

### 실험 B: 약속 목록 (`get_appointments`, 약속이 가장 많은 사람)

| 대상 | 전/후 | 중앙값(ms) | 읽은 행 | type / 쓴 인덱스 | Extra | 정렬 단계 | Handler_read_next | Handler_read_key |
|---|---|---|---|---|---|---|---|---|
| 전체 목록 | 전 | 3.00 | 40 | ref / user_id | Using filesort | 예 | 40 | 1 |
| 전체 목록 | 후 | 3.07 | 40 | ref / idx_appt_user_date | - | 아니오 | 40 | 1 |
| 12/1 이후만 (참고) | 전 | 2.00 | 40 | ref / user_id | Using where; Using filesort | 예 | 40 | 1 |
| 12/1 이후만 (참고) | 후 | 2.00 | 8 | range / idx_appt_user_date | Using index condition | 아니오 | 8 | 1 |

## 4년 (1,461일)

- 사람 100명, 채팅 830,974행, 약속 42,047행
- 채팅 가장 많은 사람: user_id 10, 29,186행 (마지막 날 12/18에 보낸 말 4개)
- 채팅 가운데 사람: user_id 63, 3,392행 (마지막 날 12/18에 보낸 말 0개)
- 약속 가장 많은 사람: user_id 17, 458행 (12/1 이후 9행)
- 인덱스: chat_messages 스키마 그대로 [idx_chat_user_day, PRIMARY] / 바꾼 뒤 [idx_chat_user, PRIMARY], appointments 스키마 그대로 [PRIMARY, user_id] / 바꾼 뒤 [idx_appt_user_date, PRIMARY]

### 실험 A: 채팅 하루 제한 (`count_chat_today`, chat_day = 12/18)

| 대상 | 전/후 | 중앙값(ms) | 읽은 행 | type / 쓴 인덱스 | Extra | 정렬 단계 | Handler_read_next | Handler_read_key |
|---|---|---|---|---|---|---|---|---|
| 가장 많은 사람 | 전 | 39.63 | 29,186 | ref / idx_chat_user | Using where | 아니오 | 29,186 | 1 |
| 가장 많은 사람 | 후 | 1.53 | 8 | ref / idx_chat_user_day | Using where | 아니오 | 8 | 1 |
| 가운데 사람 | 전 | 6.70 | 3,392 | ref / idx_chat_user | Using where | 아니오 | 3,392 | 1 |
| 가운데 사람 | 후 | 1.18 | 0 | ref / idx_chat_user_day | Using where | 아니오 | 0 | 1 |

### 실험 B: 약속 목록 (`get_appointments`, 약속이 가장 많은 사람)

| 대상 | 전/후 | 중앙값(ms) | 읽은 행 | type / 쓴 인덱스 | Extra | 정렬 단계 | Handler_read_next | Handler_read_key |
|---|---|---|---|---|---|---|---|---|
| 전체 목록 | 전 | 19.14 | 458 | ref / user_id | Using filesort | 예 | 458 | 1 |
| 전체 목록 | 후 | 20.37 | 458 | ref / idx_appt_user_date | - | 아니오 | 458 | 1 |
| 12/1 이후만 (참고) | 전 | 2.86 | 458 | ref / user_id | Using where; Using filesort | 예 | 458 | 1 |
| 12/1 이후만 (참고) | 후 | 2.21 | 9 | range / idx_appt_user_date | Using index condition | 아니오 | 9 | 1 |
