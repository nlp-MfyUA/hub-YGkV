# 第14周作业：文档解析与 DeepResearch —— Kafka 多模态 PDF 问答

## 目录

| 路径 | 内容 |
| --- | --- |
| `kafka_mineru_multimodal_rag/` | 作业1 + 作业2 的项目代码、测试、截图与说明 |
| `kafka_mineru_multimodal_rag/ID.txt` | 作业1：Compshare Company ID |
| `kafka_mineru_multimodal_rag/README.md` | 安装、启动、接口与作业要求对照 |
| `kafka_mineru_multimodal_rag/docs/设计说明.md` | 设计取舍与实现细节 |
| `kafka_mineru_multimodal_rag/docs/截图说明.md` | 运行截图逐张说明、运行环境边界 |
| `kafka_mineru_multimodal_rag/screens/` | 实际运行截图 |
| `kafka_mineru_multimodal_rag/redis_demo/` | 作业1：Redis 历史对话、Kafka 消息演示 |

## 作业完成情况

- **作业1**
  - Compshare Company ID：69129688（`ID.txt`；注册链接 https://console.compshare.cn/ ）
  - Redis：多轮对话历史按会话存 List，带保留条数与过期时间；主系统 `/chat?session_id=` 直接使用；
  - Kafka：生产者发任务、消费者处理并回写结果主题，重复消息用 Redis SETNX 去重。
- **作业2**
  - 功能1：网页上传多个 PDF → API 写盘并投 Kafka → worker 消费 → MinerU 解析 → 文本、表格、图片、向量入库；
  - 功能2：待解析 / 解析中 / 解析完成三种状态（失败可重试），刷新页面状态不丢；
  - 功能3：先文字问答，再图文提问，回答按“文字 → 文档原图 → 文字”混排并附来源页码。

快速开始见 `kafka_mineru_multimodal_rag/README.md` 第 4 节。
