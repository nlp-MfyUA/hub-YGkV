"""确定性串联两个远程 Agent；分支由已校验的分类结果决定。"""
async def run_pipeline(text, rpc):
    analysis = await rpc("sentiment", "/classify", {"text": text})
    result = await rpc("response", "/respond", {"text": text, "analysis": analysis})
    return {
        "text": text,
        "analysis": analysis,
        "strategy": "encourage" if analysis["sentiment"] == "positive" else "comfort",
        "reply": result["reply"],
    }
