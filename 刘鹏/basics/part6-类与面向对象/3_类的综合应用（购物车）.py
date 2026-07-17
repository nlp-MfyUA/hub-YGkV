# ============================================================================
# 作业三：类的综合应用 - 购物车类
# ============================================================================
#
# 任务描述：
# 定义一个ShoppingCart类，模拟购物车，包含以下内容：
# 1. __init__方法：初始化购物车（空列表）
# 2. add_item方法：添加商品到购物车（商品信息用字典存储）
# 3. remove_item方法：从购物车移除商品
# 4. calculate_total方法：计算购物车总价
# 5. display_cart方法：显示购物车内容
# 6. clear_cart方法：清空购物车
#
# 在主程序中：
# - 创建一个购物车实例
# - 添加多个商品
# - 显示购物车
# - 计算总价
# - 移除某个商品
# - 再次显示购物车和总价
#
# 要求：
# - 使用列表和字典存储数据
# - 在方法中使用self访问属性
# - 添加适当的注释


class ShoppingCart:
    def __init__(self):
        # 修复1：不要用可变对象做默认参数，直接在内部初始化空列表
        self.cart = []

    def add_item(self, product):
        """添加商品到购物车"""
        self.cart.append(product)
        print(f"添加成功：[{product['name']}] x {product['quantity']}")

    def remove_item(self, product_name):
        """从购物车移除商品"""
        # 修复2：安全删除方式
        for product in self.cart:
            if product.get("name") == product_name:
                self.cart.remove(product)  # 删除匹配到的这个字典对象
                print(f"移除成功：[{product_name}]")
                return  # 找到并删除后直接结束方法
        
        # 如果循环走完了还没找到，说明没有这个商品
        print(f"移除失败：购物车中没有找到 [{product_name}]")

    def calculate_total(self):
        """计算购物车总价"""
        total = 0
        for product in self.cart:
            # 修复3：修正拼写错误 number，并加上 return
            total += product["price"] * product["quantity"]
        return total

    def display_cart(self):
        """显示购物车内容（帮你补全）"""
        print("\n" + "=" * 30)
        print("       当前购物车")
        print("=" * 30)
        if not self.cart:
            print("  (购物车是空的)")
        else:
            for idx, product in enumerate(self.cart, 1):
                name = product["name"]
                price = product["price"]
                qty = product["quantity"]
                subtotal = price * qty
                print(f"  {idx}. {name} \t单价: {price} \t数量: {qty} \t小计: {subtotal}")
        
        total = self.calculate_total()
        print("-" * 30)
        print(f"  总计: {total:.2f} 元")
        print("=" * 30 + "\n")

    def clear_cart(self):
        """清空购物车"""
        self.cart.clear()
        print("🧹 购物车已清空！")


# ================= 主程序与输出测试 =================
if __name__ == "__main__":
    # 1. 创建一个购物车实例
    cart = ShoppingCart()

    # 2. 添加多个商品 (使用字典存储商品信息)
    cart.add_item({"name": "苹果", "price": 5.5, "quantity": 3})
    cart.add_item({"name": "香蕉", "price": 3.0, "quantity": 5})
    cart.add_item({"name": "可乐", "price": 6.0, "quantity": 2})

    # 3. 显示购物车
    cart.display_cart()

    # 4. 移除某个商品
    cart.remove_item("香蕉")
    
    # 测试移除不存在的商品
    cart.remove_item("薯片")

    # 5. 再次显示购物车和总价
    cart.display_cart()

    # 6. 测试清空购物车
    cart.clear_cart()
    cart.display_cart()


    