```markdown
# Git 作业提交指南
**仓库地址：**
- 原始仓库（老师）：https://github.com/nlp-MfyUA/hub-YGkV
- 你的仓库（Fork）：https://github.com/sharer-lp/hub-YGkV
---
## 一、初次配置（仅需做一次）
在终端中执行以下命令，将代码下载到本地并连接老师仓库：
```bash
# 1. 克隆你的仓库
git clone https://github.com/sharer-lp/hub-YGkV.git
# 2. 进入项目目录
cd hub-YGkV
# 3. 关联老师的仓库（命名为 upstream）
git remote add upstream https://github.com/nlp-MfyUA/hub-YGkV.git
# 4. 确认配置（应显示 origin 和 upstream）
git remote -v
```
---
## 二、每周作业提交流程
每次写作业前，请先同步最新代码，再提交。
### 1. 同步老师最新代码
```bash
# 拉取上游更新
git fetch upstream
# 切换到主分支
git checkout main
# 合并更新到本地
git merge upstream/main
```
*(如提示 `Already up to date` 则无需合并)*
### 2. 整理作业文件
在项目根目录下，新建以你名字命名的文件夹，并按周次存放文件。
**正确结构示例：**
```
hub-YGkV/
└── 张三/              <-- 你的名字文件夹
    └── week01/        <-- 周次文件夹
        └── code.py    <-- 代码文件
```
> ⚠️ **注意**：文件名不要包含空格或特殊符号（推荐 `week01.py`）。
### 3. 提交并上传
```bash
# 添加所有更改
git add .
# 提交（备注请写清楚：谁+第几周）
git commit -m "张三 提交 week01 作业"
# 推送到你的 GitHub 仓库
git push origin main
```
---
## 三、发起 Pull Request (PR)
将代码推送到 GitHub 后，需要通知老师合并。
1. 打开你的仓库地址：https://github.com/sharer-lp/hub-YGkV
2. 点击页面右侧绿色的 **Contribute** 或 **Compare & pull request** 按钮。
3. **如果是第一次提交**：
   - 点击 **New pull request**。
   - 点击 **Create pull request**。
   - 标题写明：`张三 提交 week01 作业`。
4. **如果是后续补充提交**：
   - 如果按钮显示 **View pull request**，说明 PR 已经存在，无需重复创建，直接等待老师合并即可。
5. 等待老师审批。
---
## ⚠️ 避坑指南
*   **文件名规范**：✅ `week01.py` | ❌ `week 01.py` (空格) 或 `week.01.py` (点号)。
*   **不要乱动**：只能修改你自己名字文件夹下的内容，**严禁**修改 `README.md` 或其他同学的文件。
*   **冲突处理**：如果 `push` 报错，请重新执行“二、每周作业提交流程”中的第 1 步（同步代码），解决冲突后再提交。
```
