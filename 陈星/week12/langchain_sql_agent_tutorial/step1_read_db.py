"""第 1 步：先不使用 AI，确认 Python 能安全查询数据库。"""
from pathlib import Path
from db_tools import SQLiteTools

db = SQLiteTools(Path(__file__).with_name("chinook.db"))
print("数据库里的表:", ", ".join(db.catalog))

sql = "SELECT COUNT(*) AS album_count FROM albums"
safe_sql = db.validate(sql)
result = db.execute(safe_sql)

print("检查通过的 SQL:", safe_sql)
print("查询列:", result.columns)
print("查询值:", result.rows)
# 这份 Chinook 数据的正确结果应为 [[347]]（字符串形式为 [['347']]）。
