# ============================================================================
# 作业四：综合应用 - 学生成绩管理系统（异常处理版）
# ============================================================================
#
# 任务描述：
# 编写一个学生成绩管理系统，使用异常处理确保程序的健壮性：
# 1. 定义一个StudentScoreManager类
#    - __init__方法：初始化，加载已有成绩数据（如果存在）
#    - load_scores方法：从JSON文件加载成绩，处理文件不存在等异常
#    - save_scores方法：保存成绩到JSON文件，处理写入异常
#    - add_score方法：添加成绩，验证分数范围（0-100），处理异常
#    - get_average方法：计算平均分，处理学生不存在等异常
#    - display_all方法：显示所有学生成绩
# 2. 在主程序中：
#    - 创建StudentScoreManager实例
#    - 添加多个学生的成绩（包括正常和异常情况）
#    - 查询和显示成绩
#    - 处理各种可能的异常
#
# 要求：
# - 使用类组织代码
# - 合理使用异常处理
# - 处理文件操作异常、数据验证异常等
# - 提供友好的错误提示
# - 使用JSON格式存储数据
# - 添加详细的注释

# ============================================================================
# 作业四：综合应用 - 学生成绩管理系统（异常处理版）
# ============================================================================

import json
import os


class StudentScoreManager:
    """
    学生成绩管理类
    - 支持增删查改成绩
    - 使用 JSON 文件持久化存储
    - 完善的异常处理机制
    """

    def __init__(self, filename="scores.json"):
        """
        初始化成绩管理器
        :param filename: 存储成绩的 JSON 文件名
        """
        self.filename = filename
        self.scores = {}  # 用字典存储：{学生姓名: 分数}
        self.load_scores()  # 初始化时自动加载已有数据

    def load_scores(self):
        """
        从 JSON 文件加载成绩数据
        - 处理文件不存在（首次使用）
        - 处理文件格式错误
        - 处理权限问题
        """
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 验证加载的数据是否为字典类型
            if not isinstance(data, dict):
                raise ValueError("数据格式错误：期望字典类型")

            self.scores = data
            print(f"成功加载 {len(self.scores)} 条成绩记录")

        except FileNotFoundError:
            print(f"数据文件 '{self.filename}' 不存在，将创建新文件")
            self.scores = {}

        except json.JSONDecodeError as e:
            print(f"错误：文件 '{self.filename}' 格式损坏 —— {e}")
            print("将使用空数据重新开始")
            self.scores = {}

        except PermissionError:
            print(f"错误：没有权限读取文件 '{self.filename}'")
            self.scores = {}

        except ValueError as e:
            print(f"错误：{e}")
            self.scores = {}

        except Exception as e:
            print(f"错误：加载文件时发生未知错误 —— {e}")
            self.scores = {}

    def save_scores(self):
        """
        将成绩数据保存到 JSON 文件
        :return: 是否保存成功（True/False）
        """
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.scores, f, ensure_ascii=False, indent=2)
            print(f"成绩已保存到 '{self.filename}'")
            return True

        except PermissionError:
            print(f"错误：没有权限写入文件 '{self.filename}'")
            return False

        except Exception as e:
            print(f"错误：保存文件时发生未知错误 —— {e}")
            return False

    def add_score(self, name, score):
        """
        添加学生成绩
        :param name: 学生姓名
        :param score: 分数（0-100，支持小数）
        :return: 是否添加成功（True/False）
        """
        try:
            # 验证姓名
            if not isinstance(name, str) or not name.strip():
                raise ValueError("学生姓名不能为空")

            name = name.strip()

            # 验证分数类型
            if not isinstance(score, (int, float)):
                raise TypeError(f"分数必须是数字，收到的是 {type(score).__name__} 类型")

            # 验证分数范围
            score = float(score)
            if score < 0 or score > 100:
                raise ValueError(f"分数 {score} 超出范围（0-100）")

            # 检查是否已存在
            if name in self.scores:
                old_score = self.scores[name]
                self.scores[name] = score
                print(f"更新成功：{name} 的成绩从 {old_score} 更新为 {score}")
            else:
                self.scores[name] = score
                print(f"添加成功：{name} 的成绩为 {score}")

            return True

        except (ValueError, TypeError) as e:
            print(f"添加失败：{e}")
            return False

        except Exception as e:
            print(f"添加失败：发生未知错误 —— {e}")
            return False

    def get_average(self, name=None):
        """
        计算平均分
        :param name: 学生姓名，为 None 时计算所有学生的平均分
        :return: 平均分，出错返回 None
        """
        try:
            if name is not None:
                # 查询指定学生的平均分（单个学生的平均分就是自己的分数）
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("学生姓名不能为空")

                name = name.strip()
                if name not in self.scores:
                    raise KeyError(f"学生 '{name}' 不存在")

                return self.scores[name]

            else:
                # 计算所有学生的平均分
                if len(self.scores) == 0:
                    raise ValueError("当前没有任何成绩数据，无法计算平均分")

                total = sum(self.scores.values())
                average = total / len(self.scores)
                return round(average, 2)

        except KeyError as e:
            print(f"查询失败：{e}")
            return None

        except ValueError as e:
            print(f"查询失败：{e}")
            return None

        except Exception as e:
            print(f"查询失败：发生未知错误 —— {e}")
            return None

    def delete_score(self, name):
        """
        删除学生成绩
        :param name: 学生姓名
        :return: 是否删除成功（True/False）
        """
        try:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("学生姓名不能为空")

            name = name.strip()
            if name not in self.scores:
                raise KeyError(f"学生 '{name}' 不存在，无法删除")

            del self.scores[name]
            print(f"删除成功：已移除 {name} 的成绩")
            return True

        except KeyError as e:
            print(f"删除失败：{e}")
            return False

        except ValueError as e:
            print(f"删除失败：{e}")
            return False

    def display_all(self):
        """
        显示所有学生成绩
        """
        print("\n" + "=" * 40)
        print(" 学生成绩表")
        print("=" * 40)

        if len(self.scores) == 0:
            print(" （暂无成绩数据）")
            print("=" * 40)
            return

        print(f" {'姓名':<10} {'分数':>8}")
        print("-" * 40)

        for name, score in self.scores.items():
            print(f" {name:<10} {score:>8.1f}")

        print("-" * 40)

        # 显示平均分
        average = self.get_average()
        if average is not None:
            print(f" {'平均分':<10} {average:>8.2f}")

        print(f" 共 {len(self.scores)} 名学生")
        print("=" * 40)


