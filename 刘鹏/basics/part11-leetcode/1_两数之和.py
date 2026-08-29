"""
LeetCode 1. 两数之和 (Two Sum)

题目描述：
给定一个整数数组 nums 和一个整数目标值 target，请你在该数组中找出和为目标值 target 的那两个整数，
并返回它们的数组下标。

你可以假设每种输入只会对应一个答案。但是，数组中同一个元素在答案里不能重复出现。
你可以按任意顺序返回答案。

示例 1：
输入：nums = [2,7,11,15], target = 9
输出：[0,1]
解释：因为 nums[0] + nums[1] == 9 ，返回 [0, 1] 。

示例 2：
输入：nums = [3,2,4], target = 6
输出：[1,2]

示例 3：
输入：nums = [3,3], target = 6
输出：[0,1]

提示：
- 2 <= nums.length <= 10^4
- -10^9 <= nums[i] <= 10^9
- -10^9 <= target <= 10^9
- 只会存在一个有效答案

解题思路：
1. 暴力法：双重循环，时间复杂度 O(n²)，空间复杂度 O(1)
2. 哈希表法：一次遍历，用哈希表存储已访问的元素，时间复杂度 O(n)，空间复杂度 O(n)
"""

"""
========================================
Two Sum 学习笔记 - 从零开始的逐步进阶
========================================
"""

# ============================================
# 知识点1：暴力解法对比
# ============================================

#  错误版本：enumerate 双重循环（start=0）
# 问题：允许自配对（idx==idy），且重复检查 (a,b) 和 (b,a)
def two_sum_wrong_v1(nums, target):
    for idx, i in enumerate(nums, start=0):
        for idy, j in enumerate(nums, start=0):
            if i + j == target:
                return [idx, idy]
    return []

# 正确版本：range 控制内层循环起点
# j 从 i+1 开始，避免自配对和重复检查
def two_sum_brute_force(nums, target):
    """
    暴力法：双重循环遍历所有可能的组合
    时间复杂度：O(n²)
    空间复杂度：O(1)
    """
    n = len(nums)
    for i in range(n):
        for j in range(i + 1, n):
            if nums[i] + nums[j] == target:
                return [i, j]
    return []


# ============================================
# 知识点2：enumerate 的 start 参数只是"索引标签"
# ============================================

#  错误理解：以为 start=1 会跳过第一个元素
# 实际上 start 只影响计数器的起始值，不跳过任何元素
def two_sum_wrong_v2(nums, target):
    for idx, i in enumerate(nums, start=0):
        for idy, j in enumerate(nums, start=1):  # idy 从1开始，但 j 还是从 nums[0] 开始
            if i + j == target:
                return [idx, idy]  # 返回的索引全部偏移了1！
    return []

# 演示：enumerate 的 start 只改变索引标签
# enumerate([10, 20, 30], start=0) → (0,10), (1,20), (2,30)
# enumerate([10, 20, 30], start=1) → (1,10), (2,20), (3,30)
# 遍历的元素完全相同，只是索引编号不同


# ============================================
# 知识点3：字典获取 values 的方式
# ============================================

# 获取所有 values
# d.values()           → dict_values 视图对象
# list(d.values())     → 转成列表
# for v in d.values()  → 遍历

# 获取单个 value 的两种方式
# d['key']             → key 不存在时抛出 KeyError
# d.get('key')         → key 不存在时返回 None（更安全）
# d.get('key', 默认值)  → key 不存在时返回指定的默认值


# ============================================
# 知识点4：哈希表解法的常见错误
# ============================================

#  错误版本：字典存反了 + 两个循环 + get()陷阱 + 返回值错误
def two_sum_wrong_v3(nums, target):
    hashmap = {}
    # 问题1：key=索引, value=值（存反了，应该 key=值, value=索引）
    for idx, j in enumerate(nums):
        hashmap.setdefault(idx, j)

    for i in nums:
        # 问题2：get() 当 value=0 时返回 0，被当作 False，会漏判
        # 问题3：返回的是 [值, 索引]，不是 [索引, 索引]
        if hashmap.get(target - i) and hashmap.get(target - i) != i:
            return [i, hashmap.get(target - i)]
    return []


# ============================================
# 知识点5：in 在不同类型中的行为
# ============================================

# 字符串：检查子串是否存在
# "hello" in "hello world" → True

# 列表/元组：检查元素是否存在（O(n)，逐个比较）
# 3 in [1, 2, 3] → True

