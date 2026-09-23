# 海运费用归集与进口关税分摊系统

企业 ERP 配套工具：针对一个海运货柜（整柜 FCL），将**整柜海运费**与**实际人民币进口关税**
归集、分摊到各 `Reference ID`（货件），并导出核对明细 Excel。支持荷兰海关税单（缴税通知 /
放行单）解析、按体积分摊海运费、按各税项原币关税比例分摊人民币关税，并用**最大余数法**严格对平，
对无法确认的税项提供人工确认与审计轨迹。

> 数据与文件**仅在本地解析**，不上传任何外部服务 / 第三方 AI / ERP 自动抓取。

---

## 一、核心能力

| 模块 | 说明 |
| --- | --- |
| 费用输入 | 一个货柜一次核算：柜号、整柜海运费（元）、实际人民币关税（元）、结算汇率 |
| 装箱单解析 | 上传 Excel，按表头名自动识别字段；聚合出各货件的箱数、体积、HS Code |
| 海关税单解析 | 上传 PDF 或 ZIP（多个 PDF）：识别 MRN、柜号、各税项关税（Douanerechten）/ VAT（Btw） |
| 海运费分摊 | 按各货件体积占比分配，最大余数法对平到整数分 |
| 关税分摊 | 按各税项原币关税占原币关税总额的比例分配人民币关税总额，最大余数法对平 |
| 异常处理 | HS 不一致 / 多货件并列 / 无对应货件 → 待确认，人工指定归属并记录审计 |
| 核对与导出 | 海运费对平、关税对平、箱数差异、报关数量差异、HS 异常；存在未解决异常时**禁止导出最终确认版** |

## 二、严格约束（已通过自动化测试）

- 海运费合计 **==** 输入整柜海运费（尾差由最大余数法吸收）。
- 已归集关税 **+** 待确认关税 **==** 实际人民币关税。
- VAT（Btw）**不计入**关税分摊基数。
- 零关税商品归集金额为 0，不为分摊整柜关税强行分配。
- **未解决关键异常时禁止导出"最终确认版"** Excel（只能导出"待确认工作版"）。

## 三、本地运行

### 方式 A：仅后端 API（最快验证）

```bash
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 接口文档： http://localhost:8000/docs
- 健康检查： http://localhost:8000/api/health

### 方式 B：带前端界面（Vue 3）

```bash
# 1) 构建前端
cd frontend
npm install
npm run build        # 产物输出到 frontend/dist，由后端直接托管

# 2) 启动后端（同方式 A）
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://localhost:8000 即可使用向导式界面。

> 一键脚本：Windows `run.bat`；Linux/macOS `start.sh`（仅后端）。

### 方式 C：Docker

```bash
docker compose up --build
# 访问 http://localhost:8000
```

数据库文件通过卷 `sea_freight_data` 持久化；可用环境变量 `SEA_FREIGHT_DB` 覆盖位置。

## 四、API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/sessions` | 创建货柜核算会话 |
| POST | `/api/sessions/{id}/packing` | 上传并解析装箱单 Excel |
| POST | `/api/sessions/{id}/customs` | 上传并解析海关 PDF / ZIP |
| POST | `/api/sessions/{id}/compute` | 计算分摊 |
| POST | `/api/sessions/{id}/confirm` | 提交人工确认（含审计） |
| POST | `/api/sessions/{id}/adjust` | 单字段手工校正 |
| POST | `/api/sessions/{id}/manual-article` | 手工补录税项 |
| GET | `/api/sessions/{id}/export?mode=final\|pending` | 导出 4 表 Excel |

导出文件名自动包含柜号；`mode=final` 在未解决异常时返回 400。

## 五、导出 Excel 结构（4 个 Sheet）

1. **货件费用归集** —— 各货件海运费、关税、费用合计、归集状态。
2. **箱型体积明细** —— 各箱型尺寸、单箱体积、箱型总体积。
3. **关税匹配明细** —— 税项与货件匹配、计税金额、原币/人民币关税、分摊依据、状态。
4. **核对与异常** —— 海运费/关税对平、箱数差异、报关数量差异、HS 异常、尾差说明、未解决异常标记。

## 六、测试

```bash
cd backend
pip install -r requirements.txt pytest
pytest app/tests -q
```

覆盖 008（海运费 54,485.80 / 关税 7,486.68 / 合计 61,972.48）、009（海运费 56,965.80 /
关税 12,284.50 / 合计 69,250.30，含"镜子税项归属待确认"场景）的回归，以及欧洲数字格式、
遮盖符号、ZIP 路径穿越防护、最大余数法对平、人工确认审计等共 45 项。

## 七、目录结构

```
sea-freight-cost-allocation/
├── backend/                 # FastAPI + 核心计算（Python，Decimal 高精度）
│   ├── app/
│   │   ├── core/            # 数字解析 / 箱规 / 体积 / 关税 / 对账
│   │   ├── parsers/         # Excel 装箱单 / PDF 海关 / ZIP
│   │   ├── services/        # 编排、Excel 导出
│   │   ├── storage/         # SQLite 仓库（参数化查询）
│   │   ├── models.py        # 领域模型
│   │   ├── schemas.py       # API 模型
│   │   ├── main.py          # FastAPI 应用
│   │   └── tests/           # 测试 + 脱敏夹具
├── frontend/                # Vue 3 + TypeScript（Vite）向导式界面
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── run.bat / start.sh
└── README.md
```

## 八、安全与合规

- 所有 SQL 使用参数化查询；会话以 UUID 为键，防止越权/遍历访问。
- ZIP 解压做路径穿越（Zip Slip）防护。
- 业务文件只在本地解析，不调用任何外部 API / 第三方模型。
- 审计日志（`audit_log`）记录每一次人工确认、校正、补录。

详见 [`docs/erp-integration.md`](docs/erp-integration.md)。
