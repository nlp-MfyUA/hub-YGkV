# ============================================================================
# requests 库完整学习指南  todo 某些接口不存在，这只是一个展示每种api的样式展示
# ============================================================================
#
# 本文件涵盖：
# 1. 四种HTTP请求方法（GET / POST / PUT / DELETE）
# 2. 不同请求格式的处理方式（params / data / json / files）
# 3. 生产环境常见坑与解决方案
# 4. 生产级请求封装模板
#
# 运行前请确保已安装 requests：pip install requests
# ============================================================================

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================================
# 第一部分：四种核心请求方法
# ============================================================================
#
# HTTP协议定义了多种请求方法，最常用的是以下四种：
# - GET：    获取数据（查）
# - POST：   创建数据（增）
# - PUT：    整体更新数据（改）—— 需要把完整对象发过去
# - PATCH：  部分更新数据（改）—— 只发需要修改的字段
# - DELETE： 删除数据（删）
#
# 对应数据库的 CRUD 操作：Create(POST)、Read(GET)、Update(PUT)、Delete(DELETE)
# ============================================================================

BASE_URL = "https://jsonplaceholder.typicode.com"


def demo_get():
    """
    GET 请求 —— 从服务器获取数据
    特点：
    - 参数拼接在URL后面（如 ?userId=1）
    - 不会修改服务器数据
    - 可以被浏览器缓存
    - 有长度限制（URL长度有限）
    """
    print("=== GET 请求示例 ===")

    # 基本用法：获取所有帖子
    response = requests.get(f"{BASE_URL}/posts")
    print(f"状态码: {response.status_code}")  # 200 表示成功
    print(f"帖子数量: {len(response.json())}")

    # 带查询参数：获取指定用户的帖子
    # params 会自动拼接成 ?userId=1
    response = requests.get(f"{BASE_URL}/posts", params={"userId": 1})
    posts = response.json()
    print(f"用户1的帖子数量: {len(posts)}")
    print(f"实际请求的URL: {response.url}")  # 可以看到拼接后的完整URL
    print()


def demo_post():
    """
    POST 请求 —— 向服务器提交数据，创建新资源
    特点：
    - 数据放在请求体（body）中，不在URL里
    - 会修改服务器数据
    - 没有长度限制
    - 不会被浏览器缓存
    """
    print("=== POST 请求示例 ===")

    new_post = {
        "title": "学习requests库",
        "body": "这是一篇通过POST请求创建的帖子",
        "userId": 1
    }

    # json 参数会自动做两件事：
    # 1. 把字典转换成JSON字符串
    # 2. 设置请求头 Content-Type: application/json
    response = requests.post(f"{BASE_URL}/posts", json=new_post)

    print(f"状态码: {response.status_code}")  # 201 表示资源创建成功
    created = response.json()
    print(f"服务器返回的ID: {created['id']}")  # 通常是 101（模拟API）
    print(f"标题是否一致: {created['title'] == new_post['title']}")
    print()


def demo_put():
    """
    PUT 请求 —— 整体更新一个已有资源
    特点：
    - 需要发送完整的资源数据（包括id）
    - 如果资源不存在，有些服务器会创建新的
    - 与 PATCH 的区别：PUT是整体替换，PATCH是部分修改
    """
    print("=== PUT 请求示例 ===")

    updated_post = {
        "id": 1,  # PUT通常需要带上资源ID
        "title": "更新后的标题",
        "body": "更新后的内容",
        "userId": 1
    }

    response = requests.put(f"{BASE_URL}/posts/1", json=updated_post)
    print(f"状态码: {response.status_code}")  # 200 表示更新成功
    result = response.json()
    print(f"更新后的标题: {result['title']}")
    print()


def demo_delete():
    """
    DELETE 请求 —— 删除服务器上的资源
    特点：
    - 通常只需要指定资源的ID
    - 幂等操作：删除一次和删除多次效果相同
    - 有些API返回200，有些返回204（No Content，无返回体）
    """
    print("=== DELETE 请求示例 ===")

    response = requests.delete(f"{BASE_URL}/posts/1")
    print(f"状态码: {response.status_code}")  # 200 表示删除成功
    print()


