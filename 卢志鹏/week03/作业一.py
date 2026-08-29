1、 langchain 工具调用 和 llm function call 有什么区别？
答：两者都是利用了 LLM 的function calling能力，即依靠大模型对工具的了解，返回合适调用函数的入参，然后本地调用对应的函数。其中，
OpenAI SDK 的 Function Call 需要我们用户自己定义函数（相关注释可以不填写），但是需要填写函数的 JSON Schema，LLM 返回的入参结果，需要手动转为合适的参数格式，
接着手动调用函数（用户手动写 dispatch 逻辑），将函数的调用结果，封装成 ToolMessage 格式，拼接回 Messages，然后再一次调用 LLM，LLM 根据历史对话记录 Messages，生成最终答案。而 LangChain 
的工具调用，无需用户填写函数的 JSON Schema，但需要用户完善函数及入参的注释，依靠 @tool 装饰器自动生成 JSON Schema，同时 LangChain 自动将 LLM 返回的函数调用
入参信息格式化，结果作为入参直接调用函数即可（tool.invoke(args)），返回的结果拼接到 Messages 中，再一次调用 LLM 得到最终答案。总结两者的区别就是 LangChain 封装了一层能力，帮用户管理生成
tool_calls JSON 的生成和函数的执行。

2、 langchain 工具调用 的 速度是受到什么影响？
答：1. LLM 的推理耗时（Token生成速度）；2.LLM API 网络往返耗时；3.响应解析（直接拿 response.choices[0]	JSON → LangChain AIMessage 对象构建、tool_calls 参数自动反序列化为 dict、Pydantic schema 校验参数合法性）。
