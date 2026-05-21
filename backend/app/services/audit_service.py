import hashlib
import json
import logging
import socket
import time
from typing import Any
from urllib import error, request

from .. import database
from ..config import (
    AUDIT_ALLOW_MOCK_FALLBACK,
    AUDIT_MODEL_MAX_INPUT_CHARS,
    AUDIT_MODEL_MAX_OUTPUT_TOKENS,
    AUDIT_MODEL_MAX_RETRIES,
    AUDIT_MODEL_RETRY_BACKOFF_SECONDS,
    AUDIT_MODEL_TIMEOUT_SECONDS,
    AUDIT_PROFILE,
    AUDIT_PROVIDER,
    AUDIT_REQUIRE_CONTRACT_KEYWORDS,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_THINKING_DISABLED,
    LOG_LEVEL,
)
from ..exceptions import AuditError
from .result_formatter import MAX_CORE_RISKS, STRATEGY_VERSION, normalize_audit_result
from .text_parser import assess_text_readability, should_use_conservative_audit


logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


SYSTEM_PROMPT = """你是合同初审助手，只能输出一个 JSON 对象。

要求：
1. 只能基于给定合同原文判断，不要编造不存在的条款。
2. 输出格式必须是：
{
  "overall_message": "字符串",
  "risks": [
    {
      "title": "字符串",
      "level": "high|medium|low",
      "reason": "字符串",
      "suggestion": "字符串"
    }
  ]
}
3. 默认优先返回 3 条核心风险，可包含少量补充风险，但不要泛滥罗列。
4. 如果文本过短、可读性差或证据不足，只返回 1 到 2 条提醒，不要泛化推断。
5. 风险标题、原因、建议必须互相一致，且必须围绕合同条款本身。
6. 相似风险不要换不同说法重复表达。
"""


def _build_user_prompt(parsed_text: str) -> str:
    readability = assess_text_readability(parsed_text)
    return (
        "请审查下面合同文本，只输出 JSON。\n"
        "重点关注付款、验收、违约、续约、保密、知识产权、争议解决。\n"
        "如果原文没有直接证据，不要推断。\n"
        "优先输出最核心的 3 条风险，如有必要可增加少量补充风险。\n"
        f"文本可读性参考：{json.dumps(readability, ensure_ascii=False)}\n\n"
        f"合同文本：\n{parsed_text}"
    )