# 字典：只检查 key，不检查 value（O(1)，哈希定位）
# 'a' in {'a': 1} → True
# 1 in {'a': 1}   → False（1 是 value，不是 key）

# 集合：检查元素是否存在（O(1)，哈希定位）
# 2 in {1, 2, 3} → True

# not in：in 的反面
# 5 not in [1, 2, 3] → True


# ============================================
# 知识点6：正确的哈希表解法（先查再存）
# ============================================

def two_sum_hashmap(nums, target):
    """
    哈希表法：使用字典存储已访问的元素及其索引
    时间复杂度：O(n)
    空间复杂度：O(n)
    """
    hashmap = {}  # 存储 {值: 索引}

    for i, num in enumerate(nums):
        complement = target - num  # 计算需要的另一个数
        if complement in hashmap:
            # 找到了匹配的数，返回两个索引
            return [hashmap[complement], i]
        # 将当前数和索引存入哈希表
        hashmap[num] = i

    return []


# ============================================
# 知识点7：为什么"先查再存"而不是"先存再查"
# ============================================

#  先存再查：会导致自己和自己配对
def two_sum_wrong_v4(nums, target):
    hashmap = {}
    for i, num in enumerate(nums):
        hashmap[num] = i              # 先存：把自己存进去
        complement = target - num
        if complement in hashmap:     # 再查：可能查到自己！
            return [hashmap[complement], i]
    return []

# 例：nums=[3,2,4], target=6
# 第1轮：num=3, complement=3
# 先存 → hashmap={3:0}
# 再查 → 3 in hashmap → True → 返回 [0,0]  自配对！

# 先查再存：只和"之前出现过"的元素配对
# 第1轮：字典为空 → 查不到 → 存进去 → 安全
# 第2轮：只能和第1轮的元素配对 → 不会自配对


# ============================================
# 知识点8：两种解法最终对比
# ============================================

# | 对比项       | 暴力法              | 哈希表法            |
# |-------------|--------------------|--------------------|
# | 时间复杂度   | O(n²)              | O(n)               |
# | 空间复杂度   | O(1)               | O(n)               |
# | 核心思路     | 双重循环穷举        | 用空间换时间，边存边查 |
# | 关键技巧     | range(i+1, n)      | 先查再存，避免自配对  |

"""
========================================
Two Sum 进阶变体学习笔记
========================================
"""


# ============================================
# 变体1：返回所有不重复的解
# ============================================

def two_sum_all_pairs(nums, target):
    """
    返回所有和为 target 的索引对
    注意：每对只返回一次，不重复
    """
    hashmap = {}  # {值: 索引}
    result = []

    for i, num in enumerate(nums):
        complement = target - num
        if complement in hashmap:
            result.append([hashmap[complement], i])
        hashmap[num] = i

    return result


# 测试
# nums = [1, 3, 2, 4, 3], target = 5
# 1+4=5 → [0,3]
# 3+2=5 → [1,2]
# 2+3=5 → [2,4]
# 结果：[[0,3], [1,2], [2,4]]


# ============================================
# 变体2：返回所有不重复的值对（去重）
# ============================================

def two_sum_unique_pairs(nums, target):
    """
    返回所有和为 target 的值对，值对不重复
    例：nums=[1,1,2,2,3,4], target=5 → [[1,4], [2,3]]
    """
    nums.sort()  # 先排序
    left = 0
    right = len(nums) - 1
    result = []

    while left < right:
        current_sum = nums[left] + nums[right]

        if current_sum == target:
            result.append([nums[left], nums[right]])
            # 跳过重复元素
            while left < right and nums[left] == nums[left + 1]:
                left += 1
            while left < right and nums[right] == nums[right - 1]:
                right -= 1
            left += 1
            right -= 1
        elif current_sum < target:
            left += 1
        else:
            right -= 1

    return result


# ============================================
# 变体3：Two Sum II - 数组已排序
# ============================================

def two_sum_sorted(nums, target):
    """
    输入数组已按升序排列，返回索引（从1开始）
    使用双指针法，空间复杂度 O(1)
    时间复杂度：O(n)
    空间复杂度：O(1)
    """
    left = 0
    right = len(nums) - 1

    while left < right:
        current_sum = nums[left] + nums[right]

        if current_sum == target:
            return [left + 1, right + 1]  # 题目要求索引从1开始
        elif current_sum < target:
            left += 1   # 和太小，左指针右移，增大和
        else:
            right -= 1  # 和太大，右指针左移，减小和

    return []


