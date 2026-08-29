
## 转换模型格式
### 通用转换操作
qwen3-0.6b
这个模型是Safetensors格式
通用转换如下：
```shell
# 创建Modelfile文件，内容如下：
FROM ./my_model_directory

# 执行创建操作：
ollama create my-model -f ./Modelfile
```

可能得到如下结果：
converting model
Error: unsupported architecture "Qwen3ForCausalLM"

**原因：**
Ollama 无法直接识别 Hugging Face 格式的 Qwen3 模型。解决方法是使用 llama.cpp 工具将其转换为 GGUF 格式

### 安装wsl虚拟机及设置
执行以下命令安装wsl虚拟机，并安装Linux
```shell
wsl.exe --install

# 查看可用发行版
wsl --list --online 

# 安装ubuntu
wsl --install -d Ubuntu-22.04
```

进入ubuntu终端,执行以下命令安装依赖源
```shell
sudo apt update && sudo apt upgrade -y
sudo apt install build-essential cmake git python3 python3-pip python3-venv -y
```

```shell
# 克隆项目
git clone https://github.com/ggerganov/llama.cpp
# 进入目录
cd llama.cpp
# 编译
cmake -B build
cmake --build build --config Release -j $(nproc)

# 建议创建并激活一个 Python 虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装转换脚本所需的依赖
pip install torch transformers accelerate sentencepiece protobuf
```

### 转换模型
```shell
# 在 WSL 终端中执行，假设你的模型在 Windows 的 D 盘
cp -r /mnt/d/Works/agent_codes/models/Qwen/Qwen3-0.6B ~/Qwen3-0.6B

python convert_hf_to_gguf.py ~/Qwen3-0.6B --outfile ~/Qwen3-0.6B-F16.gguf --outtype f16

# 将生成的gguf文件拷贝到宿主机中，创建Modelfile文件写入以下内容
FROM ./Qwen3-0.6B-F16.gguf

ollama create qwen3-0.6b -f ./Modelfile
```

此时就可以在ollama客户端里面模型的选择中看到qwen3-0.6b模型了，在命令行也可以通过
```shell
ollama run qwen3-0.6b
```
在命令行启动