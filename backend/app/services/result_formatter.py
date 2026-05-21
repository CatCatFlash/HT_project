from collections import Counter
import re


VALID_LEVELS = {"high", "medium", "low"}
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}
STRATEGY_VERSION = "v1-standardized-2026-05-21"
MAX_CORE_RISKS = 3

RISK_CATEGORY_RULES = [
    {
        "category": "payment",
        "canonical_title": "付款条款不明确",
        "keywords": ["付款", "支付", "账期", "发票", "逾期付款", "服务费", "租金"],
        "title_patterns": ["付款", "支付", "账期", "发票", "逾期付款"],
        "suggestion": "建议补充付款时间、付款条件、发票要求、账户信息以及逾期付款责任。",
        "priority": 1,
    },
    {
        "category": "liability",
        "canonical_title": "违约责任不明确",
        "keywords": ["违约", "赔偿", "责任上限", "损失", "违约责任"],
        "title_patterns": ["违约", "赔偿", "责任"],
        "suggestion": "建议明确违约责任触发条件、赔偿范围、计算方式和责任上限。",
        "priority": 2,
    },
    {
        "category": "termination",
        "canonical_title": "解约条款不明确",
        "keywords": ["解约", "解除", "终止", "提前通知"],
        "title_patterns": ["解约", "解除", "终止"],
        "suggestion": "建议明确解约条件、提前通知期限、违约后果及已履行部分的结算方式。",
        "priority": 3,
    },
    {
        "category": "renewal",
        "canonical_title": "自动续约风险",
        "keywords": ["自动续约", "续约", "续签"],
        "title_patterns": ["续约", "续签"],
        "suggestion": "建议增加续约提醒和通知期限，并明确书面拒绝续约的操作方式。",
        "priority": 4,
    },
    {
        "category": "confidentiality",
        "canonical_title": "保密条款缺失",
        "keywords": ["保密", "商业秘密", "数据保护", "confidential"],
        "title_patterns": ["保密", "数据保护", "商业秘密"],
        "suggestion": "建议补充保密范围、保密期限、例外情形和违约责任。",
        "priority": 5,
    },
    {
        "category": "ip",
        "canonical_title": "知识产权归属不明确",
        "keywords": ["知识产权", "著作权", "源代码", "专利", "商标"],
        "title_patterns": ["知识产权", "著作权", "专利", "商标"],
        "suggestion": "建议明确交付成果、源代码、文档及衍生成果的知识产权归属和使用范围。",
        "priority": 6,
    },
    {
        "category": "dispute",
        "canonical_title": "争议解决条款风险",
        "keywords": ["争议解决", "仲裁", "法院管辖", "适用法律"],
        "title_patterns": ["争议", "仲裁", "管辖"],
        "suggestion": "建议明确争议解决方式、管辖法院或仲裁机构，以及适用法律。",
        "priority": 7,
    },
    {
        "category": "acceptance",
        "canonical_title": "验收标准不明确",
        "keywords": ["验收", "交付", "验收标准", "测试", "上线"],
        "title_patterns": ["验收", "交付", "测试"],
        "suggestion": "建议补充详细的验收标准、验收流程、验收期限及验收不合格的处理方式。",
        "priority": 8,
    },
]

FALLBACK_RULE = {
    "category": "other",
    "canonical_title": "其他关键条款需人工复核",
    "suggestion": "建议结合合同上下文进一步人工复核，并补充关键权利义务条款。",
    "priority": 99,
}

RULE_BY_CATEGORY = {rule["category"]: rule for rule in RISK_CATEGORY_RULES}


def normalize_audit_result(result: dict) -> dict:
    raw_risks = result.get("risks") or []
    normalized_text = _normalize_result_text(result.get("overall_message"))
    standardized_risks = [_standardize_risk(risk) for risk in raw_risks]
    deduped_risks = _dedupe_risks(standardized_risks)
    sorted_risks = sorted(deduped_risks, key=_risk_sort_key)
    core_risks = sorted_risks[:MAX_CORE_RISKS]
    additional_risks = sorted_risks[MAX_CORE_RISKS:]
    flattened_risks = core_risks + additional_risks

    counts = Counter(item["level"] for item in flattened_risks)
    total_risks = len(flattened_risks)
    overall_message = _fallback_text(
        normalized_text,
        "建议优先处理核心风险条款，再决定是否继续推进签署。",
    )

    return {
        "strategy_version": STRATEGY_VERSION,
        "total_risks": total_risks,
        "high_risks": counts.get("high", 0),
        "medium_risks": counts.get("medium", 0),
        "low_risks": counts.get("low", 0),
        "overall_message": overall_message,
        "core_risks": core_risks,
        "additional_risks": additional_risks,
        "risks": flattened_risks,
    }


def _standardize_risk(risk: dict) -> dict:
    title = _normalize_result_text(risk.get("title"))
    reason = _normalize_result_text(risk.get("reason"))
    suggestion = _normalize_result_text(risk.get("suggestion"))
    level = str(risk.get("level", "medium")).strip().lower()
    if level not in VALID_LEVELS:
        level = "medium"

    rule = _match_rule(title, reason, suggestion)
    canonical_title = rule["canonical_title"]
    category = rule["category"]
    templated_suggestion = _build_suggestion(rule, suggestion)
    normalized_reason = _fallback_text(reason, "暂未给出具体原因，请结合合同原文进一步人工复核。")

    return {
        "title": canonical_title,
        "level": level,
        "reason": normalized_reason,
        "suggestion": templated_suggestion,
        "category": category,
        "priority": rule["priority"],
    }


def _dedupe_risks(risks: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for risk in risks:
        key = (risk["category"], risk["title"])
        existing = merged.get(key)
        if not existing:
            merged[key] = risk
            continue

        if LEVEL_ORDER[risk["level"]] < LEVEL_ORDER[existing["level"]]:
            existing["level"] = risk["level"]
        existing["reason"] = _choose_longer(existing["reason"], risk["reason"])
        existing["suggestion"] = _choose_longer(existing["suggestion"], risk["suggestion"])
    return list(merged.values())


def _match_rule(title: str, reason: str, suggestion: str) -> dict:
    haystack = f"{title} {reason} {suggestion}".lower()
    for rule in RISK_CATEGORY_RULES:
        if any(pattern.lower() in title.lower() for pattern in rule["title_patterns"]):
            return rule
        if any(keyword.lower() in haystack for keyword in rule["keywords"]):
            return rule
    return FALLBACK_RULE


def _build_suggestion(rule: dict, suggestion: str) -> str:
    normalized = _normalize_result_text(suggestion)
    template = rule.get("suggestion") or FALLBACK_RULE["suggestion"]
    if not normalized:
        return template
    if normalized == template:
        return template
    if len(normalized) < 18:
        return template
    return normalized


def _normalize_result_text(value: object) -> str:
    text = _fallback_text(value, "")
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fallback_text(value: object, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _choose_longer(left: str, right: str) -> str:
    return right if len(right) > len(left) else left


def _risk_sort_key(risk: dict) -> tuple[int, int, str]:
    return (
        LEVEL_ORDER.get(risk["level"], 3),
        risk.get("priority", 999),
        risk["title"],
    )
