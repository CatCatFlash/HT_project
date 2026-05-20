import json
import logging
import socket
import time
from typing import Any
from urllib import error, request

from ..config import (
    AUDIT_ALLOW_MOCK_FALLBACK,
    AUDIT_MODEL_MAX_INPUT_CHARS,
    AUDIT_MODEL_MAX_RETRIES,
    AUDIT_MODEL_RETRY_BACKOFF_SECONDS,
    AUDIT_MODEL_TIMEOUT_SECONDS,
    AUDIT_PROVIDER,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LOG_LEVEL,
)
from ..exceptions import AuditError
from .result_formatter import normalize_audit_result
from .text_parser import assess_text_readability


logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


SYSTEM_PROMPT = """你是 AI 合同初审助手的后端审核服务，只能输出结构化 JSON。

你的任务是基于合同原文做通用初审，不得输出法律结论，不得编造合同中不存在的内容。

必须遵守以下规则：
1. 只输出一个 JSON 对象，不要输出 markdown、代码块或额外说明。
2. JSON 顶层必须包含：
   - overall_message: string
   - risks: array
3. risks 中每一项必须包含：
   - title: string
   - level: high | medium | low
   - reason: string
   - suggestion: string
4. 只有在合同原文中能找到直接依据时，才输出对应风险；证据不足时，不要过度推断。
5. 如果文本明显乱码、缺失严重、过短或无法支撑正常审阅，不要泛化罗列大量风险。
   这种情况下只返回 1 到 2 个低风险或中风险提醒，明确说明“文本可读性不足”或“信息不足”。
6. 风险名称、原因、建议必须互相一致：
   - title 说的是什么风险
   - reason 就解释该风险为什么成立
   - suggestion 就给出对应的补充或修改建议
7. overall_message 要准确反映文本质量与整体判断，不要夸大结论。
"""


def _build_user_prompt(parsed_text: str) -> str:
    readability = assess_text_readability(parsed_text)
    return (
        "请根据下面的合同文本输出通用合同初审结果。\n"
        "请优先关注合同主体、付款条款、违约责任、解除条款、自动续约、争议解决、验收标准、保密条款、知识产权等风险。\n"
        "如果文本可读性差、内容缺失严重或证据不足，请减少风险数量，并明确说明原因。\n"
        "请直接输出 JSON 对象。\n\n"
        f"文本可读性参考：{json.dumps(readability, ensure_ascii=False)}\n\n"
        f"合同文本：\n{parsed_text}"
    )


