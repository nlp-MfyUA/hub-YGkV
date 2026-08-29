# ============================================================================
# 作业二：多条件判断 - 成绩等级系统
# ============================================================================
#
# 任务描述：
# 编写一个成绩等级评定程序，实现以下功能：
# 1. 提示用户输入学生的姓名和三科成绩（数学、语文、英语）
# 2. 计算总分和平均分
# 3. 根据平均分判断等级：
#    - 90分及以上：优秀
#    - 80-89分：良好
#    - 70-79分：中等
#    - 60-69分：及格
#    - 60分以下：不及格
# 4. 判断每科是否及格（大于等于60分）
# 5. 输出格式化的成绩单，包括：
#    - 学生姓名
#    - 各科成绩
#    - 总分和平均分
#    - 等级评定
#    - 每科的及格情况
#
# 要求：
# - 使用if-elif-else语句进行等级判断
# - 使用嵌套条件或逻辑运算符判断每科及格情况
# - 平均分保留两位小数
# - 输出格式要清晰，可以使用分隔线



def main():

    student_name = input("请输入学生姓名：")

    math_str = input("请输入数学成绩：")
    chinese_str = input("请输入语文成绩：")
    english_str = input("请输入英语成绩：")

    # str 转 float 保留两位小数
    math_score = round(float(math_str), 2)
    chinese_score = round(float(chinese_str), 2)
    english_score = round(float(english_str), 2)

    # 计算总分
    total_score = math_score + chinese_score + english_score

    # 计算平均分
    average_score = total_score / 3

    # 判断总分的状态
    if(average_score >= 90):
        info = "优秀"
    elif(average_score >= 80):
        info = "良好"
    elif(average_score >= 70):
        info = "中等"
    elif(average_score >= 60):
        info = "及格"
    else:
        info = "不及格"


    # 数学是否及格
    if(math_score >= 60):
        math_info = "及格"
    else:
        math_info = "不及格"


    # 中文是否及格
    if(chinese_score >= 60):
        chinese_info = "及格"
    else:
        chinese_info = "不及格"

    # 英文是否及格
    if(english_score >= 60):
        english_info = "及格"
    else:
        english_info = "不及格"

    
    print("=" * 50)
    print("成绩单")
    print(f"学生姓名：{student_name}")

    print(f"数学成绩：{math_score}分({math_info})")
    print(f"语文成绩：{chinese_score}分({chinese_info})")
    print(f"英文成绩：{english_score}分({english_info})")

    print(f"总分：{total_score}分")

    print(f"平均分：{average_score:.2f}分")
    print(f"等级评定：{info}")

    print("=" * 50)


if __name__ == "__main__":
    main()







