import requests
from bs4 import BeautifulSoup
import time
from typing import List, Dict, Any
import json

class SearchResult:
    def __init__(self, title:str, url:str, snippet:str, source:str, ts:str):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source
        self.ts = ts
        self.score = 0.0
        self.content = ""

    def to_dict(self):
        return {
            "title":self.title, "url":self.url, "snippet":self.snippet,
            "source":self.source, "ts":self.ts, "score":self.score,
            "content":self.content[:300]
        }

class BaseResearcher:
    def __init__(self):
        self.results:List[SearchResult] = []
        self.conflict_records = []

    def web_search(self, query:str) -> List[SearchResult]:
        """这里对接你平台的web_search接口；如果是本地可以替换SerpAPI/DuckDuckGo"""
        # 伪代码占位：实际替换成平台搜索函数
        print(f"[SEARCH] {query}")
        time.sleep(0.8)
        return []

    def fetch_page(self, url:str) -> str:
        """网页精读，提取正文，过滤广告导航"""
        try:
            headers = {"User-Agent":"Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script","style","nav","footer"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return text[:6000]
        except Exception as e:
            return f"[FETCH ERR] {str(e)}"

    def score_item(self, item:SearchResult) -> float:
        """确定性打分规则（硬编码，和skill文档规则一一对应）"""
        score = 0.0
        domain = item.source.lower()
        # 权威加分
        if "github.com" in domain: score += 3
        if "docs." in domain or "official" in domain: score += 3
        if "arxiv.org" in domain: score +=2.5
        if "juejin.cn" in domain or "zhihu.com" in domain: score +=1
        # 时效：简单判断，这里简化
        if "2025" in item.ts or "2026" in item.ts: score +=1.5
        # 低质降分
        if "推广" in item.snippet or "付费" in item.snippet: score -=3
        item.score = score
        return score

    def cross_check(self, items:List[SearchResult], keyword:str) -> (bool, List[str]):
        """交叉核验：统计多少来源支持同一个结论"""
        supports = []
        for i in items:
            if keyword in i.content:
                supports.append(i.url)
        ok = len(supports)>=2
        return ok, supports
