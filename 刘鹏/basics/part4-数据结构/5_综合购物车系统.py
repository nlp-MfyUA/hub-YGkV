# ============================================================================
# 作业五：综合应用 - 购物车系统
# ============================================================================
#
# 任务描述：
# 编写一个购物车系统，实现以下功能：
# 1. 创建一个商品列表，每个商品是一个字典，包含：
#    - 商品名称、价格、库存数量
#    - 至少包含5个商品
# 2. 创建一个购物车（空列表），用于存储用户选择的商品
# 3. 显示菜单：
#    - 1. 查看所有商品
#    - 2. 添加商品到购物车
#    - 3. 查看购物车
#    - 4. 计算购物车总价
#    - 5. 清空购物车
#    - 6. 退出
# 4. 使用while循环让程序可以重复执行，直到用户选择退出
# 5. 实现各个菜单功能：
#    - 查看商品：遍历商品列表，显示所有商品信息
#    - 添加商品：提示用户输入商品名称和数量，检查库存，添加到购物车
#    - 查看购物车：显示购物车中的所有商品和数量
#    - 计算总价：遍历购物车，计算所有商品的总价
#    - 清空购物车：清空购物车列表
#
# 要求：
# - 使用列表和字典存储数据
# - 使用while循环实现菜单系统
# - 使用for循环遍历列表和字典
# - 使用条件语句进行判断
# - 处理各种边界情况（如商品不存在、库存不足等）
# - 输出格式要清晰美观
# - 添加详细的注释


def shopping_cart_system():
    """
    根据需求，实现功能，手搓，不断优化业务场景
    """
    product_list = [
        {"商品名称": "手机", "商品描述": "智能手机", "价格": 2599, "库存量": 100},
        {"商品名称": "电脑", "商品描述": "惠普电脑", "价格": 5999, "库存量": 100},
        {"商品名称": "手表", "商品描述": "华为手表", "价格": 1999, "库存量": 100},
        {"商品名称": "手环", "商品描述": "小米手环", "价格": 1000, "库存量": 100},
        {"商品名称": "电视", "商品描述": "TCL电视", "价格": 1688, "库存量": 100},
        {"商品名称": "冰箱", "商品描述": "美的冰箱", "价格": 1895, "库存量": 100}
    ]

    shopping_cart = []

    print("=====购物车功能菜单======")
    print("1. 查看所有商品")
    print("2. 添加商品到购物车")
    print("3. 查看购物车")
    print("4. 计算购物车总价")
    print("5. 清空购物车")
    print("6. 退出")

    # 把操作按键定义成 列表
    options = ["1", "2", "3", "4", "5", "6"]

    # 询问客户是否需要进行购物活动
    is_shopping = input("请问您是否需要进行购物，请输入是（Y)/否（N):").strip().lower()

    if is_shopping == "n":
        print("购物系统已退出，欢迎您下次使用")
    elif is_shopping == "y":
        while True:
            option_input = input("请根据上边的功能菜单，输入对应的数字：").strip()
            if option_input in options:
                if option_input == "1":
                    show_products(product_list)
                    continue
                elif option_input == "2":
                    add_to_cart(product_list, shopping_cart)
                    continue
                elif option_input == "3":
                    show_cart(shopping_cart)
                    continue
                elif option_input == "4":
                    calc_total(shopping_cart)
                    continue
                elif option_input == "5":
                    clear_cart(shopping_cart)
                    continue
                elif option_input == "6":
                    print("购物系统已退出，欢迎您下次使用")
                    break
            else:
                print("请重新输入正确的数字")
                continue
    else:
        print("请输入正确的信息")


def show_products(product_list: list) -> None:
    for idx, product in enumerate(product_list, 1):
        print(f"{idx}： 商品: {product['商品名称']} | 描述: {product['商品描述']} | 价格: {product['价格']} | 库存: {product['库存量']}")


def add_to_cart(product_list: list, shopping_cart:list) -> None:
    select_product = input("请输入你选中的商品名称：").strip()
    quantity = None
    try:
        quantity = input("请输入你购买的数量：").strip()
        quantity = int(quantity)
    except ValueError as e:
        print(f"您输入的数量格式不对")

    found_product = None  # 先假设没找到
    is_stock_insufficient = False

    for product in product_list:
        if select_product in product["商品名称"]:
            found_product = product  # 找到了，把整个商品字典存起来
            if product["库存量"] >= quantity:
                is_stock_insufficient = True
                product["库存量"] -= 1
                break  # 找到了就立刻跳出循环，不用继续找了
            else:
                is_stock_insufficient = False
                break
    # 循环结束后，再来判断
    if found_product and is_stock_insufficient:
        # 1. 先假设购物车里没有这个商品
        is_in_cart = False

        # 2. 遍历购物车，只做“查找”动作
        if shopping_cart:
            for shopping_cart_temp in shopping_cart:
                # 注意：要用字典的键去和字符串比较
                if shopping_cart_temp["商品名称"] == found_product["商品名称"]:
                    # 找到了，把新买的数量加上去
                    shopping_cart_temp["数量"] += quantity
                    is_in_cart = True
                    break  # 找到了就立刻跳出，不用继续找了

        # 3. 遍历结束后，如果购物车里原本没有，才进行添加
        if not is_in_cart:
            found_product["数量"] = quantity
            shopping_cart.append(found_product)

        print(f"成功将 [{found_product['商品名称']}] 加入购物车！")
    elif not found_product:
        print("输入的商品名称不对，请重新输入")
    elif not is_stock_insufficient:
        print("库存量不够")


def show_cart(shopping_cart: list) -> None:
    if not shopping_cart:
        print("购物车空空如也~")
    else:
        for item in shopping_cart:
            print(f"商品: {item['商品名称']} | 价格: {item['价格']} | 数量： {item['数量']}")


