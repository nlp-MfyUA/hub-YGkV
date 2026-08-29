# ============================================================================
# 作业一：使用内置库 - 数学计算
# ============================================================================
#
# 任务描述：
# 编写一个程序，使用math库完成以下任务：
# 1. 计算圆的面积（给定半径）
# 2. 计算圆的周长
# 3. 计算一个数的平方根
# 4. 计算一个数的幂
# 5. 使用random库生成随机数（1-100之间）
# 6. 使用random库从列表中随机选择一个元素
#
# 要求：
# - 使用import导入math和random库
# - 使用库中的函数进行计算
# - 输出结果

import math
import random

# 给定半径
radius = 5

# 1.计算圆的面积
area = math.pi * radius ** 2
print(f"半径为{radius}的圆的面积为：{area:.2f}")

# 2.计算圆的周长
circumference = 2 * math.pi * radius
print(f"半径为{radius}的周长是{circumference:.2f}")

# 3.计算一个数的平方根
number = 12
sqrt_number = math.sqrt(number)
print(f"数字{number}的平方根是{sqrt_number:.2f}")

# 4.计算一个数的幂
base = 2
exponent = 10
power_result = math.pow(base, exponent)
print(f"{base}的{exponent}次幂为：{power_result}")


# 5.使用random库生成随机数（1-100之间）
random_number = random.randint(0, 100)
print(f"1-100之间的随机数为:{random_number}")

# 使用random库从列表中随机选择一个元素
fruits = ["苹果","香蕉","橘子","荔枝","西瓜"]
# 随机数特殊，左闭右闭
random_index = random.randint(0, len(fruits)-1)

random_fruit = random.choice(fruits)

print(f"测试choices的方法:{random.choices(fruits)}")

print(f"从列表中随机选择的水果为：{fruits[random_index]}")
print(f"从列表中随机选择的水果为：{random_fruit}")


##################################################################
print("#" * 20)
print("     生产级开发环境实战题目练习")
print("      跟着AI手敲，练手")
"""
场景：后端注册接口需要对用户密码进行强度评分（0-100分），评分规则如下：
基础分：密码长度 × 6（上限60分）
包含大写字母：+10分
包含数字：+10分
包含特殊字符（!@#$%^&*）：+10分
长度 ≥ 12：额外 +10分
使用 math 库对最终得分做归一化处理（确保不超过100）
"""
def password_score(password):
    score = 0

    # 基础分：长度 ×6，上限60
    score += min(len(password) * 6, 60)

    # 包含大写字母
    if any(c.isupper() for c in password):
        score += 10

    # 包含数字
    if any(c.isdigit() for c in password):
        score += 10

    # 包含特殊字符
    special_chars = "!@#$%^&*"
    if any(c in special_chars for c in password):
        score += 10

    # 长度大于12
    if len(password)> 12:
        score += 10

    # 使用math归一化，确保不超过100
    final_score = math.floor(min(score, 100))

    # 评级
    if final_score >= 80:
        level = "强"
    elif final_score >= 50:
        level = "中"
    else:
        level = "弱"

    return final_score, level

test_passwords = ["abc", "Abc123", "MyP@ssw0rd!", "Str0ng!Pass#2026"]
for pwd in test_passwords:
    score, level = password_score(pwd)
    print(f"密码: {pwd:<20} 得分: {score:>3}  强度: {level}")
    

# 练习题2 random库专项 抽奖系统带权重
"""
需求：
公司年会抽奖，奖品和概率如下：
特等奖（iPhone）：1%
一等奖（AirPods）：5%
二等奖（充电宝）：14%
安慰奖（纸巾）：80%
写一个函数 lottery_draw(num_people)，模拟 num_people 个人抽奖，返回一个字典，统计每个奖品被抽中的次数。
涉及知识点：
random.choices() 的 weights 参数
collections.Counter 或手动统计
概率归一化概念
"""
from collections import Counter

