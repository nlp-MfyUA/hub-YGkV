# ============================================================================
# 作业三：类型转换练习
# ============================================================================
#
# 任务描述：
# 编写一个程序，实现以下功能：
# 1. 定义以下变量（初始值都是字符串）：
#    - 学号："2024001"
#    - 数学成绩："85"
#    - 语文成绩："90"
#    - 英语成绩："88"
# 2. 将成绩字符串转换为浮点数
# 3. 计算总分和平均分
# 4. 将总分和平均分转换为字符串（保留两位小数）
# 5. 输出格式化的成绩单，包括：
#    - 学号
#    - 各科成绩
#    - 总分
#    - 平均分
#
# 要求：
# - 使用int()、float()、str()进行类型转换
# - 平均分保留两位小数
# - 添加注释说明每个转换步骤
import textwrap

def student_info():
    
    #学号
    student_number = "2024001"

    #数学成绩
    math_score_str = "85"

    #语文成绩
    chinese_score_str = "90"

    #英语成绩
    english_score_str = "88"

    # 类型转换 str -> int
    math_score_int = int(math_score_str)
    chinese_score_int = int(chinese_score_str)
    english_score_int = int(chinese_score_str)

    # int → float：将整数转换为浮点数（使用 float()）
    math_score = float(math_score_int)             
    chinese_score = float(chinese_score_int)       
    english_score = float(english_score_int)       

    #计算总分和平均分 =====
    total_score = math_score + chinese_score + english_score 
    average_score = total_score / 3          
 
    #总分和平均分转换为字符串，保留两位小数（使用 str()）
    total_score_str = str(round(total_score, 2))
    average_score_str = str(round(average_score, 2))
   

    print(textwrap.dedent(f"""/学号：{student_number}
                        各科成绩： 数学：{math_score} 
                                    英语：{english_score} 
                                    语文：{chinese_score} 
                        总分：{total_score_str} 
                        平均分：{average_score_str}"""))


if __name__ == "__main__":
   student_info()