def calc_total(shopping_cart: list) -> None:
    # 购物车中存在的商品的所有的信息
    print(f"购物车总价{sum(cart['价格'] * cart['数量'] for cart in shopping_cart)}")


def clear_cart(shopping_cart: list) -> None:
    shopping_cart.clear()
    print("购物车已清空")


if __name__ == "__main__":
    shopping_cart_system()


# ============================================================================
# 作业五：综合应用 - 购物车系统（大厂架构版：策略模式 + OOP）
# ============================================================================

class ShoppingCartSystem:
    """
    购物车系统核心类。 漂亮的代码。。。
    设计理念：
    1. 使用字典映射（策略模式）替代 if-elif，实现业务逻辑与控制流的彻底解耦。
    2. 采用 Python 推荐的 EAFP (Easier to Ask Forgiveness than Permission) 编程风格。
    """

    def __init__(self):
        # 初始化商品库（实际生产中，这里会通过依赖注入传入数据库服务）
        self.products = [
            {"id": 1, "名称": "手机", "描述": "智能手机", "价格": 2599.00, "库存": 100},
            {"id": 2, "名称": "电脑", "描述": "惠普电脑", "价格": 5999.00, "库存": 50},
            {"id": 3, "名称": "手表", "描述": "华为手表", "价格": 1999.00, "库存": 80},
            {"id": 4, "名称": "手环", "描述": "小米手环", "价格": 299.00, "库存": 200},
            {"id": 5, "名称": "电视", "描述": "TCL电视", "价格": 1688.00, "库存": 30},
        ]
        self.cart = []  # 购物车数据隔离

        # 🌟 核心设计：字典映射（策略模式）
        # 将菜单选项（Key）与具体的方法（Value）绑定。
        # 如果未来要新增功能，只需在这里加一行，完全不用修改主循环逻辑！
        self.action_map = {
            "1": self.show_products,
            "2": self.add_to_cart,
            "3": self.show_cart,
            "4": self.clear_cart,
            "5": self.exit_system,
        }

    def show_products(self):
        """展示商品列表"""
        print("\n" + "=" * 60)
        print("🛒 所有商品信息")
        print("=" * 60)
        if not self.products:
            print("暂无商品。")
            return
        for idx, product in enumerate(self.products, 1):
            print(f"{idx}. [{product['名称']}] {product['描述']} | "
                  f"💰 {product['价格']}元 | 📦 库存: {product['库存']}")
        print("=" * 60)

    def add_to_cart(self):
        """添加商品到购物车（包含严格的边界校验）"""
        name = input("请输入要添加的商品名称: ").strip()

        # 1. 查找商品
        target_product = next((p for p in self.products if p["名称"] == name), None)
        if not target_product:
            print(f"❌ 错误：未找到商品 '{name}'，请检查名称后重试。")
            return

        # 2. 获取并校验购买数量
        try:
            quantity = int(input("请输入购买数量: ").strip())
            if quantity <= 0: raise ValueError("数量必须大于0")
        except ValueError as e:
            print(f"❌ 错误：{e}")
            return

        # 3. 校验库存
        if quantity > target_product["库存"]:
            print(f"❌ 库存不足！'{name}' 当前库存仅剩 {target_product['库存']} 件。")
            return

        # 4. 处理购物车合并逻辑
        for cart_item in self.cart:
            if cart_item["名称"] == name:
                cart_item["数量"] += quantity
                target_product["库存"] -= quantity
                print(f"✅ 成功追加 [{quantity}] 件 [{name}] 到购物车！")
                return

        # 5. 购物车中不存在该商品，新建条目
        self.cart.append({"名称": name, "价格": target_product["价格"], "数量": quantity})
        target_product["库存"] -= quantity
        print(f"✅ 成功添加 [{quantity}] 件 [{name}] 到购物车！")

    def show_cart(self):
        """展示购物车详情"""
        print("\n" + "=" * 60)
        print("🛍️ 我的购物车")
        print("=" * 60)
        if not self.cart:
            print("购物车空空如也，快去选购吧~")
            return

        total_price = 0
        for idx, item in enumerate(self.cart, 1):
            subtotal = item["价格"] * item["数量"]
            total_price += subtotal
            print(f"{idx}. [{item['名称']}] 💰 {item['价格']}元 × {item['数量']}件 = {subtotal:.2f}元")

        print("-" * 60)
        print(f"🧾 购物车总计: {len(self.cart)} 种商品, 合计: {total_price:.2f}元")
        print("=" * 60)

    def clear_cart(self):
        """清空购物车"""
        self.cart.clear()
        print("🗑️ 购物车已清空！")

    def exit_system(self):
        """退出系统"""
        print("👋 感谢使用，再见！")
        self.is_running = False

    def run(self):
        """系统主运行循环（极简的控制流）"""
        print("\n🎉 欢迎使用购物车系统！")
        self.is_running = True

        menu = """
        请选择操作：
        1. 查看所有商品
        2. 添加商品到购物车
        3. 查看购物车
        4. 清空购物车
        5. 退出系统
        """
        while self.is_running:
            print(menu)
            choice = input("请输入选项 (1-5): ").strip()

            # 🌟 核心执行逻辑：通过字典动态获取方法并执行
            # get() 方法：如果 choice 在字典中，返回对应的方法；如果不在，返回 lambda 匿名函数打印错误提示。
            # 最后的 () 表示立即执行获取到的方法。
            self.action_map.get(choice, lambda: print("❌ 无效选项，请输入 1-5 之间的数字。"))()


if __name__ == "__main__":
    system = ShoppingCartSystem()
    system.run()


