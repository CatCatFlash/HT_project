const DEFAULT_BASE_URL = "http://127.0.0.1:8010";
const DEFAULT_USER_ID = "demo-user";

function getBaseURL() {
  return DEFAULT_BASE_URL;
}

function getHeaders(extraHeaders) {
  return {
    "Content-Type": "application/json",
    "X-User-Id": DEFAULT_USER_ID,
    ...(extraHeaders || {}),
  };
}

function unwrapResponse(response) {
  const { statusCode, data } = response;
  if (statusCode < 200 || statusCode >= 300) {
    const message = data && data.error && data.error.message ? data.error.message : "请求失败，请稍后重试";
    throw new Error(message);
  }

  if (!data || data.success !== true) {
    const message = data && data.error && data.error.message ? data.error.message : "服务返回异常";
    throw new Error(message);
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
      fail: () => {
        reject(new Error("无法连接后端服务，请确认本地接口已启动且 baseURL 配置正确。"));
      },
    });
  });
}

function uploadFile(filePath) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getBaseURL()}/api/v1/contracts/upload`,
      filePath,
      name: "file",
      header: {
        "X-User-Id": DEFAULT_USER_ID,
      },
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
      fail: () => {
        reject(new Error("文件上传失败，请检查网络或后端服务状态。"));
      },
    });
  });
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

function mapUploadResponse(data) {
  return {
    taskId: data.task_id,
    fileId: data.file_id,
    fileName: data.file_name,
    uploadStatus: data.upload_status,
    parseStatus: data.parse_status,
    previewText: data.preview_text,
    charCount: data.char_count,
    pageCount: data.page_count || null,
  };
}

function mapTextResponse(data) {
  return {
    taskId: data.task_id,
    status: data.status,
    previewText: data.preview_text,
    charCount: data.char_count,
  };
}

function mapPreviewResponse(data) {
  return {
    taskId: data.task_id,
    sourceType: data.source_type,
    fileName: data.file_name || "",
    parsedText: data.parsed_text,
    previewText: data.preview_text,
    charCount: data.char_count,
    status: data.status,
    pageCount: data.page_count || null,
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
  const summarySource = data.summary || (data.result
    ? {
        total_risks: data.result.total_risks,
        high_risks: data.result.high_risks,
        medium_risks: data.result.medium_risks,
        low_risks: data.result.low_risks,
        overall_message: data.result.overall_message,
      }
    : null);
  const risksSource = data.risks || (data.result ? data.result.risks || [] : []);

  return {
    taskId: data.task_id,
    status: data.status,
    errorCode: data.error_code,
    errorMessage: data.error_message,
    summary: summarySource,
    risks: risksSource,
  };
}

function mapHistoryResponse(data) {
  return {
    items: (data.items || []).map((item) => ({
      id: item.id || item.task_id,
      taskId: item.task_id,
      title: item.title || item.file_name || "粘贴合同内容",
      sourceType: item.source_type,
      fileName: item.file_name || "",
      status: item.status,
      statusText: item.status_text || item.status,
      totalRisks: item.total_risks || 0,
      highRisks: item.high_risks || 0,
      mediumRisks: item.medium_risks || 0,
      lowRisks: item.low_risks || 0,
      overallMessage: item.overall_message || "",
      createdAt: item.created_at,
      updatedAt: item.updated_at,
      completedAt: item.completed_at || "",
    })),
  };
}

module.exports = {
  getBaseURL,
  getHeaders,
  uploadFile,
  submitText,
  getPreview,
  startAudit,
  getAuditResult,
  listHistory,
  deleteHistory,
};
