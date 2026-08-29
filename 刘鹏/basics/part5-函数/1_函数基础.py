# ============================================================================
# 作业一：函数基础 - 计算器函数
# ============================================================================
#
# 任务描述：
# 编写一个程序，定义以下函数：
# 1. add(a, b)：计算两个数的和
# 2. subtract(a, b)：计算两个数的差
# 3. multiply(a, b)：计算两个数的积
# 4. divide(a, b)：计算两个数的商（注意处理除数为0的情况）
# 5. calculate_bmi(weight, height)：计算BMI指数（体重除以身高的平方）
#
# 在主程序中：
# - 测试每个函数，调用并输出结果
# - 提示用户输入两个数字，调用add函数计算和
# - 提示用户输入体重和身高，调用calculate_bmi函数计算BMI
#
# 要求：
# - 每个函数都要有清晰的注释说明
# - 使用return语句返回结果
# - 处理除数为0的情况
# - 添加适当的注释


def add(a, b):
    """
    功能:计算两个数的总和

    参数：
        a:其中一个数字
        b:另一个数字
    
    返回值：两数之和
    """
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        print("除数不能为零")
        return
    return a / b


def calculate_bmi(weight, height):
    if height == 0:
        print("身高不能为0")
        return
    return weight / height ** 2


#规范化代码
def add(a, b):
    """计算两个数的和"""
    return a + b


def subtract(a, b):
    """计算两个数的差"""
    return a - b


def multiply(a, b):
    """计算两个数的积"""
    return a * b


def divide(a, b):
    """计算两个数的商，除数为0时返回错误信息"""
    if b == 0:
        return "错误：除数不能为0！"
    return a / b


def calculate_bmi(weight, height):
    """计算BMI指数 = 体重(kg) / 身高(m)的平方"""
    return weight / (height ** 2)


if __name__ == "__main__":
    print("=" * 50)
    print("函数测试")
    print("=" * 50)

    print(f"10 + 5 = {add(10, 5)}")
    print(f"10 - 5 = {subtract(10, 5)}")
    print(f"10 * 5 = {multiply(10, 5)}")
    print(f"10 / 5 = {divide(10, 5)}")
    print(f"10 / 0 = {divide(10, 0)}")
    print(f"BMI(70kg, 1.75m) = {calculate_bmi(70, 1.75):.2f}")

    # 用户交互部分
    num1 = float(input("请输入第一个数字："))
    num2 = float(input("请输入第二个数字："))
    print(f"{num1} + {num2} = {add(num1, num2)}")

    weight = float(input("请输入体重（公斤）："))
    height = float(input("请输入身高（米）："))
    print(f"BMI指数：{calculate_bmi(weight, height):.2f}")


        
        
