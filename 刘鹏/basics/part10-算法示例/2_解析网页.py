# ============================================================================
# 作业二：解析网页 - 提取新闻标题和链接
# ============================================================================
#
# 任务描述：
# 编写一个程序，从正北方网首页提取新闻标题和链接：
# 1. 获取首页HTML内容
# 2. 使用BeautifulSoup解析HTML
# 3. 找到所有的新闻标题和对应的链接
# 4. 提取并显示前10条新闻的标题和链接
# 5. 将提取的数据保存到JSON文件
#
# 要求：
# - 使用BeautifulSoup解析HTML
# - 查找包含新闻标题的元素（可能需要观察网页结构）
# - 提取链接时需要处理相对路径和绝对路径
# - 将数据保存为JSON格式
# - 添加适当的注释

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin # 用于处理相对路径转绝对路径
import json

def crawl_northnews_news():
    """
    爬取正北方网首页的新闻标题和链接
    """
    url = "https://www.northnews.cn/"
    base_url = "https://www.northnews.cn"

    # 设置请求头
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    # 存储提取到的新闻数据
    news_list = []

    try:
        # 1. 发送GET请求获取首页HTML
        response = requests.get(url, headers=headers,timeout=10)
        response.raise_for_status()

        # 自动检测编码并设置
        response.encoding = response.apparent_encoding

        # 2. 使用BeantifulSoup解析html
        soup = BeautifulSoup(response.text, "html.parser")

        news_items = []

        selectors = [
            "div.news-item", # class为new-item的div
            "div.news-list li",  # news-list下的li
            "ul.new li",   # class为new的ul下的li
            "div.main-content a",  # 主要内容区域的链接
            "table tbody tr td span", # 这是最精确的选择器
            ]
        
        for selector in selectors:
            items = soup.select(selector)
            if items:
                news_items = items
                print(f"使用选择器‘{selector}’找到{len(items)}条新闻")
                break # 找到后就退出循环

        # 如果以上选择器都没有找到，退而求其次，找页面这种所有的a标签
        if not news_items:
            print("未找到特定新闻容器，将提取页面中所有的链接，可能包含非新闻链接")
            news_items = soup.find_all("a", href = True)

        # 提取标题和链接
        for item in news_items:
            # 提取链接
            if item.name == "a":
                # 如果item本身就是a标签
                link_tag = item
            else:
                # 如果item是容器（如div.li)，需要找到里面的a标签
                link_tag = item.find("a", href = True)

            print(f"当前的news_items是什么：{news_items}")

            if not link_tag:
                continue  # 没有找到跳过

            # 提取链接地址（href属性）
            href = link_tag.get("href")
            if not href:
                continue

            # 处理相对路径转绝对路径
            absolute_url = urljoin(base_url, href)

            # 提取标题文本
            title = link_tag.get_text(strip=True)

            # 过滤掉空标题或过短的标题
            if not title or len(title) < 2:
                continue

            # 过滤掉JavaScript：开头的链接
            if href.startswith("javascript:") :
                continue

            # 将数据添加到列表
            news_list.append({
                "title": title,
                "url": absolute_url
                })
            
            # 只显示前10条
            if len(news_list) >= 10:
                break

        print("\n" + "=" * 60)
        print("提取到的前10条新闻：")
        print("=" * 60)

        for i, news in enumerate(news_list, 1):
            print(f"{i}. {news['title']}")
            print(f"   链接: {news['url']}")
            print()


        with open("northnews_news_json", "w", encoding="utf-8") as f:
            # indent=2 让json文件格式更美观易懂
            # ensure_ascii=False 确保中文不被转义
            json.dump(news_list, f, indent=2, ensure_ascii="utf-8")
            

    except requests.exceptions.Timeout:
        print("请求超时")
    except requests.exceptions.ConnectionError:
        print("链接失败")
    except requests.exceptions.RequestException as e:
        print(f"请求异常{e}")
    except Exception as e:
        print(f"发生未知错误: {e}")



"""
未来代码的样子
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import logging
import os
from typing import List, Dict, Set

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NorthNewsCrawler:
    def __init__(self, base_url: str = "https://www.northnews.cn/"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def fetch_page(self, url: str) -> str:
        """
        获取网页HTML内容
        """
        try:
            logger.info(f"正在请求: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            logger.info("网页获取成功")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            raise

    def parse_news(self, html_content: str) -> List[Dict[str, str]]:
        """
        解析HTML，提取新闻标题和链接
        """
        soup = BeautifulSoup(html_content, "html.parser")
        news_list = []
        seen_urls: Set[str] = set()  # 用于去重

        # --- 策略一：提取顶部表格中的滚动新闻 (高频更新区) ---
        # 观察源码发现，主要新闻集中在 <table> -> <tbody> -> <tr> -> <td> -> <span> -> <a>
        table_links = soup.select("table tbody tr td span a")
        logger.info(f"策略一：在表格区域找到 {len(table_links)} 个链接")
        
        for link in table_links:
            self._process_link(link, news_list, seen_urls)

        # --- 策略二：提取各板块列表新闻 (要闻、社会民生等) ---
        # 结构通常是：板块标题(h3) -> 后续兄弟节点(ul) -> 列表项(li) -> 链接(a)
        # 使用 CSS 选择器查找所有板块下的列表链接
        section_links = soup.select("h3 + ul li a, h3 + div ul li a")
        logger.info(f"策略二：在板块列表区域找到 {len(section_links)} 个链接")

        for link in section_links:
            self._process_link(link, news_list, seen_urls)

        # --- 策略三：兜底策略 (如果前两种都没抓到，尝试找 class="blue" 的链接) ---
        if len(news_list) < 5:
            logger.warning("前两种策略提取数量较少，启动兜底策略...")
            fallback_links = soup.select('a[href*="/news/"]')
            for link in fallback_links:
                self._process_link(link, news_list, seen_urls)

        logger.info(f"去重后共提取到 {len(news_list)} 条新闻")
        return news_list

    def _process_link(self, tag, news_list: List[Dict[str, str]], seen_urls: Set[str]):
        """
        处理单个链接标签，提取信息并去重
        """
        href = tag.get("href")
        title = tag.get_text(strip=True)

        # 基础过滤
        if not href or not title or len(title) < 4:
            return
        if href.startswith("javascript:") or href.startswith("#"):
            return
        
        # 处理相对路径
        full_url = urljoin(self.base_url, href)

        # 去重逻辑
        if full_url in seen_urls:
            return
        
        seen_urls.add(full_url)

        news_list.append({
            "title": title,
            "url": full_url
        })

    def save_to_json(self, data: List[Dict[str, str]], filename: str = "northnews_news.json"):
        """
        保存数据到JSON文件
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"数据已成功保存至: {filename}")
        except IOError as e:
            logger.error(f"文件保存失败: {e}")

    def run(self):
        """
        主运行流程
        """
        try:
            html = self.fetch_page(self.base_url)
            news_data = self.parse_news(html)
            
            # 截取前10条展示
            top_10 = news_data[:100]
            
            print("\n" + "="*60)
            print(f"提取到的前 {len(top_10)} 条新闻预览：")
            print("="*60)
            for i, news in enumerate(top_10, 1):
                print(f"{i}. {news['title']}")
                print(f"   {news['url']}")
            print("="*60)

            self.save_to_json(news_data)
            
        except Exception as e:
            logger.error(f"程序运行出错: {e}")
    


# 运行程序
if __name__ == "__main__":
    #crawl_northnews_news()
    crawler = NorthNewsCrawler()
    crawler.run()