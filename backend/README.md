# AI合同初审助手 V1 后端

## 技术栈

- FastAPI
- SQLite
- 本地文件存储
- `pypdf` / `python-docx` 文本提取
- DeepSeek 审核服务接入
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
  deploy/
    env/
    nginx/
    scripts/
    systemd/
```

## 本地启动

```powershell
cd D:\HT_project\HT_project\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

本地入口：

- Swagger UI: `http://127.0.0.1:8010/docs`
- 健康检查: `http://127.0.0.1:8010/health`

## 当前接口

- `POST /api/v1/contracts/upload`
- `POST /api/v1/contracts/text`
- `GET /api/v1/contracts/{task_id}/preview`
- `POST /api/v1/contracts/{task_id}/audit`
- `GET /api/v1/contracts/{task_id}/result`
- `GET /api/v1/contracts/history`
- `DELETE /api/v1/contracts/{task_id}`
- `GET /health`

## DeepSeek 推荐生产配置

```env
AUDIT_PROVIDER=deepseek
AUDIT_PROFILE=prod
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING_DISABLED=true
AUDIT_MODEL_TIMEOUT_SECONDS=20
AUDIT_MODEL_MAX_RETRIES=0
AUDIT_MODEL_RETRY_BACKOFF_SECONDS=0.5
AUDIT_MODEL_MAX_INPUT_CHARS=6000
AUDIT_MODEL_MAX_OUTPUT_TOKENS=420
AUDIT_ALLOW_MOCK_FALLBACK=true
AUDIT_REQUIRE_CONTRACT_KEYWORDS=true
LOG_LEVEL=INFO
```

## 长期运行部署

当前推荐部署形态：

```text
微信小程序
  ->
HTTPS 域名
  ->
Nginx
  ->
Uvicorn / FastAPI:8010
  ->
SQLite
```

仓库已提供部署资产：

- `deploy/systemd/ai-contract-backend.service`
- `deploy/nginx/api.xxx.com.conf`
- `deploy/env/backend.env.example`
- `deploy/scripts/deploy_wsl_ubuntu.sh`

### WSL / Ubuntu 落地步骤

```bash
cd /mnt/d/HT_project/HT_project/backend
bash deploy/scripts/deploy_wsl_ubuntu.sh
```

脚本会完成：

1. 安装 Python / Nginx / Certbot
2. 创建虚拟环境并安装依赖
3. 安装环境变量文件到 `/etc/ai-contract/backend.env`
4. 安装 `systemd` 服务
5. 安装 Nginx 反向代理配置
6. 启动后端服务

### 上线前还需要人工完成

1. 把 `api.xxx.com` 替换成真实 API 域名
2. 在 `/etc/ai-contract/backend.env` 中填入真实 DeepSeek Key
3. 执行证书签发：

```bash
sudo certbot --nginx -d api.xxx.com
```

4. 验证：

```bash
curl https://api.xxx.com/health
```

## 当前限制

- 这台当前机器是 Windows + WSL，已确认 Ubuntu 支持 `systemd`
- 但当前会话没有 Ubuntu 的 `sudo` 密码，无法直接在本机完成 Nginx 安装、systemd 注册和证书签发
- 因此仓库侧部署资产已经补齐，系统级最终落地仍需要管理员权限配合
