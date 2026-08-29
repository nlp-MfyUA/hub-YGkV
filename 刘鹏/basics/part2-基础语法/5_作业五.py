# 作业五：综合应用 - 购物计算器
# ============================================================================
#
# 任务描述：
# 编写一个购物计算器程序，实现以下功能：
# 1. 提示用户输入以下信息：
#    - 商品1名称、单价、数量
#    - 商品2名称、单价、数量
#    - 商品3名称、单价、数量
# 2. 计算每个商品的小计（单价 × 数量）
# 3. 计算所有商品的总价（三个小计相加）
# 4. 假设折扣率为0.9（打9折），计算折扣后的价格
# 5. 输出格式化的购物清单，包括：
#    - 每个商品的名称、单价、数量、小计
#    - 总价（折扣前）
#    - 折扣率
#    - 折扣后价格
#
# 要求：
# - 使用有意义的变量名
# - 添加详细的注释
# - 输出格式要清晰，可以使用分隔线
# - 价格保留两位小数
# - 使用格式化字符串输出

# 符合本次学习内容的方法
def default():

    #输入商品信息
    product1_name = input("请输入商品1的名称:")
    product1_price = input("请输入商品1的单价信息:")
    product1_quantity = input("请输入商品1的数量:")

    product2_name = input("请输入商品2的名称:")
    product2_price = input("请输入商品2的单价信息:")
    product2_quantity = input("请输入商品2的数量:")
    
    product3_name = input("请输入商品3的名称:")
    product3_price = input("请输入商品3的单价信息:")
    product3_quantity = input("请输入商品3的数量:")

    # str 转 float
    product1_price_float = float(product1_price)
    product2_price_float = float(product2_price)
    product3_price_float = float(product3_price)

    # str 转 int
    product1_quantity_int = int(product1_quantity)
    product2_quantity_int = int(product2_quantity)
    product3_quantity_int = int(product3_quantity)

    product1_total_price = product1_price_float * product1_quantity_int
    product2_total_price = product2_price_float * product2_quantity_int
    product3_total_price = product3_price_float * product3_quantity_int

    product_total_price = product1_total_price + product2_total_price + product3_total_price

    discount = product_total_price * 0.9

    print(f"商品1的名称:{product1_name}")
    print(f"商品1的单价:{product1_price:.2f},商品1的数量：{product1_quantity}，商品1的小计:{product1_total_price:.2f}")

    print(f"商品2的名称:{product2_name}")
    print(f"商品2的单价:{product2_price:.2f},商品2的数量：{product2_quantity}，商品2的小计:{product2_total_price:.2f}")

    print(f"商品3的名称:{product3_name}")
    print(f"商品3的单价:{product3_price:.2f},商品3的数量：{product3_quantity}，商品3的小计:{product3_total_price:.2f}")

    print(f"商品的总价是：{product_total_price},折扣价是：{discount}")
    
#####################以下是优化的功能############################################

def input_info(name, price, number):
    """处理单个商品：转换类型，计算小计"""
    price_float = float(price)
    number_int = int(number)
    one_total_price = price_float * number_int  # 用转换后的数值计算
    return name, price_float, number_int, one_total_price


def total_price(pre_total_price, one_total_price):
    """累加总价"""
    return pre_total_price + one_total_price


def discount(total, discount_rate):
    """计算折扣后价格"""
    return total * discount_rate


if __name__ == "__main__":
    goods_list = []      # 存储所有商品信息
    total = 0.0          # 总价（折扣前）
    count = 1

    while count < 4:
        info = f"请输入商品{count}的名称、单价、数量（以逗号隔开）："
        goods_info = input(info)

        try:
            goods_info_split = goods_info.replace("，",",").split(",")

            # 统一用 split 后的结果
            name, price, number = goods_info_split[0], goods_info_split[1], goods_info_split[2]

            # 函数内部用转换后的数值计算
            result = input_info(name, price, number)
            goods_list.append(result)

            # 累加总价
            total = total_price(total, result[3])

            count += 1

        except ValueError:
            print("请按照相应的格式和要求填写（名称,单价,数量）")
        except IndexError:
            print("输入内容不完整，请用逗号隔开三项内容")

    # ===== 输出购物清单 =====
    discount_rate = 0.9

    print("\n" + "=" * 45)
    print("             购物清单")
    print("=" * 45)
    print(f"{'商品名称':<10}{'单价':>8}{'数量':>6}{'小计':>10}")
    print("-" * 45)

    for name, price, number, subtotal in goods_list:
        print(f"{name:<10}{price:>8.2f}{number:>6}{subtotal:>10.2f}")

    print("-" * 45)
    print(f"总价（折扣前）：{total:.2f}")
    print(f"折扣率：{discount_rate}（打{int(discount_rate * 10)}折）")
    print(f"折扣后价格：{discount(total, discount_rate):.2f}")
    print("=" * 45)



