# ============================================================================
# 作业四：综合应用 - 简单的API客户端
# ============================================================================
#
# 任务描述：
# 编写一个简单的API客户端程序，实现以下功能：
# 1. 显示菜单：
#    - 1. 获取所有用户
#    - 2. 获取指定用户信息（输入用户ID）
#    - 3. 获取所有帖子
#    - 4. 获取指定用户的帖子（输入用户ID）
#    - 5. 退出
# 2. 使用while循环让程序可以重复执行
# 3. 根据用户选择执行相应的API调用
# 4. 格式化显示API返回的数据
# 5. 处理错误情况（网络错误、无效输入等）
#
# 要求：
# - 使用函数组织代码
# - 使用requests库发送HTTP请求
# - 使用try-except处理错误
# - 输出格式清晰美观
# - 添加详细的注释
#

import requests

# API 基础地址
BASE_URL = "https://jsonplaceholder.typicode.com"


def get_all_users():
    """获取并显示所有用户信息"""
    print("\n=== 所有用户列表 ===")
    try:
        response = requests.get(f"{BASE_URL}/users")
        if response.status_code == 200:
            users = response.json()
            print(f"共 {len(users)} 个用户\n")
            for user in users:
                print(f"  ID: {user['id']}")
                print(f"  姓名: {user['name']}")
                print(f"  用户名: {user['username']}")
                print(f"  邮箱: {user['email']}")
                print(f"  {'─' * 30}")
        else:
            print(f"请求失败，状态码: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"网络错误: {e}")


def get_user_by_id():
    """根据用户ID获取指定用户信息"""
    print("\n=== 查询指定用户 ===")
    user_id = input("请输入用户ID（1-10）: ").strip()

    # 验证输入是否为数字
    if not user_id.isdigit():
        print("❌ 输入无效，请输入一个数字。")
        return

    try:
        response = requests.get(f"{BASE_URL}/users/{user_id}")
        if response.status_code == 200:
            user = response.json()
            print(f"\n  姓名: {user['name']}")
            print(f"  用户名: {user['username']}")
            print(f"  邮箱: {user['email']}")
            print(f"  电话: {user['phone']}")
            print(f"  网站: {user['website']}")
            print(f"  地址: {user['address']['street']}, "
                  f"{user['address']['city']}, "
                  f"{user['address']['zipcode']}")
            print(f"  公司: {user['company']['name']}")
        elif response.status_code == 404:
            print(f"❌ 未找到ID为 {user_id} 的用户。")
        else:
            print(f"请求失败，状态码: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"网络错误: {e}")


def get_all_posts():
    """获取并显示所有帖子的标题"""
    print("\n=== 所有帖子列表 ===")
    try:
        response = requests.get(f"{BASE_URL}/posts")
        if response.status_code == 200:
            posts = response.json()
            print(f"共 {len(posts)} 个帖子\n")
            for post in posts:
                print(f"  [{post['id']}] (用户{post['userId']}) {post['title']}")
        else:
            print(f"请求失败，状态码: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"网络错误: {e}")


def get_posts_by_user():
    """根据用户ID获取该用户的所有帖子"""
    print("\n=== 查询指定用户的帖子 ===")
    user_id = input("请输入用户ID（1-10）: ").strip()

    # 验证输入是否为数字
    if not user_id.isdigit():
        print("❌ 输入无效，请输入一个数字。")
        return

    try:
        # 方式一：使用查询参数 ?userId=xxx
        response = requests.get(f"{BASE_URL}/posts", params={"userId": user_id})
        if response.status_code == 200:
            posts = response.json()
            if len(posts) == 0:
                print(f"用户 {user_id} 没有任何帖子。")
            else:
                print(f"\n用户 {user_id} 共有 {len(posts)} 个帖子:\n")
                for post in posts:
                    print(f"  [{post['id']}] {post['title']}")
                    print(f"         {post['body'][:60]}...")
                    print()
        else:
            print(f"请求失败，状态码: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"网络错误: {e}")


def show_menu():
    """显示主菜单"""
    print("  API 客户端程序          ")
    print("1. 获取所有用户             ")
    print("2. 获取指定用户信息       ")
    print("3. 获取所有帖子            ")
    print("4. 获取指定用户的帖子      ")
    print("5. 退出                   ")
 


def main():
    """主函数：程序入口"""
    while True:
        show_menu()
        choice = input("\n请选择功能（1-5）: ").strip()

        if choice == "1":
            get_all_users()
        elif choice == "2":
            get_user_by_id()
        elif choice == "3":
            get_all_posts()
        elif choice == "4":
            get_posts_by_user()
        elif choice == "5":
            print("\n👋 再见！感谢使用 API 客户端。")
            break
        else:
            print("❌ 无效选择，请输入 1-5 之间的数字。")


if __name__ == "__main__":
    main()