class MockAuditService:
    def analyze(self, parsed_text: str) -> dict:
        text = parsed_text.strip()
        readability = assess_text_readability(text)
        if len(text) < 30:
            raise AuditError("AUDIT_EMPTY_RESULT", "未识别到有效合同内容，请检查后重试", 400)

        if should_use_conservative_audit(parsed_text):
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
                    "title": "违约责任需重点核查",
                    "level": "high",
                    "reason": "合同提到了违约或赔偿，但责任边界、赔偿范围或上限不够清晰时，后续容易产生争议。",
                    "suggestion": "建议明确违约责任触发条件、赔偿范围、计算方式和责任上限。",
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
        if "验收" in text or "交付" in text:
            risks.append(
                {
                    "title": "验收标准可能缺失",
                    "level": "medium",
                    "reason": "如果验收标准、验收流程或验收期限不够明确，容易导致付款与履约争议。",
                    "suggestion": "建议补充验收标准、验收流程、验收期限及不合格处理方式。",
                }
            )
        if "保密" not in text and "confidential" not in lowered:
            risks.append(
                {
                    "title": "保密条款可能缺失",
                    "level": "medium",
                    "reason": "文本中未明显体现保密义务，商业信息或数据保护可能不够充分。",
                    "suggestion": "建议补充保密范围、保密期限、例外情形和违约责任。",
                }
            )

        if not risks:
            risks = [
                {
                    "title": "建议人工复核关键条款",
                    "level": "low",
                    "reason": "当前文本未识别出明显高频风险，但这并不代表合同不存在法律或商务风险。",
                    "suggestion": "建议重点复核付款、违约、解除、争议解决和知识产权相关条款。",
                }
            ]

        return normalize_audit_result(
            {
                "overall_message": "本次为通用合同初审结果，建议优先处理核心风险条款，复杂场景仍需专业法务复核。",
                "risks": risks[:5],
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
        self.max_output_tokens = AUDIT_MODEL_MAX_OUTPUT_TOKENS
        self.disable_thinking = DEEPSEEK_THINKING_DISABLED

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
            started = time.time()
            try:
                raw_result = self._call_chat_completions_api(clipped_text)
                parsed_result = self._extract_json_payload(raw_result)
                normalized_result = normalize_audit_result(parsed_result)
                self._validate_result_quality(normalized_result, clipped_text)
                logger.info(
                    "audit model call succeeded provider=deepseek profile=%s model=%s attempt=%s elapsed=%.2fs total_risks=%s core_risks=%s",
                    AUDIT_PROFILE,
                    self.model,
                    attempt,
                    time.time() - started,
                    normalized_result["total_risks"],
                    len(normalized_result["core_risks"]),
                )
                return normalized_result
            except AuditError as exc:
                last_error = exc
                logger.warning(
                    "deepseek audit error provider=deepseek profile=%s model=%s attempt=%s code=%s",
                    AUDIT_PROFILE,
                    self.model,
                    attempt,
                    exc.code,
                )
                if not self._is_retryable_audit_error(exc) or attempt >= attempts:
                    raise
            except error.HTTPError as exc:
                last_error = exc
                mapped_error = self._map_http_error(exc)
                logger.warning(
                    "deepseek http error provider=deepseek profile=%s model=%s attempt=%s status=%s",
                    AUDIT_PROFILE,
                    self.model,
                    attempt,
                    exc.code,
                )
                if mapped_error and not self._is_retryable_audit_error(mapped_error):
                    raise mapped_error from exc
                if attempt >= attempts:
                    if mapped_error:
                        raise mapped_error from exc
                    break
            except (error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "deepseek request failed provider=deepseek profile=%s model=%s attempt=%s error=%s",
                    AUDIT_PROFILE,
                    self.model,
                    attempt,
                    exc,
                )
                if attempt >= attempts:
                    break

            time.sleep(self.retry_backoff_seconds * attempt)

        logger.exception(
            "deepseek call failed after retries provider=deepseek profile=%s model=%s",
            AUDIT_PROFILE,
            self.model,
            exc_info=last_error,
        )
        if isinstance(last_error, AuditError):
            raise last_error
        raise AuditError("DEEPSEEK_TIMEOUT", "DeepSeek 审核超时，请稍后重试", 504)

    def _call_chat_completions_api(self, parsed_text: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(parsed_text)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
        if len(normalized_result["core_risks"]) > MAX_CORE_RISKS:
            raise AuditError("AUDIT_RESULT_OVERINFERRED", "DeepSeek 返回的核心风险数量超过当前上限，准备重试", 502)
        if not readability["is_readable"] and normalized_result["total_risks"] > 2:
            raise AuditError("AUDIT_RESULT_OVERINFERRED", "DeepSeek 在文本不可读场景下输出了过多风险，准备重试", 502)
        if len(parsed_text) < 150 and normalized_result["high_risks"] > 2:
            raise AuditError("AUDIT_RESULT_OVERINFERRED", "合同文本过短但高风险数量过多，准备重试", 502)
        if AUDIT_REQUIRE_CONTRACT_KEYWORDS and not _looks_like_contract_audit(normalized_result):
            raise AuditError("AUDIT_RESULT_DOMAIN_MISMATCH", "DeepSeek 返回内容与合同审核领域不匹配，准备重试", 502)

    def _map_http_error(self, exc: error.HTTPError) -> AuditError | None:
        if exc.code == 400:
            return AuditError("DEEPSEEK_BAD_REQUEST", "DeepSeek 请求参数不合法，请检查模型参数配置", 502)
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
            "AUDIT_RESULT_DOMAIN_MISMATCH",
            "DEEPSEEK_TIMEOUT",
            "DEEPSEEK_UNAVAILABLE",
            "DEEPSEEK_RATE_LIMITED",
        }


class AuditService:
    def __init__(self) -> None:
        self.mock_service = MockAuditService()
        self.deepseek_service = DeepSeekAuditService()
        self.strategy_version = STRATEGY_VERSION

    def build_text_hash(self, parsed_text: str) -> str:
        return hashlib.sha256(parsed_text.strip().encode("utf-8")).hexdigest()

    def analyze(self, parsed_text: str, *, user_id: str | None = None) -> dict:
        provider = AUDIT_PROVIDER or "deepseek"
        readability = assess_text_readability(parsed_text)
        text_hash = self.build_text_hash(parsed_text)

        if user_id:
            reusable = database.find_reusable_audit_result(
                user_id=user_id,
                text_hash=text_hash,
                strategy_version=self.strategy_version,
            )
            if reusable:
                result = reusable["result_json"]
                result["overall_message"] = _append_reuse_hint(result["overall_message"])
                logger.info(
                    "audit result reused provider=%s strategy=%s source_task=%s",
                    provider,
                    self.strategy_version,
                    reusable["task_id"],
                )
                return result

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


def _looks_like_contract_audit(result: dict) -> bool:
    text = " ".join(
        [
            str(result.get("overall_message", "")),
            *[
                " ".join(
                    [
                        str(item.get("title", "")),
                        str(item.get("reason", "")),
                        str(item.get("suggestion", "")),
                    ]
                )
                for item in result.get("risks", [])
            ],
        ]
    ).lower()
    keywords = [
        "合同",
        "条款",
        "付款",
        "验收",
        "违约",
        "保密",
        "续约",
        "争议",
        "知识产权",
        "甲方",
        "乙方",
        "contract",
        "payment",
        "termination",
        "confidential",
        "intellectual property",
    ]
    return any(keyword.lower() in text for keyword in keywords)


def _append_reuse_hint(message: str) -> str:
    hint = "检测到相同内容，本次已复用最近一次标准化审核结果。"
    if hint in message:
        return message
    return f"{message} {hint}".strip()
