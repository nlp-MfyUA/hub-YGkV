"""消防风险分级：不信任模型的直接评级，只读取可见事实。"""
import json

REQUIRED_FLAGS = (
    "is_corridor",
    "electric_vehicle_or_battery",
    "unsafe_charging",
    "severe_obstruction",
    "large_combustible_pile",
    "small_clutter",
)

ADVICE = {
    "非楼道": "请重新拍摄楼道、楼梯间、电梯前室等公共疏散通道。",
    "无隐患": "继续保持楼道整洁、疏散通道畅通，定期巡查。",
    "低风险": "及时清理少量堆放物品，避免进一步占用疏散通道。",
    "中等风险": "尽快清理大量堆积物与可燃物，恢复通行宽度；必要时联系物业处理。",
    "高风险": "立即停止可见的违规充电行为，通知物业将电动车或电池移出公共疏散通道；若现场已有烟火，应立即报警并安全撤离。",
}


def validate_facts(raw: str) -> dict:
    """校验模型 JSON：缺字段、类型错误时拒绝判断，而不是默认为安全。"""
    try:
        obj = json.loads(raw.strip())
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("模型未返回有效的 JSON") from exc
    if not isinstance(obj, dict):
        raise ValueError("模型 JSON 必须是对象")
    for flag in REQUIRED_FLAGS:
        if type(obj.get(flag)) is not bool:
            raise ValueError(f"模型字段 {flag} 缺失或不是布尔值")
    if not isinstance(obj.get("description"), str):
        raise ValueError("模型缺少文字描述")
    evidence = obj.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence):
        raise ValueError("模型返回的依据必须是字符串列表")
    obj["description"] = obj["description"][:400]
    obj["evidence"] = [line[:120] for line in evidence[:8]]
    return obj


def classify(facts: dict) -> str:
    """从最优先的非楼道判定开始，逐级判断消防风险。"""
    if not facts["is_corridor"]:
        return "非楼道"
    if facts["electric_vehicle_or_battery"] or facts["unsafe_charging"]:
        return "高风险"
    if facts["severe_obstruction"] or facts["large_combustible_pile"]:
        return "中等风险"
    if facts["small_clutter"]:
        return "低风险"
    return "无隐患"


def make_report(facts: dict, provider: str, model: str) -> dict:
    level = classify(facts)
    return {
        "risk_level": level,
        "description": facts["description"],
        "evidence": facts["evidence"],
        "suggestion": ADVICE[level],
        "is_corridor": facts["is_corridor"],
        "provider": provider,
        "model": model,
        "is_demo": False,
    }