class MockAuditService:
    def analyze(self, parsed_text: str) -> dict:
        text = parsed_text.strip()
        readability = assess_text_readability(text)
        if len(text) < 30:
            raise AuditError("AUDIT_EMPTY_RESULT", "未识别到有效合同内容，请检查后重试", 400)

        if not readability["is_readable"]:
            return normalize_audit_result(
                {
                    "overall_message": "合同文本可读性较差，当前无法稳定识别关键条款，建议先修复文本后再发起审核。",
                    "risks": [
                        {
                            "title": "合同文本可读性不足",
                            "level": "medium",
                            "reason": "当前文本中存在较多乱码、问号占位或内容缺失，无法作为稳定的审核依据。",
                            "suggestion": "建议重新导出原始合同，优先上传文本可复制的 PDF 或 DOCX，必要时改为直接粘贴纯文本。",
                        }
                    ],
                }
            )

        risks: list[dict[str, str]] = []
        lowered = text.lower()

        if "违约" in text or "赔偿" in text:
            risks.append(
                {
                    "title": "违约责任需要重点核查",
                    "level": "high",
                    "reason": "合同提到了违约或赔偿，但若责任边界、赔偿范围或上限不清晰，后续容易产生争议。",
                    "suggestion": "建议明确违约责任触发条件、赔偿范围、计算方式和责任上限，避免责任明显失衡。",
                }
            )
        if "付款" in text or "支付" in text:
            risks.append(
                {
                    "title": "付款条款可能不够明确",
                    "level": "medium",
                    "reason": "付款节点、发票条件或逾期付款责任如果表述模糊，容易影响履约和结算。",
                    "suggestion": "建议补充付款时间、付款条件、发票要求、账户信息以及逾期付款责任。",
                }
            )
        if "自动续约" in text or "续签" in text:
            risks.append(
                {
                    "title": "存在自动续约风险",
                    "level": "medium",
                    "reason": "自动续约条款可能导致一方在未充分留意的情况下继续承担合同义务。",
                    "suggestion": "建议增加续约提醒和通知期限，并明确书面拒绝续约的操作方式。",
                }
            )
        if "争议" in text or "仲裁" in text or "法院" in text:
            risks.append(
                {
                    "title": "争议解决条款需要确认",
                    "level": "low",
                    "reason": "争议解决地、管辖法院或仲裁机构若明显偏向对方，会增加后续维权成本。",
                    "suggestion": "建议确认争议解决方式、适用法律和管辖地是否合理，尽量选择可接受地点。",
                }
            )
        if "保密" not in text and "confidential" not in lowered:
            risks.append(
                {
                    "title": "保密条款可能缺失",
                    "level": "medium",
                    "reason": "文本中未明显体现保密义务，商业信息、报价或数据保护可能不够充分。",
                    "suggestion": "建议补充保密范围、保密期限、例外情形和违约责任。",
                }
            )

        if not risks:
            risks = [
                {
                    "title": "建议人工复核关键条款",
                    "level": "low",
                    "reason": "当前文本未识别出明显高频风险，但这并不代表合同不存在法律或商务风险。",
                    "suggestion": "建议重点复核合同主体、付款、违约、解除、争议解决和知识产权相关条款。",
                }
            ]

        return normalize_audit_result(
            {
                "overall_message": "本次为通用合同初审结果，建议优先处理高风险条款，复杂场景仍需专业法务复核。",
                "risks": risks,
            }
        )


class DeepSeekAuditService:
    def __init__(self) -> None:
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        self.model = DEEPSEEK_MODEL
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
                raw_result = self._call_chat_completions_api(clipped_text)
                parsed_result = self._extract_json_payload(raw_result)
                normalized_result = normalize_audit_result(parsed_result)
                self._validate_result_quality(normalized_result, clipped_text)
                logger.info(
                    "audit model call succeeded provider=deepseek model=%s attempt=%s total_risks=%s",
                    self.model,
                    attempt,
                    normalized_result["total_risks"],
                )
                return normalized_result
            except AuditError as exc:
                last_error = exc
                if not self._is_retryable_audit_error(exc) or attempt >= attempts:
                    raise
                logger.warning(
                    "deepseek returned retryable result, retrying attempt=%s/%s code=%s",
                    attempt,
                    attempts,
                    exc.code,
                )
            except error.HTTPError as exc:
                last_error = exc
                mapped_error = self._map_http_error(exc)
                if mapped_error and not self._is_retryable_audit_error(mapped_error):
                    raise mapped_error from exc
                if attempt >= attempts:
                    if mapped_error:
                        raise mapped_error from exc
                    break
                logger.warning(
                    "deepseek request failed, retrying attempt=%s/%s status=%s",
                    attempt,
                    attempts,
                    exc.code,
                )
            except (error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "deepseek request failed, retrying attempt=%s/%s error=%s",
                    attempt,
                    attempts,
                    exc,
                )
            time.sleep(self.retry_backoff_seconds * attempt)

        logger.exception("deepseek call failed after retries", exc_info=last_error)
        if isinstance(last_error, AuditError):
            raise last_error
        raise AuditError("DEEPSEEK_TIMEOUT", "DeepSeek 审核超时，请稍后重试", 504)

    def _call_chat_completions_api(self, parsed_text: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(parsed_text)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 1400,
            "temperature": 0.2,
        }
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
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
        choices = response_payload.get("choices") or []
        if not choices:
            raise AuditError("AUDIT_EMPTY_RESULT", "DeepSeek 未返回任何候选结果", 502)
        content = (((choices[0] or {}).get("message") or {}).get("content")) or ""
        if not isinstance(content, str) or not content.strip():
            raise AuditError("AUDIT_EMPTY_RESULT", "DeepSeek 未返回可解析的审核结果", 502)
        return json.loads(content)

    def _validate_result_quality(self, normalized_result: dict, parsed_text: str) -> None:
        readability = assess_text_readability(parsed_text)
        if normalized_result["total_risks"] <= 0:
            raise AuditError("AUDIT_EMPTY_RESULT", "DeepSeek 未返回有效审核结果，请稍后重试", 502)
        if not readability["is_readable"] and normalized_result["total_risks"] > 2:
            raise AuditError("AUDIT_RESULT_OVERINFERRED", "DeepSeek 在文本不可读场景下输出了过多风险，准备重试", 502)
        if len(parsed_text) < 150 and normalized_result["high_risks"] > 2:
            raise AuditError("AUDIT_RESULT_OVERINFERRED", "合同文本过短但高风险数量过多，准备重试", 502)

    def _map_http_error(self, exc: error.HTTPError) -> AuditError | None:
        if exc.code == 401:
            return AuditError("DEEPSEEK_AUTH_INVALID", "DeepSeek 鉴权失败，请检查 API Key", 502)
        if exc.code == 408:
            return AuditError("DEEPSEEK_TIMEOUT", "DeepSeek 审核超时，请稍后重试", 504)
        if exc.code == 429:
            return AuditError("DEEPSEEK_RATE_LIMITED", "DeepSeek 请求过于频繁，请稍后重试", 429)
        if exc.code in {500, 502, 503, 504}:
            return AuditError("DEEPSEEK_UNAVAILABLE", "DeepSeek 审核服务暂时不可用，请稍后重试", 502)
        return None

    def _is_retryable_audit_error(self, exc: AuditError) -> bool:
        return exc.code in {
            "AUDIT_EMPTY_RESULT",
            "AUDIT_RESULT_OVERINFERRED",
            "DEEPSEEK_TIMEOUT",
            "DEEPSEEK_UNAVAILABLE",
            "DEEPSEEK_RATE_LIMITED",
        }


