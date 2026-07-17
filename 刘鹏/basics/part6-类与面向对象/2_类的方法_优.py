# ============================================================================
# 作业二：类的方法 - 银行账户类
# ============================================================================

from decimal import Decimal, InvalidOperation

class BankAccount:
    """银行账户类"""

    def __init__(self, account_id, account_name, balance=0):
        self.account_id = account_id
        self.account_name = account_name
        # 余额使用 Decimal，避免浮点数精度丢失，强烈传入字符串
        self.balance = Decimal(str(balance))

    def _validate_amount(self, amount, action="操作"):
        """内部方法：校验金额格式和合法性"""
        try:
            amount = Decimal(str(amount))
        except InvalidOperation:
            raise ValueError(f"{action}失败：请输入有效的数字")

        if amount <= 0:
            raise ValueError(f"{action}失败：金额必须大于0")

        # 限制最多两位小数，这是decimal模块中用来精准判断小数位数的方法
        if amount.as_tuple().exponent < -2:
            raise ValueError(f"{action}失败：金额最多保留两位小数")
       
        return amount

    def deposit(self, amount):
        """存款：增加余额"""
        amount = self._validate_amount(amount, "存款")
        self.balance += amount
        print(f"存款成功：+{amount}，当前余额：{self.balance}")

    def withdraw(self, amount):
        """取款：减少余额，需检查余额是否充足"""
        amount = self._validate_amount(amount, "取款")

        if self.balance < amount:
            raise ValueError(f"取款失败：余额不足（当前余额：{self.balance}）")

        self.balance -= amount
        print(f"取款成功：-{amount}，当前余额：{self.balance}")

    def get_balance(self):
        """查询余额"""
        return self.balance

    def display_info(self):
        """显示账户信息"""
        print("=" * 50)
        print("           账户信息")
        print("=" * 50)
        print(f"账户号：{self.account_id}")
        print(f"账户名：{self.account_name}")
        print(f"余  额：{self.balance}")
        print("=" * 50)


if __name__ == "__main__":
    # 创建账户
    account = BankAccount("6228480012345678", "张三", 1000)
    account.display_info()

    # 多次存款
    account.deposit(500)
    account.deposit("300.50")

    # 多次取款
    account.withdraw(200)
    account.withdraw("100.25")

    # 查询余额
    print(f"\n查询余额：{account.get_balance()}")

    # 测试异常情况，方法中有raise时，主程序中必须用try-except进行捕获，并不强制执行
    print("\n--- 异常测试 ---")
    try:
        account.deposit(-100)         # 存负数
    except ValueError as e:
        print(e)

    try:
        account.withdraw(999999)      # 余额不足
    except ValueError as e:
        print(e)

    try:
        account.deposit("abc")        # 非数字
    except ValueError as e:
        print(e)

    try:
        account.deposit("100.999")    # 超过两位小数
    except ValueError as e:
        print(e)

    # 最终账户信息
    print()
    account.display_info()
