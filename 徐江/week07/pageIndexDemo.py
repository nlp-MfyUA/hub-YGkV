"""
pageindex_cached_qa.py
==========================================
基于 PageIndex 的 PDF 文档切分 + 本地持久化 QA 引擎（Windows 优化版）

【主要改进】
    * API Key 从 config.ini 读取（不再硬编码）
    * 路径处理兼容 Windows（使用 pathlib）
    * JSON 存储增强容错（default=str）
    * 索引就绪等待添加超时
    * 配置文件自动创建模板

【依赖】
    pip install pageindex
    （pypdf 非必需，本代码仅用 hashlib/os/pathlib）

【配置】
    在程序目录下创建 config.ini，内容如下：
        [pageindex]
        api_key = sk-7e37fcd6ba634ecbbce8758b07599f72
        index_model = gpt-5.6-luna
        chat_model = gpt-5.6-sol
        storage_path = ./.pageindex_cache

【用法】
    engine = PageIndexQAEngine()
    doc_id = engine.ingest("report.pdf")   # 首次切分并缓存
    doc_id = engine.ingest("report.pdf")   # 直接命中缓存，不再切分
    engine.ask("核心结论？", doc_id=doc_id, stream=True)
"""

import os
import json
import time
import hashlib
import configparser
from pathlib import Path
from typing import Optional, Dict, Any, List


# ----------------------------------------------------------------------
# 配置文件加载（自动创建模板）
# ----------------------------------------------------------------------
def load_config(config_file: str = "config.ini") -> configparser.SectionProxy:
    """从 config.ini 读取 [pageindex] 配置段，若不存在则创建模板并退出。"""
    config_path = Path(config_file)
    if not config_path.exists():
        print(f"⚠️ 配置文件 {config_file} 不存在，正在创建模板...")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("""[pageindex]
api_key = your_api_key_here
index_model = deepseek-v4-flash	
chat_model = deepseek-v4-flash	
storage_path = ./.pageindex_cache
""")
        print(f"请编辑 {config_file} 填入您的 API Key 后重新运行程序。")
        raise SystemExit(0)

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if "pageindex" not in parser:
        raise SystemExit("config.ini 中缺少 [pageindex] 配置段")
    return parser["pageindex"]


# ----------------------------------------------------------------------
# 文档指纹
# ----------------------------------------------------------------------
def file_fingerprint(pdf_path: str, head_bytes: int = 4096) -> str:
    """生成稳定指纹，用于判断文档是否已切分过。"""
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")
    stat = p.stat()
    h = hashlib.md5()
    with open(p, "rb") as f:
        h.update(f.read(head_bytes))
    raw = f"{p.resolve()}|{stat.st_size}|{int(stat.st_mtime)}|{h.hexdigest()[:12]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# 主引擎
