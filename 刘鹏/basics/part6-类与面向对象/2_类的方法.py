class BankAccount:
    def __init__(self, account_id, account_name, balance=0):
        self.account_id = account_id
        self.account_name = account_name
        self.balance = balance
    
    def deposit(self, amount):
        # 1. 只把类型转换放在 try 里，专门捕获格式错误
        try:
            amount = float(amount)
        except ValueError:
            raise ValueError(f"请输入有效的数字")
        
        # 2. 业务逻辑放在外面，抛出准确的业务错误
        if amount <= 0:
            raise ValueError(f"金额必须大于0")
        self.balance += amount

    def withdraw(self, amount):
        try:
            amount = float(amount)
        except ValueError:
            raise ValueError(f"请输入有效的数字")
        
        if amount <= 0:
            raise ValueError(f"金额必须大于0")
            
        if self.balance >= amount:
            self.balance -= amount
        else:
            raise ValueError(f"取款失败：余额不足（当前余额：{self.balance}）")
        
    # 修正缩进为 4 个空格
    def get_balance(self):
        return self.balance
        
    def display_info(self):
        print(f"账号姓名：{self.account_name}, 账户余额：{self.balance}")


if __name__ == "__main__":
    bank = BankAccount("0001", "小明")
    
    # 3. 在主程序中使用 try...except 捕获异常，防止程序崩溃
    try:
        # 测试非法输入
        bank.deposit("1000a")
    except ValueError as e:
        print(f"存款异常: {e}")

    try:
        # 测试存入正数
        bank.deposit(1000)
        print("存款1000成功")
    except ValueError as e:
        print(f"存款异常: {e}")

    try:
        # 测试取款
        bank.withdraw(50)
        print("取款50成功")
    except ValueError as e:
        print(f"取款异常: {e}")

    # 显示最终信息
    bank.display_info()
