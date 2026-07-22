# ============================================================================
# 作业二：处理API响应 - 数据提取
# ============================================================================
#
# 任务描述：
# 编写一个程序，从JSONPlaceholder API获取数据并进行处理：
# 1. 获取所有帖子（posts）
#    URL: https://jsonplaceholder.typicode.com/posts
# 2. 统计帖子总数
# 3. 找出用户ID为1的所有帖子
# 4. 显示前5个帖子的标题
# 5. 找出标题最长的帖子
#
# 要求：
# - 解析JSON响应
# - 使用循环和条件语句处理数据
# - 输出格式清晰


import requests

def main():
    """
    主函数：从API获取帖子数据并进行处理
    """
    url = "https://jsonplaceholder.typicode.com/posts"
    
    try:
        # 1. 获取所有帖子
        print("=== 正在获取所有帖子... ===")
        response = requests.get(url)
        
        if response.status_code == 200:
            # 解析JSON响应
            posts = response.json()

            print(f"先查看数据样式和格式：{posts}")
            
            # 2. 统计帖子总数
            total_posts = len(posts)
            print(f"\n帖子总数: {total_posts}")
            
            # 3. 找出用户ID为1的所有帖子
            user1_posts = []
            for post in posts:
                if post["userId"] == 1:
                    user1_posts.append(post)
            
            print(f"\n用户ID为1的帖子数量: {len(user1_posts)}")
            
            # 4. 显示前5个帖子的标题
            print("\n--- 前5个帖子的标题 ---")
            for i, post in enumerate(posts[:5], 1):
                print(f"{i}. {post['title']}")
            
            # 5. 找出标题最长的帖子
            longest_post = posts[0]
            for post in posts:
                if len(post["title"]) > len(longest_post["title"]):
                    longest_post = post
            
            print("\n--- 标题最长的帖子 ---")
            print(f"标题: {longest_post['title']}")
            print(f"长度: {len(longest_post['title'])} 个字符")
            print(f"作者ID: {longest_post['userId']}")
            
        else:
            print(f"请求失败，状态码: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"发生网络错误: {e}")

if __name__ == "__main__":
    main()