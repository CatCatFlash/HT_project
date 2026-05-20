from collections import Counter


VALID_LEVELS = {"high", "medium", "low"}


def normalize_audit_result(result: dict) -> dict:
    risks = result.get("risks") or []
    normalized_risks = []
    for risk in risks:
        level = str(risk.get("level", "medium")).lower()
        if level not in VALID_LEVELS:
            level = "medium"
        normalized_risks.append(
            {
                "title": _fallback_text(risk.get("title"), "未命名风险"),
                "level": level,
                "reason": _fallback_text(risk.get("reason"), "暂未给出具体原因，请人工复核"),
                "suggestion": _fallback_text(risk.get("suggestion"), "建议结合合同上下文进一步确认并补充约定"),
            }
        )

    counts = Counter(item["level"] for item in normalized_risks)
    total_risks = len(normalized_risks)
    overall_message = _fallback_text(
        result.get("overall_message"),
        "建议优先关注高风险与中风险条款，再决定是否继续推进签署",
    )
    return {
        "total_risks": total_risks,
        "high_risks": counts.get("high", 0),
        "medium_risks": counts.get("medium", 0),
        "low_risks": counts.get("low", 0),
        "overall_message": overall_message,
        "risks": sorted(normalized_risks, key=_risk_sort_key),
    }


def _fallback_text(value: object, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _risk_sort_key(risk: dict) -> int:
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get(risk["level"], 3)
