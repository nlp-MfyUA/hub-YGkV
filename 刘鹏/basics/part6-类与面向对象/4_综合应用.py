# ============================================================================
# 作业四：综合应用 - 学生管理系统（类版）
# ============================================================================
#
# 任务描述：
# 定义一个Student类和一个StudentManager类：
#
# Student类：
# 1. __init__方法：初始化学生信息
# 2. calculate_average方法：计算平均分
# 3. get_grade方法：获取等级
# 4. display_info方法：显示学生信息
#
# StudentManager类：
# 1. __init__方法：初始化学生列表（空列表）
# 2. add_student方法：添加学生
# 3. find_student方法：查找学生
# 4. display_all方法：显示所有学生
# 5. get_class_average方法：计算班级平均分
#
# 在主程序中：
# - 创建StudentManager实例
# - 添加多个学生
# - 显示所有学生信息
# - 查找并显示指定学生
# - 显示班级平均分
#
# 要求：
# - 使用类组织代码
# - 一个类管理多个对象
# - 添加详细的注释
class Student():
    def __init__(self, name, age, scores = None):
        """初始化学生信息"""
        self.name = name
        self.age = age
        self.scores = scores if scores is not None else {}

    def calculate_average(self):
        """计算平均分"""
        scores = self.scores
        total = sum(scores.values()) 
        return total / len(scores)
    
    def get_grade(self):
        "获取成绩等级"
        average = self.calculate_average()
        if average >= 90:
            return "A (优秀)"
        elif average >= 80:
            return "B (良好)"
        elif average >= 70:
            return "C (中等)"
        elif average >= 60:
            return "D (及格)"
        else:
            return "F (不及格)"
        
    def display_info(self):
        """显示学生信息"""
        print("-" * 30)
        print(f"姓名: {self.name} (年龄: {self.age})")
        print(f"成绩: {self.scores}")
        print(f"平均分: {self.calculate_average():.2f}")
        print(f"等级: {self.get_grade()}")


class StudentManager:
    def __init__(self):
        """初始化学生列表"""
        self.students = [ ]

    def add_student(self, student):
        """添加学生"""
        if isinstance(student, Student):
            self.students.append(student)
            print("添加学生成功")
        else:
            print("添加学生失败")

    def find_student(self, name):
        """查找学生"""
        for stu in self.students:
            if stu.name == name:
                return stu  # 找到了就返回这个学生对象
        print(f"未找到学生: {name}")
        return None

    def display_all(self):
        """显示所有学生"""
        print("\n" + "=" * 30)
        print("       全班学生花名册")
        print("=" * 30)
        if not self.students:
            print("  (暂无学生信息)")
        else:
            for stu in self.students:
                stu.display_info()  # 直接复用 Student 类自己的显示方法
        print("=" * 30 + "\n")

    def get_class_average(self):
        """计算班级平均分"""
        if not self.students:
            return 0.0
        total_avg = 0
        for stu in self.students:
            total_avg += stu.calculate_average()  # 累加每个人的平均分
        
        # 班级平均分 = 所有人平均分的总和 / 总人数
        class_avg = total_avg / len(self.students)
        return class_avg


# ================= 主程序测试 =================
if __name__ == "__main__":
    # 1. 创建管理器实例
    manager = StudentManager()

    # 2. 创建并添加多个学生
    # 成绩字典格式：{"科目": 分数}
    s1 = Student("张三", 18, {"语文": 85, "数学": 90, "英语": 88})
    s2 = Student("李四", 19, {"语文": 60, "数学": 55, "英语": 70})
    s3 = Student("王五", 18, {"语文": 95, "数学": 98, "英语": 92})

    manager.add_student(s1)
    manager.add_student(s2)
    manager.add_student(s3)

    # 3. 显示所有学生信息
    manager.display_all()

    # 4. 查找并显示指定学生
    print("----- 查找学生测试 -----")
    found_stu = manager.find_student("李四")
    if found_stu:
        found_stu.display_info()
    
    manager.find_student("赵六")  # 测试找不到的情况

    # 5. 显示班级平均分
    print("\n----- 班级数据 -----")
    class_avg = manager.get_class_average()
    print(f"班级整体平均分为: {class_avg:.2f}")