# ============================================================================
# 主程序测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 45)
    print(" 学生成绩管理系统（异常处理版）")
    print("=" * 45)

    # 创建成绩管理器实例
    manager = StudentScoreManager("student_scores.json")

    # --------------------------------------------------
    # 测试1：正常添加成绩
    # --------------------------------------------------
    print("\n【测试1】正常添加成绩")
    manager.add_score("张三", 85)
    manager.add_score("李四", 92.5)
    manager.add_score("王五", 78)
    manager.add_score("赵六", 95.5)

    # --------------------------------------------------
    # 测试2：异常添加（分数超出范围）
    # --------------------------------------------------
    print("\n【测试2】异常添加 —— 分数超出范围")
    manager.add_score("孙七", 150)     # 分数超过100
    manager.add_score("周八", -10)     # 分数为负数

    # --------------------------------------------------
    # 测试3：异常添加（类型错误）
    # --------------------------------------------------
    print("\n【测试3】异常添加 —— 类型错误")
    manager.add_score("吴九", "八十分")  # 分数不是数字
    manager.add_score("", 80)            # 姓名为空

    # --------------------------------------------------
    # 测试4：更新已有学生成绩
    # --------------------------------------------------
    print("\n【测试4】更新已有学生成绩")
    manager.add_score("张三", 90)  # 张三已有成绩，应该更新

    # --------------------------------------------------
    # 测试5：显示所有成绩
    # --------------------------------------------------
    manager.display_all()

    # --------------------------------------------------
    # 测试6：查询平均分
    # --------------------------------------------------
    print("\n【测试5】查询平均分")
    avg = manager.get_average()
    if avg is not None:
        print(f"所有学生的平均分：{avg}")

    print("\n【测试6】查询指定学生")
    score = manager.get_average("李四")
    if score is not None:
        print(f"李四的成绩：{score}")

    # 查询不存在的学生
    manager.get_average("不存在的学生")

    # --------------------------------------------------
    # 测试7：删除学生
    # --------------------------------------------------
    print("\n【测试7】删除学生")
    manager.delete_score("王五")
    manager.delete_score("不存在的学生")  # 删除不存在的

    # --------------------------------------------------
    # 测试8：保存并验证
    # --------------------------------------------------
    print("\n【测试8】保存成绩到文件")
    manager.save_scores()

    # 重新加载验证
    print("\n【测试9】重新加载验证")
    manager2 = StudentScoreManager("student_scores.json")
    manager2.display_all()



    # =====================生产级优化=====================================
    # ============================================================================
