from research_base import BaseResearcher, SearchResult

class EmotionAgentResearcher(BaseResearcher):
    def get_queries(self) -> List[str]:
        return [
            "LangGraph 情感识别agent 状态机 分支路由",
            "OpenAI Agents SDK emotion agent handoff 结构化输出",
            "大模型情感识别提示词 正向鼓励 负面疏导",
            "LangGraph vs OpenAI Agents SDK 开发调试对比",
            "LangGraph agent记忆持久化 流式输出示例"
        ]

    def run(self):
        raw = []
        for q in self.get_queries():
            batch = self.web_search(q)
            raw.extend(batch)
        for r in raw:
            self.score_item(r)
        raw_sorted = sorted(raw, key=lambda x:x.score, reverse=True)
        candidates = [x for x in raw_sorted if x.score >=2.0]
        for item in candidates[:6]:
            item.content = self.fetch_page(item.url)
        report = self.build_report(candidates)
        return report

    def build_report(self, items:List[SearchResult]) -> str:
        refs = "\n".join([f"- {it.title}: {it.url}" for it in items])
        report = f"""# LangGraph vs OpenAI Agents：情感识别对话Agent调研报告
## 1. 调研摘要
【脚本自动汇总】
## 2. 需求回顾
流程：接收用户文本请求 → 情感识别节点 → 根据情感结果分支输出（正向鼓励 / 负面情绪疏导）
## 3. LangGraph方案调研
3.1 状态机设计思路
3.2 节点划分、路由逻辑
3.3 样例核心代码要点、优势、短板
## 4. OpenAI Agents SDK方案调研
4.1 Agent定义、工具调用、结构化情感输出
4.2 实现思路、优势、短板
## 5. 多维度对比表（开发难度、调试、扩展、部署成本、生态）
## 6. 落地选型建议
## 7. 置信度标注 & 参考来源链接
{refs}
## 8. 调研局限性
"""
        return report

if __name__=="__main__":
    s = EmotionAgentResearcher()
    print(s.run())
