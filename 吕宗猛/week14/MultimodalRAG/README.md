# MultimodalRAG

基于 Kafka 的多模态 RAG 问答演示项目：前端上传多个 PDF → Kafka → worker 调 MinerU 解析 → 图片作为独立资源存储 → 检索时将图片与周围文本一起送入 Magpie 的视觉模型回答。

## 目录

```text
MultimodalRAG/
├── app/                后端（FastAPI API + Kafka worker + MinerU/Embedding/LLM 客户端）
├── frontend/           Vue3 + Element Plus 前端
├── deploy/             Docker Compose、MinerU 镜像、MySQL 初始化脚本
├── docs/               架构、数据库、接口、部署与验收文档
├── samples/            验收用 PDF
└── data/               本地运行时数据（容器内挂载到 /data）
```

## 关键决策

- Kafka + api + worker + web + MinerU 全部部署在飞牛。
- 复用飞牛现有 `rag-mysql` 实例，新建独立库 `rag_mm` 与专用用户。
- 复用 `rag-models` 的 `bge-small-zh-v1.5`（512 维）做文本向量化。
- MinerU 使用 **4.2.1** 的 `basic` CPU 档；飞牛无 GPU。
- 问答模型为 Magpie 的 `workbuddy/deepseek-v4.1-flash`，输入支持 text+image。
- 文档解析状态通过 SSE 实时推送。
- 左侧栏保存会话记录，点击历史会话可继续问答；输入框支持 Ctrl+V 直接粘贴截图；每轮问答后由 LLM 生成会话标题。

## 访问地址（飞牛）

| 服务 | 地址 |
|---|---|
| 前端 | http://192.168.124.88:8082 |
| API 健康检查 | http://192.168.124.88:8002/api/health |
| SSE 文档状态 | http://192.168.124.88:8002/api/documents/events |
| Kafka（宿主机外部监听） | 192.168.124.88:9094 |

详细设计与部署步骤见 `docs/`：

- [架构设计](docs/01-架构设计.md)
- [数据库设计](docs/02-数据库设计.md)
- [接口文档](docs/03-接口文档.md)
- [部署运维](docs/04-部署运维.md)
- [验收测试](docs/05-验收测试.md)
- [MinerU 版本与 GPU 结论](docs/06-MinerU版本与GPU结论.md)
- [部署与验收记录](docs/07-部署与验收记录.md)
