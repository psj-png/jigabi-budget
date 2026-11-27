-- 지갑이 DB (MySQL 8)
SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS jigabi DEFAULT CHARACTER SET utf8mb4;
USE jigabi;

-- 처음부터 다시 만들 때
DROP TABLE IF EXISTS loans;
DROP TABLE IF EXISTS periods;
DROP TABLE IF EXISTS balance_logs;
DROP TABLE IF EXISTS wish_items;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS fixed_costs;
DROP TABLE IF EXISTS incomes;
DROP TABLE IF EXISTS routine_days;
DROP TABLE IF EXISTS routines;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    public_id CHAR(36) NOT NULL UNIQUE,
    comfort_daily INT NOT NULL DEFAULT 10000,
    hourly_wage INT NOT NULL DEFAULT 10320,
    emergency_fund INT NOT NULL DEFAULT 0,
    grocery_weekly INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 매주 가는 곳 (학교, 알바)
CREATE TABLE routines (
    routine_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(20) NOT NULL,
    round_trip_fare INT NOT NULL DEFAULT 0,
    meals_out TINYINT NOT NULL DEFAULT 0,
    meal_price INT NOT NULL DEFAULT 0,
    start_date DATE NULL,
    end_date DATE NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 요일: 0=월 ~ 6=일 (MySQL WEEKDAY()와 같음)
CREATE TABLE routine_days (
    routine_id INT NOT NULL,
    weekday TINYINT NOT NULL,
    PRIMARY KEY (routine_id, weekday),
    FOREIGN KEY (routine_id) REFERENCES routines(routine_id) ON DELETE CASCADE
);

CREATE TABLE incomes (
    income_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(20) NOT NULL,
    day_of_month TINYINT NOT NULL,
    amount INT NOT NULL,
    is_main BOOLEAN NOT NULL DEFAULT FALSE,
    -- 주 수입은 한 사람에 하나만: 주 수입 줄만 user_id를 갖고 나머지는 NULL (UNIQUE는 NULL을 여러 개 허용)
    -- STORED는 user_id의 ON DELETE CASCADE FK와 같이 못 써서 VIRTUAL로 둔다
    main_user INT AS (IF(is_main, user_id, NULL)) VIRTUAL,
    UNIQUE KEY uq_main_income (main_user),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE fixed_costs (
    fixed_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(20) NOT NULL,
    day_of_month TINYINT NOT NULL,
    amount INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE appointments (
    appt_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    appt_date DATE NOT NULL,
    title VARCHAR(40) NOT NULL,
    amount INT NOT NULL,
    transport_fare INT NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE wish_items (
    item_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(60) NOT NULL,
    price INT NOT NULL,
    need_by DATE NULL,
    url VARCHAR(500) NULL,  -- 채팅에서 담은 무신사 상품 링크 (R21)
    status ENUM('wish', 'planned', 'bought', 'returned') NOT NULL DEFAULT 'wish',
    planned_date DATE NULL,
    bought_date DATE NULL,
    received_date DATE NULL,
    returned_date DATE NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 밤 잔액. 가장 많이 쌓이는 테이블
CREATE TABLE balance_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    log_date DATE NOT NULL,
    balance INT NOT NULL,
    income_in INT NOT NULL DEFAULT 0,
    spent INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_user_date (user_id, log_date),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE periods (
    period_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    opening_balance INT NOT NULL,
    repay_amount INT NOT NULL DEFAULT 0,
    -- 같은 시작일의 기간은 한 줄만 (ensure_period가 겹쳐 불려도 두 번 만들어지지 않게)
    UNIQUE KEY uq_period_start (user_id, start_date),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 비상금에서 빌린 돈 (R14). 다음 기간 첫날 periods.repay_amount로 갚는다
CREATE TABLE loans (
    loan_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    borrowed_on DATE NOT NULL,
    amount INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 지갑이 채팅 (R21): 무신사 쇼핑 추천 대화. 하루 물어본 횟수는 chat_day로 센다
CREATE TABLE chat_messages (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    chat_day DATE NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    mode ENUM('shop', 'plan') NOT NULL DEFAULT 'shop',  -- 무신사에서 찾기 / 계획 짜기 (R22)
    content VARCHAR(500) NOT NULL,
    items_json JSON NULL,  -- 지갑이가 고른 상품 카드 (이름·가격·링크·이유)
    plan_json JSON NULL,   -- 계획 도우미 제안 (도시락 날, 모아 두기)
    applied TINYINT(1) NOT NULL DEFAULT 0,  -- 제안을 [이대로 적용] 했는지
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_chat_user_day (user_id, chat_day),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 지갑이와 바꾼 계획 (R22): 도시락 날은 그날 점심값 하나가 최소 생활비에서 빠지고, 모아 두기는 그 기간 여유 돈에서 빠진다
CREATE TABLE plan_changes (
    change_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    day DATE NOT NULL,                  -- 도시락: 그날, 모아 두기: 그 기간의 끝 날
    kind ENUM('meal', 'save') NOT NULL,
    amount INT NOT NULL,                -- 도시락: 아끼는 점심값, 모아 두기: 남겨 둘 돈
    note VARCHAR(60) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_plan_day_kind (user_id, day, kind),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);