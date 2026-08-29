# ============================================================================
# 作业五：综合应用 - 简单计算器与菜单系统
# ============================================================================
#
# 任务描述：
# 编写一个带菜单的简单计算器程序，实现以下功能：
# 1. 显示菜单选项：
#    - 1. 加法
#    - 2. 减法
#    - 3. 乘法
#    - 4. 除法
#    - 5. 退出
# 2. 使用while循环让程序可以重复执行，直到用户选择退出
# 3. 根据用户选择的菜单项，提示输入两个数字
# 4. 执行相应的运算并输出结果
# 5. 对于除法运算，需要判断除数是否为0，如果为0则提示错误
# 6. 每次运算后，重新显示菜单


def main():
    #实现记录上一次的结果
    last_result = None
    while True:
        # 显示菜单
        print("\n" + "#" * 40)
        print("       欢迎使用简易计算器")
        print("#" * 40)
        print("  1. 加法")
        print("  2. 减法")
        print("  3. 乘法")
        print("  4. 除法")
        print("  5. 退出")
        print("#" * 40)

        # 先让用户选择菜单项
        choice = input("请选择操作（1-5）：").strip()

        # 退出判断（放在最前面，不用输入数字）
        if choice == "5":
            print("已退出计算器，感谢使用！")
            break

        # 校验菜单选择是否合法
        if choice not in ("1", "2", "3", "4"):
            print("无效选择，请输入 1-5 之间的数字！")
            continue

        # 输入两个数字
        if last_result is not None:
            use_last = input(f"是否使用上次结果 {last_result} 作为数字1？(y/n)：").strip().lower()
            if use_last == "y":
                number1 = last_result
            else:
                try:
                    number1 = float(input("请输入数字1："))
                except ValueError:
                    print("请输入有效的数字！")
                    continue
        else:
            try:
                number1 = float(input("请输入数字1："))
            except ValueError:
                print("请输入有效的数字！")
                continue

        try:
            number2 = float(input("请输入数字2："))
        except ValueError:
            print("请输入有效的数字！")
            continue

        # 根据菜单选择执行对应运算
        if choice == "1":
            result = number1 + number2
            symbol = "+"
        elif choice == "2":
            result = number1 - number2
            symbol = "-"
        elif choice == "3":
            result = number1 * number2
            symbol = "*"
        elif choice == "4":
            if number2 == 0:
                print(" 错误：除数不能为 0！")
                continue  # 跳过本次，回到菜单
            result = number1 / number2
            symbol = "/"

        # 格式化输出结果（整数去小数点）
        if result == int(result):
            result = int(result)
        last_result = result
        print(f"计算结果：{number1} {symbol} {number2} = {result}")


if __name__ == "__main__":
    main()