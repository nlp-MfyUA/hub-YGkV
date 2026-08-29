# 作业二：用户输入与计算
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 提示用户输入姓名（字符串）
# 2. 提示用户输入年龄（整数）
# 3. 提示用户输入身高（浮点数，单位：米）
# 4. 计算用户明年的年龄
# 5. 使用print()函数输出格式化的信息，包括：
#    - 姓名
#    - 今年年龄
#    - 明年年龄
#    - 身高
#
# 要求：
# - 使用input()函数获取用户输入
# - 注意input()返回的是字符串，需要进行类型转换
# - 输出格式要清晰美观
import textwrap


#不适用本次没有学过知识点的做法
def default():
    name = input("请输入您的名字：")
    age = input("请输入您的年龄：")
    height = input("请输入您的身高：")

    age = int(age)
    height = float(height)

    print(f"姓名：{name}")
    print(f"今年年龄：{age}")
    print(f"明年年龄：{age+1}")
    print(f"身高：{height}")


def main():

    # 每输入一个信息就校验一次
    name = input("请输入您的姓名：")

    # 校验年龄（必须是整数）
    age = input("请输入您的年龄（填写数字，不可乱填）：")
    if not age.isdigit():
        return print("请输入正确的年龄，整数格式，不用计算月份")
    age = int(age)

    # 校验身高（必须是数字，可以是小数）
    height = input("请输入您的身高（单位：米）：")
    # 先去掉小数点，再校验是否全部是数字
    if not height.replace(".","",1).isdigit():
        return print("请填入准确的身高信息，精确到厘米")
    
    height_split = height.split(".")
    if "." in height and (len(height_split[1]) > 2 or len(height_split[0]) > 1):
        return print("身高精确到厘米即可，整数部分最多一位，小数点后最多两位")
    
    height = float(height)
    
    print(textwrap.dedent(f"""\
                        姓名：{name}
                        今年年龄：{age}
                        明年年龄：{age + 1}
                        身高：{height}"""))
    

    print("-" * 15 + "进一步优化，错误后循环输入，直到成功输入信息正确为止" + "-" * 15)


# 发现这样存在问题，重新输入后不会再进行上一层的校验了。
def optimize_one():

    print("判断是否是执行的第一个优化方法")

    name_one = input("请输入您的姓名：")

    age_one = input("请输入正确的年龄信息（填写数字，不可乱填）：")

    # 校验年龄，必须是整数
    while not age_one.isdigit():
        print(f"输入的信息为：{age_one}，格式不对")
        age_one = input("请重新输入准确的年龄信息：")
    age_one = int(age_one)

    height_one = input("请输入您的身高，单位米，精确到厘米：")

    # 第一层：校验是否全是数字
    while not height_one.replace(".", "", 1).isdigit():
        print(f"输入的信息为：{height_one}，应该是数字格式")
        height_one = input("请重新输入：")

    # 第二层：校验整数部分只能是 0、1、2
    height_one_split = height_one.split(".")
    while int(height_one_split[0]) not in [0, 1, 2]:
        print(f"输入的信息为：{height_one}，正常人身高不会超过2米")
        height_one = input("请重新输入：")
        height_one_split = height_one.split(".")  # 重新输入后必须重新 split

    # 第三层：有小数点时，校验小数部分最多两位
    if "." in height_one:
        while len(height_one_split[1]) > 2:
            print(f"输入的信息为：{height_one}，精确到厘米即可，小数点后最多两位")
            height_one = input("请重新输入：")
            height_one_split = height_one.split(".")  # 重新输入后必须重新 split

    height_one = float(height_one)

    print(textwrap.dedent(f"""\
                        姓名：{name_one}
                        今年年龄：{age_one}
                        明年年龄：{age_one + 1}
                        身高：{height_one}"""))


def optimize_two():
    print("判断是否是执行的第二个优化方法")

    name = input("请输入您的姓名：")

    age = input("请输入正确的年龄信息（填写数字，不可乱填）：")

    # 校验年龄，必须是整数
    while not age.isdigit():
        print(f"输入的信息为：{age}，格式不对")
        age = input("请重新输入准确的年龄信息：")
    age = int(age)

    height = input("请输入您的身高，单位米，精确到厘米：")

    while True:
    # 校验1：是否是合法数字
        if not height.replace(".", "", 1).isdigit():
            print("格式不对")
            height = input("请重新输入：")
            continue  # 跳回开头，重新从校验1开始

        height_split = height.split(".")

        # 校验2：整数部分只能是 0、1、2
        if int(height_split[0]) not in [0, 1, 2]:
            print("身高不能超过2米")
            height = input("请重新输入：")
            continue  # 跳回开头，重新从校验1开始

        # 校验3：有小数点时，小数部分最多两位
        if "." in height and len(height_split[1]) > 2:
            print("小数点后最多两位")
            height = input("请重新输入：")
            continue  # 跳回开头，重新从校验1开始

        # 全部通过，跳出循环
        break

    height = float(height)

    print(textwrap.dedent(f"""\
                        姓名：{name}
                        今年年龄：{age}
                        明年年龄：{age + 1}
                        身高：{height}"""))

    
# 最后一种优化方式，提高自己的代码能力，开拓视野。体会真个演变过程

def get_valid_input(prompt, error_msg, validator):
    """"
    通用输入校验函数
    :param prompt:输入提示信息
    :param error_msg:错误提示（可用{}占位符显示用户输入的值）
    :param validator:校验函数，返回（是否通过，转换后的值）
    """
    #去除空格
    value = input(prompt).strip
    while True:
        valid, result = validator(value)
        if valid:
            return result
        print(error_msg.format(value))
        value = input("请重新输入：").strip
    
def validate_age(value):
    """"年龄校验：必须是正整数，且不超过150岁"""
    try:
        value = int(value)
        if value <= 0 or value > 150:
           return False, value
        return True, value
    except ValueError:
        return False, value
    
def validate_height(value):
    """"
    身高校验：必须是数字，整数部分必须是0,1,2，小数部分小于两位小数
    """

    try:
        height = float(value)
    except ValueError:
        return False, value
    
    height_split = value.split(".")
    
    # 校验2：整数部分只能是 0、1、2
    if int(height_split[0]) not in [0, 1, 2]:
        return False, value

    # 校验3：有小数点时，小数部分最多两位
    if "." in value and len(height_split[1]) > 2:
        return False, value

    return True, height
    

def optimize_three():
    print("判断是否是用的第三个优化方法")

    name_one = input("请输入您的姓名：").strip()

    age_one = get_valid_input(
        "请输入正确的年龄信息（填写数字，不可乱填）：",
        "输入的信息为：{}，年龄必须是1~150之间的整数",
        validate_age
    )

    height_one = get_valid_input(
        "请输入您的身高，单位米，精确到厘米：",
        "输入的信息为：{}，正常人身高不超过2米，小数点后最多两位",
        validate_height
    )

    print(textwrap.dedent(f"""\
                        姓名：{name_one}
                        今年年龄：{age_one}
                        明年年龄：{age_one + 1}
                        身高：{height_one}"""))

if __name__ == "__main__":
    # main()
    #存在问题
    #optimize_one()
    #optimize_two()
    default()