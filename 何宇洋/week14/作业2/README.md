# Kafka 多模态 PDF 问答

这是课程项目 `05-multimodal-rag-chatbot` 的独立本地实现。浏览器批量上传 PDF，Web 服务保存原件并把 PDF 二进制发送到 Kafka。独立 worker 消费消息，通过 MinerU 提取全文、图片和页码，将解析产物与 BGE 向量保存在本地。

问答用问题向量检索正文、图注和图片附近的文字。DeepSeek 接收检索到的文字、相关 PDF 图片和用户附加的图片，回答中可以在段落之间插入原图，并链接到 PDF 对应页。

## 启动

在当前目录打开 PowerShell，启动 Kafka 并准备 Python 环境。

```powershell
conda activate python-learning
python -m pip install -r requirements.txt
docker compose up -d
```

如果本机已准备 BGE 权重，在 Web 和 worker 两个终端中配置同一个路径。本机现有模型目录为 `D:/WorkSpace/AIModels/BAAI/bge-small-zh-v1.5`。默认模型为 `BAAI/bge-small-zh-v1.5`，首次使用时可能下载权重。

```powershell
$env:RAG_EMBEDDING_MODEL = 'D:/WorkSpace/AIModels/BAAI/bge-small-zh-v1.5'
```

分别在两个终端启动以下进程，每个终端都先执行 `conda activate python-learning`。

| 进程 | 命令 |
| --- | --- |
| Web | `python -m uvicorn app:app --host 127.0.0.1 --port 8000` |
| worker | `python worker.py` |

浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。网页每约 1.2 秒刷新状态。每批可上传 10 份 PDF，每份上限 20 MiB。问答可附加 1 张上限 8 MiB 的 PNG、JPEG、GIF 或 WebP 图片。

Web 从本地环境变量 `DEEPSEEK_API_KEY` 读取凭据，默认模型为 `deepseek-flash`。提问时，问题、附件和本次检索到的资料会发送给 DeepSeek。PDF 解析和向量计算在本机完成。 [DeepSeek 视觉接口文档](https://api-docs.deepseek.com/guides/vision/)

## 本地设置

| 环境变量 | 默认值与用途 |
| --- | --- |
| `KAFKA_PORT` | `19092`，本机 Kafka 端口 |
| `KAFKA_BOOTSTRAP_SERVERS` | `127.0.0.1:19092`，连接已有 Kafka 时设置，broker 和 topic 需允许约 21 MiB 消息 |
| `RAG_DATA_DIR` | 项目下的 `data`，两个 Python 进程共用 |
| `MINERU_TIER` | `flash`，可按本机 MinerU 配置选择解析档位 |
| `MINERU_DEVICE_MODE` | 由 MinerU 自动检测，可设置为 `cpu` |
| `MINERU_TIMEOUT` | 单份 PDF 最多解析 `1800` 秒 |
| `RAG_EMBEDDING_MODEL` | BGE 模型目录或模型名。更换模型后，重新上传要检索的 PDF 以重建向量 |
| `DEEPSEEK_MODEL` | `deepseek-flash`，更换时需选择支持图文输入的模型 |

MinerU 首次运行可能下载模型。`data/documents/` 保存原始 PDF、Markdown、结构化 JSON、抽取图片和每次解析的 `mineru.log`。`data/rag.sqlite3` 保存状态和向量。Kafka 投递失败会重试，worker 在保存解析结果或失败状态之后才提交消费位点。

## 停止与清理

在 Web 和 worker 终端按 `Ctrl+C`，然后移除本项目的 Kafka 容器和镜像。

```powershell
docker compose down --rmi all
```

该命令保留 Kafka 数据卷和本地 `data/`，下次可以继续消费排队的 PDF。Kafka 数据卷保留已投递的 PDF 消息。
