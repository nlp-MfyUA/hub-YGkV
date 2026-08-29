from agent import run_agent


def main():

    while True:

        text = input(
            "\n请输入："
        )


        result = run_agent(text)


        if result["type"] == "no_relation":

            print(
                "我是一个人物关系抽取智能体，请输入人物关系。示例：小明喜欢小姚",
                #"\n原始LLM输出：",result["content"]     # 用于调试
            )


        else:

            graph = result["data"]
            # content = result["content"]    # 用于调试

            print(
                graph.model_dump_json(
                    indent=4,
                    ensure_ascii=False
                ),
                #"\n原始LLM输出：",content    # 用于调试
            )


if __name__ == "__main__":
    main()