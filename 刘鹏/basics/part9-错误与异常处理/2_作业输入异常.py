# ============================================================================
# 作业二：用户输入验证 - 安全的用户输入处理
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现安全的用户输入验证功能：
# 1. 编写一个get_positive_int函数
#    - 提示用户输入一个正整数
#    - 使用try-except处理输入错误（ValueError）
#    - 验证输入是否为正整数
#    - 如果输入无效，给出提示并让用户重新输入
#    - 使用循环直到输入有效
# 2. 编写一个get_age函数
#    - 获取用户年龄（0-150之间）
#    - 使用异常处理验证输入
#    - 处理非数字输入和超出范围的情况
# 3. 编写一个get_score函数
#    - 获取用户分数（0-100之间）
#    - 支持小数输入
#    - 使用异常处理验证输入
# 4. 在主程序中测试这些函数
#
# 要求：
# - 使用while循环实现重试机制
# - 捕获ValueError处理输入错误
# - 提供清晰的错误提示
# - 使用KeyboardInterrupt处理用户中断（Ctrl+C）
# - 添加适当的注释

# ============================================================================
# 作业二：用户输入验证 - 安全的用户输入处理
# ============================================================================


def get_positive_int():
    """
    获取用户输入的正整数
    - 使用while循环持续提示，直到输入有效
    - 使用try-except处理非数字输入
    - 使用KeyboardInterrupt处理Ctrl+C中断
    """
    while True:
        try:
            user_input = input("请输入一个正整数：")
            num = int(user_input)

            if num <= 0:
                print(f"提示：{num} 不是正整数，请重新输入！\n")
                continue

        except ValueError:
            print(f"提示：'{user_input}' 不是有效的整数，请重新输入！\n")
            continue
        except KeyboardInterrupt:
            print("\n用户取消了输入（Ctrl+C）")
            return None

        # 走到这里说明输入合法，退出循环
        return num


def get_age():
    """
    获取用户年龄（0-150之间）
    - 处理非数字输入（ValueError）
    - 处理超出范围的情况
    直接将输入的信息 str -> int 来通过先转然后再捕获异常，对比isintance+raise的区别
    """
    while True:
        try:
            user_input = input("请输入年龄（0-150）：")
            age = int(user_input)

            if age < 0 or age > 150:
                print(f"提示：年龄 {age} 超出范围（0-150），请重新输入！\n")
                continue

        except ValueError:
            print(f"提示：'{user_input}' 不是有效的整数，请重新输入！\n")
            continue
        except KeyboardInterrupt:
            print("\n用户取消了输入（Ctrl+C）")
            return None

        return age


def get_score():
    """
    获取用户分数（0-100之间，支持小数）
    - 使用float()转换，支持小数输入
    - 处理非数字输入和超出范围的情况
    """
    while True:
        try:
            user_input = input("请输入分数（0-100）：")
            score = float(user_input)

            if score < 0 or score > 100:
                print(f"提示：分数 {score} 超出范围（0-100），请重新输入！\n")
                continue

        except ValueError:
            print(f"提示：'{user_input}' 不是有效的数字，请重新输入！\n")
            continue
        except KeyboardInterrupt:
            print("\n用户取消了输入（Ctrl+C）")
            return None

        return score


if __name__ == "__main__":
    print("=" * 40)
    print(" 用户输入验证系统")
    print("=" * 40)

    # 测试 get_positive_int
    print("\n【测试1】获取正整数")
    num = get_positive_int()
    if num is not None:
        print(f"你输入的正整数是：{num}")
    else:
        print("未获取到有效输入")

    # 测试 get_age
    print("\n【测试2】获取年龄")
    age = get_age()
    if age is not None:
        print(f" 你的年龄是：{age} 岁")
    else:
        print("未获取到有效输入")

    # 测试 get_score
    print("\n【测试3】获取分数")
    score = get_score()
    if score is not None:
        print(f"你的分数是：{score}")
    else:
        print("未获取到有效输入")

    # 汇总显示
    if num is not None and age is not None and score is not None:
        print("\n" + "=" * 40)
        print(" 输入汇总")
        print("=" * 40)
        print(f"  正整数：{num}")
        print(f"  年龄：  {age}")
        print(f"  分数：  {score}")
        print("=" * 40)