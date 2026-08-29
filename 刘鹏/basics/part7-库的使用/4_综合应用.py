# ============================================================================
# 作业四：综合应用 - 随机抽奖系统
# ============================================================================
#
# 任务描述：
# 编写一个随机抽奖系统，实现以下功能：
# 1. 从文件读取参与者名单（每行一个名字）
# 2. 使用random库随机选择获奖者
# 3. 可以设置获奖人数
# 4. 将获奖名单写入文件
# 5. 显示获奖名单
#
# 要求：
# - 使用文件读写
# - 使用random库
# - 处理文件不存在的情况
# - 添加适当的注释

import os, random

FIFIE_NAME = "student.csv"

PARTICIPANTS_FILE = "participats.txt"    # 参赛者名单文件
WINNERS_FILE = "winners.txt"                    # 获奖者文件

def create_participants_file(filename):
    """创建参与者名单文件（如果不存在的话）"""
    if os.path.exists(filename):
        print(f"参与者名单已存在：{filename}")
        return
    
    participants = [
        "张三", "李四", "王五", "赵六", "孙七",
        "周八", "吴九", "郑十", "陈一", "林二",
        "黄小明", "刘小红", "杨小刚", "马小丽", "何大伟",
    ]

    with open(filename,"w",encoding="utf-8") as f:
        for participant in participants:
            f.write(participant + "\n")

    print(f"已创建参与者名单，共{len(participants)}")


def read_participants(filename):
    """随机抽取获奖者"""
    if not os.path.exists(filename):
        print("错误，请先创建参与者名单")
        return [ ]
    
    with open(filename,"r",encoding="utf-8") as f:
        participants = [ line.strip() for line in f.readlines() if line.strip()]

    print(f"成功读取 {len(participants)} 位参与者")
    print(participants)
    return participants


def draw_winners(participants, num):
    """随机抽取获奖者"""
    if not participants:
        print("没有参与者，无法抽奖")
        return [ ]

    if num > len(participants):
        print(f"抽奖人数({num})超过参与者总数({len(participants)})，自动调整为全部参与者")
        num = len(participants)

    # random.sample 从列表中不重复地随机抽取 num 个元素。与choices的区别。无权重，不重复
    winners = random.sample(participants, num)
    return winners


def write_winners(winners, filename):
    """往文件中写获胜者名单"""
    with open(filename, "w", encoding="utf-8") as f:
        for i, name in enumerate(winners, 1):
            f.write(f"{i}. {name}\n")

    print(f"获奖名单已保存到 {filename}")


def display_winners(winners):
    """显示获奖名单"""
    print("\n" + "=" * 35)
    print("       获奖名单 ")
    print("=" * 35)

    for i, name in enumerate(winners, 1):
        print(f"  第 {i} 等奖：{name}")

    print("=" * 35)


if __name__ == "__main__":
    # 步骤1：创建参与者名单文件
    create_participants_file(PARTICIPANTS_FILE)

    # 步骤2：读取参与者名单
    participants = read_participants(PARTICIPANTS_FILE)

    # 步骤3：设置获奖人数并抽奖
    num_winners = 7
    print(f"\n正在从 {len(participants)} 人中抽取 {num_winners} 位获奖者...\n")
    winners = draw_winners(participants, num_winners)

    # 步骤4：将获奖名单写入文件
    write_winners(winners, WINNERS_FILE)

    # 步骤5：显示获奖名单
    display_winners(winners)