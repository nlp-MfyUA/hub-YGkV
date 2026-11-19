-- 在 rag-mysql 实例中创建独立库与专用用户
-- 执行前把 __PASSWORD__ 替换为 deploy/.env 中的 MYSQL_PASSWORD
CREATE DATABASE IF NOT EXISTS rag_mm
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'rag_mm'@'%' IDENTIFIED BY '__PASSWORD__';
ALTER USER 'rag_mm'@'%' IDENTIFIED BY '__PASSWORD__';
GRANT ALL PRIVILEGES ON rag_mm.* TO 'rag_mm'@'%';
FLUSH PRIVILEGES;
