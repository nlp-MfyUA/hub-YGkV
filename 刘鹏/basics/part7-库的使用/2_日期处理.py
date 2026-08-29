# ============================================================================
# 作业二：日期时间处理
# ============================================================================
#
# 任务描述：
# 编写一个程序，使用datetime库完成以下任务：
# 1. 获取当前日期和时间
# 2. 格式化显示日期和时间
# 3. 计算两个日期之间的天数差
# 4. 计算某个日期之后N天的日期
# 5. 显示今天是星期几
#
# 要求：
# - 使用datetime库
# - 格式化日期输出
# - 进行日期计算

from datetime import datetime, timedelta

# 1.获取当前日期和时间
now = datetime.now()

print("#" * 50)
print(f"    当前日期时间对象：{now}")
print(f"    年：{now.year}  月：{now.month} 日：{now.day}")
print(f"    时：{now.hour}  分：{now.minute}  秒：{now.second}")


# 2.格式化日期
print(f"    格式化1（YYYY-MM-DD）:               {now.strftime('%Y-%m-%d')}")
print(f"    格式2（YYYY/MM/DD HH:MM:           {now.strftime('%Y/%m/%d %H:%M')}" )
print(f"    格式3（中文）：                                 {now.strftime('%Y年%m月%d日 %H时%M分%S秒')}")
print(f"    格式4（完整版)：                                {now.strftime('%Y-%m-%d %A')}")


# 3.计算两个日期之间的天数差
date1 = datetime(2026,7,2)
date2 = datetime(2026,7, 5)

delta = date2 - date1

print(f"   日期1: {date1.strftime('%Y-%m-%d')}")
print(f"   日期2: {date2.strftime('%Y-%m-%d')}")
print(f"    相差天数：{delta.days}天")

# 也可以计算与今天的差值
spring_festival = datetime(2027, 2, 6)
days_to_festival = (spring_festival - now).days
print(f"\n   今天到2027年春节({spring_festival.strftime('%Y-%m-%d')})还有: {days_to_festival} 天")

# 4. 计算某个日期之后的N天的日期

n = 100
future_date = now + timedelta(days=n)

print(f"    今天之后{n}天：{future_date.strftime('%Y-%m-%d')}")

# 再演示几个不同的天数
for days in [7, 30, 365]:
    result = now + timedelta(days=days)
    print(f"   今天之后 {days:>3} 天: {result.strftime('%Y-%m-%d')}")


# 5. 显示今天是星期几

weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
# weekday() 返回 0~6，0=周一，6=周日
today_weekday = now.weekday()
print(f"   今天是: {weekdays_cn[today_weekday]}")
print(f"   weekday() 返回值: {today_weekday} (0=周一, 6=周日)")

print(f"   strftime('%A'): {now.strftime('%A')}")
print(f"   strftime('%a'): {now.strftime('%a')}")
