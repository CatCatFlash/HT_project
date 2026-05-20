import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from ..config import (
    AUDIT_ALLOW_MOCK_FALLBACK,
    AUDIT_MODEL_API_KEY,
    AUDIT_MODEL_BASE_URL,
    AUDIT_MODEL_MAX_INPUT_CHARS,
    AUDIT_MODEL_MAX_RETRIES,
    AUDIT_MODEL_NAME,
    AUDIT_MODEL_RETRY_BACKOFF_SECONDS,
    AUDIT_MODEL_TIMEOUT_SECONDS,
    LOG_LEVEL,
)
from ..exceptions import AuditError
from .result_formatter import normalize_audit_result


logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


SYSTEM_PROMPT = """你是AI合同初审助手的后端审核服务。
你的任务是对合同文本做通用初审，只输出结构化 JSON。

要求：
1. 只做通用合同风险识别，不输出法律结论。
2. 必须输出 JSON 对象，且包含：
   - overall_message: string
   - risks: array
3. risks 中每一项必须包含：
   - title: string
   - level: high | medium | low
   - reason: string
   - suggestion: string
4. 如果合同文本信息不足，也必须返回一个合理的 overall_message，并尽量给出低风险或中风险提醒。
5. 不要输出 markdown，不要输出代码块，不要输出 JSON 之外的任何说明。
"""


def _build_user_prompt(parsed_text: str) -> str:
    return (
        "请根据下面的合同文本，输出通用合同初审结果。"
        "请重点关注合同主体、付款条款、违约责任、解除条款、自动续约、争议解决、验收标准、保密条款、知识产权等风险。\n\n"
        f"合同文本：\n{parsed_text}"
    )


@dataclass
class AuditExecutionMeta:
    provider: str
    model: str
    fallback_used: bool = False
    attempts: int = 0


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
                    "title": "违约责任需要重点核查",
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


class OpenAIAuditService:
    def __init__(self) -> None:
        self.api_key = AUDIT_MODEL_API_KEY
        self.base_url = AUDIT_MODEL_BASE_URL
        self.model = AUDIT_MODEL_NAME
        self.timeout_seconds = AUDIT_MODEL_TIMEOUT_SECONDS
        self.max_retries = AUDIT_MODEL_MAX_RETRIES
        self.retry_backoff_seconds = AUDIT_MODEL_RETRY_BACKOFF_SECONDS
        self.max_input_chars = AUDIT_MODEL_MAX_INPUT_CHARS

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def analyze(self, parsed_text: str) -> dict:
        text = parsed_text.strip()
        if len(text) < 30:
            raise AuditError("AUDIT_EMPTY_RESULT", "未识别到有效合同内容，请检查后重试", 400)

        clipped_text = text[: self.max_input_chars]
        last_error: Exception | None = None
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                raw_result = self._call_responses_api(clipped_text)
                parsed_result = self._extract_json_payload(raw_result)
                normalized_result = normalize_audit_result(parsed_result)
                if normalized_result["total_risks"] <= 0:
                    raise AuditError("AUDIT_EMPTY_RESULT", "模型未返回有效审核结果，请稍后重试", 502)
                logger.info(
                    "audit model call succeeded model=%s attempt=%s total_risks=%s",
                    self.model,
                    attempt,
                    normalized_result["total_risks"],
                )
                return normalized_result
            except AuditError as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                logger.warning(
                    "audit model returned invalid result, retrying attempt=%s/%s code=%s",
                    attempt,
                    attempts,
                    exc.code,
                )
            except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "audit model request failed, retrying attempt=%s/%s error=%s",
                    attempt,
                    attempts,
                    exc,
                )
            time.sleep(self.retry_backoff_seconds * attempt)

        logger.exception("audit model call failed after retries", exc_info=last_error)
        if isinstance(last_error, AuditError):
            raise last_error
        raise AuditError("AUDIT_MODEL_UNAVAILABLE", "审核服务暂时不可用，请稍后重试", 502)

    def _call_responses_api(self, parsed_text: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": _build_user_prompt(parsed_text)}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "contract_audit_result",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "overall_message": {"type": "string"},
                            "risks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "title": {"type": "string"},
                                        "level": {"type": "string", "enum": ["high", "medium", "low"]},
                                        "reason": {"type": "string"},
                                        "suggestion": {"type": "string"},
                                    },
                                    "required": ["title", "level", "reason", "suggestion"],
                                },
                            },
                        },
                        "required": ["overall_message", "risks"],
                    },
                    "strict": True,
                }
            },
        }
        req = request.Request(
            url=f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_json_payload(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        output_text = response_payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return json.loads(output_text)

        for output_item in response_payload.get("output", []):
            content_items = output_item.get("content", [])
            for content_item in content_items:
                if content_item.get("type") in {"output_text", "text"}:
                    text = content_item.get("text")
                    if isinstance(text, str) and text.strip():
                        return json.loads(text)

        raise AuditError("AUDIT_EMPTY_RESULT", "模型未返回可解析的审核结果", 502)


class AuditService:
    def __init__(self) -> None:
        self.mock_service = MockAuditService()
        self.real_service = OpenAIAuditService()

    def analyze(self, parsed_text: str) -> dict:
        if self.real_service.is_configured():
            try:
                return self.real_service.analyze(parsed_text)
            except AuditError:
                if not AUDIT_ALLOW_MOCK_FALLBACK:
                    raise
                logger.warning("audit model failed, falling back to mock service")
            except Exception:
                if not AUDIT_ALLOW_MOCK_FALLBACK:
                    raise AuditError("AUDIT_MODEL_UNAVAILABLE", "审核服务暂时不可用，请稍后重试", 502)
                logger.exception("unexpected audit model error, falling back to mock service")
        else:
            logger.info("audit model api key not configured, using mock audit fallback")

        result = self.mock_service.analyze(parsed_text)
        result["overall_message"] = (
            f"{result['overall_message']} 当前结果由降级审核服务生成，建议配置真实模型后复核。"
        )
        return result