# ============================================================================
# 第二部分：不同请求格式的处理方式
# ============================================================================
#
# requests 提供了多种传参方式，对应不同的数据格式：
# - params：拼接到URL后面，用于GET请求的查询参数
# - data：  以表单格式发送（application/x-www-form-urlencoded）
# - json：  以JSON格式发送（application/json）
# - files： 以multipart/form-data格式发送，用于文件上传
#
# 最容易搞混的是 data 和 json，它们的区别决定了服务器能否正确解析数据。
# ============================================================================


def demo_params():
    """
    params —— URL查询参数
    适用场景：GET请求中传递筛选条件
    效果：自动拼接到URL后面，用 ? 和 & 连接
    """
    print("=== params 参数示例 ===")

    # 手动拼接URL（不推荐，容易出错）
    url_manual = f"{BASE_URL}/posts?userId=1&_limit=3"

    # 使用params（推荐，自动处理编码和拼接）
    url_auto = f"{BASE_URL}/posts"
    params = {"userId": 1, "_limit": 3}

    response = requests.get(url_auto, params=params)
    print(f"实际请求URL: {response.url}")
    # 输出类似: https://jsonplaceholder.typicode.com/posts?userId=1&_limit=3
    print(f"返回帖子数: {len(response.json())}")
    print()


def demo_data():
    """
    data —— 表单格式提交
    适用场景：模拟HTML表单提交、部分老式API
    Content-Type: application/x-www-form-urlencoded
    发送格式: key1=value1&key2=value2
    """
    print("=== data 参数示例（表单格式）===")

    form_data = {"title": "表单帖子", "body": "通过data参数发送", "userId": 1}

    response = requests.post(f"{BASE_URL}/posts", data=form_data)
    print(f"状态码: {response.status_code}")
    print(f"Content-Type请求头: {response.request.headers['Content-Type']}")
    # 输出: application/x-www-form-urlencoded
    print()


def demo_json():
    """
    json —— JSON格式提交
    适用场景：现代RESTful API（绝大多数情况用这个）
    Content-Type: application/json
    发送格式: {"key1":"value1","key2":"value2"}
    """
    print("=== json 参数示例（JSON格式）===")

    json_data = {"title": "JSON帖子", "body": "通过json参数发送", "userId": 1}

    response = requests.post(f"{BASE_URL}/posts", json=json_data)
    print(f"状态码: {response.status_code}")
    print(f"Content-Type请求头: {response.request.headers['Content-Type']}")
    # 输出: application/json
    print()


def demo_data_vs_json():
    """
    data 和 json 的核心区别（最容易踩的坑）
    """
    print("=== data 和 json 的区别 ===")

    payload = {"title": "测试", "userId": 1}

    # 用 data 发送：服务器收到的是表单格式
    # 请求体: title=测试&userId=1
    r1 = requests.post(f"{BASE_URL}/posts", data=payload)
    print(f"data 发送 -> Content-Type: {r1.request.headers['Content-Type']}")
    print(f"data 发送 -> 请求体: {r1.request.body}")

    # 用 json 发送：服务器收到的是JSON格式
    # 请求体: {"title": "测试", "userId": 1}
    r2 = requests.post(f"{BASE_URL}/posts", json=payload)
    print(f"json 发送 -> Content-Type: {r2.request.headers['Content-Type']}")
    print(f"json 发送 -> 请求体: {r2.request.body}")

    print()
    print("结论：大多数现代API只接受JSON格式，所以优先使用 json 参数。")
    print("如果API要求表单格式（如某些登录接口），才使用 data 参数。")
    print()


def demo_files():
    """
    files —— 文件上传
    适用场景：上传图片、文档等二进制文件
    Content-Type: multipart/form-data
    """
    print("=== files 参数示例（文件上传）===")
    print("（此处仅展示写法，不实际执行上传）")
    print()
    print("写法示例：")
    print('  with open("photo.jpg", "rb") as f:')
    print('      requests.post(url, files={"file": f})')
    print()
    print('  # 同时上传文件和表单数据：')
    print('  with open("photo.jpg", "rb") as f:')
    print('      requests.post(url,')
    print('          data={"description": "我的照片"},')
    print('          files={"file": f})')
    print()


# ============================================================================
# 第三部分：生产环境常见坑与解决方案
# ============================================================================


