# 第十部分-算法示例 作业说明
# 
# 本部分作业共4道题，从简单到复杂，帮助巩固以下知识点：
# - 使用requests库发送HTTP请求
# - 使用BeautifulSoup解析网页HTML
# - 提取网页中的结构化数据
# - 处理文件读写（JSON格式）
# - 异常处理在网络爬虫中的应用
#
# 注意：本部分作业需要使用以下库：
# - requests：pip install requests
# - beautifulsoup4：pip install beautifulsoup4
# - 本部分作业可以使用之前学过的所有知识

"""
response = requests.get(url, headers=headers)

# 通过 Content-Type 判断返回格式
content_type = response.headers.get("Content-Type", "")

if "json" in content_type:
    data = response.json()
    print("返回的是JSON格式")

elif "xml" in content_type:
    soup = BeautifulSoup(response.text, "xml")
    print("返回的是XML格式")

elif "html" in content_type:
    soup = BeautifulSoup(response.text, "html.parser")
    print("返回的是HTML格式")

elif "image" in content_type or "octet-stream" in content_type:
    with open("file", "wb") as f:
        f.write(response.content)
    print("返回的是二进制文件")

else:
    print(f"未知格式: {content_type}")
    print(response.text[:200])  # 先打印前200字符看看
"""
#
# ============================================================================
# 作业一：基础爬虫 - 获取网页内容
# ============================================================================
#
# 任务描述：
# 编写一个程序，爬取正北方网（https://www.northnews.cn/）的首页内容：
# 1. 使用requests库发送GET请求获取网页
# 2. 设置合适的请求头（User-Agent）
# 3. 打印响应状态码
# 4. 获取网页的标题（title标签）
# 5. 打印网页的部分内容（前500个字符）
# 6. 使用异常处理处理网络错误
#
# 要求：
# - 使用requests.get()发送请求
# - 设置合适的请求头
# - 使用try-except处理网络异常
# - 添加适当的注释

import requests
from bs4 import BeautifulSoup
import random

def crawl_northnews():
    """
    爬取北正方网首页内容
    """

    # 目标URL
    url = "https://www.northnews.cn/"

    # 准备多个User-Agent，随机切换，降低被识别概率
    USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]

    # 设置请求头，模拟浏览器访问，防止被反爬虫机制拦截
    headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html, application/xhtml+xml, application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;qq=0.9,en;q=0.8"
        }
    
    # 使用try-except处理网络异常
    try:
        # 1.发送GET请求获取网页内容，设置超时时间为10秒
        response = requests.get(url, headers=headers,timeout=10)

        # 2. 打印响应状态为200（成功）
        response.raise_for_status()

        # 3.设置响应内容的编码
        # response.encoding # requests猜测的编码
        # 有些网站编码不正确。需要手动指定,chardet库自动检测的编码
        response.encoding = response.apparent_encoding

        # 4.使用BeantifulSoup解析html内容
        soup = BeautifulSoup(response.text, "html.parser")

        # 5. 获取网址标题
        title = soup.title.string if  soup.title else "未找到标题"
        print(f"网页标题: {title}")

        # 6.打印网页的部分内容
        # 使用 get_text()提取文本内容，strip()去除首尾空白
        page_text = soup.get_text(strip=True)
        print(f"\n网页内容（前500个字符）:")
        print("-" * 50)
        print(page_text[:500])
        print("-" * 50)

        # 补充：打印网页的文本总长度
        print(f"\n网页文本总长度: {len(page_text)} 个字符")

    except requests.exceptions.Timeout:
        print("请求超时！请检查网络连接或增加超时时间。")
    except requests.exceptions.ConnectionError:
        print("连接失败！请检查网络连接或目标网站是否可访问。")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误！状态码: {e.response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")


# 运行程序
if __name__ == "__main__":
    print("=" * 60)
    print("作业一：基础爬虫 - 获取正北方网首页内容")
    print("=" * 60)
    crawl_northnews()

     