# 原理图解：
# nums = [2, 7, 11, 15], target = 9
#
# 第1轮：left=0(2), right=3(15) → 2+15=17 > 9 → right左移
# 第2轮：left=0(2), right=2(11) → 2+11=13 > 9 → right左移
# 第3轮：left=0(2), right=1(7)  → 2+7=9 == 9  → 返回 [1, 2] ✅


# ============================================
# 变体4：Two Sum III - 设计数据结构
# ============================================

class TwoSum:
    """
    设计一个数据结构，支持：
    - add(number)：添加一个数
    - find(value)：是否存在两个数之和等于 value
    """

    def __init__(self):
        self.count = {}  # {数值: 出现次数}

    def add(self, number):
        """添加一个数到数据结构中"""
        self.count[number] = self.count.get(number, 0) + 1

    def find(self, value):
        """判断是否存在两个数之和等于 value"""
        for num in self.count:
            complement = value - num
            if complement in self.count:
                if complement != num:
                    # 两个不同的数
                    return True
                elif self.count[num] >= 2:
                    # 同一个数，但出现了至少2次
                    return True
        return False


# 测试
# obj = TwoSum()
# obj.add(1)
# obj.add(3)
# obj.add(5)
# obj.find(4)  → True  (1+3=4)
# obj.find(7)  → False


# ============================================
# 变体5：Three Sum（三数之和）
# ============================================

def three_sum(nums, target=0):
    """
    找出所有和为 target 的三元组，不重复
    思路：固定一个数 + Two Sum（双指针）
    时间复杂度：O(n²)
    """
    nums.sort()
    result = []

    for i in range(len(nums) - 2):
        # 跳过重复的第一个数
        if i > 0 and nums[i] == nums[i - 1]:
            continue

        left = i + 1
        right = len(nums) - 1

        while left < right:
            current_sum = nums[i] + nums[left] + nums[right]

            if current_sum == target:
                result.append([nums[i], nums[left], nums[right]])
                # 跳过重复
                while left < right and nums[left] == nums[left + 1]:
                    left += 1
                while left < right and nums[right] == nums[right - 1]:
                    right -= 1
                left += 1
                right -= 1
            elif current_sum < target:
                left += 1
            else:
                right -= 1

    return result


# ============================================
# 所有变体对比总结
# ============================================

# | 变体           | 核心方法     | 时间复杂度 | 空间复杂度 | 关键点              |
# |---------------|-------------|-----------|-----------|--------------------|
# | 基础 Two Sum   | 哈希表       | O(n)      | O(n)      | 先查再存，避免自配对   |
# | 返回所有解     | 哈希表       | O(n)      | O(n)      | 不 break，继续找     |
# | 去重值对       | 排序+双指针   | O(n logn) | O(1)      | 跳过重复元素         |
# | 已排序数组     | 双指针       | O(n)      | O(1)      | 利用有序性，无需哈希   |
# | 设计数据结构   | 哈希表(计数)  | add:O(1)  | O(n)      | 记录出现次数         |
# | 三数之和       | 排序+固定+双指针| O(n²)    | O(1)      | 降维：固定一个数→Two Sum|


# ============================================
# 测试所有变体
# ============================================
if __name__ == "__main__":
    nums = [2, 7, 11, 15]
    target = 9

    print("=== 基础 Two Sum ===")
    print("哈希表法：", two_sum_hashmap(nums, target))

    print("\n=== 返回所有解 ===")
    print("所有解：", two_sum_all_pairs([1, 3, 2, 4, 3], 5))

    print("\n=== 去重值对 ===")
    print("去重值对：", two_sum_unique_pairs([1, 1, 2, 2, 3, 4], 5))

    print("\n=== 已排序数组 ===")
    print("双指针法：", two_sum_sorted([2, 7, 11, 15], 9))

    print("\n=== 设计数据结构 ===")
    obj = TwoSum()
    obj.add(1)
    obj.add(3)
    obj.add(5)
    print("find(4)：", obj.find(4))
    print("find(7)：", obj.find(7))

    print("\n=== 三数之和 ===")
    print("三数之和：", three_sum([-1, 0, 1, 2, -1, -4]))

# ============================================
# 测试
# ============================================
if __name__ == "__main__":
    nums = [2, 7, 11, 15]
    target = 9

    print("暴力法结果：", two_sum_brute_force(nums, target))      # [0, 1]
    print("哈希表法结果：", two_sum_hashmap(nums, target))        # [0, 1]
