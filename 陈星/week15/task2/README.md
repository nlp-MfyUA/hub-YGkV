# 作业 2 · 用 Docker 打包 OpenAI Agents SDK 版

这次把作业 1 的 OpenAI Agents SDK 版装进一个容器。运行容器时，一键启动器在容器内拉起四个业务进程。

| 业务进程 | 地址或入口 | 分工 |
| --- | --- | --- |
| 前端 | 容器终端 | 接收输入，展示识别结果、回复和 PID |
| 后端 | `127.0.0.1:8100` | 依次向进程 1 和进程 2 发送 HTTP 请求 |
| 进程 1 | `127.0.0.1:8101` | 识别用户情感 |
| 进程 2 | `127.0.0.1:8102` | 正向鼓励，负面排解 |

四个进程共享同一个容器的网络。前端在容器终端运行，三项 HTTP 服务通过容器内的回环地址通信，运行时可省略 `-p`。

## 1. 检查 Docker 环境

打开 PowerShell、WSL 或系统终端，运行下方命令。

```bash
docker version
```

看到 `Client` 和 `Server` 的版本信息再继续。若只显示客户端并提示连接失败，先启动 Docker Desktop 或 Linux 上的 Docker 服务。Windows 的 Docker Desktop 请选择 Linux 容器模式。[Docker Desktop 安装说明](https://docs.docker.com/get-docker/desktop/)

## 2. 进入构建目录

解压 ZIP，打开 `homework2` 目录。该目录中有 `Dockerfile`、`requirements-docker.txt`、`common/` 和 `openai_agents_impl/`。如果你想在作业 1 的优化版项目上操作，可以将此处的 `Dockerfile`、`.dockerignore` 和 `requirements-docker.txt` 放到作业 1 的项目根目录，然后在那里构建。

| Dockerfile 指令 | 在这里的作用 |
| --- | --- |
| `FROM python:3.12-slim` | 提供 Linux 和 Python 3.12 运行环境 |
| `ENV` | 及时输出终端日志，关闭字节码文件写入，默认使用离线 Mock |
| `WORKDIR /app` | 指定容器里的工作目录 |
| 第一条 `COPY` 和 `RUN` | 先复制明确锁定的直接依赖，再在镜像内安装，改 Python 源码时通常可复用依赖层 |
| 后两条 `COPY` | 复制 SDK 版及其共用的 Python 源文件 |
| `USER 10001:10001` | 用非 root 用户运行后续入口 |
| `ENTRYPOINT` | 容器启动时执行作业 1 的一键启动器，镜像名后面的 `--text` 参数会传给它 |

`.dockerignore` 在构建时排除环境文件、虚拟环境和缓存。真实模型的 Key 可通过运行时环境传入。

## 3. 构建镜像

```bash
docker build -t homework2-agents:1.0 .
docker image ls homework2-agents
```

最后一个点指定当前目录作为构建上下文，`COPY` 从这里读取文件。镜像名是 `homework2-agents`，版本标签是 `1.0`。初次构建通常需要下载 Python 基础镜像和依赖。看到 `1.0` 这一行，表示本地已有可运行镜像。

## 4. 验证两个分支

```bash
docker run --rm homework2-agents:1.0 --text "今天好开心，面试通过了！"
docker run --rm homework2-agents:1.0 --text "今天很焦虑，担心明天的面试。"
```

| 输入 | 预期分类 | 预期策略与实际执行者 |
| --- | --- | --- |
| 今天好开心，面试通过了！ | 正向 `positive` | 鼓励 `encourage`，`EncourageAgent` |
| 今天很焦虑，担心明天的面试。 | 负面 `negative` | 排解 `comfort`，`ComfortAgent` |

每次运行会打印四个业务进程各自的 PID。容器退出后，`--rm` 删除这次运行产生的容器，镜像可用来再次运行。

用下面的命令打开交互终端，可以连续输入多条消息。

```bash
docker run --rm -it homework2-agents:1.0
```

`-i` 保留标准输入，`-t` 分配终端。输入“退出”结束。

## 5. 按提交要求导出镜像

如果老师需要实际镜像文件，用下方命令导出验收通过的镜像。

```bash
docker image save -o homework2-agents_1.0.tar homework2-agents:1.0
```

另一台架构兼容的电脑可用 `docker image load -i homework2-agents_1.0.tar` 导入，然后执行相同的 `docker run` 命令。提交时可附上 Dockerfile、依赖清单、`docker image ls` 的输出和两条分支的运行结果。[Docker 镜像导出说明](https://docs.docker.com/reference/cli/docker/image/save/)

## 可选 · 运行时使用真实模型

在你自己的电脑上创建 `.env`，按下面的格式填写变量，将示例值换成自己的 API Key。

```dotenv
LLM_MODE=openai
OPENAI_API_KEY=your_api_key
```

```bash
docker run --rm -it --env-file .env homework2-agents:1.0
```

这样可以用同一个镜像切换运行模式。使用第三方兼容网关时，可在 `.env` 中配 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`。网关需支持分类使用的结构化输出和 Handoff 使用的工具调用。[Docker 运行时环境变量说明](https://docs.docker.com/reference/cli/docker/container/run/#env)
