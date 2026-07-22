class ShoppingCart:
    def __init__(self):
        # 改为 _cart，提示外部不要直接修改这个列表
        self._cart = []

    def add_item(self, product: dict):
        """添加商品到购物车（带校验和合并逻辑）"""
        # 1. 数据校验：必须是字典，必须包含指定键，且值必须大于0
        if not isinstance(product, dict):
            raise TypeError("商品必须是字典格式")
        
        required_keys = ["name", "price", "quantity"]
        for key in required_keys:
            if key not in product:
                raise ValueError(f"商品信息缺失，必须包含 {required_keys}")
        
        if product["price"] <= 0 or product["quantity"] <= 0:
            raise ValueError("商品价格和数量必须大于0")

        # 2. 合并逻辑：如果购物车已有该商品，累加数量
        name = product["name"]
        for item in self._cart:
            if item["name"] == name:
                item["quantity"] += product["quantity"]
                print(f"数量更新：[{name}] 当前总数量为 {item['quantity']}")
                return
        
        # 3. 如果是新商品，正常添加
        self._cart.append(product)
        print(f"添加成功：[{name}] x {product['quantity']}")

    def remove_item(self, product_name: str):
        """从购物车移除商品"""
        # 遍历的是 _cart
        for product in self._cart:
            if product.get("name") == product_name:
                self._cart.remove(product)
                print(f"移除成功：[{product_name}]")
                return
        print(f"移除失败：购物车中没有找到 [{product_name}]")

    def calculate_total(self) -> float:
        """计算购物车总价"""
        total = 0
        for product in self._cart:
            total += product["price"] * product["quantity"]
        return total

    def display_cart(self):
        """显示购物车内容"""
        print("\n" + "=" * 30)
        print("       当前购物车")
        print("=" * 30)
        if not self._cart:
            print("  (购物车是空的)")
        else:
            for idx, product in enumerate(self._cart, 1):
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
        self._cart.clear()
        print("购物车已清空！")


# ================= 主程序测试 =================
if __name__ == "__main__":
    cart = ShoppingCart()

    # 正常添加
    cart.add_item({"name": "苹果", "price": 5.5, "quantity": 3})
    
    # 测试提升点1：重复添加同款商品，应该变成 5 个苹果，而不是两条记录
    cart.add_item({"name": "苹果", "price": 5.5, "quantity": 2})
    cart.add_item({"name": "香蕉", "price": 3.0, "quantity": 5})

    cart.display_cart()

    # 测试提升点2：错误数据拦截
    try:
        # 缺失价格，会被拦截
        cart.add_item({"name": "梨", "quantity": 2})
    except (ValueError, TypeError) as e:
        print(f"拦截异常：{e}")

    try:
        # 传入负数数量，会被拦截
        cart.add_item({"name": "烂橘子", "price": 1.0, "quantity": -5})
    except (ValueError, TypeError) as e:
        print(f"拦截异常：{e}")
