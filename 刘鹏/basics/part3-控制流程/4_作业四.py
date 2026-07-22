# ============================================================================
# 作业四：for循环与range()函数
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 使用for循环和range()函数打印1到20的所有数字
# 2. 使用for循环和range()函数打印1到20的所有偶数
# 3. 使用for循环和range()函数打印1到20的所有奇数
# 4. 使用for循环和range()函数倒序打印20到1
# 5. 使用for循环计算1到10的乘积（阶乘）
# 6. 使用for循环遍历一个字符串，统计其中某个字符出现的次数
#    （提示：可以让用户输入一个字符串和一个要查找的字符）
#
# 要求：
# - 使用for循环和range()函数
# - 使用字符串遍历
# - 输出格式要清晰
# - 添加适当的注释


def main():

    # 1. 使用for循环和range()函数打印1到20的所有数字
    # range(1,21)生成从1到20的所有数字
    for i in range(1, 21):
        print(i, end=" ")
    print() # 换行

    print("=" * 50)


    # 2. 使用for循环和range()函数打印1到20的所有偶数
    for i in range(2,21,2):
        print(i, end=" ")
    print()

    print("=" * 50)

    # 3. 使用for循环和range()函数打印1到20的所有奇数
    for i in range(1,21,2):
        print(i, end= " ")
    print()

    print("=" * 50)


    # 4. 使用for循环和range()函数倒序打印20到1
    for i in range(20, 0, -1):
        print(i, end= " ")
    print()

    # 5. 使用for循环计算1到10的乘积（阶乘）
    a = 1
    for i in range(1, 11):
        a = a * i
    print(f"1到10的乘积 = {a}")

    # 6. 使用for循环遍历一个字符串，统计其中某个字符出现的次数
    input_info = input("请输入一个字符串：")
    search_char = input("请输入查找的字符的信息")
    count = 0
    for char in input_info:
        if(char ==  search_char):
            count = count + 1
    print(f"出现次数的汇总：{count}")


if __name__ == "__main__":
    main()
