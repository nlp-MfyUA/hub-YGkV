# ============================================================================
# 作业四：列表与字典结合 - 多学生管理系统
# ============================================================================
#
# 任务描述：
# 编写一个多学生管理系统，实现以下功能：
# 1. 创建一个列表，列表中每个元素是一个字典，存储一个学生的信息
#    （至少包含3个学生的信息）
# 2. 使用for循环遍历列表，打印所有学生的基本信息（姓名、年龄、成绩等）
# 3. 计算所有学生的平均分，并找出平均分最高的学生
# 4. 统计每个等级的人数（优秀、良好、中等、及格、不及格）
# 5. 提示用户输入一个学生姓名，查找并显示该学生的详细信息
# 6. 如果找到，允许用户修改该学生的某科成绩
#
# 要求：n
# - 使用列表存储多个字典
# - 使用嵌套循环（外层遍历列表，内层遍历字典）
# - 使用条件语句进行判断和查找
# - 输出格式要清晰美观
# - 添加详细的注释


def student_system():
    """
    初版本，先实现功能
    """
    student_info = [
      {"姓名": "王林","年龄": 150,"性别": "男","英语成绩": 99.5, "语文成绩": 85},
      {"姓名": "木婉清","年龄": 100,"性别": "女","英语成绩": 99.5, "语文成绩": 89},
      {"姓名": "李慕婉","年龄": 50,"性别": "女","英语成绩": 80.5, "语文成绩": 75},
      {"姓名": "王平","年龄": 30,"性别": "男","英语成绩": 60.5, "语文成绩": 65}
    ]

    # 2. 使用for循环遍历列表，打印所有学生的基本信息（姓名、年龄、成绩等）
    for student in student_info:
        for key, value in student.items():
            print(f"{key}:{value}")
        print("\n")

    # 3. 计算所有学生的平均分，并找出平均分最高的学生
    for student in student_info:
        avg = round((student["英语成绩"] + student["语文成绩"] ) / 2, 2)
        student["平均成绩"] = avg
        print(f"{student['姓名']}:{student['平均成绩']}")

    # 最高分
    best = student_info[0]

    for student in student_info:
        if student["平均成绩"] > best["平均成绩"]:
            best = student
    
    print(f"最高成绩平均分是:{best['姓名']}")

    # 4. 统计每个等级的人数（优秀、良好、中等、及格、不及格）

    excellent = 0
    good = 0
    average = 0
    pas = 0
    fail = 0
    
    for student in student_info:
        if student["平均成绩"] >= 90:
            excellent += 1
        elif student["平均成绩"] >= 80:
            good += 1
        elif student["平均成绩"] >= 70:
            average += 1
        elif student["平均成绩"] >= 60:
            pas += 1
        elif student["平均成绩"] < 60:
            fail += 1
    
    print(f"优秀{excellent}, 良好:{good}, 中等:{average}, 及格:{pas}, 不及格：{fail}")


    # 5. 提示用户输入一个学生姓名，查找并显示该学生的详细信息
    name = input("请输入一个学生的姓名：")
    # result = [student for student in student_info if student["姓名"] == name]
    result = next((s for s in student_info if s["姓名"] == name), None)
    # 6. 如果找到，允许用户修改该学生的某科成绩
    if result:
        print(result)
        subjects = ["英语成绩","语文成绩"]
        subject = input("请输入你要修改的科目：")
        if subject in subjects:
            score = input("请输出对应的成绩：")
            try:
                score = int(score)
                # 这个地方需要优化
                if subject == "英语成绩":
                    result["英语成绩"] = score
                if subject == "语文成绩":
                    result["语文成绩"] = score
            except ValueError as e:
                print("输入的成绩存在问题")
    else:
        print("未找到该学生")

    print(f"{student_info}")


def student_system_refactor():
    """多学生管理系统 重构版 生产级代码"""

    # ---- 数据 ----
    subjects = ["语文", "数学", "英语"]
    students = [
        {"姓名": "王林",   "年龄": 15, "语文": 85,  "数学": 92,  "英语": 99.5},
        {"姓名": "木婉清", "年龄": 16, "语文": 89,  "数学": 95,  "英语": 99.5},
        {"姓名": "李慕婉", "年龄": 15, "语文": 75,  "数学": 68,  "英语": 80.5},
        {"姓名": "王平",   "年龄": 14, "语文": 65,  "数学": 58,  "英语": 60.5},
    ]

    # ---- 计算平均分 ----
    for s in students:
        total = sum(s[sub] for sub in subjects)
        s["平均分"] = round(total / len(subjects), 2)

    # ---- 打印所有学生 ----
    print("=" * 50)
    print("  所有学生信息")
    print("=" * 50)
    for s in students:
        for key, value in s.items():
            suffix = " 分" if key in subjects or key == "平均分" else ""
            print(f"  {key}：{value}{suffix}")
        print("-" * 50)

    # ---- 找最高分 ----
    best = max(students, key=lambda s: s["平均分"])
    print(f"\n  最高平均分：{best['姓名']}（{best['平均分']} 分）")

    # ---- 全体平均分 ----
    overall = round(sum(s["平均分"] for s in students) / len(students), 2)
    print(f"  全体平均分：{overall} 分")

    # ---- 等级统计 ----
    grade_count = {"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0}
    for s in students:
        avg = s["平均分"]
        if avg >= 90:   grade_count["优秀"] += 1
        elif avg >= 80: grade_count["良好"] += 1
        elif avg >= 70: grade_count["中等"] += 1
        elif avg >= 60: grade_count["及格"] += 1
        else:           grade_count["不及格"] += 1

    print(f"\n  等级统计：")
    for grade, count in grade_count.items():
        print(f"  {grade}：{count} 人  {'█' * count}")

    # ---- 查找并修改 ----
    name = input("\n  请输入要查找的学生姓名：").strip()
    student = next((s for s in students if s["姓名"] == name), None)

    if not student:
        print(f"  未找到【{name}】")
        return

    print(f"\n  找到学生：")
    for key, value in student.items():
        print(f"  {key}：{value}")

    subject = input(f"\n  要修改哪科？（{'/'.join(subjects)}）：").strip()
    if subject not in subjects:
        print(f"  无效科目：{subject}")
        return

    try:
        new_score = float(input(f"  请输入新的{subject}成绩："))
        if not (0 <= new_score <= 150):
            print("   成绩须在 0~150 之间")
            return
    except ValueError:
        print("  输入不是有效数字")
        return

    student[subject] = new_score
    total = sum(student[sub] for sub in subjects)
    student["平均分"] = round(total / len(subjects), 2)

    print(f"\n  修改成功！更新后：")
    for key, value in student.items():
        print(f"  {key}：{value}")





if __name__ == "__main__":
    student_system_refactor()