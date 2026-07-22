# ============================================================================
# 作业三：文件操作异常处理 - 安全读写文件
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现安全的文件操作功能：
# 1. 编写一个read_file_safe函数
#    - 接收文件名作为参数
#    - 尝试读取文件内容
#    - 使用try-except处理FileNotFoundError（文件不存在）
#    - 使用try-except处理PermissionError（权限不足）
#    - 使用try-except处理UnicodeDecodeError（编码错误）
#    - 使用finally确保资源清理
#    - 返回文件内容，如果出错返回None
# 2. 编写一个write_file_safe函数
#    - 接收文件名和内容作为参数
#    - 尝试写入文件
#    - 处理可能的异常
#    - 返回是否成功
# 3. 编写一个copy_file_safe函数
#    - 接收源文件名和目标文件名
#    - 尝试复制文件内容
#    - 使用异常处理确保操作安全
# 4. 在主程序中测试这些函数
#
# 要求：
# - 使用with语句打开文件
# - 捕获具体的异常类型
# - 提供有意义的错误信息
# - 使用finally进行资源清理
# - 添加适当的注释



# ============================================================================
# 作业三：文件操作异常处理 - 安全读写文件
# ============================================================================
import hashlib

def read_file_safe(filename):
    """
    安全地读取文件内容
    - 处理文件不存在（FileNotFoundError）
    - 处理权限不足（PermissionError）
    - 处理编码错误（UnicodeDecodeError）
    - 使用 finally 确保资源清理
    - 成功返回内容，失败返回 None
    """
    f = None
    try:
        f = open(filename, "r", encoding="utf-8")
        content = f.read()
    except FileNotFoundError:
        print(f"错误：文件 '{filename}' 不存在！")
        return None
    except PermissionError:
        print(f"错误：没有权限读取文件 '{filename}'！")
        return None
    except UnicodeDecodeError:
        print(f"错误：文件 '{filename}' 编码不是 UTF-8，无法读取！")
        return None
    except Exception as e:
        print(f"错误：读取文件时发生未知错误 —— {e}")
        return None
    else:
        print(f"成功读取文件：{filename}（{len(content)} 个字符）")
        return content
    finally:
        # finally 确保文件被关闭，即使发生异常也不会泄漏资源
        if f is not None:
            f.close()
            print(f"[finally] 已关闭文件：{filename}")


def write_file_safe(filename, content):
    """
    安全地写入文件
    - 处理权限不足（PermissionError）
    - 处理其他异常
    - 返回是否写入成功（True/False）
    """
    f = None
    try:
        f = open(filename, "w", encoding="utf-8")
        f.write(content)
    except PermissionError:
        print(f"错误：没有权限写入文件 '{filename}'！")
        return False
    except Exception as e:
        print(f"错误：写入文件时发生未知错误 —— {e}")
        return False
    else:
        print(f"成功写入文件：{filename}（{len(content)} 个字符）")
        return True
    finally:
        if f is not None:
            f.close()
            print(f"[finally] 已关闭文件：{filename}")


def copy_file_safe(source, target):
    """
    安全地复制文件
    - 先读取源文件，再写入目标文件
    - 源文件不存在、目标文件无权限等情况都能处理
    - 返回是否复制成功（True/False）
    """
    print(f"\n正在复制：{source} → {target}")

    # 第一步：安全读取源文件
    content = read_file_safe(source)
    if content is None:
        print("复制失败：无法读取源文件")
        return False

    # 第二步：安全写入目标文件
    success = write_file_safe(target, content)
    if success:
        print(f"复制完成：{source} → {target}")
    else:
        print("复制失败：无法写入目标文件")

    return success


def file_hash(filename):
    """计算文件的 MD5 哈希值,方法扩展，避免占用过大的内存"""
    try:
        with open(filename, "rb") as f:
            # 读取文件内容并计算 MD5 值
            return hashlib.md5(f.read()).hexdigest()
    except FileNotFoundError:
        return None


if __name__ == "__main__":
    print("=" * 45)
    print(" 文件操作异常处理测试")
    print("=" * 45)

    # --------------------------------------------------
    # 测试1：写入文件（正常）
    # --------------------------------------------------
    print("\n【测试1】写入文件")
    test_content = "Hello, 异常处理！\n这是第二行。\n这是第三行。\n"
    write_file_safe("test_output.txt", test_content)

    # --------------------------------------------------
    # 测试2：读取文件（正常）
    # --------------------------------------------------
    print("\n【测试2】读取文件（正常）")
    content = read_file_safe("test_output.txt")
    if content is not None:
        print(f"文件内容：\n{content}")

    # --------------------------------------------------
    # 测试3：读取不存在的文件
    # --------------------------------------------------
    print("\n【测试3】读取不存在的文件")
    result = read_file_safe("不存在的文件.txt")
    print(f"返回值：{result}")

    # --------------------------------------------------
    # 测试4：复制文件（正常）
    # --------------------------------------------------
    print("\n【测试4】复制文件（正常）")
    copy_file_safe("test_output.txt", "test_copy.txt")

    # --------------------------------------------------
    # 测试5：复制不存在的文件
    # --------------------------------------------------
    print("\n【测试5】复制不存在的文件")
    copy_file_safe("不存在的文件.txt", "test_copy2.txt")

    # --------------------------------------------------
    # 测试6：验证复制结果
    # --------------------------------------------------
    print("\n【测试6】验证复制结果")
    original = read_file_safe("test_output.txt")
    copied = read_file_safe("test_copy.txt")
    if original == copied:
        print("复制成功，两个文件内容完全一致！")
    else:
        print("复制失败，内容不一致！")