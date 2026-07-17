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

"""
成绩处理模块，此处作为模块级docstring，用于描述整个模块的用途/功能/典型用法，可以通过help(模块名）或模块名.__doc__

提供学生成绩的统计分析功能，包括平均分计算、极值查找、
及格率统计、等级划分等。

典型用法：
    scores = [85, 92, 67, 45, 78, 55, 90, 73, 88, 60]
    report = process_scores(scores)
    print_report(report)
"""

import logging
# 1. 导入 typing 模块中的大写类型，补充导入 Union 以支持多类型列表
from typing import List, Tuple, Dict, Any, Union

# 日志级别：DEBUG < INFO < WARNING < ERROR < CRITICAL
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
DEFAULT_PASS_SCORE = 60

GRADE_THRESHOLDS = [
    (90, "优秀"),
    (80, "良好"),
    (70, "中等"),
    (60, "及格"),
]
DEFAULT_GRADE = "不及格"

REPORT_SEPARATOR = "=" * 50
REPORT_SUB_SEPARATOR = "-" * 50


# ──────────────────────────────────────────────
# 输入校验 _为私有方法
# ──────────────────────────────────────────────
def _validate_scores(scores: List) -> None:
    """校验成绩列表的合法性。

    Args:
        scores: 待校验的成绩列表。

    Raises:
        TypeError: scores 不是列表，或列表元素不是数字。
        ValueError: scores 为空列表，或包含负数 / 超过100的值。
    """
    if not isinstance(scores, list):
        raise TypeError(f"成绩必须是列表类型，当前类型: {type(scores).__name__}")

    if len(scores) == 0:
        raise ValueError("成绩列表不能为空")

    for i, score in enumerate(scores):
        if not isinstance(score, (int, float)):
            raise TypeError(
                f"成绩列表第 {i} 个元素类型错误: {type(score).__name__}，期望 int 或 float"
            )
        if score < 0 or score > 100:
            raise ValueError(
                f"成绩列表第 {i} 个元素超出有效范围 [0, 100]: {score}"
            )


# ──────────────────────────────────────────────
# 核心函数
# ──────────────────────────────────────────────
def calculate_average(scores: List[float]) -> float:
    """计算成绩列表的平均分。

    Args:
        scores: 成绩列表，元素为 int 或 float，取值范围 [0, 100]。

    Returns:
        平均分（浮点数）。

    Raises:
        TypeError: scores 不是列表，或元素不是数字。
        ValueError: scores 为空，或元素超出 [0, 100]。

    Examples:
        >>> calculate_average([80, 90, 100])
        90.0
    """
    _validate_scores(scores)
    return sum(scores) / len(scores)


def find_max_min(scores: List[float]) -> Tuple[float, float]:
    """查找成绩列表中的最高分和最低分。

    Args:
        scores: 成绩列表。

    Returns:
        (最高分, 最低分) 的元组。

    Raises:
        TypeError: scores 不是列表，或元素不是数字。
        ValueError: scores 为空，或元素超出 [0, 100]。

    Examples:
        >>> find_max_min([80, 90, 60])
        (90, 60)
    """
    _validate_scores(scores)
    return max(scores), min(scores)


def count_pass_fail(
    scores: List[float],
    pass_score: float = DEFAULT_PASS_SCORE,
) -> Dict[str, int]:
    """统计及格和不及格的人数。

    Args:
        scores: 成绩列表。
        pass_score: 及格分数线，默认 60，取值范围 [0, 100]。

    Returns:
        包含 "及格人数" 和 "不及格人数" 的字典。

    Raises:
        TypeError: scores 不是列表，或元素不是数字。
        ValueError: scores 为空，或元素超出 [0, 100]，
                    或 pass_score 不在 [0, 100] 范围内。

    Examples:
        >>> count_pass_fail([80, 50, 60, 45])
        {'及格人数': 2, '不及格人数': 2}
    """
    _validate_scores(scores)

    if not isinstance(pass_score, (int, float)) or not (0 <= pass_score <= 100):
        raise ValueError(f"及格分数线必须在 [0, 100] 范围内，当前值: {pass_score}")

    pass_count = sum(1 for score in scores if score >= pass_score)

    return {
        "及格人数": pass_count,
        "不及格人数": len(scores) - pass_count,
    }


