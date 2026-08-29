relationship_tool = {
    "type": "function",
    "function": {
        "name": "extract_relationship",
        "description": "从文本中抽取人物或实体关系",
        "parameters": {
            "type": "object",
            "properties": {
                "relationships": {
                    "type": "array",
                    "description": "人物关系列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "description": "关系主体"
                            },
                            "relation": {
                                "type": "string",
                                "description": "关系类型"
                            },
                            "target": {
                                "type": "string",
                                "description": "关系对象"
                            }
                        },
                        "required": [
                            "source",
                            "relation",
                            "target"
                        ]
                    }
                }
            },
            "required": [
                "relationships"
            ]
        }
    }
}