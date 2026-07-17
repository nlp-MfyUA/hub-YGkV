# ============================================================================
# 作业三：分类爬取 - 爬取不同分类的新闻
# ============================================================================
#
# 任务描述：
# 编写一个程序，爬取正北方网不同分类的新闻：
# 1. 定义多个分类的URL（如：内蒙古、国内、国际等）
# 2. 为每个分类创建一个爬取函数
# 3. 从每个分类页面提取新闻列表（标题、链接、时间等）
# 4. 将不同分类的新闻分别保存到不同的JSON文件
# 5. 统计每个分类爬取的新闻数量
#
# 要求：
# - 使用函数组织代码
# - 处理每个分类的网页结构差异
# - 添加适当的延时，避免请求过快
# - 使用异常处理确保某个分类失败不影响其他分类
# - 添加详细的注释

import requests
from bs4 import BeautifulSoup
import json
import time
import os

def crawl_category(url, category_name):
    """爬取指定分类的新闻列表"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        print(f"\n正在爬取分类：{category_name}")
        print(f"URL：{url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        
        if response.status_code != 200:
            print(f"请求失败，状态码：{response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        news_list = []
        seen_urls = set()  # 【优化1】用集合去重，替代 any() 遍历
        
        # 提取新闻列表
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            if text and len(text) > 5 and len(text) < 100:
                # 处理链接
                if href.startswith('/'):
                    full_url = 'https://www.northnews.cn' + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # 【优化1】用 set 判断去重，时间复杂度从 O(n) 降到 O(1)
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    news_list.append({
                        'title': text,
                        'url': full_url,
                        'category': category_name
                    })
        
        print(f"找到 {len(news_list)} 条新闻")
        return news_list[:20]
        
    except Exception as e:
        print(f"爬取分类 {category_name} 时出错：{type(e).__name__}: {e}")
        return []

def save_category_data(news_list, category_name):
    """保存分类数据到JSON文件"""
    if not news_list:
        print(f"分类 {category_name} 没有数据可保存")
        return False
    
    # 【优化2】统一输出到子目录，避免文件散落在当前目录
    output_dir = 'northnews_output'
    os.makedirs(output_dir, exist_ok=True)
    
    filename = os.path.join(output_dir, f'northnews_{category_name}.json')
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(news_list, f, ensure_ascii=False, indent=2)
        print(f"分类 {category_name} 的数据已保存到 {filename}")
        return True
    except Exception as e:
        print(f"保存分类 {category_name} 数据失败：{type(e).__name__}: {e}")
        return False

# 主程序
print("=" * 60)
print("分类爬取 - 爬取不同分类的新闻")
print("=" * 60)

# 定义不同分类的URL
categories = {
    '首页': 'https://www.northnews.cn/',
    '财经': 'https://www.northnews.cn/finance/',
    '国内': 'https://www.northnews.cn/news/guonei/',
    '国际': 'https://www.northnews.cn/news/guoji/',
}

print(f"\n准备爬取 {len(categories)} 个分类")

all_results = {}

for category_name, url in categories.items():
    # 爬取分类
    news_list = crawl_category(url, category_name)
    
    if news_list:
        all_results[category_name] = news_list
        # 保存每个分类的数据
        save_category_data(news_list, category_name)
    
    # 添加延时，避免请求过快
    if category_name != list(categories.keys())[-1]:
        print("等待1秒后继续...")
        time.sleep(1)

# 统计信息
print("\n" + "=" * 60)
print("爬取统计")
print("=" * 60)

total_news = 0
for category_name, news_list in all_results.items():
    count = len(news_list)
    total_news += count
    print(f"{category_name}：{count} 条")

print(f"\n总计：{total_news} 条新闻")

# 保存所有数据到一个文件
# 【优化2】汇总文件也保存到同一子目录
output_dir = 'northnews_output'
os.makedirs(output_dir, exist_ok=True)
all_data_file = os.path.join(output_dir, 'northnews_all_categories.json')
try:
    with open(all_data_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n所有分类数据已保存到 {all_data_file}")
except Exception as e:
    print(f"保存总数据失败：{type(e).__name__}: {e}")

print("\n" + "=" * 60)
    