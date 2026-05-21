const { getRuntimeEnv } = require("../config/env");
const { getOrCreateAnonymousUserId } = require("../utils/storage");

const UPLOAD_RETRY_LIMIT = 2;
const UPLOAD_RETRY_DELAY_MS = 800;
const INLINE_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;
const CHUNK_UPLOAD_SIZE = 96 * 1024;

function getBaseURL() {
  return getRuntimeEnv().baseURL;
}

function getUserId() {
  return getOrCreateAnonymousUserId();
}

function getHeaders(extraHeaders, options) {
  const nextOptions = options || {};
  const headers = {
    "X-User-Id": getUserId(),
    ...(extraHeaders || {}),
  };

  if (nextOptions.includeJsonContentType !== false) {
    headers["Content-Type"] = "application/json";
  }

  return headers;
}

function unwrapResponse(response) {
  const { statusCode, data } = response;

  if (statusCode < 200 || statusCode >= 300) {
    const message = data && data.error && data.error.message ? data.error.message : "请求失败，请稍后重试";
    throw createBusinessError(message, data && data.error && data.error.code);
  }

  if (!data || data.success !== true) {
    const message = data && data.error && data.error.message ? data.error.message : "服务返回异常";
    throw createBusinessError(message, data && data.error && data.error.code);
  }

  return data.data;
}

function request({ url, method, data, header }) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getBaseURL()}${url}`,
      method,
      data,
      header: getHeaders(header),
      success: (response) => {
        try {
          resolve(unwrapResponse(response));
        } catch (error) {
          reject(error);
        }
      },
      fail: (error) => {
        console.error("[api.request] fail", {
          url: `${getBaseURL()}${url}`,
          method,
          error,
        });
        reject(classifyRequestFailure(error));
      },
    });
  });
}

function uploadFile(filePath) {
  return uploadFileWithRetry(filePath, 0);
}

function uploadFileWithRetry(filePath, attempt) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getBaseURL()}/api/v1/contracts/upload`,
      filePath,
      name: "file",
      header: getHeaders({}, { includeJsonContentType: false }),
      timeout: 120000,
      success: (response) => {
        try {
          const parsed = typeof response.data === "string" ? JSON.parse(response.data) : response.data;
          const data = unwrapResponse({
            statusCode: response.statusCode,
            data: parsed,
          });
          resolve(mapUploadResponse(data));
        } catch (error) {
          reject(error);
        }
      },
      fail: (error) => {
        const debugInfo = extractClientErrorInfo(error);
        console.error("[api.uploadFile] fail", {
          url: `${getBaseURL()}/api/v1/contracts/upload`,
          filePath,
          attempt,
          error,
          debugInfo,
        });
        const classifiedError = classifyUploadFailure(error);
        if (shouldRetryUpload(classifiedError, attempt)) {
          console.warn("[api.uploadFile] retry", {
            filePath,
            attempt,
            nextAttempt: attempt + 1,
            type: classifiedError.type,
            details: classifiedError.details,
          });
          delay(UPLOAD_RETRY_DELAY_MS * (attempt + 1))
            .then(() => uploadFileWithRetry(filePath, attempt + 1))
            .then(resolve)
            .catch(reject);
          return;
        }
        reject(classifiedError);
      },
    });
  });
}

function uploadFileInline(filePath, fileName) {
  return new Promise((resolve, reject) => {
    wx.getFileSystemManager().readFile({
      filePath,
      success: (readResult) => {
        const fileContent = readResult && readResult.data;
        let base64 = "";

        if (typeof fileContent === "string") {
          base64 = fileContent;
        } else if (fileContent && typeof wx.arrayBufferToBase64 === "function") {
          base64 = wx.arrayBufferToBase64(fileContent);
        }

        if (!base64) {
          reject(createTypedError("文件内容读取失败，请重新选择文件后再试。", "upload-inline-read"));
          return;
        }

        const byteLength = typeof fileContent === "string"
          ? estimateBase64DecodedBytes(fileContent)
          : (fileContent.byteLength || 0);

        if (byteLength > INLINE_UPLOAD_MAX_BYTES) {
          reject(createBusinessError("文件大小不能超过 10MB，请压缩后重新上传。", "UPLOAD_FILE_TOO_LARGE"));
          return;
        }

        uploadInlineBase64(fileName, base64)
          .then(resolve)
          .catch((inlineError) => {
            console.error("[api.uploadFileInline] inline fail, switching to chunk upload", {
              filePath,
              fileName,
              error: inlineError,
            });
            uploadFileInChunks(fileName, base64)
              .then(resolve)
              .catch(reject);
          });
      },
      fail: (error) => {
        console.error("[api.uploadFileInline] read fail", {
          filePath,
          fileName,
          error,
        });
        reject(classifyRequestFailure(error));
      },
    });
  });
}

