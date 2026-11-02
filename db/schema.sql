-- 지갑이 DB (MySQL 8)
SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS jigabi DEFAULT CHARACTER SET utf8mb4;
USE jigabi;

-- 처음부터 다시 만들 때
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
    recovery_hash CHAR(64) NOT NULL,
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
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
