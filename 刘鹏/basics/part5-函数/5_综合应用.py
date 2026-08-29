# ============================================================================
# 作业五：综合应用 - 计算器程序（函数版）
# ============================================================================
#
# 任务描述：
# 将之前的购物车系统改造成使用函数的版本，定义以下函数：
# 1. display_menu()：显示菜单
# 2. show_products(products)：显示所有商品
# 3. add_to_cart(cart, products, product_name, quantity)：添加商品到购物车
# 4. show_cart(cart)：显示购物车内容
# 5. calculate_total(cart)：计算购物车总价
# 6. clear_cart(cart)：清空购物车
# 7. main()：主函数，包含主循环和菜单逻辑
#
# 在主程序中：
# - 调用main()函数启动程序
# - 使用函数组织代码，使程序更模块化
#
# 要求：
# - 使用函数重构代码
# - 每个功能对应一个函数
# - 使用main()函数作为程序入口
# - 代码结构清晰，易于维护
# - 添加详细的注释


class ShoppingCartSystem:
    """
    购物车系统核心类
    设计理念：
    1.使用字典映射替代if-elif，实现业务逻辑与控制流的彻底解耦
    2.采用Python推荐EAFP编程风格
    """


    def __init__(self):
        # 初始化商品库（实际生产中，会通过依赖注入传入数据库服务）
        self.is_running = True
        self.products = [
            {"id": 1, "名称": "手机", "描述": "智能手机", "价格": 2599.00, "库存": 100},
            {"id": 2, "名称": "电脑", "描述": "惠普电脑", "价格": 5999.00, "库存": 50},
            {"id": 3, "名称": "手表", "描述": "华为手表", "价格": 1999.00, "库存": 80},
            {"id": 4, "名称": "手环", "描述": "小米手环", "价格": 299.00, "库存": 200},
            {"id": 5, "名称": "电视", "描述": "TCL电视", "价格": 1688.00, "库存": 30},
        ]

        self.cart = [] # 购物车数据隔离

        # 核心设计：字典映射
        # 将菜单选线与具体的方法绑定
        # 如果未来要新增功能，只需要在这里加一行，完全不用修改主循环逻辑
        self.action_map = {
            "1": self.show_products,
            "2": self.add_to_cart,
            "3": self.show_cart,
            "4": self.clear_cart,
            "5": self.exit_system,
        }

    def display_menu(self):
        """显示菜单，系统主运行循环"""
        print("\n 欢迎使用购物车系统!")

        menu = """
            1.查看所有商品
            2.添加商品到购物车
            3.查看购物车
            4.清空购物车
            5.退出系统
        """

        while self.is_running:
            print(menu)
            choice = input("请输入选项（1~5）：").strip()

            # 核心执行逻辑，通过字典动态获取方法并执行
            # get()方法，如果choice在字典中，返回对应的方法；如果不在，返回lamdba匿名提示
            # 最后加 ()表示立即执行获取到的新方法
            self.action_map.get(choice, lambda: print("❌ 无效选项，请输入 1-5 之间的数字。"))()

    def show_products(self):
        """展示商品列表"""
        print("\n" + "=" * 60)
        print("所有产品的信息")
        print("=" * 60)
        if not self.products:
            print("暂无商品。")
            return
        for idx, product in enumerate(self.products, 1):
            print(f"{idx}: [{product['名称']}] {product['描述']} | "
                  f"{product['价格']}元 | 库存：{product['库存']}")
            print("=" * 60)

    def add_to_cart(self):
        """添加商品到购物车（包含严格的边界校验）"""
        name = input("请输入要添加的商品名称：").strip()

        # 1.查找商品
        target_product = next((p for p in self.products if p["名称"] == name), None)
        if not target_product:
            print(f"未找到商品'{name}',请检查名称后重试")
            return

        # 2. 获取并校验购买数量
        try:
            quantity = int(input("请输入购买数量：").strip())
            if quantity <= 0: raise ValueError("数量必须大于0")
        except ValueError as e:
            print(f"错误：{e}")
            return

        # 3. 校验库存
        if quantity > target_product["库存"]:
            print(f"库存不足！'{name}'当前库存仅剩{target_product['库存']}件。")
            return

        # 4.处理购物车合并逻辑
        for cart_item in self.cart:
            if cart_item["名称"] == name:
                cart_item["数量"] += quantity
                target_product["库存"] -= quantity
                print(f"成功追加[{quantity}]件[{name}]到购物车！")
                return

        # 5. 购物车中不存在改商品，新建条目
        self.cart.append({"名称": name, "价格": target_product["价格"], "数量": quantity})
        target_product["库存"] -= quantity
        print(f"✅ 成功添加 [{quantity}] 件 [{name}] 到购物车！")

    def show_cart(self):
        """展示购物车详情"""
        print("\n" + "=" * 60)
        print("我的购物车")
        print("=" * 60)
        if not self.cart:
            print("购物车空空如也，快去购物吧")
            return

        total_price = 0
        for idx, item in enumerate(self.cart, 1):
            sub_total = item["价格"] * item["数量"]
            total_price += sub_total
            print(f"{idx}. [{item['名称']}]  {item['价格']}元 × {item['数量']}件 = {sub_total:.2f}元")

        print("-" * 60)
        print(f"购物车总计: {len(self.cart)} 种商品, 合计: {total_price:.2f}元")
        print("=" * 60)

    def release_cart_stock(self):
        carts = self.cart
        for cart in carts:
            target_product = next((p for p in self.products if p["名称"] == cart["名称"]),None)
            target_product["库存"] += cart["数量"]

    def clear_cart(self):
        self.release_cart_stock()
        """清空购物车"""
        self.cart.clear()
        print("购物车已清空！")


    def exit_system(self):
        """退出系统"""
        print("感谢使用，再见！")
        self.is_running = False


if __name__ == "__main__":
    system = ShoppingCartSystem()
    system.display_menu()





















