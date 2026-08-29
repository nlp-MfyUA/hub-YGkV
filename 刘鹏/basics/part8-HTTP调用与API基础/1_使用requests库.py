# 第八部分-HTTP调用与API基础 作业说明
# 
# 本部分作业共4道题，从简单到复杂，帮助巩固以下知识点：
# - HTTP的基本概念
# - 使用requests库发送HTTP请求
# - GET请求和POST请求
# - 处理API响应（JSON格式）
# - 错误处理
#
# 注意：
# - 需要先安装requests库：pip install requests
# - 可以使用免费的测试API（如JSONPlaceholder）
# - 本部分作业可以使用之前学过的所有知识
#
# ============================================================================
# 作业一：使用requests库 - GET请求
# ============================================================================
#
# 任务描述：
# 编写一个程序，使用requests库完成以下任务：
# 1. 发送GET请求到JSONPlaceholder API获取用户列表
#    URL: https://jsonplaceholder.typicode.com/users
# 2. 打印响应状态码
# 3. 解析JSON响应数据
# 4. 显示前3个用户的姓名和邮箱
# 5. 发送GET请求获取单个用户信息
#    URL: https://jsonplaceholder.typicode.com/users/1
# 6. 显示该用户的详细信息
#
# 要求：
# - 使用requests.get()发送GET请求
# - 使用response.json()解析JSON数据
# - 处理可能的错误（如网络错误）
# - 添加适当的注释

import requests

def main():
    """
    主函数：演示如何使用 requests 库发送 GET 请求并处理 JSON 响应
    """
    # --- 任务 1-4: 获取用户列表 ---
    print("=== 正在获取用户列表... ===")
    url_users = "https://jsonplaceholder.typicode.com/users"
    
    try:
        # 1. 发送 GET 请求
        response = requests.get(url_users)
        
        # 2. 打印响应状态码
        print(f"响应状态码: {response.status_code}")
        
        # 检查请求是否成功 (状态码 200-299)
        if response.status_code == 200:
            # 3. 解析 JSON 响应数据
            # response.json() 会自动将 JSON 字符串转换为 Python 对象 (列表或字典)
            users_data = response.json()
            
            # 4. 显示前3个用户的姓名和邮箱
            print("\n--- 前3位用户信息 ---")
            # 使用切片 [:3] 获取列表的前3个元素
            for user in users_data[:3]:
                # user 是一个字典，可以直接通过键来获取值
                print(f"姓名: {user['name']}, 邮箱: {user['email']}")
        else:
            print(f"获取用户列表失败，状态码: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        # 捕获所有 requests 库可能抛出的异常，如网络错误、超时等
        print(f"发生网络错误: {e}")

    print("\n" + "-"*30 + "\n")

    # --- 任务 5-6: 获取单个用户信息 ---
    print("=== 正在获取单个用户信息... ===")
    url_user_one = "https://jsonplaceholder.typicode.com/users/1"
    
    try:
        # 5. 发送 GET 请求获取单个用户信息
        response = requests.get(url_user_one)
        
        if response.status_code == 200:
            # 解析 JSON 数据
            user_data = response.json()
            
            # 6. 显示该用户的详细信息
            print("\n--- 用户ID为1的详细信息 ---")
            # 使用 f-string 格式化输出，展示嵌套的 JSON 数据
            print(f"姓名: {user_data['name']}")
            print(f"用户名: {user_data['username']}")
            print(f"邮箱: {user_data['email']}")
            print(f"电话: {user_data['phone']}")
            print(f"网站: {user_data['website']}")
            print("地址:")
            print(f"  街道: {user_data['address']['street']}")
            print(f"  城市: {user_data['address']['city']}")
            print(f"  邮编: {user_data['address']['zipcode']}")
            print("公司:")
            print(f"  名称: {user_data['company']['name']}")
            print(f"  口号: {user_data['company']['catchPhrase']}")
        else:
            print(f"获取用户信息失败，状态码: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"发生网络错误: {e}")

if __name__ == "__main__":
    main()
