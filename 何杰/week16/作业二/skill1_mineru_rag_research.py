from research_base import BaseResearcher, SearchResult

class MinerURAGResearcher(BaseResearcher):
    def get_queries(self) -> List[str]:
        # 固定预设搜索query，替代大模型自己瞎想搜索词
        return [
            "MinerU PDF解析 图文提取 输出格式",
            "kafka 异步RAG任务队列 状态流转 待解析 解析中",
            "多模态RAG 图文联合召回 图文混排回答实现",
            "MinerU kafka 多模态RAG工程踩坑 分片 幂等",
            "MinerU官方文档 支持图片公式表格"
        ]

    def run(self):
        raw = []
        for q in self.get_queries():
            batch = self.web_search(q)
            raw.extend(batch)
        # 打分、排序、过滤低分
        for r in raw:
            self.score_item(r)
        raw_sorted = sorted(raw, key=lambda x:x.score, reverse=True)
        candidates = [x for x in raw_sorted if x.score >=2.0]
        # 精读高分
        for item in candidates[:6]:
            item.content = self.fetch_page(item.url)
        # 固定报告模板，确定性填充
        report = self.build_report(candidates)
        return report

    def build_report(self, items:List[SearchResult]) -> str:
        refs = "\n".join([f"- {it.title}: {it.url}" for it in items])
        report = f"""# Kafka+MinerU多模态RAG系统调研报告
## 1. 调研摘要
【脚本自动汇总】
## 2. 核心组件调研详情
2.1 MinerU能力边界、解析输出结构、部署方式
2.2 Kafka异步任务链路设计（上传→入队→消费解析→状态回写）
2.3 多模态检索&问答实现（图文混排输出、图文联合提问）
## 3. 典型工程架构图文字版
## 4. 风险与坑点清单（重点）
## 5. 选型建议&扩展方向
## 6. 信息置信说明 & 参考来源列表
{refs}
## 7. 调研局限性
"""
        return report

if __name__=="__main__":
    s = MinerURAGResearcher()
    print(s.run())