# 作业四：综合应用 - 学生成绩管理系统（生产级异常处理版）
# ============================================================================

import json
import os
from datetime import datetime


class StudentScoreManager:
    """
    学生成绩管理类（生产级封装）

    设计原则：
    - 私有属性（__xxx）保护内部数据，外部无法直接访问
    - 私有方法（_xxx）封装内部逻辑，外部不应调用
    - 公共方法提供安全的对外接口
    - 所有可能失败的操作都有异常处理
    """

    # 类常量：定义在类级别，所有实例共享
    SCORE_MIN = 0
    SCORE_MAX = 100
    DEFAULT_FILENAME = "scores.json"

    def __init__(self, filename=None):
        """
        初始化成绩管理器
        :param filename: 存储成绩的 JSON 文件路径，默认 scores.json
        """
        # 私有属性：外部无法直接访问和修改
        self.__filename = filename or self.DEFAULT_FILENAME
        self.__scores = {}           # 核心数据：{姓名: 分数}
        self.__is_dirty = False      # 数据是否被修改（用于延迟保存）
        self.__last_modified = None  # 最后修改时间

        # 初始化时加载已有数据
        self.__load_scores()

    # ========================================================================
    # 私有方法：内部逻辑封装（外部不应调用）
    # ========================================================================

    def __load_scores(self):
        """
        从 JSON 文件加载成绩数据（私有方法）
        在 __init__ 中自动调用
        """
        try:
            if not os.path.exists(self.__filename):
                print(f"[初始化] 数据文件不存在，使用空数据")
                return

            with open(self.__filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError(f"期望字典类型，实际为 {type(data).__name__}")

            # 逐条校验数据合法性
            validated = {}
            for name, score in data.items():
                if self.__validate_score_value(score):
                    validated[name] = float(score)
                else:
                    print(f"[警告] 跳过无效数据：{name}={score}")

            self.__scores = validated
            print(f"[初始化] 成功加载 {len(self.__scores)} 条成绩记录")

        except json.JSONDecodeError as e:
            print(f"[错误] 文件格式损坏：{e}")
        except PermissionError:
            print(f"[错误] 没有权限读取文件 '{self.__filename}'")
        except ValueError as e:
            print(f"[错误] 数据验证失败：{e}")
        except Exception as e:
            print(f"[错误] 加载文件时发生未知错误：{e}")

    def __save_scores(self):
        """
        将成绩数据保存到 JSON 文件（私有方法）
        只在数据被修改后才实际写入（延迟保存策略）
        :return: 是否保存成功
        """
        if not self.__is_dirty:
            return True  # 数据未修改，无需保存

        try:
            # 先写入临时文件，再替换原文件（原子操作，防止写入中断导致数据丢失）
            temp_filename = self.__filename + ".tmp"

            with open(temp_filename, "w", encoding="utf-8") as f:
                json.dump(self.__scores, f, ensure_ascii=False, indent=2)

            # 替换原文件
            os.replace(temp_filename, self.__filename)

            self.__is_dirty = False
            self.__last_modified = datetime.now()
            print(f"[保存] 成绩已保存到 '{self.__filename}'")
            return True

        except PermissionError:
            print(f"[错误] 没有权限写入文件 '{self.__filename}'")
            self.__cleanup_temp_file()
            return False
        except Exception as e:
            print(f"[错误] 保存文件失败：{e}")
            self.__cleanup_temp_file()
            return False

    def __cleanup_temp_file(self):
        """清理可能残留的临时文件（私有方法）"""
        temp_filename = self.__filename + ".tmp"
        try:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
        except OSError:
            pass  # 清理失败不影响主流程

    def __validate_name(self, name):
        """
        校验学生姓名（私有方法）
        :param name: 学生姓名
        :return: 校验通过后的姓名（去除首尾空格）
        :raises ValueError: 姓名无效时抛出
        :raises TypeError: 类型不对时抛出
        """
        if not isinstance(name, str):
            raise TypeError(f"姓名必须是字符串，收到 {type(name).__name__} 类型")

        name = name.strip()
        if not name:
            raise ValueError("学生姓名不能为空")

        if len(name) > 50:
            raise ValueError(f"姓名长度不能超过50个字符，当前为 {len(name)}")

        return name

    def __validate_score_value(self, score):
        """
        校验分数值（私有方法）
        :param score: 分数
        :return: True 表示合法，False 表示不合法
        """
        if not isinstance(score, (int, float)):
            return False
        return self.SCORE_MIN <= float(score) <= self.SCORE_MAX

    def __mark_dirty(self):
        """标记数据已被修改（私有方法）"""
        self.__is_dirty = True

    # ========================================================================
    # 公共方法：对外接口
    # ========================================================================

    def add_score(self, name, score):
        """
        添加或更新学生成绩
        :param name: 学生姓名
        :param score: 分数（0-100，支持整数和小数）
        :return: (是否成功, 消息)
        """
        try:
            # 使用私有方法做校验
            name = self.__validate_name(name)

            if not isinstance(score, (int, float)):
                raise TypeError(f"分数必须是数字，收到 {type(score).__name__} 类型")

            score = float(score)
            if not self.__validate_score_value(score):
                raise ValueError(f"分数 {score} 超出范围（{self.SCORE_MIN}-{self.SCORE_MAX}）")

            # 判断是新增还是更新
            if name in self.__scores:
                old_score = self.__scores[name]
                self.__scores[name] = score
                self.__mark_dirty()
                return True, f"更新成功：{name} 的成绩从 {old_score} → {score}"
            else:
                self.__scores[name] = score
                self.__mark_dirty()
                return True, f"添加成功：{name} 的成绩为 {score}"

        except (ValueError, TypeError) as e:
            return False, f"添加失败：{e}"
        except Exception as e:
            return False, f"添加失败：未知错误 —— {e}"

    def get_score(self, name):
        """
        查询指定学生的成绩
        :param name: 学生姓名
        :return: (是否成功, 分数或错误信息)
        """
        try:
            name = self.__validate_name(name)

            if name not in self.__scores:
                return False, f"学生 '{name}' 不存在"

            return True, self.__scores[name]

        except (ValueError, TypeError) as e:
            return False, str(e)

    def get_average(self, name=None):
        """
        计算平均分
        :param name: 指定学生姓名，None 表示计算所有人的平均分
        :return: (是否成功, 平均分或错误信息)
        """
        try:
            if name is not None:
                name = self.__validate_name(name)
                if name not in self.__scores:
                    return False, f"学生 '{name}' 不存在"
                return True, self.__scores[name]

            if not self.__scores:
                return False, "当前没有任何成绩数据"

            total = sum(self.__scores.values())
            average = round(total / len(self.__scores), 2)
            return True, average

        except (ValueError, TypeError) as e:
            return False, str(e)

    def delete_score(self, name):
        """
        删除学生成绩
        :param name: 学生姓名
        :return: (是否成功, 消息)
        """
        try:
            name = self.__validate_name(name)

            if name not in self.__scores:
                return False, f"学生 '{name}' 不存在，无法删除"

            del self.__scores[name]  # 这里用了 del 语句
            self.__mark_dirty()
            return True, f"删除成功：已移除 {name} 的成绩"

        except (ValueError, TypeError) as e:
            return False, str(e)
        except KeyError as e:
            return False, f"删除失败：{e}"

    def get_all_scores(self):
        """
        获取所有成绩的副本（防止外部直接修改内部数据）
        :return: 字典的浅拷贝
        """
        return self.__scores.copy()

    def get_student_count(self):
        """获取学生总数"""
        return len(self.__scores)

    def save(self):
        """
        手动触发保存（公共接口）
        :return: 是否保存成功
        """
        return self.__save_scores()

    def display_all(self):
        """显示所有学生成绩"""
        print("\n" + "=" * 45)
        print(" 📋 学生成绩表")
        print("=" * 45)

        if not self.__scores:
            print(" （暂无成绩数据）")
            print("=" * 45)
            return

        print(f" {'序号':<6} {'姓名':<12} {'分数':>8} {'等级':>6}")
        print("-" * 45)

        for i, (name, score) in enumerate(self.__scores.items(), 1):
            grade = self.__get_grade(score)
            print(f" {i:<6} {name:<12} {score:>8.1f} {grade:>6}")

        print("-" * 45)

        success, avg = self.get_average()
        if success:
            print(f" {'平均分':<18} {avg:>8.2f}")

        print(f" 共 {len(self.__scores)} 名学生")
        print("=" * 45)

    def __get_grade(self, score):
        """根据分数返回等级（私有方法）"""
        if score >= 90:
            return "优秀"
        elif score >= 80:
            return "良好"
        elif score >= 70:
            return "中等"
        elif score >= 60:
            return "及格"
        else:
            return "不及格"

    def __str__(self):
        """定义对象的字符串表示"""
        return f"StudentScoreManager(文件={self.__filename}, 学生数={len(self.__scores)})"

    def __repr__(self):
        """定义对象的调试表示"""
        return f"StudentScoreManager(filename='{self.__filename}', count={len(self.__scores)})"


# ============================================================================
# 主程序测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print(" 学生成绩管理系统（生产级封装版）")
    print("=" * 50)

    # 创建实例
    manager = StudentScoreManager("student_scores.json")
    print(f"\n系统信息：{manager}")

    # --------------------------------------------------
    # 测试1：正常添加
    # --------------------------------------------------
    print("\n【测试1】正常添加成绩")
    success, msg = manager.add_score("张三", 85)
    print(msg)
    success, msg = manager.add_score("李四", 92.5)
    print(msg)
    success, msg = manager.add_score("王五", 78)
    print(msg)
    success, msg = manager.add_score("赵六", 55)
    print(msg)

    # --------------------------------------------------
    # 测试2：异常添加
    # --------------------------------------------------
    print("\n【测试2】异常添加")
    _, msg = manager.add_score("孙七", 150)
    print(msg)
    _, msg = manager.add_score("周八", -10)
    print(msg)
    _, msg = manager.add_score("吴九", "八十分")
    print(msg)
    _, msg = manager.add_score("", 80)
    print(msg)

    # --------------------------------------------------
    # 测试3：更新已有成绩
    # --------------------------------------------------
    print("\n【测试3】更新成绩")
    _, msg = manager.add_score("张三", 90)
    print(msg)

    # --------------------------------------------------
    # 测试4：显示所有成绩
    # --------------------------------------------------
    manager.display_all()

    # --------------------------------------------------
    # 测试5：查询
    # --------------------------------------------------
    print("\n【测试5】查询成绩")
    success, result = manager.get_score("李四")
    print(f"李四的成绩：{result}" if success else result)

    success, result = manager.get_average()
    print(f"全班平均分：{result}" if success else result)

    success, result = manager.get_score("不存在的人")
    print(result)

    # --------------------------------------------------
    # 测试6：删除
    # --------------------------------------------------
    print("\n【测试6】删除学生")
    _, msg = manager.delete_score("王五")
    print(msg)
    _, msg = manager.delete_score("不存在的人")
    print(msg)

    # --------------------------------------------------
    # 测试7：保存并验证
    # --------------------------------------------------
    print("\n【测试7】保存并重新加载")
    manager.save()

    # 创建新实例验证数据持久化
    manager2 = StudentScoreManager("student_scores.json")
    manager2.display_all()

    # --------------------------------------------------
    # 测试8：验证私有属性不可直接访问
    # --------------------------------------------------
    print("\n【测试8】验证封装性")
    try:
        print(manager.__scores)  # 外部无法访问私有属性
    except AttributeError as e:
        print(f"✅ 私有属性保护成功：{e}")

    # 但可以通过公共接口获取副本
    scores_copy = manager.get_all_scores()
    print(f"通过公共接口获取的数据：{scores_copy}")