def get_grade(score: float) -> str:
    """根据单个分数返回对应的等级。

    等级划分规则：
        - 90 ~ 100: 优秀
        - 80 ~ 89:  良好
        - 70 ~ 79:  中等
        - 60 ~ 69:  及格
        - 0  ~ 59:  不及格

    Args:
        score: 单个分数，取值范围 [0, 100]。

    Returns:
        等级字符串。

    Raises:
        TypeError: score 不是数字。
        ValueError: score 超出 [0, 100]。

    Examples:
        >>> get_grade(85)
        '良好'
    """
    if not isinstance(score, (int, float)):
        raise TypeError(f"分数必须是数字，当前类型: {type(score).__name__}")
    if score < 0 or score > 100:
        raise ValueError(f"分数超出有效范围 [0, 100]: {score}")

    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade

    return DEFAULT_GRADE


def process_scores(
    scores: List[float],
    pass_score: float = DEFAULT_PASS_SCORE,
) -> Dict[str, Any]:
    """对成绩列表进行完整处理，返回汇总结果字典。

    内部依次调用 calculate_average、find_max_min、count_pass_fail、
    get_grade，将所有结果整合到一个字典中返回。

    Args:
        scores: 成绩列表。
        pass_score: 及格分数线，默认 60。

    Returns:
        包含以下键的字典：
            - "平均分" (float)
            - "最高分" (float)
            - "最低分" (float)
            - "及格人数" (int)
            - "不及格人数" (int)
            - "等级分布" (dict[str, int])
            - "各分数等级" (list[str])

    Raises:
        TypeError: scores 不是列表，或元素不是数字。
        ValueError: scores 为空，或元素超出 [0, 100]。

    Examples:
        >>> result = process_scores([85, 92, 67, 45])
        >>> result["平均分"]
        72.25
    """
    average = calculate_average(scores)
    max_score, min_score = find_max_min(scores)
    pass_fail = count_pass_fail(scores, pass_score)

    # 统计等级分布 + 记录每个分数的等级
    grade_distribution = {grade: 0 for _, grade in GRADE_THRESHOLDS}
    grade_distribution[DEFAULT_GRADE] = 0

    individual_grades = []
    for score in scores:
        grade = get_grade(score)
        individual_grades.append(grade)
        grade_distribution[grade] += 1

    logger.info(
        "成绩处理完成: 共 %d 人, 平均分 %.1f, 及格率 %.1f%%",
        len(scores),
        average,
        pass_fail["及格人数"] / len(scores) * 100,
    )

    return {
        "平均分": average,
        "最高分": max_score,
        "最低分": min_score,
        "及格人数": pass_fail["及格人数"],
        "不及格人数": pass_fail["不及格人数"],
        "等级分布": grade_distribution,
        "各分数等级": individual_grades,
    }


# ──────────────────────────────────────────────
# 输出展示
# ──────────────────────────────────────────────
def print_report(scores: List[Union[float, int]], result: Dict[str, Any]) -> None:
    """将 process_scores 的返回结果格式化打印为成绩报告。

    Args:
        scores: 原始成绩列表。
        result: process_scores 函数返回的字典。
    """
    total = result["及格人数"] + result["不及格人数"]
    pass_rate = result["及格人数"] / total * 100 if total > 0 else 0

    print(f"\n{REPORT_SEPARATOR}")
    print("            📊 成绩分析报告")
    print(REPORT_SEPARATOR)

    print(f"  平均分：{result['平均分']:.2f}")
    print(f"  最高分：{result['最高分']}")
    print(f"  最低分：{result['最低分']}")

    print(f"\n{REPORT_SUB_SEPARATOR}")
    print("  及格情况：")
    print(f"    及格人数：{result['及格人数']}人")
    print(f"    不及格人数：{result['不及格人数']}人")
    print(f"    及格率：{pass_rate:.1f}%")

    print(f"\n{REPORT_SUB_SEPARATOR}")
    print("  等级分布：")
    for grade, count in result["等级分布"].items():
        bar = "█" * count
        print(f"    {grade}：{count:>2}人  {bar}")

    print(f"\n{REPORT_SUB_SEPARATOR}")
    print("  各分数等级明细：")
    # 修正：使用 enumerate 获取索引 i，同时解包 zip 返回的 (score, grade) 元组
    for i, (score, grade) in enumerate(zip(scores, result["各分数等级"])):
        print(f"    分数[{i}] → {score}分 ({grade})")

    print(REPORT_SEPARATOR)


# ──────────────────────────────────────────────
# 主程序入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # 2. 补充配置日志格式
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    scores = [85, 92, 67, 45, 78, 55, 90, 73, 88, 100.0]

    try:
        result = process_scores(scores, pass_score=60)
        print_report(scores, result)
    except (TypeError, ValueError) as e:
        print(f"数据处理失败: {e}")