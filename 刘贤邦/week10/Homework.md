# 作业一

按照下openai agents框架，实现一个应用需求：

用户输入文本，判断下文本的语种（是什么语言的）。如果是非中文的，则翻译为中文；如果是中文，则翻译为英文。最终输出格式如下

```json
{
    "query_input": "",
    "language": "",
    "result": ""
}
```



# 作业二

基于已有的 `2-兼容OpenAI-Agent mcp` 代码，自己增加3个mcp 工具，并通过agent进行调用。