def pitfall_1_no_timeout():
    """
    坑一：不设置超时，程序永久阻塞

    原因：requests 默认不设超时。如果目标服务器无响应，
    你的程序会一直等下去，在生产环境中会导致线程/连接堆积，最终系统崩溃。

    这是生产环境最常见的事故原因之一。
    """
    print("=== 坑一：不设置超时 ===")

    # 错误写法：没有超时，可能永远卡住
    # response = requests.get(url)

    # 正确写法：设置超时
    # timeout 可以传一个数字（连接和读取用同一个超时）
    # 也可以传一个元组（连接超时, 读取超时）
    try:
        response = requests.get(f"{BASE_URL}/posts", timeout=(3, 10))
        print(f"请求成功，状态码: {response.status_code}")
    except requests.exceptions.Timeout:
        print("请求超时！")
    print()

    print("建议值：")
    print("  - 内网接口：timeout=(1, 3)")
    print("  - 外网接口：timeout=(3, 10)")
    print("  - 文件下载：timeout=(5, 60)")
    print()


def pitfall_2_no_exception_handling():
    """
    坑二：不处理异常，程序直接崩溃

    原因：网络请求随时可能失败（断网、DNS解析失败、服务器宕机、超时等），
    如果不捕获异常，程序会直接崩溃退出。
    """
    print("=== 坑二：不处理异常 ===")

    # 错误写法：任何网络问题都会导致程序崩溃
    # response = requests.get("https://不存在的域名.com")
    # data = response.json()  # 如果请求失败，这里也会报错

    # 正确写法：完整的异常处理
    try:
        response = requests.get(f"{BASE_URL}/posts", timeout=(3, 5))
        response.raise_for_status()  # 关键！状态码 >= 400 时主动抛出异常
        data = response.json()
        print(f"成功获取 {len(data)} 条数据")
    except requests.exceptions.ConnectTimeout:
        print("连接超时：服务器太忙或网络不通")
    except requests.exceptions.ReadTimeout:
        print("读取超时：服务器处理太慢")
    except requests.exceptions.ConnectionError:
        print("连接错误：DNS解析失败或服务器拒绝连接")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误：状态码 {e.response.status_code}")
    except requests.exceptions.RequestException as e:
        # 这是所有requests异常的基类，放在最后兜底
        print(f"其他网络异常：{e}")
    print()


def pitfall_3_no_session():
    """
    坑三：每次请求都新建连接，性能低下

    原因：每次调用 requests.get() 都会：
    1. 建立新的TCP连接（三次握手）
    2. 如果是HTTPS，还要进行SSL握手
    3. 请求结束后关闭连接

    如果需要连续请求同一个服务器，这些重复的连接开销非常大。
    """
    print("=== 坑三：不使用Session ===")

    # 错误写法：循环中每次都新建连接
    # for i in range(100):
    #     requests.get(f"{url}/data/{i}")  # 100次TCP握手！

    # 正确写法：使用Session复用连接
    with requests.Session() as session:
        # Session 的好处：
        # 1. 连接池：复用TCP连接，不用每次握手
        # 2. Cookie持久化：登录一次，后续请求自动带上Cookie
        # 3. 统一配置：设置一次Headers，所有请求都生效

        # 设置统一的请求头（比如认证Token）
        session.headers.update({
            "Accept": "application/json",
            "User-Agent": "MyApp/1.0"
        })

        # 后续所有请求都会自动带上上面的Headers，且复用连接
        r1 = session.get(f"{BASE_URL}/posts/1")
        r2 = session.get(f"{BASE_URL}/posts/2")
        print(f"请求1状态码: {r1.status_code}")
        print(f"请求2状态码: {r2.status_code}")
    print()


