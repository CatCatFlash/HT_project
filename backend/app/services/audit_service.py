from ..exceptions import AuditError
from .result_formatter import normalize_audit_result


class MockAuditService:
    def analyze(self, parsed_text: str) -> dict:
        text = parsed_text.strip()
        if len(text) < 30:
            raise AuditError("AUDIT_EMPTY_RESULT", "未识别到有效合同内容，请检查后重试", 400)

        risks: list[dict] = []
        lowered = text.lower()

        if "违约" in text or "赔偿" in text:
            risks.append(
                {
                    "title": "违约责任需重点核查",
                    "level": "high",
                    "reason": "合同中涉及违约或赔偿内容，但责任边界、赔偿上限或双方对等性可能不够清晰。",
                    "suggestion": "建议明确双方违约责任、赔偿范围、计算方式和责任上限，避免责任明显失衡。",
                }
            )
        if "付款" in text or "支付" in text:
            risks.append(
                {
                    "title": "付款条款可能不够明确",
                    "level": "medium",
                    "reason": "付款节点、发票条件或逾期付款责任若表述模糊，容易引发履约争议。",
                    "suggestion": "建议补充付款时间、付款条件、账户信息、发票要求及逾期责任。",
                }
            )
        if "自动续约" in text or "续签" in text:
            risks.append(
                {
                    "title": "存在自动续约风险",
                    "level": "medium",
                    "reason": "自动续约条款可能导致一方在未充分留意的情况下继续承担合同义务。",
                    "suggestion": "建议增加续约提醒、明确通知期限，并允许在合理期限内书面拒绝续约。",
                }
            )
        if "争议" in text or "仲裁" in text or "法院" in text:
            risks.append(
                {
                    "title": "争议解决条款需要确认",
                    "level": "low",
                    "reason": "争议解决地、法院管辖或仲裁机构若约定偏向对方，会增加后续维权成本。",
                    "suggestion": "建议确认争议解决方式、适用法律和管辖地是否合理，尽量选择可接受地点。",
                }
            )
        if "保密" not in text and "confidential" not in lowered:
            risks.append(
                {
                    "title": "保密条款可能缺失",
                    "level": "medium",
                    "reason": "合同中未明显体现保密义务，可能导致商业信息、报价或数据保护不足。",
                    "suggestion": "建议补充保密范围、保密期限、例外情形及违约责任。",
                }
            )

        if not risks:
            risks = [
                {
                    "title": "建议人工复核关键条款",
                    "level": "low",
                    "reason": "当前文本未识别出明显高频风险，但并不代表合同不存在法律或商业风险。",
                    "suggestion": "建议重点复核合同主体、付款、违约、解约、争议解决和知识产权相关条款。",
                }
            ]

        return normalize_audit_result(
            {
                "overall_message": "本次为通用合同初审结果，建议优先处理高风险条款，复杂场景仍需专业法务复核。",
                "risks": risks,
            }
        )
