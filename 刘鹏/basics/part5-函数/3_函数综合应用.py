# ============================================================================
# 作业三：函数综合应用 - 学生管理系统
# ============================================================================
#
# 任务描述：
# 编写一个学生管理系统，定义以下函数：
# 1. create_student(name, age, scores)：创建并返回一个学生字典，scores也是一个字典，记录三个科目的成绩
# 2. calculate_student_average(student)：计算学生的平均分并更新字典
# 3. get_student_grade(student)：根据平均分判断等级并更新字典
# 4. display_student_info(student)：格式化显示学生信息
# 5. add_student(students_list, name, age, scores)：向学生列表添加新学生
# 6. find_student(students_list, name)：在学生列表中查找指定姓名的学生
# 7. get_class_average(students_list)：计算班级平均分
#
# 在主程序中：
# - 创建一个空的学生列表
# - 使用循环添加至少3个学生
# - 显示所有学生信息
# - 查找并显示指定学生的信息
# - 显示班级平均分
#
# 要求：
# - 使用函数组织代码
# - 函数之间可以相互调用
# - 使用列表和字典存储数据
# - 添加详细的注释

DEFAULT_PASS_SCORE = 60

GRADE_THRESHOLDS = [
    (90, "优秀"),
    (80, "良好"),
    (70, "中等"),
    (60, "及格"),
]
DEFAULT_GRADE = "不及格"


def create_student(name, age, scores):
    """创建一个学生字典"""
    student_dict = {
        "姓名": name,
        "年龄": age,
        "数学": scores["数学"],
        "语文": scores["语文"],
        "英语": scores["英语"]
    }
    return student_dict


def calculate_student_average(student):
    """计算学生的平均分并更新字典"""
    score_sum = student["数学"] + student["语文"] + student["英语"]
    score_avg = score_sum / 3
    student["平均值"] = score_avg


def get_student_grade(student):
    """根据平均分判断等级并更新字典"""
    if not isinstance(student["平均值"], (int, float)):
        raise TypeError(f"分数必须是数字，当前类型：{type(student['平均值']).__name__}")
    if student["平均值"] < 0 or student["平均值"] > 100:
        raise ValueError(f"分数超出有效范围[0, 100]: {student['平均值']}")
    for threshold, grade in GRADE_THRESHOLDS:
        if student["平均值"] >= threshold:
            student['等级'] = grade
            return

    student['等级'] = DEFAULT_GRADE


def display_student_info(student):
    """格式化显示学生信息"""
    print(f"姓名：{student['姓名']}，年龄：{student['年龄']}岁")
    print(f"  数学：{student['数学']}分，语文：{student['语文']}分，英语：{student['英语']}分")
    print(f"  平均分：{student['平均值']:.2f}分，等级：{student['等级']}")


def add_student(students_list, name, age, scores):
    """向学生列表添加新学生"""
    student = create_student(name, age, scores)
    calculate_student_average(student)
    get_student_grade(student)
    students_list.append(student)


def find_student(students_list, name):
    """在学生列表中查找指定姓名的学生"""
    for student in students_list:
        if student["姓名"] == name:
            return student
    return None


def get_class_average(students_list):
    """计算班级平均分"""
    return sum(student["平均值"] for student in students_list) / len(students_list)


if __name__ == "__main__":
    student_list = []
    add_student(student_list,"小米","25",{"数学": 100, "语文": 80, "英语": 60})
    add_student(student_list,"小王","35",{"数学": 98, "语文": 75, "英语": 50})
    add_student(student_list, "小明", "45", {"数学": 95, "语文": 70, "英语": 60})
    find_name = input("请输入要查找的学生姓名：")
    found_student = find_student(student_list, find_name)

    if found_student:
        print("\n找到学生：")
        display_student_info(found_student)
    else:
        print(f"\n未找到姓名为 '{find_name}' 的学生！")

    for idx,student in enumerate(student_list):
        print(f"第{idx + 1}个学生的信息")
        display_student_info(student)
        print("\n")

    print(f"整个班级的平均分：{get_class_average(student_list):.2f}")