function uploadInlineBase64(fileName, base64) {
  return request({
    url: "/api/v1/contracts/upload-inline",
    method: "POST",
    data: {
      file_name: fileName,
      file_content_base64: base64,
    },
  }).then(mapUploadResponse);
}

async function uploadFileInChunks(fileName, base64) {
  const uploadId = createUploadId();
  const totalChunks = Math.ceil(base64.length / CHUNK_UPLOAD_SIZE);

  for (let index = 0; index < totalChunks; index += 1) {
    const start = index * CHUNK_UPLOAD_SIZE;
    const chunk = base64.slice(start, start + CHUNK_UPLOAD_SIZE);
    await request({
      url: "/api/v1/contracts/upload-chunk",
      method: "POST",
      data: {
        upload_id: uploadId,
        file_name: fileName,
        chunk_index: index,
        total_chunks: totalChunks,
        chunk_base64: chunk,
      },
    });
  }

  return request({
    url: "/api/v1/contracts/upload-chunk/complete",
    method: "POST",
    data: {
      upload_id: uploadId,
      file_name: fileName,
      total_chunks: totalChunks,
    },
  }).then(mapUploadResponse);
}

function createUploadId() {
  return `wx_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function submitText(text) {
  return request({
    url: "/api/v1/contracts/text",
    method: "POST",
    data: { text },
  }).then(mapTextResponse);
}

function getPreview(taskId) {
  return request({
    url: `/api/v1/contracts/${taskId}/preview`,
    method: "GET",
  }).then(mapPreviewResponse);
}

function startAudit(taskId) {
  return request({
    url: `/api/v1/contracts/${taskId}/audit`,
    method: "POST",
  }).then(mapStartAuditResponse);
}

function getAuditResult(taskId) {
  return request({
    url: `/api/v1/contracts/${taskId}/result`,
    method: "GET",
  }).then(mapAuditResultResponse);
}

function listHistory() {
  return request({
    url: "/api/v1/contracts/history",
    method: "GET",
  }).then(mapHistoryResponse);
}

function deleteHistory(taskId) {
  return request({
    url: `/api/v1/contracts/${taskId}`,
    method: "DELETE",
  }).then((data) => ({
    taskId: data.task_id,
    deleted: data.deleted,
  }));
}

function createBusinessError(message, code) {
  const error = new Error(message);
  error.type = "business";
  error.code = code || "";
  return error;
}

function createTypedError(message, type, details) {
  const error = new Error(message);
  error.type = type;
  error.details = details || "";
  return error;
}

function classifyRequestFailure(error) {
  const errMsg = normalizeText(error && error.errMsg).toLowerCase();

  if (isDomainOrHttpsFailure(errMsg)) {
    return createTypedError(
      "当前网络请求未通过，请确认小程序已配置合法 HTTPS 域名，且证书与服务均可正常访问。",
      "domain",
      errMsg
    );
  }

  if (isTimeoutFailure(errMsg)) {
    return createTypedError("网络请求超时，请检查网络后重试。", "network-timeout", errMsg);
  }

  return createTypedError("网络连接失败，请检查当前网络后重试。", "network", errMsg);
}

function classifyUploadFailure(error) {
  const debugInfo = extractClientErrorInfo(error);
  const errMsg = normalizeText(debugInfo.errMsg).toLowerCase();

  if (isDomainOrHttpsFailure(errMsg)) {
    return createTypedError(
      "文件上传未通过，请确认小程序已配置合法 HTTPS 域名，且线上证书与上传服务可正常访问。",
      "domain",
      errMsg
    );
  }

  if (!errMsg) {
    return createTypedError(
      "文件上传未发出，请优先检查小程序后台是否已单独配置 uploadFile 合法域名，并确认当前网络允许访问该 HTTPS 域名。",
      "upload-config",
      JSON.stringify(debugInfo)
    );
  }

  if (isTimeoutFailure(errMsg)) {
    return createTypedError("文件上传超时，请检查网络后重新上传。", "network-timeout", errMsg);
  }

  if (isConnectionFailure(errMsg)) {
    return createTypedError("文件上传连接失败，请检查当前网络后重试。", "network", errMsg);
  }

  return createTypedError("文件上传失败，请稍后重试。", "upload", errMsg);
}

function shouldRetryUpload(error, attempt) {
  if (!error || attempt >= UPLOAD_RETRY_LIMIT) {
    return false;
  }

  if (error.type === "network-timeout") {
    return true;
  }

  if (error.type !== "network") {
    return false;
  }

  const details = normalizeText(error.details).toLowerCase();
  return [
    "err_connection_reset",
    "connection reset",
    "errcode:-101",
    "cronet_error_code:-101",
    "software caused connection abort",
  ].some((keyword) => details.includes(keyword));
}

function isDomainOrHttpsFailure(errMsg) {
  return [
    "url not in domain list",
    "url scheme is invalid",
    "ssl",
    "certificate",
    "cert",
    "tls",
    "https",
  ].some((keyword) => errMsg.includes(keyword));
}

function isTimeoutFailure(errMsg) {
  return errMsg.includes("timeout");
}

function isConnectionFailure(errMsg) {
  return [
    "request:fail",
    "uploadfile:fail",
    "fail connect",
    "unable to resolve host",
    "network",
  ].some((keyword) => errMsg.includes(keyword));
}

function estimateBase64DecodedBytes(base64Text) {
  const normalized = String(base64Text || "").replace(/\s/g, "");
  if (!normalized) return 0;
  const padding = normalized.endsWith("==") ? 2 : normalized.endsWith("=") ? 1 : 0;
  return Math.floor((normalized.length * 3) / 4) - padding;
}

function mapUploadResponse(data) {
  return {
    taskId: data.task_id,
    fileId: data.file_id,
    fileName: normalizeText(data.file_name),
    uploadStatus: data.upload_status || "uploaded",
    parseStatus: data.parse_status || "parsing",
    previewText: normalizeText(data.preview_text),
    charCount: data.char_count,
    pageCount: data.page_count || null,
  };
}

function mapTextResponse(data) {
  return {
    taskId: data.task_id,
    status: data.status,
    previewText: normalizeText(data.preview_text),
    charCount: data.char_count,
  };
}

function mapPreviewResponse(data) {
  return {
    taskId: data.task_id,
    sourceType: data.source_type,
    fileName: normalizeText(data.file_name),
    parsedText: normalizeText(data.parsed_text),
    previewText: normalizeText(data.preview_text),
    charCount: data.char_count,
    status: data.status || data.parse_status || "parsed",
    pageCount: data.page_count || null,
    errorCode: data.error_code || "",
    errorMessage: normalizeText(data.error_message),
  };
}

function mapStartAuditResponse(data) {
  return {
    taskId: data.task_id,
    auditJobId: data.audit_job_id,
    status: data.status,
  };
}

function mapAuditResultResponse(data) {
  const legacyRisks = Array.isArray(data.risks) ? data.risks : (data.result ? data.result.risks || [] : []);
  const coreRiskSource = Array.isArray(data.core_risks) ? data.core_risks : [];
  const additionalRiskSource = Array.isArray(data.additional_risks) ? data.additional_risks : [];

  const normalizedLegacyRisks = normalizeRiskItems(legacyRisks);
  const normalizedCoreRisks = normalizeRiskItems(coreRiskSource);
  const normalizedAdditionalRisks = normalizeRiskItems(additionalRiskSource);

  const usesSplitRiskStructure = normalizedCoreRisks.length || normalizedAdditionalRisks.length;
  const coreRisks = usesSplitRiskStructure ? normalizedCoreRisks : normalizedLegacyRisks.slice(0, 3);
  const additionalRisks = usesSplitRiskStructure ? normalizedAdditionalRisks : normalizedLegacyRisks.slice(3);
  const allRisks = coreRisks.concat(additionalRisks);

  const summarySource = data.summary || (data.result
    ? {
        total_risks: data.result.total_risks,
        high_risks: data.result.high_risks,
        medium_risks: data.result.medium_risks,
        low_risks: data.result.low_risks,
        overall_message: data.result.overall_message,
      }
    : null);

  return {
    taskId: data.task_id,
    status: data.status,
    errorCode: data.error_code,
    errorMessage: normalizeText(data.error_message),
    summary: normalizeSummary(summarySource, allRisks),
    risks: allRisks,
    coreRisks,
    additionalRisks,
    reusedRecentResult: Boolean(
      data.reused_recent_result ||
      data.reused_result ||
      data.result_reused ||
      data.hit_cache
    ),
  };
}

function normalizeRiskItems(risksSource) {
  return (risksSource || [])
    .filter((item) => item && (item.title || item.reason || item.suggestion))
    .map((item, index) => normalizeRiskItem(item, index))
    .sort(compareRiskItems);
}

function normalizeRiskItem(item, index) {
  const rawTitle = normalizeText(item.title) || `风险提示 ${index + 1}`;
  const normalizedTitle = normalizeRiskTitle(rawTitle);

  return {
    title: normalizedTitle,
    level: normalizeRiskLevel(item.level),
    reason: normalizeSentence(
      normalizeText(item.reason) || "已识别到潜在风险，但当前未返回完整原因说明。"
    ),
    suggestion: normalizeSuggestion(
      normalizeText(item.suggestion) || "建议结合合同原文继续人工复核，并补充更明确的修改方案。"
    ),
  };
}

function mapHistoryResponse(data) {
  return {
    items: (data.items || []).map((item) => ({
      id: item.id || item.task_id,
      taskId: item.task_id,
      title: normalizeText(item.title) || normalizeText(item.file_name) || "粘贴合同内容",
      sourceType: item.source_type,
      fileName: normalizeText(item.file_name),
      status: item.status,
      statusText: normalizeText(item.status_text) || mapStatusText(item.status),
      totalRisks: toSafeNumber(item.total_risks, 0),
      highRisks: toSafeNumber(item.high_risks, 0),
      mediumRisks: toSafeNumber(item.medium_risks, 0),
      lowRisks: toSafeNumber(item.low_risks, 0),
      overallMessage: normalizeText(item.overall_message),
      createdAt: item.created_at,
      updatedAt: item.updated_at,
      completedAt: item.completed_at || "",
      displayTime: formatDateTime(item.completed_at || item.updated_at || item.created_at),
    })),
  };
}

function mapStatusText(status) {
  const statusMap = {
    uploaded: "已上传",
    parsing: "解析中",
    parsed: "已解析",
    analyzing: "审核中",
    success: "审核完成",
    failed: "审核失败",
  };
  return statusMap[status] || status || "未知状态";
}

function normalizeSummary(summarySource, normalizedRisks) {
  const fallbackMessage = normalizedRisks.length
    ? "已完成合同初审，请结合业务场景继续复核风险内容。"
    : "已完成合同初审，当前未识别到明确风险项，建议结合原文人工复核。";
  const countedSummary = buildSummaryFromRisks(
    normalizedRisks,
    normalizeText(summarySource && summarySource.overall_message) || fallbackMessage
  );

  if (!summarySource) {
    return countedSummary;
  }

  const totalRisks = toSafeNumber(summarySource.total_risks, countedSummary.total_risks);
  const highRisks = toSafeNumber(summarySource.high_risks, countedSummary.high_risks);
  const mediumRisks = toSafeNumber(summarySource.medium_risks, countedSummary.medium_risks);
  const lowRisks = toSafeNumber(summarySource.low_risks, countedSummary.low_risks);
  const inconsistent = totalRisks !== normalizedRisks.length || highRisks + mediumRisks + lowRisks !== normalizedRisks.length;

  return {
    total_risks: inconsistent ? countedSummary.total_risks : totalRisks,
    high_risks: inconsistent ? countedSummary.high_risks : highRisks,
    medium_risks: inconsistent ? countedSummary.medium_risks : mediumRisks,
    low_risks: inconsistent ? countedSummary.low_risks : lowRisks,
    overall_message: normalizeText(summarySource.overall_message) || countedSummary.overall_message,
  };
}

function buildSummaryFromRisks(risks, overallMessage) {
  return {
    total_risks: risks.length,
    high_risks: risks.filter((item) => item.level === "high").length,
    medium_risks: risks.filter((item) => item.level === "medium").length,
    low_risks: risks.filter((item) => item.level === "low").length,
    overall_message: overallMessage,
  };
}

function normalizeRiskLevel(level) {
  const text = normalizeText(level).toLowerCase();
  if (["high", "h", "严重", "高", "高风险"].includes(text)) return "high";
  if (["medium", "mid", "m", "中", "中风险"].includes(text)) return "medium";
  if (["low", "l", "低", "低风险"].includes(text)) return "low";
  return "medium";
}

function normalizeRiskTitle(title) {
  const text = normalizeText(title);
  const canonicalMap = [
    { pattern: /(付款|支付).*(不明|模糊|不清|未明确|付款条件不明|支付约定不清)/i, title: "付款条款不明确" },
    { pattern: /(违约责任).*(不明|模糊|不清|缺失)|责任缺失/i, title: "违约责任不明确" },
    { pattern: /(自动续约|续签|续费).*(风险|未明确|不清)/i, title: "自动续约风险" },
    { pattern: /(保密).*(缺失|不足|不明|不清)/i, title: "保密条款不完善" },
    { pattern: /(争议解决|管辖|仲裁|法院).*(不明|不清|风险)/i, title: "争议解决条款不明确" },
    { pattern: /(解约|解除).*(不明|不清|模糊|风险)/i, title: "解约条款不明确" },
    { pattern: /(验收标准|验收).*(不明|不清|缺失|模糊)/i, title: "验收标准不明确" },
    { pattern: /(知识产权|成果归属).*(不明|不清|缺失|模糊)/i, title: "知识产权归属不明确" },
  ];

  const matched = canonicalMap.find((item) => item.pattern.test(text));
  return matched ? matched.title : text;
}

function normalizeSuggestion(text) {
  const normalized = normalizeSentence(text);
  if (!normalized) {
    return "建议结合合同原文继续人工复核，并补充更明确的修改方案。";
  }

  if (/^建议/.test(normalized)) {
    return normalized;
  }

  return `建议${normalized}`;
}

function normalizeSentence(text) {
  const normalized = normalizeText(text).replace(/[；;]/g, "，");
  if (!normalized) return "";
  if (/[。！？!?]$/.test(normalized)) {
    return normalized;
  }
  return `${normalized}。`;
}

function compareRiskItems(a, b) {
  const levelDiff = getRiskWeight(b.level) - getRiskWeight(a.level);
  if (levelDiff !== 0) return levelDiff;

  const titleDiff = getRiskTitleWeight(a.title) - getRiskTitleWeight(b.title);
  if (titleDiff !== 0) return titleDiff;

  return a.title.localeCompare(b.title, "zh-CN");
}

function getRiskTitleWeight(title) {
  const rules = [
    { pattern: /付款/, weight: 1 },
    { pattern: /违约责任/, weight: 2 },
    { pattern: /解约/, weight: 3 },
    { pattern: /自动续约/, weight: 4 },
    { pattern: /验收标准/, weight: 5 },
    { pattern: /保密/, weight: 6 },
    { pattern: /知识产权/, weight: 7 },
    { pattern: /争议解决/, weight: 8 },
  ];

  const matched = rules.find((item) => item.pattern.test(title));
  return matched ? matched.weight : 99;
}

function getRiskWeight(level) {
  if (level === "high") return 3;
  if (level === "medium") return 2;
  return 1;
}

function toSafeNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : fallback;
}

function normalizeText(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/\r\n/g, "\n").replace(/\u0000/g, "").trim();
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function extractClientErrorInfo(error) {
  if (!error || typeof error !== "object") {
    return {
      errMsg: normalizeText(error),
    };
  }

  const plain = {};
  Object.getOwnPropertyNames(error).forEach((key) => {
    plain[key] = error[key];
  });

  return {
    errMsg: normalizeText(error.errMsg || plain.errMsg),
    errCode: normalizeText(error.errCode || plain.errCode),
    errno: normalizeText(error.errno || plain.errno),
    message: normalizeText(error.message || plain.message),
    stack: normalizeText(error.stack || plain.stack),
    raw: plain,
  };
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hour = `${date.getHours()}`.padStart(2, "0");
  const minute = `${date.getMinutes()}`.padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

module.exports = {
  getBaseURL,
  getHeaders,
  uploadFile,
  uploadFileInline,
  submitText,
  getPreview,
  startAudit,
  getAuditResult,
  listHistory,
  deleteHistory,
};