def pitfall_4_no_retry():
    """
    坑四：没有重试机制，一次失败就放弃

    原因：网络请求失败很多时候是临时性的（网络抖动、服务器短暂过载），
    加一个重试机制就能大幅提高成功率。
    """
    print("=== 坑四：不使用重试机制 ===")

    # 配置重试策略
    retry_strategy = Retry(
        total=3,                        # 最多重试3次
        backoff_factor=1,               # 重试间隔：第1次等1秒，第2次等2秒，第3次等4秒（指数退避）
        status_forcelist=[429, 500, 502, 503, 504],  # 只对特定状态码重试
        # 429 = 请求过于频繁（限流）
        # 500 = 服务器内部错误
        # 502 = 网关错误
        # 503 = 服务不可用
        # 504 = 网关超时
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    with requests.Session() as session:
        # 将重试策略挂载到https和http协议上
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        response = session.get(f"{BASE_URL}/posts/1", timeout=(3, 5))
        print(f"请求状态码: {response.status_code}")
        print("如果请求失败，会自动重试最多3次，间隔逐渐增大")
    print()

    print("注意事项：")
    print("  - 默认不重试POST请求（因为POST不是幂等的，重复提交可能产生重复数据）")
    print("  - 如果确实需要重试POST，需要显式声明 allowed_methods=['GET', 'POST']")
    print("  - 重试只针对网络错误和status_forcelist中的状态码，4xx错误不会重试")
    print()


def pitfall_5_encoding():
    """
    坑五：中文乱码

    原因：requests 会根据响应头中的 Content-Type 猜测编码，
    但很多网站（尤其是国内老网站）响应头声明的编码和实际编码不一致。
    """
    print("=== 坑五：中文乱码 ===")

    # 错误写法：直接使用 response.text，可能乱码
    # response = requests.get("https://某个中文网站.com")
    # print(response.text)  # 可能是一堆乱码

    # 正确写法：手动指定编码
    # response.encoding = "utf-8"   # 或 "gbk"，根据实际网站编码
    # print(response.text)

    # 判断编码的方法：
    # 1. 查看网页源代码中的 <meta charset="xxx">
    # 2. 查看响应头 Content-Type: text/html; charset=xxx
    # 3. 用 response.apparent_encoding 让chardet库自动检测（较慢）

    print("常见编码：")
    print("  - utf-8：绝大多数现代网站")
    print("  - gbk/gb2312：国内老网站、政府网站")
    print("  - 查看方法：response.apparent_encoding")
    print()


def pitfall_6_ssl_verify():
    """
    坑六：SSL证书验证问题

    原因：访问HTTPS网站时，requests会验证服务器的SSL证书。
    如果证书过期、自签名、或内网环境没有正确的CA证书，请求会报错。

    很多人图省事直接关闭验证，这在生产环境中是严重的安全隐患，
    容易遭受中间人攻击（MITM）。
    """
    print("=== 坑六：SSL证书验证 ===")

    # 错误写法：关闭SSL验证（安全隐患！）
    # response = requests.get(url, verify=False)
    # 会看到警告: InsecureRequestWarning: Unverified HTTPS request...

    # 正确做法一：使用公司内部的CA证书
    # response = requests.get(url, verify="/path/to/company-ca.pem")

    # 正确做法二：更新系统CA证书包
    # pip install --upgrade certifi

    print("正确做法：")
    print("  - 生产环境绝对不能设置 verify=False")
    print("  - 如果是内网自签名证书，使用 verify='/path/to/ca.pem' 指定证书")
    print("  - 如果是证书过期，联系运维更新证书")
    print()


def pitfall_7_version():
    """
    坑七：依赖版本不一致

    原因：开发环境用 requests 2.31.0，生产环境装了 2.25.1，
    两者在SSL处理、编码、重定向等行为上可能有差异，
    导致"在我电脑上能跑，上线就报错"。
    """
    print("=== 坑七：依赖版本不一致 ===")

    print("解决方案：使用 requirements.txt 锁死版本")
    print()
    print("requirements.txt 内容示例：")
    print("  requests==2.31.0")
    print("  urllib3==2.0.7")
    print("  certifi==2024.2.2")
    print()
    print("安装命令：")
    print("  pip install -r requirements.txt")
    print()
    print("导出当前环境依赖：")
    print("  pip freeze > requirements.txt")
    print()


# ============================================================================
# 第四部分：生产级请求封装模板
# ============================================================================
#
# 把前面的最佳实践整合起来，形成一个可复用的请求工具类。
# 在实际项目中，所有API调用都应该通过这个封装来发请求，
# 而不是直接调用 requests.get() / requests.post()。
# ============================================================================


def create_production_session():
    """
    创建一个生产级的Session，包含：
    - 重试机制
    - 超时设置
    - 统一请求头
    """
    session = requests.Session()

    # 配置重试策略
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))

    # 设置默认请求头
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "MyApp/1.0"
    })

    return session


