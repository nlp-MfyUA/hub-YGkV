# ============================================================================
# 作业二：函数参数与返回值 - 成绩处理函数
# ============================================================================
#
# 任务描述：
# 编写一个程序，定义以下函数：
# 1. calculate_average(scores)：接收一个成绩列表，计算并返回平均分
# 2. find_max_min(scores)：接收一个成绩列表，返回最高分和最低分（返回两个值）
# 3. count_pass_fail(scores, pass_score=60)：接收成绩列表和及格分数线（默认60），返回及格人数和不及格人数
# 4. get_grade(score)：接收一个分数，返回等级（优秀/良好/中等/及格/不及格）
# 5. process_scores(scores)：接收成绩列表，调用以上函数，返回处理结果（字典形式）
#
# 在主程序中：
# - 创建一个成绩列表
# - 调用process_scores函数处理成绩
# - 输出格式化的成绩报告
#
# 要求：
# - 使用默认参数（pass_score=60）
# - 函数返回多个值（使用元组）
# - 函数返回字典
# - 添加详细的注释


def calculate_average(scores):
    """计算平均分"""
    if len(scores) == 0:
        return 0
    total = 0
    for score in scores:
        total += score
    return total / len(scores)


def find_max_min(scores):
    """返回最高分和最低分（元组）"""
    max_score = scores[0]
    min_score = scores[0]
    for score in scores:
        if score > max_score:
            max_score = score
        if score < min_score:
            min_score = score
    return max_score, min_score


def count_pass_fail(scores, pass_score=60):
    """统计及格和不及格人数，返回字典"""
    pass_count = 0
    for score in scores:
        if score >= pass_score:
            pass_count += 1
    return {
        "及格人数": pass_count,
        "不及格人数": len(scores) - pass_count
    }


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


def process_scores(scores):
    """汇总所有处理结果，返回字典"""
    avg = calculate_average(scores)
    max_score, min_score = find_max_min(scores)
    pass_fail = count_pass_fail(scores)

    # 统计各等级人数
    grade_count = {"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0}
    for score in scores:
        grade = get_grade(score)
        grade_count[grade] += 1

    return {
        "平均分": avg,
        "最高分": max_score,
        "最低分": min_score,
        "及格人数": pass_fail["及格人数"],
        "不及格人数": pass_fail["不及格人数"],
        "等级分布": grade_count
    }


# ==================== 主程序 ====================
if __name__ == "__main__":
    scores = [85, 92, 67, 45, 78, 55, 90, 73, 88, 60]

    result = process_scores(scores)

    print("=" * 40)
    print("        成绩报告")
    print("=" * 40)
    print(f"平均分：{result['平均分']:.1f}")
    print(f"最高分：{result['最高分']}")
    print(f"最低分：{result['最低分']}")
    print(f"及格人数：{result['及格人数']}")
    print(f"不及格人数：{result['不及格人数']}")
    print("-" * 40)
    print("等级分布：")
    for grade, count in result["等级分布"].items():
        print(f"  {grade}：{count}人")



    
    