def lottery_draw(num_people):
    prizes = ["特等奖","一等奖","二等奖","安慰奖"]
    weights = [1, 5,14,80] # 权重，不需要加起来等于100，choices会自动归一化

    results = random.choices(prizes, weights=weights, k=num_people)

    print(f"返回的结果是:{results}")

    # 统计次数
    count = dict(Counter(results))

    print(f"统计次数后的汇总：{count}")

    # 确保所有奖品都出现，即使次数为0
    # 这个方法就不需要了，通过下面的推导式就可以随便完成
    #for prize in prizes:
    #   if  prize not in count:
    #        count[prize] = 0

    # 对输出的抽奖结果进行排序
    # 按 prizes 固定顺序生成有序字典
    sorted_count = {prize: count.get(prize, 0) for prize in prizes}


    
    return sorted_count

# 测试模拟1000人
print(f"抽奖结果：{lottery_draw(5)}")



# 进一步加深
# 1. 配置：奖项、权重、各奖项最大数量
prizes = ["特等奖", "一等奖", "二等奖", "安慰奖"]
weights = [1, 5, 14, 80]
max_limits = {"特等奖": 2, "一等奖": 5, "二等奖": 15, "安慰奖": 80}  # 各奖项上限
num_people = 100  # 总抽奖人数

# 2. 抽奖逻辑：保证特等奖至少1个 + 控制各奖项不超上限
def controlled_lottery(prizes, weights, max_limits, num_people):
    results = []
    # 先强制抽1个特等奖（保证至少1个）
    results.append("特等奖")
    remaining = num_people - 1  # 剩余抽奖次数
    
    # 剩余次数按权重抽，但实时检查是否超上限
    for _ in range(remaining):
        # 动态过滤：只保留未达上限的奖项
        valid_prizes = []
        valid_weights = []
        for p, w in zip(prizes, weights):
            if results.count(p) < max_limits[p]:
                valid_prizes.append(p)
                valid_weights.append(w)
        # 从有效奖项中抽1个
        draw = random.choices(valid_prizes, weights=valid_weights, k=1)[0]
        results.append(draw)
    return results

# 3. 执行抽奖
results = controlled_lottery(prizes, weights, max_limits, num_people)
count = dict(Counter(results))

# 4. 漂亮打印结果
print("=" * 40)
print(f" 抽奖结果（共 {num_people} 人）")
print("=" * 40)
# 按奖项等级排序打印
for prize in prizes:
    print(f"{prize:>6}：{count.get(prize, 0):>2} 人")
print("=" * 40)



"""
需要再次升级，统计20个人的获奖情况，并符合权重以及每个奖项的数量
"""

# ================抽奖逻辑=========================
def controlled_lottery_with_names(names, prizes, weights, max_limits):
    num_people = len(names)
    people =names.copy()
    random.shuffle(people)

    assignments = {}  # {人名:  奖项}

    # 第一步 保证特定奖至少一个
    first_people = people.pop()
    assignments[first_people] = "特等奖"

    for person in people:
        # 动态过滤：只保留未达到上限的奖项
        valid_prizes = []
        valid_weights = []

        for p, w in zip(prizes, weights):
            current_count  = list(assignments.values()).count(p)
            if current_count  < max_limits[p]:
                valid_prizes.append(p)
                valid_weights.append(w)

        draw = random.choices(valid_prizes, weights= valid_weights, k=1)[0]
        assignments[person] = draw
    return assignments
    



if __name__ == "__main__":

    # ============ 配置区 ============
    names = [
        "张伟", "王芳", "李娜", "刘洋", "陈静",
        "杨帆", "赵磊", "黄丽", "周杰", "吴敏",
        "徐浩", "孙悦", "马超", "朱婷", "胡歌",
        "郭靖", "林黛", "何冰", "高圆圆", "罗翔"
    ]

    prizes = ["特等奖", "一等奖", "二等奖", "安慰奖"]
    weights = [1, 5, 14, 80]
    max_limits = {"特等奖": 2, "一等奖": 5, "二等奖": 15, "安慰奖": 20}
    # ============ 执行抽奖 ============
    assignments = controlled_lottery_with_names(names, prizes, weights, max_limits)

    count = Counter(assignments.values())

    # 按奖项等级分组展示
    for prize in prizes:
        winners = [name for name, p in assignments.items() if p == prize]
        print(f"\n  【{prize}】{count[prize]} 人")
        if winners:
            print(f"   → {', '.join(winners)}")