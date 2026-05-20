# AI合同初审助手 V1 后端

## 技术栈

- FastAPI
- SQLite
- 本地文件存储
- `pypdf` / `python-docx` 文本提取
- 真实大模型审核服务接入
- mock 审核兜底

## 目录结构

```text
backend/
  app/
    routers/
    services/
    config.py
    database.py
    exceptions.py
    main.py
    models.py
    schemas.py
```

## 启动方式

```powershell
cd D:\HT_project\HT_project\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
```

接口地址：
- Swagger UI: `http://127.0.0.1:8010/docs`
- 健康检查: `http://127.0.0.1:8010/health`

## 当前 V1 接口

- `POST /api/v1/contracts/upload`
- `POST /api/v1/contracts/text`
- `GET /api/v1/contracts/{task_id}/preview`
- `POST /api/v1/contracts/{task_id}/audit`
- `GET /api/v1/contracts/{task_id}/result`
- `GET /api/v1/contracts/history`
- `DELETE /api/v1/contracts/{task_id}`

## 联调约定

- 当前通过请求头 `X-User-Id` 区分用户历史记录，联调阶段可固定传 `demo-user`
- 当前默认联调地址是 `http://127.0.0.1:8010`
- 文件上传稳定支持文本型 `pdf` 和 `docx`
- `doc` 文件会返回明确降级提示，建议前端提示用户转成 `docx`
- 历史记录接口已补充 `id`、`title`、`status_text`、`completed_at`
- 审核结果接口除 `result` 外，也会返回 `summary` 和 `risks` 兼容字段

## 真实模型配置

后端已支持通过环境变量接入真实大模型审核服务：

```powershell
$env:OPENAI_API_KEY="your_key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:AUDIT_MODEL_TIMEOUT_SECONDS="40"
$env:AUDIT_MODEL_MAX_RETRIES="2"
$env:AUDIT_MODEL_RETRY_BACKOFF_SECONDS="1.5"
$env:AUDIT_ALLOW_MOCK_FALLBACK="true"
```

说明：
- 已配置 `OPENAI_API_KEY` 时，审核优先走真实模型
- 未配置密钥，或真实模型调用失败且允许兜底时，会自动降级到 mock 审核
- 无论走真实模型还是兜底，返回 JSON 结构保持一致

## 当前生产化机制

- 超时控制：模型调用有独立超时配置
- 重试策略：请求失败后按固定次数重试
- 失败兜底：可配置为失败即报错，或自动降级到 mock
- 结果规范化：所有审核结果都会经过统一结构化清洗
- 日志记录：记录模型调用成功、失败、重试、降级情况