class AuditService:
    def __init__(self) -> None:
        self.mock_service = MockAuditService()
        self.deepseek_service = DeepSeekAuditService()

    def analyze(self, parsed_text: str) -> dict:
        provider = AUDIT_PROVIDER or "deepseek"
        readability = assess_text_readability(parsed_text)
        if provider != "deepseek":
            logger.warning("unsupported audit provider=%s, falling back to mock", provider)
            return self._mock_result(parsed_text, "当前未启用 DeepSeek，已降级到 mock 审核。")

        if not readability["is_readable"]:
            logger.warning("parsed text readability is poor, using conservative mock fallback")
            return self._mock_result(parsed_text, "检测到文本可读性较差，本次改用保守兜底结果，请先修复原文后再重试。")

        if self.deepseek_service.is_configured():
            try:
                return self.deepseek_service.analyze(parsed_text)
            except AuditError as exc:
                if not AUDIT_ALLOW_MOCK_FALLBACK:
                    raise
                logger.warning("deepseek failed code=%s, falling back to mock", exc.code)
                return self._mock_result(
                    parsed_text,
                    f"DeepSeek 调用失败，已自动降级到 mock 审核。失败原因：{exc.code}",
                )
            except Exception:
                if not AUDIT_ALLOW_MOCK_FALLBACK:
                    raise AuditError("DEEPSEEK_UNAVAILABLE", "DeepSeek 审核服务暂时不可用，请稍后重试", 502)
                logger.exception("unexpected deepseek error, falling back to mock")
                return self._mock_result(parsed_text, "DeepSeek 调用出现异常，已自动降级到 mock 审核。")

        logger.warning("deepseek api key not configured, using mock audit fallback")
        return self._mock_result(parsed_text, "当前未配置 DeepSeek API Key，已降级到 mock 审核。")

    def _mock_result(self, parsed_text: str, suffix: str) -> dict:
        result = self.mock_service.analyze(parsed_text)
        result["overall_message"] = f"{result['overall_message']} {suffix}"
        return result
