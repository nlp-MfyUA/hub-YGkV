# ============================================================================
# 作业三：while循环 - 数字累加器
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 提示用户输入一个正整数n
# 2. 使用while循环计算1到n的所有整数的和
# 3. 使用while循环计算1到n的所有偶数的和
# 4. 使用while循环计算1到n的所有奇数的和
# 5. 输出三个计算结果
#
# 要求：
# - 使用while循环
# - 注意循环条件的设置，避免无限循环
# - 使用取余运算符（%）判断奇偶数
# - 添加适当的注释说明
#
# 示例：
# 如果输入n=10，应该输出：
# 1到10的和：55
# 1到10的偶数和：30
# 1到10的奇数和：25


def main():

    #请用户输入一个正整数
    input_info = input("请输入一个正整数n:")
    input_info_int = int(input_info)

    total_all = 0
    total_even = 0
    total_odd = 0

    i = 1

    while(i <= input_info_int):
        total_all = total_all + i
        
        if(i % 2 == 0):
            total_even = total_even + i
        elif(i % 2 != 0):
            total_odd = total_odd + i
            
        i = i + 1
        
    print(f"1到{input_info_int}的所有整数的和：{total_all}")
    print(f"1到{input_info_int}的所有偶数的和：{total_even}")
    print(f"1到{input_info_int}的所有奇数的和：{total_odd}")


if __name__ == "__main__":
    main()