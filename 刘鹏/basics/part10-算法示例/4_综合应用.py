import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. 日志配置 (生产环境标准) ---
def setup_logger() -> logging.Logger:
    """配置结构化日志"""
    logger = logging.getLogger("NewsCrawler")
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler (在 Jupyter 等环境中很重要)
    if not logger.handlers:
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    
    return logger

logger = setup_logger()

# --- 2. 爬虫类定义 ---
class NorthNewsCrawler:
    """
    正北方网新闻爬虫 (生产级重构版)
    """
    
    def __init__(self, 
                 base_url: str = "https://www.northnews.cn",
                 timeout: int = 10,
                 output_dir: str = "output"):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在

        # 初始化 Session 并配置重试策略
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # 添加自动重试机制 (网络波动时自动重试)
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def get_category_urls(self) -> Dict[str, str]:
        """获取分类URL字典"""
        return {
            '首页': f'{self.base_url}/',
            '内蒙古': f'{self.base_url}/news/nmgnews/',
            '国内': f'{self.base_url}/news/guonei/',
            '国际': f'{self.base_url}/news/guoji/',
            '财经': f'{self.base_url}/finance/',
            '体育': f'{self.base_url}/news/sports/',
            '文化': f'{self.base_url}/cywh/tjyd/',
        }

    def get_news_list(self, category_url: str) -> List[Dict[str, str]]:
        """解析分类页面，提取新闻链接"""
        news_links = []
        try:
            response = self.session.get(category_url, timeout=self.timeout)
            response.raise_for_status()  # 抛出 HTTP 错误
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link['href']
                text = link.get_text(strip=True)
                
                # 简单的过滤逻辑 (根据实际网站结构调整)
                if text and 5 < len(text) < 100:
                    if href.startswith('/'):
                        full_url = self.base_url + href
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        continue
                    
                    # 去重
                    if not any(item['url'] == full_url for item in news_links):
                        news_links.append({'url': full_url, 'title': text})
                        
        except requests.RequestException as e:
            logger.error(f"获取列表失败 [{category_url}]: {e}")
        except Exception as e:
            logger.error(f"解析列表异常: {e}")
            
        return news_links

    def get_news_content(self, title: str, news_url: str) -> Optional[Dict[str, str]]:
        """获取单篇新闻详情"""
        try:
            response = self.session.get(news_url, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 尝试多种选择器 (根据实际网站结构调整)
            content_selectors = [
                ('div', {'class': 'content'}),
                ('div', {'class': 'article-content'}),
                ('div', {'id': 'content'}),
                ('article', {}),
            ]
            
            content = ""
            for tag, attrs in content_selectors:
                elem = soup.find(tag, attrs)
                if elem:
                    # 提取所有段落文本
                    paragraphs = elem.find_all('p')
                    if paragraphs:
                        content = '\n'.join([p.get_text(strip=True) for p in paragraphs])
                    else:
                        content = elem.get_text(strip=True)
                    break
            
            if not content:
                logger.warning(f"未提取到正文内容: {title}")
                content = "无法获取内容"
            else:
                content = self._clean_content(content)
                
            return {
                'title': title,
                'content': content,
                'url': news_url
            }
            
        except Exception as e:
            logger.error(f"获取内容失败 [{news_url}]: {e}")
            return None

    def _clean_content(self, content: str) -> str:
        """清理文本内容"""
        if not content: return ""
        # 移除多余空白和换行
        content = re.sub(r'\s+', ' ', content)
        return content.strip()

    def crawl_category(self, category_name: str, category_url: str, max_news: int = 10) -> List[Dict]:
        """爬取单个分类"""
        logger.info(f"开始爬取分类: {category_name}")
        news_list = self.get_news_list(category_url)
        
        if not news_list:
            logger.warning(f"分类 {category_name} 未找到新闻链接")
            return []
            
        news_list = news_list[:max_news]
        results = []
        
        for i, item in enumerate(news_list, 1):
            logger.info(f"[{category_name}] ({i}/{len(news_list)}): {item['title']}")
            data = self.get_news_content(item['title'], item['url'])
            if data:
                results.append(data)
            
            # 礼貌爬取：避免请求过快
            time.sleep(0.5)
            
        logger.info(f"分类 {category_name} 爬取完成，成功获取 {len(results)} 篇")
        return results

    def save_data(self, data: Any, filename: str) -> bool:
        """
        生产级安全保存：
        1. 使用原子写入 (先写临时文件，再重命名)
        2. 确保目录存在
        """
        file_path = self.output_dir / filename
        
        try:
            # 使用 NamedTemporaryFile 确保原子性 (delete=False 因为我们要保留它)
            # 注意：在 Windows 上，临时文件必须关闭后才能重命名
            with tempfile.NamedTemporaryFile(
                'w', 
                dir=self.output_dir, 
                delete=False, 
                encoding='utf-8',
                suffix='.tmp'
            ) as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                tmp_path = Path(tmp_file.name)
            
            # 原子性替换 (如果文件存在则覆盖)
            tmp_path.replace(file_path)
            logger.info(f"数据已安全保存至: {file_path}")
            return True
            
        except OSError as e:
            logger.error(f"文件写入失败: {e}")
            # 清理可能残留的临时文件
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return False
        except Exception as e:
            logger.error(f"保存数据时发生未知错误: {e}")
            return False

    def crawl_all_categories(self, max_news_per_category: int = 5) -> Dict[str, List]:
        """爬取所有分类"""
        categories = self.get_category_urls()
        all_data = {}
        
        for name, url in categories.items():
            data = self.crawl_category(name, url, max_news_per_category)
            if data:
                all_data[name] = data
            # 分类间延时
            time.sleep(1)
            
        return all_data

# --- 3. 主程序入口 ---
if __name__ == '__main__':
    crawler = NorthNewsCrawler()
    
    # 场景1：爬取所有分类
    logger.info("="*30 + " 开始全量爬取 " + "="*30)
    all_news = crawler.crawl_all_categories(max_news_per_category=3)
    
    if all_news:
        # 统计信息
        total = sum(len(v) for v in all_news.values())
        logger.info(f"爬取结束。共获取 {total} 篇新闻，涉及 {len(all_news)} 个分类。")
        
        # 保存数据
        crawler.save_data(all_news, 'full_news_data.json')
    
    # 场景2：爬取单个分类示例
    logger.info("="*30 + " 开始单分类测试 " + "="*30)
    test_cat = "国内"
    test_url = crawler.get_category_urls()[test_cat]
    single_news = crawler.crawl_category(test_cat, test_url, max_news=2)
    
    if single_news:
        crawler.save_data(single_news, f'{test_cat}_test.json')

    logger.info("程序执行完毕。")