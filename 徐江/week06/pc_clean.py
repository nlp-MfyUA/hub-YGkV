# -*- coding: utf-8 -*-
"""
Windows 深度清理版扫描器
功能：
  1. 自动统计 conda / pip / modelscope / huggingface / 回收站 / 临时目录 等真正的大头占用
  2. 扫描 C 盘前 N 大文件夹
  3. 可视化展示空间都被谁吃了（柱状图）
  4. 输出【精确清理命令】，复制即可执行

说明：
  - 本脚本【只读不写】，不会删除任何文件，安全可放心运行
  - 扫描大目录可能耗时几十秒到几分钟，请耐心等待
  - 需要 matplotlib 用于绘图（pip install matplotlib）

用法：
  python deep_clean.py                 # 默认扫描 C 盘 Top20
  python deep_clean.py --drive C       # 指定盘符
  python deep_clean.py --top 30        # 指定 Top N
  python deep_clean.py --no-plot       # 不弹图（服务器/无界面环境）
"""

import os
import sys
import shutil
import argparse
import platform
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")  # 无界面也能保存图片
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    # 尝试设置中文字体
    for fp in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]:
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp)
            plt.rcParams["font.sans-serif"] = [os.path.basename(fp).rsplit(".", 1)[0]]
            break
    plt.rcParams["axes.unicode_minus"] = False
    HAS_PLOT = True
except Exception:
    HAS_PLOT = False


# ============================================================
# 工具函数
# ============================================================
def get_dir_size(path: str) -> int:
    """递归计算目录大小（字节），遇到无权访问的跳过"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
            for f in filenames:
                try:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total += os.path.getsize(fp)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total


def human_size(num: float) -> str:
    """字节转人类可读格式"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


# ============================================================
# 第一部分：大头占用统计
# ============================================================
def find_conda_envs():
    """定位 conda 环境目录"""
    paths = []
    for env_var in ["CONDA_ROOT", "CONDA_HOME", "CONDA_PREFIX"]:
        v = os.environ.get(env_var)
        if v:
            paths.append(v)
    # 常见安装位置
    for p in [
        r"C:\ProgramData\Anaconda3",
        r"C:\ProgramData\Miniconda3",
        os.path.expanduser(r"~\.conda\envs"),
    ]:
        if os.path.exists(p) and p not in paths:
            paths.append(p)
    # 从 conda 命令反查
    try:
        import subprocess
        out = subprocess.run(
            ["conda", "info", "--base"],
            capture_output=True, text=True, timeout=10
        )
        base = out.stdout.strip()
        if base and os.path.exists(base):
            paths.append(base)
    except Exception:
        pass
    return list(dict.fromkeys(paths))  # 去重保序


def scan_heavy_items():
    """扫描各类"大头"缓存/环境目录"""
    home = os.path.expanduser("~")
    items = []

    # 1. Conda 相关
    for p in find_conda_envs():
        if os.path.exists(p):
            items.append(("Conda环境", p))
    # conda 的 pkgs 缓存（占空间大户）
    for p in find_conda_envs():
        pkg = os.path.join(p, "pkgs")
        if os.path.exists(pkg):
            items.append(("Conda包缓存(pkgs)", pkg))

    # 2. pip 缓存
    pip_cache = os.path.join(home, "AppData", "Local", "pip", "cache")
    if os.path.exists(pip_cache):
        items.append(("pip缓存", pip_cache))

    # 3. ModelScope 缓存
    for p in [
        os.path.join(home, ".modelscope", "cache"),
        r"E:\modelscope_cache",
        os.path.join(home, "modelscope_cache"),
    ]:
        if os.path.exists(p):
            items.append(("ModelScope缓存", p))

    # 4. HuggingFace 缓存
    hf = os.path.join(home, ".cache", "huggingface")
    if os.path.exists(hf):
        items.append(("HuggingFace缓存", hf))

    # 5. 回收站（每个盘都有）
    for drive in ["C", "D", "E", "F"]:
        bin_path = f"{drive}:\\$Recycle.Bin"
        if os.path.exists(bin_path):
            items.append((f"回收站({drive}:)", bin_path))

    # 6. 临时目录
    for p in [os.environ.get("TEMP"), r"C:\Windows\Temp"]:
        if p and os.path.exists(p):
            items.append(("系统临时目录", p))

    # 7. Windows 更新缓存（大户）
    win_update = r"C:\Windows\SoftwareDistribution\Download"
    if os.path.exists(win_update):
        items.append(("Windows更新缓存", win_update))

    return items


