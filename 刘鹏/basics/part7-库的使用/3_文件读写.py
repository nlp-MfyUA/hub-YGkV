# ============================================================================
# 作业三：文件读写 - 学生信息管理
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 创建一个学生信息列表（至少3个学生）
# 2. 将学生信息写入文件（每个学生一行，信息用逗号分隔）
# 3. 从文件读取学生信息
# 4. 解析并显示学生信息
# 5. 在文件末尾追加新学生信息
#
# 要求：
# 文件格式示例：
# 张三,20,85,90,88
# 李四,19,92,88,90
#
# - 使用open()函数打开文件
# - 使用write()写入文件
# - 使用read()或readlines()读取文件
# - 处理文件编码（utf-8）
# - 使用with语句（推荐）或记得关闭文件


import os

FILE_NAME = "student.csv"

# 学生信息列表
students = [
    {"name": "张三", "age": 20, "scores": [85, 90, 88]},
    {"name": "李四", "age": 19, "scores": [92, 88, 90]},
    {"name": "王五", "age": 21, "scores": [78, 85, 82]},
]

# 将学生信息写入文件，覆盖写入

def write_students(students, filename):
    """将学生列表写入文件"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("姓名,年龄,语文,数学,英语,平均分\n")
        for stu in students:
            # 将分数列表转为字符串，再和姓名、年龄拼接
            scores_str = ",  ".join(map(str, stu["scores"]))
            line = f"{stu['name']},  {stu['age']},  {scores_str},  {calcuate_avager(stu['scores']):.2f}\n"
            f.write(line)
    print(f"写入 {len(students)} 条学生信息到 {filename}")

def calcuate_avager(scores: list):
    return sum(scores) / len(scores)


def read_and_display_students(filename):
    """读取文件并格式化显示"""
    if not os.path.exists(filename):
        print(f"文件：{filename}不存在")
        return
    
    print("\n" + "=" * 45)
    print(f" 学生信息列表 ({filename})")
    print("=" * 45)
    print(f" {'姓名':<6} {'年龄':<4} {'语文':<4} {'数学':<4} {'英语':<4} {'平均分':<6}")
    print("-" * 45)


    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[1:]:  # 跳过开头的字段
        line = line.strip()  # 去掉末尾换行符
        if not line:         # 跳过空行
            continue
        parts = line.split(",")
        name = parts[0]
        age = parts[1]
        scores = list(map(int, parts[2:5]))  # 只取第3~5列（语文、数学、英语）
        avg = calcuate_avager(scores)
        print(f" {name:<6} {age:<4} {scores[0]:<4} {scores[1]:<4} {scores[2]:<4} {avg:<6.1f}")

    print("=" * 45)


def append_student(filename, name, age, scores):
    """在文件末尾追加一条学生记录"""
    scores_str = ",  ".join(map(str, scores))
    avg = calcuate_avager(scores)
    line = f"{name},  {age},  {scores_str},  {avg:.2f}\n"

    with open(filename, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"已追加学生: {name}")


if __name__ == "__main__":
    # 步骤1 & 2: 创建并写入
    write_students(students, FILE_NAME)

    # 步骤3 & 4: 读取并显示
    read_and_display_students(FILE_NAME)

    # 步骤5: 追加新学生
    append_student(FILE_NAME, "赵六", 20, [95, 98, 92])

    # 再次读取，验证追加是否成功
    read_and_display_students(FILE_NAME)