# 第九部分-错误处理与异常处理 作业说明
# 
# 本部分作业共4道题，从简单到复杂，帮助巩固以下知识点：
# - 使用try-except捕获和处理异常
# - 处理不同类型的异常（ValueError、TypeError、FileNotFoundError等）
# - 使用try-except-else-finally
# - 异常处理在实际应用中的使用
#
# 注意：本部分作业可以使用之前学过的所有知识
# - 变量、数据类型、运算符、输入输出
# - 条件语句、循环结构
# - 列表、字典等数据结构
# - 函数
# - 类
# - 文件操作
# - 异常处理
#
# ============================================================================
# 作业一：基础异常处理 - 安全的数值计算
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现安全的数值计算功能：
# 1. 编写一个safe_divide函数，实现安全的除法运算
#    - 接收两个参数：被除数和除数
#    - 使用try-except捕获ZeroDivisionError（除数为0）
#    - 使用try-except捕获TypeError（参数不是数字）
#    - 如果正常计算，返回结果
#    - 如果出错，打印错误信息并返回None
# 2. 编写一个safe_power函数，计算一个数的幂
#    - 接收两个参数：底数和指数
#    - 使用异常处理确保参数是数字
#    - 返回计算结果
# 3. 在主程序中测试这些函数，包括正常情况和异常情况
#
# 要求：
# - 使用try-except捕获具体的异常类型
# - 提供有意义的错误信息
# - 测试多种异常情况
# - 添加适当的注释
#

# ============================================================================
# 作业一：基础异常处理 - 安全的数值计算
# ============================================================================


def safe_divide(a, b):
    """
    安全的除法运算
    - 正常计算：返回结果
    - 除数为0：捕获 ZeroDivisionError
    - 参数不是数字：捕获 TypeError
    - 其他异常：捕获 Exception
    """
    try:
        result = a / b
    except ZeroDivisionError:
        print(f"错误：除数不能为0！（{a} / {b}）")
        return None
    except TypeError:
        print(f"错误：参数必须是数字！（{a} / {b}），类型分别是 {type(a).__name__} 和 {type(b).__name__}")
        return None
    except Exception as e:
        print(f"未知错误：{e}")
        return None
    else:
        # 没有异常时才执行
        print(f"{a} / {b} = {result}")
        return result


def safe_power(base, exponent):
    """
    安全的幂运算
    - 正常计算：返回结果
    - 参数不是数字：捕获 TypeError
    """
    try:
        # 先检查类型，提前报错
        if not isinstance(base, (int, float)) or not isinstance(exponent, (int, float)):
            raise TypeError(f"参数必须是数字，收到的是 {type(base).__name__} 和 {type(exponent).__name__}")

        result = base ** exponent
    except TypeError as e:
        print(f"错误：{e}")
        return None
    except OverflowError:
        print(f"错误：计算结果超出范围！（{base} ** {exponent}）")
        return None
    except Exception as e:
        print(f"未知错误：{e}")
        return None
    else:
        print(f"{base} ** {exponent} = {result}")
        return result


if __name__ == "__main__":
    print("=" * 40)
    print(" 测试 safe_divide 函数")
    print("=" * 40)

    # 正常情况
    safe_divide(10, 3)       # 正常除法
    safe_divide(100, 5)      # 整除

    # 异常情况：除数为0
    safe_divide(10, 0)

    # 异常情况：参数不是数字
    safe_divide("10", 3)
    safe_divide(10, "abc")
    safe_divide(None, 5)

    print("\n" + "=" * 40)
    print(" 测试 safe_power 函数")
    print("=" * 40)

    # 正常情况
    safe_power(2, 10)        # 2的10次方
    safe_power(3, 3)         # 3的3次方
    safe_power(5, 0)         # 任何数的0次方 = 1

    # 异常情况：参数不是数字
    safe_power("2", 10)
    safe_power(2, "abc")
    safe_power(None, 5)