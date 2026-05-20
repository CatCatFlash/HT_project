# AI合同初审助手 V1 后端

## 技术选型

- FastAPI
- SQLite
- 本地文件存储
- `pypdf` / `python-docx` 文本提取
- Mock 审核服务（保留正式版替换点）

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

接口文档：

- Swagger UI: `http://127.0.0.1:8000/docs`
- 健康检查: `http://127.0.0.1:8000/health`

## 当前 V1 接口

- `POST /api/v1/contracts/upload`
- `POST /api/v1/contracts/text`
- `GET /api/v1/contracts/{task_id}/preview`
- `POST /api/v1/contracts/{task_id}/audit`
- `GET /api/v1/contracts/{task_id}/result`
- `GET /api/v1/contracts/history`
- `DELETE /api/v1/contracts/{task_id}`

## 联调约定

- 当前通过请求头 `X-User-Id` 区分用户历史记录；前端联调阶段可先固定传 `demo-user`
- 当前默认联调地址就是 `http://127.0.0.1:8000`
- 文件上传仅稳定支持文本型 `pdf` 与 `docx`
- `doc` 文件会进入解析失败兜底，并返回明确提示，建议前端提示用户转成 `docx` 后重试
- 历史记录接口已补充 `id`、`title`、`status_text`、`completed_at`，便于前端直接展示
- 审核结果接口除了 `result` 外，也额外返回 `summary` 和 `risks` 兼容字段，便于前端与原 mock 结构对齐
