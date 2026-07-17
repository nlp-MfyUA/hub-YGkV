# ============================================================================
# 作业二：列表综合应用 - 成绩管理系统
# ============================================================================
#
# 任务描述：
# 编写一个成绩管理系统，实现以下功能：
# 1. 创建一个列表存储5个学生的成绩（可以预设或用户输入）
# 2. 计算并输出：总分、平均分、最高分、最低分
# 3. 统计及格人数（成绩>=60）和不及格人数
# 4. 找出所有大于等于90分的成绩，并输出
# 5. 使用循环遍历列表，为每个成绩评定等级：
#    - 90分及以上：优秀
#    - 80-89分：良好
#    - 70-79分：中等
#    - 60-69分：及格
#    - 60分以下：不及格
# 6. 输出格式化的成绩单
#
# 要求：
# - 使用列表的索引访问元素
# - 使用for循环遍历列表
# - 使用条件语句进行判断
# - 使用列表的append()方法（如果需要）
# - 输出格式要清晰美观

# 手搓，主要先实现功能
def student_system():
    scores = [63, 89, 99.22, 96, 39]

    # 总成绩
    total_scores = sum(scores)
    # 平均数
    ave_scores = total_scores / len(scores)
    # 最高分
    highest = max(scores)
    # 最低分
    lowest = min(scores)

    print(f"总分：{total_scores}")
    print(f"平均分：{ave_scores}")
    print(f"最高分：{highest}")
    print(f"最低分：{lowest}")

    fail_quantity = 0
    pass_quantity = 0

    for i in scores:
        if i >= 60:
            pass_quantity += 1
        else:
            fail_quantity += 1

    print(f"及格人数:{pass_quantity}")
    print(f"不及格任务：{fail_quantity}")

    # 4. 找出所有大于等于90分的成绩，并输出
    print([x for x in scores if x >= 90])

    # 5. 使用循环遍历列表，为每个成绩评定等级：
    #    - 90分及以上：优秀
    #    - 80-89分：良好
    #    - 70-79分：中等
    #    - 60-69分：及格
    #    - 60分以下：不及格
    for i in scores:
        if i >= 90:
            print("90分为优秀")
        elif 90 > i >= 80:
            print("0-89分：良好")
        elif 80 > i >= 70:
            print("70-79分：中等")
        elif 70 > i >= 60:
            print("60-69分：及格")
        elif i < 60:
            print("60分以下：不及格")


# 未来的代码方向
def get_grade(score):
    """根据分数返回等级"""
    if score >= 90:
        return "优秀"
    elif score >= 80:
        return "良好"
    elif score >= 70:
        return "中等"
    elif score >= 60:
        return "及格"
    else:
        return "不及格"


def student_system_refactor():
    """学生成绩管理系统（生产级重构版）"""
    # 1.使用列表存储成绩
    scores = [85, 92, 78, 96, 88, 63, 99.22, 39]

    # 2.使用内置函数进行统计
    total_score = sum(scores)
    average_score = total_score / len(scores)
    highest_score = max(scores)
    lowest_score = min(scores)

    # 3. 使用sum + 生成器表达式统计及格人数
    pass_count = sum(1 for score in scores if score >= 60)
    fail_count = len(scores) - pass_count

    # 4.使用列表推导式筛选优秀成绩
    excellent_score = [score for score in scores if score >= 90]

    # 5. 使用推导式 + 条件表达式生成等级列表
    grads = [
        "优秀" if s >= 90 else "良好" if s >= 80 else
        "中等" if s >= 70 else "及格" if s >= 60 else "不及格"
        for s in scores
    ]

    # 优化方式，与上边的方法存在重复
    grades_dict = {s: get_grade(s) for s in scores}

    print(f"{grads}")

    # 6. 数据与展示分离，格式化输出
    print("    成绩管理系统")
    print("=" * 40)
    print(f"成绩列表：{scores}")
    print(f"平均分：{average_score:.2f} 分")
    print(f"最高分：{highest_score} 分 |  最低分：{lowest_score} 分")
    print(f"及格人数：{pass_count} 人 | 不及格人数：{fail_count} 人")
    print(f"优秀成绩 (>=90)：{excellent_score}")
    print("-" * 40)

    # 7. 使用zip优雅地同时便利成绩和等级
    for idx, (score, grade) in enumerate(zip(scores, grads), start=1):
        print(f"学生 {idx:02d}：{score:>6} 分 - {grade}")
        print("=" * 40)

    # 对上面的方法进行优化
    for idx, (score, grade) in enumerate(grades_dict.items(), start=1):
        print(f"学生 {idx:02d}：{score} 分 → {grade}")