# ----------------------------------------------------------------------
class PageIndexQAEngine:
    """PageIndex 文档切分 + 本地缓存 + 问答引擎（Windows 优化版）"""

    MANIFEST_FILENAME = "manifest.json"

    def __init__(
        self,
        config_file: str = "config.ini",
        api_key: Optional[str] = None,
        index_model: Optional[str] = None,
        chat_model: Optional[str] = None,
        storage_path: Optional[str] = None,
        fingerprint_head_bytes: int = 4096,
    ):
        """
        参数优先级：构造函数显式传入 > config.ini 配置 > 环境变量。
        通常只需提供 config_file，其他参数从配置文件读取。
        """
        # 读取配置文件（若存在）
        if Path(config_file).exists():
            config = load_config(config_file)
            api_key = api_key or config.get("api_key", "")
            index_model = index_model or config.get("index_model", "deepseek-v4-flash")
            chat_model = chat_model or config.get("chat_model", "deepseek-v4-flash")
            storage_path = storage_path or config.get("storage_path", "./.pageindex_cache")
        else:
            # 无配置文件时回退到环境变量或默认值
            api_key = api_key or os.environ.get("PAGEINDEX_API_KEY", "")
            index_model = index_model or os.environ.get("INDEX_MODEL", "deepseek-v4-flash")
            chat_model = chat_model or os.environ.get("CHAT_MODEL", "deepseek-v4-flash")
            storage_path = storage_path or os.environ.get("STORAGE_PATH", "./.pageindex_cache")

        if not api_key or api_key == "your_api_key_here":
            raise SystemExit("错误：API Key 未配置，请在 config.ini 中填写真实 Key。")

        # 路径统一转换为绝对路径，避免 Windows 下相对路径不一致
        self.storage_path = str(Path(storage_path).resolve())
        os.makedirs(self.storage_path, exist_ok=True)
        self.fingerprint_head_bytes = fingerprint_head_bytes

        # 初始化 PageIndex 客户端
        try:
            from pageindex import PageIndexClient
        except ImportError:
            raise SystemExit("请先安装 pageindex：pip install pageindex")

        self.client = PageIndexClient(
            api_key=api_key,
            index_model=index_model,
            chat_model=chat_model,
            storage_path=self.storage_path,
        )

        # 加载 manifest
        self.manifest_path = os.path.join(self.storage_path, self.MANIFEST_FILENAME)
        self.manifest = self._load_manifest()

    # ─── manifest 读写 ────────────────────────────────────────────
    def _load_manifest(self) -> Dict[str, Any]:
        """加载 manifest.json，若损坏则重建。"""
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"⚠️ manifest.json 损坏，重建（错误：{e}）")
        return {"documents": {}}

    def _save_manifest(self):
        """保存 manifest.json，增强容错。"""
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(self.manifest, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"❌ 保存 manifest.json 失败：{e}")

    # ─── 文档切分（带缓存）──────────────────────────────────────
    def ingest(
        self,
        pdf_path: str,
        force_reindex: bool = False,
        wait: bool = True,
        export_snapshot: bool = True,
    ) -> str:
        """
        切分 PDF 并缓存结果。
        同一文档再次调用将直接返回缓存 doc_id，不再调用模型切分。
        """
        pdf_path = str(Path(pdf_path).resolve())
        fingerprint = file_fingerprint(pdf_path, self.fingerprint_head_bytes)

        # ① 命中缓存
        if not force_reindex and fingerprint in self.manifest["documents"]:
            cached = self.manifest["documents"][fingerprint]
            doc_id = cached["doc_id"]
            print(f"✅ 命中本地缓存，跳过切分（doc_id={doc_id}）")
            if self._is_ready(doc_id):
                return doc_id
            print("⚠️ 缓存索引未就绪，重新切分...")

        # ② 首次切分（唯一调用模型的步骤）
        print(f"🔪 首次切分文档: {pdf_path}")
        print("   （此步骤会调用 index_model 构建层级树索引）")
        try:
            result = self.client.submit_document(pdf_path, wait=wait)
            doc_id = result["doc_id"]
        except Exception as e:
            raise RuntimeError(f"提交文档切分失败：{e}")

        if wait:
            doc_id = self._wait_until_ready(doc_id)

        # ③ 持久化 manifest
        self.manifest["documents"][fingerprint] = {
            "doc_id": doc_id,
            "pdf_path": pdf_path,
            "file_name": os.path.basename(pdf_path),
            "fingerprint": fingerprint,
            "index_model": self.client.index_model,
            "indexed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_manifest()

        if export_snapshot:
            self._export_tree_snapshot(doc_id, fingerprint)

        print(f"💾 切分产物已持久化到: {self.storage_path}")
        return doc_id

    def _wait_until_ready(self, doc_id: str, timeout: int = 600, poll_interval: int = 5) -> str:
        """轮询等待索引就绪，超时后抛出异常。"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                info = self.client.get_document(doc_id)
                status = info.get("status", "")
                if status == "completed":
                    return doc_id
                if status in ("failed", "error"):
                    raise RuntimeError(f"文档切分失败，status={status}, info={info}")
                print("   ⏳ 正在建立树索引...")
                time.sleep(poll_interval)
            except Exception as e:
                print(f"   ⚠️ 查询状态异常：{e}，继续等待...")
                time.sleep(poll_interval)
        raise TimeoutError(f"等待索引就绪超时（{timeout}秒）")

    def _is_ready(self, doc_id: str) -> bool:
        try:
            return self.client.get_document(doc_id).get("status") == "completed"
        except Exception:
            return False

    # ─── 导出树快照 ──────────────────────────────────────────────
    def _export_tree_snapshot(self, doc_id: str, fingerprint: str):
        """导出可序列化的树快照，默认使用 default=str 避免不可序列化对象。"""
        try:
            tree = self.client.get_tree(
                doc_id, node_summary=True, include_text=False
            ).get("result", {})
            snap_path = os.path.join(
                self.storage_path, f"tree_snapshot_{fingerprint[:10]}.json"
            )
            with open(snap_path, "w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2, default=str)
            print(f"   📄 树索引快照已导出: {os.path.basename(snap_path)}")
        except Exception as e:
            # 快照失败不影响主流程
            print(f"   ⚠️ 快照导出失败（可忽略）: {e}")

    def load_tree_snapshot(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """读取本地树快照。"""
        snap_path = os.path.join(
            self.storage_path, f"tree_snapshot_{fingerprint[:10]}.json"
        )
        if os.path.exists(snap_path):
            try:
                with open(snap_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    # ─── 问答 ──────────────────────────────────────────────────────
    def ask(self, question: str, doc_id: str, stream: bool = True) -> str:
        """基于已切分索引回答问题（只调用 chat_model）。"""
        if not self._is_ready(doc_id):
            raise RuntimeError(f"doc_id={doc_id} 尚未切分就绪，请先调用 ingest()")

        if stream:
            print("💡 ", end="", flush=True)
            full = ""
            try:
                for chunk in self.client.chat_completions(
                    messages=[{"role": "user", "content": question}],
                    doc_id=doc_id,
                    stream=True,
                ):
                    print(chunk, end="", flush=True)
                    full += chunk
                print()
            except Exception as e:
                print(f"\n❌ 问答流式输出错误：{e}")
                return ""
            return full

        try:
            resp = self.client.chat_completions(
                messages=[{"role": "user", "content": question}],
                doc_id=doc_id,
                stream=False,
            )
            ans = resp["choices"][0]["message"]["content"]
            print(f"💡 {ans}")
            return ans
        except Exception as e:
            print(f"❌ 问答失败：{e}")
            return ""

    def ask_multi(self, question: str, doc_ids: List[str], stream: bool = True) -> str:
        """多文档联合问答。"""
        if stream:
            full = ""
            print("💡 ", end="", flush=True)
            try:
                for chunk in self.client.chat_completions(
                    messages=[{"role": "user", "content": question}],
                    doc_id=doc_ids,
                    stream=True,
                ):
                    print(chunk, end="", flush=True)
                    full += chunk
                print()
            except Exception as e:
                print(f"\n❌ 多文档流式问答错误：{e}")
                return ""
            return full

        try:
            resp = self.client.chat_completions(
                messages=[{"role": "user", "content": question}],
                doc_id=doc_ids,
                stream=False,
            )
            ans = resp["choices"][0]["message"]["content"]
            print(f"💡 {ans}")
            return ans
        except Exception as e:
            print(f"❌ 多文档问答失败：{e}")
            return ""

    # ─── 信息查看 ─────────────────────────────────────────────────
    def list_indexed(self):
        """列出本地已切分缓存的所有文档。"""
        docs = self.manifest.get("documents", {})
        if not docs:
            print("（暂无已切分文档）")
            return {}
        print(f"=== 本地已切分文档 ({len(docs)} 个) ===")
        for fp, info in docs.items():
            print(f"  [{info['doc_id']}] {info['file_name']}  "
                  f"(模型={info['index_model']}, 时间={info['indexed_at']})")
        return docs


# ----------------------------------------------------------------------
# 命令行演示
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # 自动从 config.ini 读取配置
    engine = PageIndexQAEngine()

    pdf_path = Path("2404.16130v2-GraphRAG.pdf")
    if not pdf_path.exists():
        print(f"⚠️ 未找到 {pdf_path}，请将真实 PDF 放到该路径后运行。")
        print()
        print("    # ---- 第一次运行：切分 + 缓存（调模型）----")
        print('    doc_id = engine.ingest("report.pdf")')
        print('    engine.ask("核心结论是什么？", doc_id=doc_id, stream=True)')
        print()
        print("    # ---- 第二次运行：命中缓存，不再切分 ----")
        print('    doc_id = engine.ingest("report.pdf")  # 立即返回，无模型调用')
        print('    engine.ask("再问一次", doc_id=doc_id, stream=True)')
        engine.list_indexed()
    else:
        doc_id = engine.ingest(str(pdf_path))          # 第一次：切分
        doc_id = engine.ingest(str(pdf_path))          # 第二次：命中缓存
        engine.ask("这份文档的核心结论是什么？", doc_id=doc_id, stream=True)
        engine.list_indexed()