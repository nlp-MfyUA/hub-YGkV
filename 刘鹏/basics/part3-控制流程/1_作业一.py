# 本部分作业共5道题，从简单到复杂，帮助巩固以下知识点：
# - 条件语句（if、if-else、if-elif-else、嵌套条件）
# - 循环结构（while循环、for循环、range()函数）
# - break和continue语句
# - 循环嵌套
#
# 注意：本部分作业只使用已学过的知识
# - 可以使用：变量、数据类型、运算符、输入输出、条件语句、循环结构
# - 不使用：列表、字典、函数、类等后续内容
#
# ============================================================================
# 作业一：条件语句基础
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 提示用户输入一个整数
# 2. 判断这个数字是正数、负数还是零
# 3. 判断这个数字是奇数还是偶数
# 4. 判断这个数字是否在0到100之间（包含0和100）
# 5. 根据以上判断，输出详细的分析结果
#
# 要求：
# - 使用if-else或if-elif-else语句
# - 使用比较运算符和逻辑运算符
# - 输出格式要清晰美观
# - 添加适当的注释


def main():

    # 输入信息
    input_info = input("请用户输入一个整数：")
    input_info_int = int(input_info)

    if(input_info_int > 0):
        print(f"输入的数字是正数：{input_info}")
    elif(input_info_int < 0):
        print(f"输入的数字是负数：{input_info}")
    elif(input_info_int == 0):
        print(f"输入的数字是零：{input_info}")


    if (input_info_int % 2 == 0):
        print(f"输入的数字是偶数: {input_info_int}")
    else:
        print(f"输入的数字是计数：{input_info_int}")

    if(input_info_int >= 0 and input_info_int <= 100):
        print(f"输入的数字在0到100")
    else:
        print(f"不在0到100之间")





if __name__ == "__main__":
    main();