# 代码的又进一步升级
# ============================================================================
# 常量定义 —— 所有"魔法数字"集中管理
# ============================================================================

GRADE_THRESHOLDS = [
    (90, "优秀"),
    (80, "良好"),
    (70, "中等"),
    (60, "及格"),
]

DEFAULT_GRADE = "不及格"

PASS_SCORE = 60

# ============================================================================
# 核心函数 —— 每个函数只做一件事
# ============================================================================
def get_grade(score: float) -> str:
    """根据分数返回等级（唯一等级判断入口）


    使用配置驱动代替硬编码 if-elif链,
    将来新增/修改等级只需要改GRAGE_THROSHOLDS,函数本身不用动
    """
    for throsholds, grade in GRADE_THRESHOLDS:
        if score >= throsholds:
            return grade
    return DEFAULT_GRADE
    

def get_statistics(scores: list[float]) -> dict:
    """计算统计指标，返回字典"""
    return {
        "总分": sum(scores),
        "平均分": sum(scores) / len(scores),
        "最高分": max(scores),
        "最低分": min(scores),
        "总人数": len(scores),
        "及格人数": sum(1 for s in scores if s >= PASS_SCORE),
        "不及格人数": sum(1 for s in scores if s < PASS_SCORE),
        "优秀列表": [s for s in scores if s >= 90],
    }


def get_grade_details(scores: list[float]) -> list[tuple[float, str]]:
    """返回 [(分数, 等级), ...] 的明细列表。

    复用 get_grade，不重复写判断逻辑。
    """
    return [(score, get_grade(score)) for score in scores]


def get_grade_distribution(scores: list[float]) -> dict[str, int]:
    """统计各等级的人数分布。

    复用 get_grade，不重复写判断逻辑。
    """
    # 先初始化所有等级为 0（保证顺序固定） 这里看不太懂，学完再回来
    distribution = {grade: 0 for _, grade in GRADE_THRESHOLDS}
    distribution[DEFAULT_GRADE] = 0

    for score in scores:
        grade = get_grade(score)
        distribution[grade] += 1

    return distribution


# ============================================================================
# 展示层 —— 只负责打印，不做任何计算
# ============================================================================
def print_report(scores: list[float]) -> None:
    """格式化输出成绩报告。"""
    stats = get_statistics(scores)
    details = get_grade_details(scores)
    distribution = get_grade_distribution(scores)

    print("=" * 48)
    print("           📊 成绩管理系统")
    print("=" * 48)

    # 基础统计
    print(f"  成绩列表：{scores}")
    print(f"  平均分：{stats['平均分']:.2f} 分")
    print(f"  最高分：{stats['最高分']} 分  |  最低分：{stats['最低分']} 分")
    print(f"  及格人数：{stats['及格人数']} 人  |  不及格人数：{stats['不及格人数']} 人")
    print(f"  优秀成绩 (>=90)：{stats['优秀列表']}")

    # 等级分布
    print("-" * 48)
    print("  等级分布：")
    for grade, count in distribution.items():
        bar = "█" * count
        print(f"    {grade}：{count:>2} 人  {bar}")

    # 逐条明细
    print("-" * 48)
    print("  成绩明细：")
    for idx, (score, grade) in enumerate(details, start=1):
        print(f"    学生 {idx:02d}：{score:>6} 分 → {grade}")

    print("=" * 48)


if __name__ == "__main__":
    #student_system()
    student_system_refactor()

    scores = [85, 92, 78, 96, 88, 63, 99.22, 39]
    print_report(scores)
