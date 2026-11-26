# 作业2：使用 Dockerfile 打包 OpenAI Agents 版本

本目录自包含，包含从作业1复制的 `agents_app/`、`common/`、`run.py` 以及 Dockerfile。构建时无需引用作业1目录，不安装 LangGraph。

## 1. 构建镜像

先启动 Docker Desktop，切换到 Linux 容器，在本目录执行：

```powershell
docker build -t sentiment-agents:hw2 .
# 或执行构建脚本
.\build.ps1
```

默认基础镜像为 `python:3.11-slim`，本机已有该镜像缓存，且依赖支持 Python 3.11。本地开发环境为 `python-learning`（Python 3.12），两者分别验证。也可选用 Python 3.12 基础镜像：

```powershell
docker build --build-arg PYTHON_IMAGE=python:3.12-slim -t sentiment-agents:hw2 .
```

拉取基础镜像和安装依赖需要可用网络。Docker Hub 网络超时应检查 Docker Desktop 代理/网络配置。

## 2. 启动容器

确保当前 PowerShell 已继承 `DEEPSEEK_API_KEY` 环境变量：

```powershell
Test-Path Env:DEEPSEEK_API_KEY
docker run -d --name sentiment-hw2 -p 127.0.0.1:8200:8000 -e DEEPSEEK_API_KEY sentiment-agents:hw2
docker logs sentiment-hw2
docker inspect --format '{{.State.Health.Status}}' sentiment-hw2
```

访问 <http://localhost:8200>。健康状态由 `starting` 变为 `healthy` 后即可使用；也可请求 <http://localhost:8200/health>。输入正向文字会得到鼓励，负面文字会得到排解。

可额外传入 `-e DEEPSEEK_MODEL` 和 `-e DEEPSEEK_BASE_URL` 以覆盖当前终端设置的模型/接口。默认模型为 `deepseek-flash`。不要把密钥写进 Dockerfile、构建参数或镜像文件；`-e DEEPSEEK_API_KEY` 仅在运行时从当前环境传入。

停止和删除本作业容器：

```powershell
docker stop sentiment-hw2
docker rm sentiment-hw2
```

## 3. 镜像结构与进程

| Dockerfile 指令 | 用途 |
| --- | --- |
| `ARG` / `FROM` | 可选的 Python slim 基础镜像 |
| `WORKDIR` | 工作目录 `/app` |
| `COPY requirements.txt` / `RUN pip install` | 安装固定版本的直接依赖，复用构建缓存 |
| `COPY` | 仅复制 OpenAI Agents 实现、公共服务和启动器 |
| `USER app` | 使用普通用户运行应用 |
| `EXPOSE 8000` | 声明前端端口，实际发布由 `-p` 决定 |
| `HEALTHCHECK` | 通过前端递归检查全部服务进程，不调用模型 |
| `CMD` | 运行启动器，启动并监管四个独立服务进程 |

容器内前端监听 `0.0.0.0:8000`，后端、识别、回应进程分别监听 `127.0.0.1:8001/8002/8003`。仅发布前端端口。停止容器时启动器接收 SIGTERM 并终止子进程；任一子进程意外退出时关闭整组进程并以非零状态退出。

`.dockerignore` 排除 `.env`、缓存、测试脚本和其他无关文件；Dockerfile 明确列出复制路径。

## 4. 检查与交付

```powershell
docker image inspect sentiment-agents:hw2 --format '{{.Id}}'
docker top sentiment-hw2
# 如需提交离线镜像文件（文件可能较大）
docker save -o sentiment-agents-hw2.tar sentiment-agents:hw2
# 另一台机器导入
docker load -i sentiment-agents-hw2.tar
```

也可以在本地开发环境直接验证本目录代码：

```powershell
conda activate python-learning
python verify.py --framework openai-agents
python verify.py --framework openai-agents --live
# 对已经构建的镜像执行容器验收，通常调用模型4次，结束后删除临时容器
python verify_container.py
```

接口与情感分类约定见作业1 README。真实构建和运行结果见本目录 `验证记录.md`。

参考：[Dockerfile 官方文档](https://docs.docker.com/build/concepts/dockerfile/)、[OpenAI Agents 模型配置](https://openai.github.io/openai-agents-python/models/)。
