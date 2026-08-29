# ============================================================================
# 作业一：类的基础 - 学生类
# ============================================================================
#
# 任务描述：
# 定义一个Student类，包含以下内容：
# 1. __init__方法：初始化学生的姓名、年龄、学号
# 2. display_info方法：显示学生的基本信息
# 3. set_score方法：设置学生的数学、语文、英语成绩
# 4. calculate_average方法：计算学生的平均分
# 5. get_grade方法：根据平均分返回等级
#
# 在主程序中：
# - 创建至少2个Student实例
# - 调用各个方法测试功能
# - 显示所有学生的信息
#
# 要求：
# - 正确使用self参数
# - 在方法中访问和修改实例属性
# - 添加适当的注释

# ============================================================================
# 作业一：类的基础 - 学生类
# ============================================================================

"""使用类的场景：
    需要维护状态：当多个方法需要共享或修改同一组数据时，类是自然的选择
    需要封装和数据隐藏：当一组数据和操作这些数据的方法紧密耦合时，用类封装
    需要多态/继承时，当多种类型共享接口，但具体实现不同时，类的继承体系更合适
    需要创建多个实例：创建多个独立的对象，每个对象都有自己的数据时
    实现设计模式：如单例、工厂、策略、观察者等设计模式，类是基础
    需要支持上下文管理器 with语句

核心：能用函数解决的别用类。函数是python的一等公民，优先使用函数。
      只有当你确实需要封装状态、实现多态、管理多个实例时，才引入类。
      过度使用类会导致代码臃肿，违背python的简洁哲学
"""

# ========================
# 全局配置（数据与逻辑分离）
# ========================

# 修正拼写：THRESHOLEDS -> THRESHOLDS，并按降序排列
GRADE_THRESHOLDS = [
    (90, "优秀"),
    (80, "良好"),
    (70, "中等"),
    (60, "及格"),
]

DEFAULT_GRADE = "不及格"


class Student:
    """定义学生的类"""

    def __init__(self, name, age, stu_id):
        self.name = name
        self.age = age
        self.stu_id = stu_id
        self.scores = {}      # 用字典存储成绩，扩展性好
        self.average = 0      # 缓存平均分
        self.grade = ""       # 缓存等级

    def display_info(self):
        print("=" * 50)
        print("     学生信息如下")
        print(f"学生姓名：{self.name}")
        print(f"学生年龄：{self.age}")
        print(f"学生学号：{self.stu_id}")
        # 只有设置了成绩才显示成绩信息
        if self.scores:
            print(f"学生各科成绩：{self.scores}")
            print(f"学生平均成绩：{self.average:.2f}")
            print(f"学生成绩等级：{self.grade}")

    def set_score(self, scores):
        """设置成绩后，自动联动更新平均分和等级，保证数据一致性"""
        self.scores = dict(scores)  # 浅拷贝，避免外部修改影响内部数据
        self._update_average()
        self._update_grade()

    def _update_average(self):
        """内部方法：计算平均分"""
        if  self.scores:
            self.average = sum(self.scores.values()) / len(self.scores)
        else:
            self.average = 0

    def _update_grade(self):
        """内部方法：更新等级"""
        for threshold, grade in GRADE_THRESHOLDS:
            if self.average >= threshold:
                self.grade = grade
                return
        self.grade = DEFAULT_GRADE

    def get_grade(self):
        """对外方法：返回当前缓存的等级"""
        return self.grade


if __name__ == "__main__":
    print("=" * 50)
    print("学生类测试")
    print("=" * 50)

    # 创建2个Student实例
    student1 = Student("张三", 12, 20260627)
    student2 = Student("李四", 13, 20260628)

    # 设置成绩（设置后自动计算平均分和等级）
    student1.set_score({"数学": 100, "英语": 69, "语文": 85})
    student2.set_score({"数学": 55, "英语": 60, "语文": 48})

    # 显示信息
    print("\n学生1信息：")
    student1.display_info()

    print()
    student2.display_info()

    # 测试 get_grade 方法
    print(f"\n通过 get_grade() 获取学生1的等级：{student1.get_grade()}")