def safe_request(session, method, url, **kwargs):
    """
    安全的请求封装函数

    参数：
        session: requests.Session 对象
        method: 请求方法，如 "GET", "POST", "PUT", "DELETE"
        url: 请求地址
        **kwargs: 传递给 session.request() 的其他参数（如 json, params, timeout 等）

    返回：
        成功时返回解析后的JSON数据（字典或列表）
        失败时返回 None
    """
    # 设置默认超时（如果调用者没有指定的话）
    kwargs.setdefault("timeout", (3, 10))

    try:
        response = session.request(method, url, **kwargs)
        response.raise_for_status()  # 状态码 >= 400 时抛出异常
        return response.json()
    except requests.exceptions.Timeout:
        print(f"请求超时: {method} {url}")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误 {e.response.status_code}: {method} {url}")
    except requests.exceptions.ConnectionError:
        print(f"连接失败: {method} {url}")
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
    return None


def demo_production_template():
    """演示生产级模板的使用"""
    print("=== 生产级请求模板演示 ===")

    session = create_production_session()

    # GET 请求
    data = safe_request(session, "GET", f"{BASE_URL}/posts/1")
    if data:
        print(f"GET 成功，帖子标题: {data['title'][:40]}...")

    # POST 请求
    new_post = {"title": "测试", "body": "内容", "userId": 1}
    data = safe_request(session, "POST", f"{BASE_URL}/posts", json=new_post)
    if data:
        print(f"POST 成功，返回ID: {data['id']}")

    # PUT 请求
    updated = {"id": 1, "title": "更新", "body": "更新内容", "userId": 1}
    data = safe_request(session, "PUT", f"{BASE_URL}/posts/1", json=updated)
    if data:
        print(f"PUT 成功，更新后标题: {data['title']}")

    # DELETE 请求
    data = safe_request(session, "DELETE", f"{BASE_URL}/posts/1")
    print(f"DELETE 完成，返回: {data}")

    print()


# ============================================================================
# 第五部分：常用HTTP状态码速查
# ============================================================================
#
# 2xx 成功：
#   200 OK           - 请求成功（GET、PUT、DELETE常用）
#   201 Created      - 资源创建成功（POST常用）
#   204 No Content   - 请求成功但没有返回内容（DELETE常用）
#
# 3xx 重定向：
#   301 Moved Permanently - 资源已永久移动到新URL
#   302 Found              - 资源临时移动
#   304 Not Modified       - 资源未修改，可使用缓存
#
# 4xx 客户端错误（你的请求有问题）：
#   400 Bad Request        - 请求参数有误（如JSON格式错误）
#   401 Unauthorized       - 未认证（没登录或Token过期）
#   403 Forbidden          - 已认证但无权限
#   404 Not Found          - 资源不存在（URL写错了）
#   405 Method Not Allowed - 请求方法不允许（如该接口只支持GET）
#   429 Too Many Requests  - 请求过于频繁，被限流了
#
# 5xx 服务器错误（对方的问题）：
#   500 Internal Server Error - 服务器内部错误
#   502 Bad Gateway           - 网关错误（通常是上游服务挂了）
#   503 Service Unavailable   - 服务不可用（服务器过载或维护中）
#   504 Gateway Timeout       - 网关超时（上游服务响应太慢）
# ============================================================================


# ============================================================================
# 主程序：运行所有示例
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("第一部分：四种核心请求方法")
    print("=" * 60)
    demo_get()
    demo_post()
    demo_put()
    demo_delete()

    print("=" * 60)
    print("第二部分：不同请求格式的处理方式")
    print("=" * 60)
    demo_params()
    demo_data()
    demo_json()
    demo_data_vs_json()
    demo_files()

    print("=" * 60)
    print("第三部分：生产环境常见坑")
    print("=" * 60)
    pitfall_1_no_timeout()
    pitfall_2_no_exception_handling()
    pitfall_3_no_session()
    pitfall_4_no_retry()
    pitfall_5_encoding()
    pitfall_6_ssl_verify()
    pitfall_7_version()

    print("=" * 60)
    print("第四部分：生产级请求模板")
    print("=" * 60)
    demo_production_template()