def format_items_with_size(items):
    """计算大小并排序"""
    results = []
    for name, path in items:
        size = get_dir_size(path)
        results.append((name, path, size))
    results.sort(key=lambda x: x[2], reverse=True)
    return results


# ============================================================
# 第二部分：C 盘（指定盘）Top N 大文件夹
# ============================================================
def scan_drive_top_folders(drive: str, top: int = 20):
    """扫描某盘根目录下的顶级文件夹大小"""
    root = f"{drive}:\\"
    if not os.path.exists(root):
        return []
    folders = []
    try:
        for entry in os.listdir(root):
            full = os.path.join(root, entry)
            if os.path.isdir(full) and not os.path.islink(full):
                size = get_dir_size(full)
                folders.append((entry, full, size))
    except PermissionError:
        pass
    folders.sort(key=lambda x: x[2], reverse=True)
    return folders[:top]


# ============================================================
# 第三部分：生成清理命令
# ============================================================
def build_cleanup_commands(results):
    """根据扫描结果生成精确的清理命令"""
    cmds = []
    for name, path, size in results:
        if size <= 0:
            continue
        if "回收站" in name:
            continue  # 回收站建议手动清空，不自动命令
        if "Conda包缓存" in name:
            cmds.append(("# 清理 conda 包缓存（保留已安装包）", "conda clean --pkgs --yes"))
            cmds.append(("# 更彻底：清理所有缓存（索引/包/源码/tarball）", "conda clean -a --yes"))
        elif "Conda环境" in name:
            cmds.append(("# ⚠️ conda 环境目录，请确认无用的环境后手动删除", f"# 示例：conda remove -n 环境名 --all"))
        elif "pip缓存" in name:
            cmds.append(("# 清理 pip 缓存", "pip cache purge"))
        elif "ModelScope" in name:
            cmds.append(("# 清理 ModelScope 指定模型（先确认不再用）", f"# 手动删除：{path}\\具体模型文件夹"))
        elif "HuggingFace" in name:
            cmds.append(("# 清理 HuggingFace 缓存（在 Python 中执行）",
                         "python -c \"from huggingface_hub import scan_cache_dir; scan_cache_dir().delete_revisions('*').execute()\""))
        elif "临时目录" in name:
            cmds.append(("# 清理临时目录（跳过正在使用的文件）", f"del /q /f /s \"{path}\\*.*\""))
        elif "Windows更新缓存" in name:
            cmds.append(("# ⚠️ Windows 更新缓存，建议用 cleanmgr 清理", "cleanmgr"))
        else:
            cmds.append((f"# 手动清理 {name}", f"# 请确认后手动删除：{path}"))
    return cmds


# ============================================================
# 第四部分：可视化
# ============================================================
def plot_pie(items, out_path="heavy_items.png"):
    """饼图：大头占用分布"""
    if not HAS_PLOT:
        return
    data = [(n, s / (1024 ** 3)) for n, _, s in items if s > 0]
    if not data:
        return
    labels = [f"{n}\n{v:.1f}GB" for n, v in data]
    sizes = [v for _, v in data]

    fig, ax = plt.subplots(figsize=(10, 8))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.1f%%", startangle=140,
        wedgeprops=dict(edgecolor="white", linewidth=1.5)
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("磁盘空间大头占用分布（GB）", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"\n📊 饼图已保存：{out_path}")


