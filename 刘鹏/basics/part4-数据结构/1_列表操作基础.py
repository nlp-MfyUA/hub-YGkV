from typing import List


# ============================================================================
# 作业一：列表操作基础
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 创建一个空列表，用于存储学生姓名
# 2. 使用循环提示用户输入5个学生的姓名，并添加到列表中
# 3. 使用for循环遍历列表，打印所有学生姓名
# 4. 计算并打印列表的长度
# 5. 提示用户输入一个要查找的姓名，判断该姓名是否在列表中
# 6. 如果存在，打印该姓名在列表中的位置（索引）
#
# 要求：
# - 使用列表的append()方法添加元素
# - 使用len()函数获取列表长度
# - 使用in关键字判断元素是否存在
# - 使用index()方法查找索引（如果存在）
# - 添加适当的注释


# 版本一：手搓先实现功能
def list_test():
    """
    列表相关知识的学习
    """

    # 1. 创建一个空列表，用于存储学生姓名
    my_list = list()

    count = 0

    # 2. 使用循环提示用户输入5个学生的姓名，并添加到列表中
    while count < 5:
        name = input("请输入您的姓名：")
        my_list.append(name)
        count += 1

    # 3. 使用for循环遍历列表，打印所有学生姓名
    for i in my_list:
        print(i)

    # 4. 计算并打印列表的长度
    print(f"集合的长度是：{len(my_list)}")

    # 5. 提示用户输入一个要查找的姓名，判断该姓名是否在列表中
    input_name = input("请输入一个查找人的姓名：")

    # 6. 如果存在，打印该姓名在列表中的位置（索引）
    for i, value in enumerate(my_list, start=1):
        if value == input_name:
            print(f"存在{value}的姓名，他是第{i}位")


# 版本二：代码未来的样子
def get_student_names(count: int = 5) -> List[str]:
    """
    获取指定数量的学生姓名，
    将I/O交互与业务逻辑分离，方便后续进行单元测试
    """
    students = []
    for i in range(count):
        # 生产环境中应处理用户输入异常或者空输入，这里做基础的去空格处理
        name = input(f"请输入第{i + 1}位学生的姓名：").strip()
        if name:
            students.append(name)
        else:
            print("姓名不能为空，请重新输入")
            # 实际的生产过程中可能会使用while循环强制要求输入，此处简化演示
    return students


def find_student_index(students: List[str], target_name: str) -> int:
    """
    在列表中查找学生姓名，返回其索引（从1开始）
    使用内置方法替代手写循环，将时间复杂度从o(n)优化
    """
    try:
        return students.index(target_name) + 1
    except ValueError:
        return -1


def main():
    """主入口函数，负责流程编排"""
    # 1.获取主数据
    student_list = get_student_names(5)

    if not student_list:
        print("为获取到任何有效的学生姓名，程序退出")
        return

        # 2. 展示数据
    print("\n -- 学生名单--")
    for idx, name in enumerate(student_list):
        print(f"{idx}. {name}")
    print(f"共计{len(student_list)}人。\n")

    # 3.查找数据
    search_name = input("请输入要查找的姓名：").strip()

    index = find_student_index(student_list, search_name)

    if index != -1:
        print(f"找到{search_name}，他是第{index}位学生")
    else:
        print(f"列表中不存在{search_name}")


if __name__ == "__main__":
    # list_test()
    main()
