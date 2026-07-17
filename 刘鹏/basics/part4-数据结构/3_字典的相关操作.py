# ============================================================================
# 作业三：字典操作 - 学生信息管理
# ============================================================================
#
# 任务描述：
# 编写一个学生信息管理程序，实现以下功能：
# 1. 创建一个字典，存储一个学生的信息：
#    - 姓名、年龄、学号、数学成绩、语文成绩、英语成绩
# 2. 计算该学生的总分和平均分，并添加到字典中
# 3. 根据平均分判断等级，并添加到字典中（等级判断规则同作业二）
# 4. 使用for循环遍历字典，打印所有信息
# 5. 提示用户输入要修改的科目和新的成绩，更新字典
# 6. 重新计算总分、平均分和等级
# 7. 输出更新后的学生信息
#
# 要求：
# - 使用字典存储学生信息
# - 使用字典的键访问和修改值
# - 使用字典的items()方法遍历
# - 使用条件语句进行等级判断
# - 添加适当的注释

# 版本一 手搓以及问题修改
def student_info():
    """
    学习字典相关知识
    """
    # 1.创建一个字典，存储学生的信息
    student = {
        "姓名": "张三",
        "年龄": "15",
        "学号": "20260001",
        "数学": 99,
        "英语": 89,
        "语文": 59
    }

    # 2.计算总分和平均分，并放到字典中
    total_score = student.get("数学") + student.get("英语") + student.get("语文")

    average_score = total_score / 3
    """
    这里对于setdefault的方法使用错误：
    setdefault(key, value) 的底层逻辑是：如果 key 存在，就返回原值，什么都不做；只有当 key 不存在时，才插入新的 value
    对于确定要更新或覆盖的字段，必须使用 dict[key] = value
    """
    # student.setdefault("总分", total_score)
    # student.setdefault("平均分", average_score)
    student["总分"] = total_score
    student["平均分"] = average_score

    if average_score >= 90:
        grade = "优秀"
    elif average_score >= 80:
        grade = "良好"
    elif average_score >= 70:
        grade = "中等"
    elif average_score >= 60:
        grade = "及格"
    else:
        grade = "不及格"

    # student.setdefault("等级", grade)
    student["等级"] = grade

    for key, value in student.items():
        if key == "平均分":
            print(f"{key}:{value:.2f}")
        else:
            print(f"{key}：{value}")

    subject = input("请输入要修改的科目信息：")
    score = input("请输入对应的学习成绩：")

    while True:
        if subject in student:
            try:
                score = float(score)
            except ValueError:
                print("输入的成绩格式不对")

            student.update({subject: score})

            total_score = student.get("数学") + student.get("英语") + student.get("语文")

            average_score = total_score / 3

            student["总分"] = total_score
            student["平均分"] = average_score

            if average_score >= 90:
                grade = "优秀"
            elif average_score >= 80:
                grade = "良好"
            elif average_score >= 70:
                grade = "中等"
            elif average_score >= 60:
                grade = "及格"
            else:
                grade = "不及格"

            student["等级"] = grade

            for key, value in student.items():
                print(f"{key}：{value}")
            break
        else:
            print(f"输入的学科不存在：{subject}")
            subject = input("请重新输入要修改的科目信息：")


# 版本二：生产级的应用
def calculate_grade(average_score: float) -> str:
    """将等级判断逻辑抽离为独立的函数，实现代码复用"""
    if average_score >= 90:
        return "优秀"
    elif average_score >= 80:
        return "良好"
    elif average_score >= 70:
        return "中等"
    elif average_score >= 60:
        return "及格"
    return "不及格"


def update_student_stats(student: dict) -> None:
    """
    统一处理成绩统计与更新
    无论初始化还是修改成绩，都调用此函数
    """
    # 提取所有科目成绩（通过键名特征过滤，避免把年龄等算进去）
    subjects = ["数学","英语","语文"]

    try:
        total = sum(student[sub] for sub in subjects)
    except TypeError as e:
        print(f"成绩数据格式异常，请检查字典数据：{e}")
        total = 0  # 给予默认值，防止程序崩溃

    average = total / len(subjects)
    # 使用直接赋值（修复 setdefault 的 Bug）
    student["总分"] = total
    student["平均分"] = round(average, 2)
    student["等级"] = calculate_grade(average)


def print_student_info(student: dict) -> None:
    """格式化打印学生信息"""
    print("=" * 20)
    for key, value in student.items():
        # 统一格式化输出，如果是平均分保留两位小数
        if key == "平均分":
            print(f"{key}：{value:.2f}")
        else:
            print(f"{key}：{value}")
    print("=" * 40)


def student_info_refactor():
    """主交互数据"""
    student = {
        "姓名": "张三", "年龄": 15, "学号": "20260001",
        "数学": 99, "英语": 89, "语文": 59
    }

    # 初始化统计
    update_student_stats(student)
    print_student_info(student)

    # 交互式修改
    while True:
        subject = input("\n请输入要修改的科目（数学/英语/语文，输入q退出）：").strip()
        if subject.lower() == ":q":
            break

        if subject not in student:
            print(f"错误：'{subject}' 不是有效的科目！")
            continue

        try:
            new_score = float(input(f"请输入 {subject} 的新成绩："))
            student[subject] = new_score

            # 复用统计函数
            update_student_stats(student)
            print("\n更新成功！最新信息如下：")
            print_student_info(student)
            break

        except ValueError:
            print("成绩必须是数字，请重新输入！")


if __name__ == "__main__":
    #student_info()
    student_info_refactor()
