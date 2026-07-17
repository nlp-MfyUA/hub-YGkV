# ============================================================================
# 作业三：POST请求 - 创建数据
# ============================================================================
#
# 任务描述：
# 编写一个程序，使用POST请求创建新数据：
# 1. 使用POST请求创建一个新帖子
#    URL: https://jsonplaceholder.typicode.com/posts
# 2. 请求体包含：title、body、userId
# 3. 打印响应状态码和响应数据
# 4. 验证返回的数据是否包含提交的数据
#
# 要求：
# - 使用requests.post()发送POST请求
# - 使用json参数传递数据
# - 处理响应数据
# - 添加适当的注释

import requests

def main():
    """
    主函数：演示如何使用 POST 请求创建新数据
    """
    url = "https://jsonplaceholder.typicode.com/posts"
    
    # 准备要发送的数据
    # 这相当于填写一个表单，包含标题、内容和用户ID
    new_post_data = {
        "title": "我的第一个API帖子",
        "body": "这是通过Python requests库发送POST请求创建的帖子内容。",
        "userId": 1
    }
    
    print("=== 正在创建新帖子... ===")
    print(f"准备发送的数据: {new_post_data}")
    
    try:
        # 1. 使用POST请求发送数据
        # 使用 json 参数，requests 会自动将字典转换为 JSON 格式
        # 并设置正确的 Content-Type 请求头
        response = requests.post(url, json=new_post_data)
        
        # 2. 打印响应状态码
        # 201 Created 表示资源创建成功
        print(f"\n响应状态码: {response.status_code}")
        
        # 3. 解析并打印响应数据
        # 服务器会返回创建成功的完整资源信息
        created_post = response.json()
        print("\n服务器返回的数据:")
        print(f"帖子ID: {created_post['id']}")
        print(f"用户ID: {created_post['userId']}")
        print(f"标题: {created_post['title']}")
        print(f"内容: {created_post['body']}")
        
        # 4. 验证返回的数据是否包含提交的数据
        print("\n=== 数据验证 ===")
        is_title_match = created_post['title'] == new_post_data['title']
        is_body_match = created_post['body'] == new_post_data['body']
        is_userId_match = created_post['userId'] == new_post_data['userId']
        
        if is_title_match and is_body_match and is_userId_match:
            print("验证成功！返回的数据与提交的数据完全匹配。")
        else:
            print("验证失败！数据不匹配。")
            if not is_title_match:
                print(f"  标题不匹配: 期望='{new_post_data['title']}', 实际='{created_post['title']}'")
            if not is_body_match:
                print(f"  内容不匹配: 期望='{new_post_data['body']}', 实际='{created_post['body']}'")
            if not is_userId_match:
                print(f"  用户ID不匹配: 期望={new_post_data['userId']}, 实际={created_post['userId']}")
                
    except requests.exceptions.RequestException as e:
        print(f"发生网络错误: {e}")

if __name__ == "__main__":
    main()