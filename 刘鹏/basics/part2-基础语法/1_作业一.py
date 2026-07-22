# ============================================================================
# 作业一：基础变量与运算
# ============================================================================
#
# 任务描述：
# 1. 定义三个变量：商品名称（字符串）、商品价格（浮点数）、商品数量（整数）
# 2. 计算商品的总价（价格 × 数量）
# 3. 使用print()函数输出商品信息，格式如下：
#    "商品名称：xxx"
#    "单价：xxx元"
#    "数量：xxx"
#    "总价：xxx元"
#
# 要求：
# - 变量名要有意义，符合命名规范
# - 添加适当的注释说明
# - 使用格式化字符串输出
import textwrap

def main():
    goods_name = "手机"
    goods_one_price = 9999.99
    goods_num = 2

    goods_total_price = goods_num * goods_one_price

    #优化显示格式，方案一：去掉缩进
    print(f"""商品名称：{goods_name}
单价：{goods_one_price}元
数量：{goods_num}个
总价：{goods_total_price}元
        """)
    
    #方案二：textwrap.dedent，推荐
    print(textwrap.dedent(f"""\
        商品名称：{goods_name}
        单价：{goods_one_price}元
        数量：{goods_num}个
        总价：{goods_total_price}元"""))

    #方案三：多个print
    print(f"商品名称：{goods_name}")
    print(f"单价：{goods_one_price}元")
    print(f"数量：{goods_num}个")
    print(f"总价：{goods_total_price}元")

    #方案四：用\n拼接
    print(f"商品名称：{goods_name}\n"
      f"单价：{goods_one_price}元\n"
      f"数量：{goods_num}个\n"
      f"总价：{goods_total_price}元")

if __name__ == "__main__":
    main()