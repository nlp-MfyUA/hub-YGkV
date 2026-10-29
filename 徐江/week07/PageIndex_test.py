"""
pageindex_cached_qa.py
==========================================
基于 PageIndex 的 PDF 文档切分 + 本地持久化 QA 引擎

【设计目标】
    * 第一次运行：调用 PageIndex 把 PDF 切成层级树索引（这是"切分"动作，会调模型），
      树索引自动持久化到本地 storage_path，同时导出一份可序列化的快照。
    * 后续运行：检测到本地已存在该文档的索引 → 直接复用，【不再调用模型做切分】，
      只调用大模型做问答（retrieval + generation）。

【核心机制说明】
    PageIndex 本地模式下，`storage_path` 会把整棵层级索引树持久化到磁盘（官方机制）。
    本模块额外维护一份 `manifest.json`（文档指纹 → doc_id 映射），作为"是否已切分"
    的快速判据；文档指纹由 (绝对路径 + 文件大小 + mtime + 前 N 字节 MD5) 构成，
    文件变更后自动失效、触发重建。

    切分产物 = PageIndex 的层级树索引（结构化、可追溯到页码），
    与传统 embedding chunks 不同，无需 embedding 模型。

【依赖】
    pip install pageindex pypdf
    （pypdf 仅用于可选的高级指纹；本模块只用 hashlib/os，pypdf 非必需）

【用法】
    engine = PageIndexQAEngine(
        storage_path="./.pageindex_cache",
        index_model="gpt-5.6-luna",   # 切分/建树用，便宜即可
        chat_model="gpt-5.6-sol",     # 问答用，可用最强
        api_key=None,                  # 纯本地模式可留空
    )

    doc_id = engine.ingest("report.pdf")   # 第一次：切分 + 缓存（调模型）
    doc_id = engine.ingest("report.pdf")   # 第二次：命中缓存，不再切分 ✅
    engine.ask("报告的核心结论是什么？", doc_id=doc_id, stream=True)
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import Optional
import sys

# ----------------------------------------------------------------------
# 工具：计算文档指纹（判断是否需要重新切分）
# ----------------------------------------------------------------------
def _file_fingerprint(pdf_path: str, head_bytes: int = 4096) -> str:
    """
    用 (绝对路径 + 大小 + mtime + 前 N 字节 MD5) 生成稳定指纹。
    前三项足以应对绝大多数场景；head 哈希用于防同名篡改。
    """
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
    """PageIndex 文档切分 + 本地缓存 + 问答引擎"""

    MANIFEST_FILENAME = "manifest.json"

    def __init__(
        self,
        storage_path: str = "./.pageindex_cache",
        index_model: str = "deepseek-v4-flash",
        chat_model: str = "deepseek-v4-pro",
        api_key: Optional[str] = None,
        fingerprint_head_bytes: int = 4096,
    ):
        """
        :param storage_path: 本地持久化目录（PageIndex 树索引 + manifest 都放这里）
        :param index_model:  建树/切分模型（仅第一次切分时使用）
        :param chat_model:   问答模型（每次问答都使用）
        :param api_key:      PageIndex API Key；纯本地模式可留空
        :param fingerprint_head_bytes: 指纹采样字节数
        """
        self.storage_path = os.path.abspath(storage_path)
        os.makedirs(self.storage_path, exist_ok=True)
        self.fingerprint_head_bytes = fingerprint_head_bytes

        # 初始化 PageIndex 客户端（本地模式：索引存入 storage_path）
        from pageindex import PageIndexClient
        self.client = PageIndexClient(
            api_key=api_key,
            index_model=index_model,
            chat_model=chat_model,
            storage_path=self.storage_path,
        )

        # 加载 / 初始化 manifest（记录每个文档的切分产物位置）
        self.manifest_path = os.path.join(self.storage_path, self.MANIFEST_FILENAME)
        self.manifest = self._load_manifest()

    # ─── manifest 持久化 ──────────────────────────────────────────
    def _load_manifest(self) -> dict:
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("⚠️ manifest.json 损坏，重建")
        return {"documents": {}}

    def _save_manifest(self):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)

    # ─── 核心：文档切分（带缓存） ───────────────────────────────
    def ingest(
        self,
        pdf_path: str,
        force_reindex: bool = False,
        wait: bool = True,
        export_snapshot: bool = True,
    ) -> str:
        """
        把 PDF "切分"成层级树索引并缓存。

        逻辑：
            * 本地已存在相同指纹的索引且非强制重建
              → 直接返回已缓存的 doc_id，【不再调用模型做切分】。
            * 否则调用 client.submit_document 建树（唯一会调模型的地方），
              完成后记录 doc_id + 导出树快照到本地。

        :param force_reindex: True 则忽略缓存，强制重新切分
        :param wait:          是否阻塞等待切分完成
        :param export_snapshot: 是否额外导出可序列化的树快照（双保险）
        :return: doc_id
        """
        pdf_path = os.path.abspath(pdf_path)
        fingerprint = _file_fingerprint(pdf_path, self.fingerprint_head_bytes)

        # ① 命中缓存：直接复用，不切分
        if not force_reindex and fingerprint in self.manifest["documents"]:
            cached = self.manifest["documents"][fingerprint]
            doc_id = cached["doc_id"]
            print(f"✅ 命中本地缓存，跳过切分（doc_id={doc_id}）")
            if self._is_ready(doc_id):
                return doc_id
            print("⚠️ 缓存的索引未就绪，重新切分...")

        # ② 未命中 / 强制重建：调用模型切分（唯一会调模型的地方）
        print(f"🔪 首次切分文档: {pdf_path}")
        print("   （此步骤会调用 index_model 构建层级树索引，耗时随页数增长）")
        result = self.client.submit_document(pdf_path, wait=wait)
        doc_id = result["doc_id"]

        if wait:
            doc_id = self._wait_until_ready(doc_id)

        # ③ 切分完成 → 持久化（PageIndex 已写入 storage_path，这里补一份快照）
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

    def _wait_until_ready(self, doc_id: str, poll: int = 5) -> str:
        """轮询等待切分 / 索引就绪"""
        while True:
            info = self.client.get_document(doc_id)
            status = info.get("status", "")
            if status == "completed":
                return doc_id
            if status in ("failed", "error"):
                raise RuntimeError(f"文档切分失败，status={status}, info={info}")
            print("   ⏳ 正在建立树索引...")
            time.sleep(poll)

    def _is_ready(self, doc_id: str) -> bool:
        try:
            return self.client.get_document(doc_id).get("status") == "completed"
        except Exception:
            return False

    # ─── 导出树快照（双保险，纯结构化数据，无需模型） ──────────
    def _export_tree_snapshot(self, doc_id: str, fingerprint: str):
        """
        把 PageIndex 的树索引导出为 JSON 快照存到本地。
        后续即使脱离 PageIndex 也能查看切分结构（检索仍走 client）。
        """
        try:
            tree = self.client.get_tree(
                doc_id, node_summary=True, include_text=False
            ).get("result", {})
            snap_path = os.path.join(
                self.storage_path, f"tree_snapshot_{fingerprint[:10]}.json"
            )
            with open(snap_path, "w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
            print(f"   📄 树索引快照已导出: {os.path.basename(snap_path)}")
        except Exception as e:
            # 快照失败不影响主流程（真实检索靠 storage_path 里的索引）
            print(f"   ⚠️ 快照导出失败（可忽略）: {e}")

    def load_tree_snapshot(self, fingerprint: str) -> Optional[dict]:
        """读取本地树快照（验证切分产物确实持久化了）"""
        snap_path = os.path.join(
            self.storage_path, f"tree_snapshot_{fingerprint[:10]}.json"
        )
        if os.path.exists(snap_path):
            with open(snap_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    # ─── 问答（只调 chat_model，不做切分） ───────────────────────
    def ask(
        self,
        question: str,
        doc_id: str,
        stream: bool = True,
    ) -> str:
        """
        基于已切分（已缓存）的索引回答问题。
        此过程只调用 chat_model 做检索 + 生成，【不再切分文档】。
        """
        if not self._is_ready(doc_id):
            raise RuntimeError(
                f"doc_id={doc_id} 尚未切分就绪，请先调用 ingest()"
            )

        if stream:
            print("💡 ", end="", flush=True)
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

        # 非流式：显式 stream=False（官方 chat_completions 默认即 False，此处防御性书写）
        resp = self.client.chat_completions(
            messages=[{"role": "user", "content": question}],
            doc_id=doc_id,
            stream=False,
        )
        ans = resp["choices"][0]["message"]["content"]
        print(f"💡 {ans}")
        return ans

    # ─── 多文档联合问答 ─────────────────────────────────────────
    def ask_multi(self, question: str, doc_ids: list, stream: bool = True) -> str:
        """多个已索引文档联合推理（同样只调 chat_model）"""
        if stream:
            full = ""
            print("💡 ", end="", flush=True)
            for chunk in self.client.chat_completions(
                messages=[{"role": "user", "content": question}],
                doc_id=doc_ids,
                stream=True,
            ):
                print(chunk, end="", flush=True)
                full += chunk
            print()
            return full

        resp = self.client.chat_completions(
            messages=[{"role": "user", "content": question}],
            doc_id=doc_ids,
            stream=False,
        )
        ans = resp["choices"][0]["message"]["content"]
        print(f"💡 {ans}")
        return ans

    # ─── 信息查看 ───────────────────────────────────────────────
    def list_indexed(self):
        """列出本地已切分缓存的所有文档"""
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
# 演示
# ----------------------------------------------------------------------
if __name__ == "__main__":
    """
    演示流程：
        1) 第一次 ingest → 调模型切分 + 缓存
        2) 第二次 ingest（同文件）→ 命中缓存，不再切分
        3) ask → 只调 chat_model 问答
    注：需准备真实 PDF 放在 ./sample.pdf，或自行替换路径。
    """
    import os as _os
    api_key="sk-7e37fcd6ba634ecbbce8758b07599f72"


    # 1. 设置存储路径（推荐方式）
    def setup_storage_path():
        # 获取当前文件所在目录
        current_dir = Path(__file__).parent

        # 在项目目录下创建 cache/pageindex 文件夹
        storage_dir = current_dir / "cache" / "pageindex"

        # 创建目录（如果不存在）
        storage_dir.mkdir(parents=True, exist_ok=True)

        return str(storage_dir)


    # 使用
    storage_path = setup_storage_path()
    engine = PageIndexQAEngine(
        storage_path="./.pageindex_cache",
        index_model=os.environ.get("INDEX_MODEL", "deepseek/deepseek-v4-flash"),
        chat_model=os.environ.get("CHAT_MODEL", "deepseek/deepseek-v4-flash"),
        api_key=api_key,
    )


    pdf_path = _os.path.abspath("2404.16130v2-GraphRAG.pdf")
    if not _os.path.exists(pdf_path):
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
        doc_id = engine.ingest(pdf_path)          # 第一次：切分
        doc_id = engine.ingest(pdf_path)          # 第二次：命中缓存 ✅
        engine.ask("这份文档的核心结论是什么？", doc_id=doc_id, stream=True)
        engine.list_indexed()
