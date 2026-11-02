-- 예시 사람: 본가에서 통학, 토·일 알바 (2026-10-30 기준)
SET NAMES utf8mb4;
USE jigabi;

INSERT INTO users (public_id, recovery_hash, comfort_daily, hourly_wage, emergency_fund)
VALUES ('3f6b2a1c-7d4e-4b8a-9c2d-1e5f6a7b8c9d', SHA2('DEMO-RECOVERY-CODE', 256), 10000, 10320, 100000);
SET @uid = LAST_INSERT_ID();

INSERT INTO routines (user_id, name, round_trip_fare, meals_out, meal_price, start_date, end_date)
VALUES (@uid, '학교', 3100, 2, 6000, '2026-09-01', '2026-12-18');
SET @school = LAST_INSERT_ID();
INSERT INTO routine_days (routine_id, weekday) VALUES (@school, 0), (@school, 1), (@school, 2), (@school, 3);

INSERT INTO routines (user_id, name, round_trip_fare, meals_out, meal_price)
VALUES (@uid, '알바', 3100, 0, 0);
SET @alba = LAST_INSERT_ID();
INSERT INTO routine_days (routine_id, weekday) VALUES (@alba, 5), (@alba, 6);

INSERT INTO incomes (user_id, name, day_of_month, amount, is_main) VALUES
(@uid, '알바비', 25, 420000, TRUE),
(@uid, '용돈', 1, 250000, FALSE);

INSERT INTO fixed_costs (user_id, name, day_of_month, amount) VALUES
(@uid, '통신비', 5, 33000),
(@uid, '음악 구독', 12, 10900);

INSERT INTO appointments (user_id, appt_date, title, amount, transport_fare) VALUES
(@uid, '2026-11-07', '동기 술자리', 30000, 0);

INSERT INTO wish_items (user_id, name, price, need_by) VALUES
(@uid, '롱패딩', 189000, '2026-12-01'),
(@uid, '니트', 49000, NULL),
(@uid, '목도리', 29000, NULL),
(@uid, '부츠', 119000, NULL);

-- 첫 기간: 앱을 시작한 10/30부터 알바비 전날 11/24까지
INSERT INTO periods (user_id, start_date, end_date, opening_balance) VALUES
(@uid, '2026-10-30', '2026-11-24', 290000);

-- 10/30 밤 잔액 (문서의 밤 잔액 예시)
INSERT INTO balance_logs (user_id, log_date, balance, income_in, spent) VALUES
(@uid, '2026-10-30', 284200, 0, 5800);
