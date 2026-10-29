"""
pageindex_multimodel.py
支持：多 LLM 提供商、多 Key 管理、Index/Chat 模型分离、运行时热切换
"""

import os
import time
import yaml
from pageindex import PageIndexClient


class PageIndexMultiModel:
    """
    PageIndex 多模型管理器

    用法：
        qa = PageIndexMultiModel(config_path="pageindex_config.yaml")
        qa.index_pdf("report.pdf")
        qa.ask("这份报告的核心结论是什么？")
        qa.switch_chat_model("qwen", "qwen-max", "sk-qwen-xxx", "https://...")
        qa.ask("换模型后再问一次")
    """

    # 内置常见提供商的默认 base_url
    PROVIDER_BASE_URLS = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
    }

    def __init__(self, config_path: str = None, config_dict: dict = None):
        """
        初始化
        :param config_path: YAML 配置文件路径
        :param config_dict: 直接传入配置字典（优先级最高）
        """
        if config_dict:
            self.config = config_dict
        elif config_path:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = self._load_from_env()

        self._apply_env_vars()  # 把 key/base_url 注入环境变量
        self.client = self._create_client()
        self._current_doc_id = None

    # ─── 初始化辅助 ───────────────────────────────────────────────

    def _load_from_env(self) -> dict:
        """
            从环境变量加载（无配置文件时的兜底方案）
        """
        return {
            "pageindex": {"api_key": os.getenv("PAGEINDEX_API_KEY", "")},
            "index": {
                "provider": os.getenv("INDEX_PROVIDER", "deepseek"),
                "model": os.getenv("INDEX_MODEL", "deepseek-chat"),
                "api_key": os.getenv("INDEX_API_KEY", ""),
                "base_url": os.getenv("INDEX_BASE_URL", self.PROVIDER_BASE_URLS["deepseek"]),
            },
            "chat": {
                "provider": os.getenv("CHAT_PROVIDER", "openai"),
                "model": os.getenv("CHAT_MODEL", "gpt-4o"),
                "api_key": os.getenv("CHAT_API_KEY", ""),
                "base_url": os.getenv("CHAT_BASE_URL", self.PROVIDER_BASE_URLS["deepseek"]),
            },
        }

    def _apply_env_vars(self):
        """
        把当前配置的 key 和 base_url 写入环境变量
        PageIndex 底层用 OpenAI SDK，会从环境变量读取
        """
        os.environ["OPENAI_API_KEY"] = self.config["chat"]["api_key"]
        os.environ["OPENAI_BASE_URL"] = self.config["chat"]["base_url"]

    def _create_client(self) -> PageIndexClient:
        """根据当前配置创建 PageIndexClient"""
        return PageIndexClient(
            api_key=self.config["pageindex"]["api_key"],
            index_model=self.config["index"]["model"],
            chat_model=self.config["chat"]["model"],
        )

    # ─── 公开 API ──────────────────────────────────────────────────

    def switch_index_model(self, provider: str, model: str,
                           api_key: str = None, base_url: str = None):
        """热切换建树模型"""
        self.config["index"]["provider"] = provider
        self.config["index"]["model"] = model
        if api_key:
            self.config["index"]["api_key"] = api_key
        self.config["index"]["base_url"] = base_url or self.PROVIDER_BASE_URLS.get(
            provider, base_url or ""
        )
        # 重建客户端
        self.client = self._create_client()
        print(f"✅ 索引模型已切换为: {provider} / {model}")

    def switch_chat_model(self, provider: str, model: str,
                          api_key: str = None, base_url: str = None):
        """热切换问答模型"""
        self.config["chat"]["provider"] = provider
        self.config["chat"]["model"] = model
        if api_key:
            self.config["chat"]["api_key"] = api_key
        self.config["chat"]["base_url"] = base_url or self.PROVIDER_BASE_URLS.get(
            provider, base_url or ""
        )
        self._apply_env_vars()
        self.client = self._create_client()
        print(f"✅ 问答模型已切换为: {provider} / {model}")

    def index_pdf(self, pdf_path: str, wait: bool = True) -> str:
        """上传并索引 PDF"""
        result = self.client.submit_document(pdf_path)
        doc_id = result["doc_id"]
        self._current_doc_id = doc_id
        print(f"📄 文档已提交，doc_id = {doc_id}")

        if not wait:
            return doc_id

        while True:
            info = self.client.get_document(doc_id)
            status = info["status"]
            if status == "completed":
                pages = info.get("pageNum", "?")
                print(f"✅ 索引完成（共 {pages} 页）")
                return doc_id
            elif status == "processing":
                print("⏳ 正在建立树索引...")
                time.sleep(8)
            else:
                raise RuntimeError(f"索引失败，状态: {status}")

    def ask(self, question: str, doc_id: str = None,
            stream: bool = True) -> str:
        """提问"""
        doc_id = doc_id or self._current_doc_id
        if not doc_id:
            raise ValueError("请先调用 index_pdf() 或传入 doc_id")

        if stream:
            print(f"\n💡 [{self.config['chat']['provider']}/{self.config['chat']['model']}] ", end="")
            full = ""
            for chunk in self.client.chat_completions(
                    messages=[{"role": "user", "content": question}],
                    doc_id=doc_id,
                    stream=True,
            ):
                print(chunk, end="", flush=True)
                full += chunk
            print()
            return full
        else:
            resp = self.client.chat_completions(
                messages=[{"role": "user", "content": question}],
                doc_id=doc_id,
            )
            ans = resp["choices"][0]["message"]["content"]
            print(f"\n💡 [{self.config['chat']['provider']}/{self.config['chat']['model']}] {ans}")
            return ans

    def get_tree(self, doc_id: str = None):
        """获取文档的树状索引结构"""
        doc_id = doc_id or self._current_doc_id
        tree = self.client.get_tree(doc_id, node_summary=True)["result"]
        return tree

    def show_config(self):
        """打印当前配置"""
        print("\n=== 当前 PageIndex 配置 ===")
        print(f"PageIndex API Key: {'已配置' if self.config['pageindex']['api_key'] else '未配置'}")
        print(f"索引模型: {self.config['index']['provider']} / {self.config['index']['model']}")
        print(f"问答模型: {self.config['chat']['provider']} / {self.config['chat']['model']}")
        print("===========================\n")