def plot_bar(folders, out_path="c_drive_top.png", drive="C"):
    """柱状图：C 盘 Top N 大文件夹"""
    if not HAS_PLOT:
        return
    data = [(n, s / (1024 ** 3)) for n, _, s in folders if s > 0]
    if not data:
        return
    labels = [f"{n}\n{v:.1f}GB" for n, v in data][::-1]
    sizes = [v for _, v in data][::-1]

    fig, ax = plt.subplots(figsize=(10, max(6, len(sizes) * 0.4)))
    bars = ax.barh(range(len(sizes)), sizes, color="#4C9BE8")
    ax.set_yticks(range(len(sizes)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("大小 (GB)", fontsize=11)
    ax.set_title(f"{drive} 盘前 {len(sizes)} 大文件夹", fontsize=14, fontweight="bold")
    for bar, v in zip(bars, sizes):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                f"{v:.1f}GB", va="center", fontsize=8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"📊 柱状图已保存：{out_path}")


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Windows 深度清理扫描器")
    parser.add_argument("--drive", default="C", help="要扫描的盘符（默认 C）")
    parser.add_argument("--top", type=int, default=20, help="Top N 文件夹（默认 20）")
    parser.add_argument("--no-plot", action="store_true", help="不生成图表")
    args = parser.parse_args()

    if platform.system() != "Windows":
        print("⚠️ 本脚本专为 Windows 设计，当前非 Windows 系统，部分路径可能不适用")

    print("=" * 60)
    print("🧹 Windows 深度清理扫描器（只读不写，安全）")
    print("=" * 60)

    # ---------- 第一部分：大头占用 ----------
    print("\n📦 正在扫描大头占用（conda / pip / modelscope / 回收站 等）...")
    print("    （首次扫描可能需要几分钟，请耐心等待）\n")
    items = scan_heavy_items()
    results = format_items_with_size(items)

    print("-" * 60)
    print(f"{'类别':<22}{'大小':>12}   路径")
    print("-" * 60)
    total = 0
    for name, path, size in results:
        total += size
        print(f"{name:<20}{human_size(size):>12}   {path}")
    print("-" * 60)
    print(f"{'合计可回收/占用':<22}{human_size(total):>12}")

    # ---------- 第二部分：指定盘 Top N ----------
    print(f"\n📂 正在扫描 {args.drive} 盘前 {args.top} 大文件夹...")
    folders = scan_drive_top_folders(args.drive, args.top)
    print("-" * 60)
    print(f"{'排名':<5}{'文件夹':<25}{'大小':>12}")
    print("-" * 60)
    for i, (name, full, size) in enumerate(folders, 1):
        print(f"{i:<5}{name:<25}{human_size(size):>12}")
    print("-" * 60)

    # ---------- 第三部分：清理命令 ----------
    print("\n" + "=" * 60)
    print("🛠️  精确清理命令（复制执行，建议先确认再删）")
    print("=" * 60)
    cmds = build_cleanup_commands(results)
    printed = set()
    for comment, cmd in cmds:
        if cmd in printed:
            continue
        printed.add(cmd)
        print(f"\n{comment}")
        print(f"    {cmd}")

    print("\n# 通用补充命令：")
    print("    conda clean -a --yes          # 清理所有 conda 缓存")
    print("    pip cache purge               # 清理 pip 缓存")
    print("    cleanmgr                      # 打开 Windows 磁盘清理")
    print("    # 清空回收站：桌面右键回收站 → 清空（或按 Win+R 输入 emptyrecyclebin）")

    # ---------- 第四部分：可视化 ----------
    if not args.no_plot and HAS_PLOT:
        plot_pie(results, out_path=f"heavy_items_{args.drive}.png")
        plot_bar(folders, out_path=f"{args.drive}_drive_top.png", drive=args.drive)
    elif not HAS_PLOT:
        print("\n💡 未安装 matplotlib，跳过图表。安装：pip install matplotlib")

    print("\n✅ 扫描完成。以上仅统计与建议，未做任何删除操作。")


if __name__ == "__main__":
    main()
