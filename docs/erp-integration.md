# ERP 集成说明

本系统定位为**独立可部署的费用归集微服务**，可通过两种方式与现有 ERP 集成：
（1）前端以 `iframe` 嵌入 ERP 菜单；（2）后端以 REST API 被 ERP 调用。两者均不要求
ERP 开放数据库，也不做任何外部网络抓取。

---

## 1. 认证与网络边界

| 场景 | 建议 |
| --- | --- |
| 演示 / 内网隔离 | `CORS_ORIGINS=*`（默认），不与公网互通 |
| 正式嵌入 ERP | 将 `CORS_ORIGINS` 设为 ERP 域名，例如 `https://erp.your-company.com` |
| 多租户 | 由 ERP 在调用时传入租户头（建议新增 `X-Tenant-Id`，后续可扩展会话隔离） |

> 本系统自身**不实现账号体系**，沿用 ERP 的单点登录：ERP 在 `iframe` 中携带可信令牌，
> 后端通过网关校验后放行。审计字段 `actor` 由 ERP 写入操作人。

## 2. 方式一：iframe 嵌入（推荐，改动最小）

ERP 侧新增菜单项，URL 指向本系统地址：

```
https://sea-freight.internal/            # 本系统前端
```

前端所有请求走同源 `/api`，由本系统后端处理；ERP 仅负责"打开页面 + 记录谁在操作"。
无需跨域（iframe 内同源），但若 ERP 域名与本系统不同源，需在 Nginx 侧对本系统开启
对应 `CORS_ORIGINS`。

**注意**：若 ERP 对 iframe 设置了 `X-Frame-Options: DENY` / `CSP frame-ancestors`，
需将本系统域名加入白名单。

## 3. 方式二：REST API 直连（适合批量 / 后台作业）

ERP 按货柜逐个调用，典型流程：

```
1. POST /api/sessions
      body: { "cabinet_no": "008", "sea_freight": 54485.80,
              "rmb_duty": 7486.68, "exchange_rate": 8.2, "note": "..." }
      → { "session_id": "..." }

2. POST /api/sessions/{id}/packing        (multipart, 装箱单 xlsx)
3. POST /api/sessions/{id}/customs        (multipart, 税单 pdf/zip 可多选)

4. POST /api/sessions/{id}/compute
      → { "refs", "matches", "sea_freight_alloc", "duty_alloc",
          "pending_duty", "reconciliation" }

5. （可选）POST /api/sessions/{id}/confirm
      body: { "confirmations": { "<article_key>": "<ref_id>" },
              "splits": {} , "actor": "<erp_user>" }

6. GET  /api/sessions/{id}/export?mode=final     → 触发浏览器下载 .xlsx
   （后端返回标准附件头，ERP 下载落库或推送到对象存储）
```

### 集成要点

- **一个柜一次核算**：`cabinet_no` 作为业务主键用于导出文件名与检索。
- **金额口径**：`sea_freight` 为整柜海运费（元），`rmb_duty` 为实际人民币关税（元），
  二者即为对账基准，系统保证分摊后合计严格等于输入。
- **未解决异常阻断**：当 `reconciliation.unresolved_exceptions == true` 时，调用
  `mode=final` 导出会返回 `400`。ERP 应据此拦截"最终确认"动作，引导用户先处理待确认税项。
- **审计**：人工确认 / 校正 / 补录均写入 `audit_log`，ERP 可通过后续接口读取供合规查证。

## 4. 数据回写 ERP（可选）

导出的 Excel 为最终交付物；若需结构化回写，建议：

- 读取 `GET /api/sessions/{id}` 的 `data` JSON（含 `sea_alloc` / `duty_alloc` / `matches`）；
- 或扩展 `GET /api/sessions/{id}/export` 同时落库一份 JSON 快照。

所有金额字段均为字符串（Decimal 序列化），ERP 消费时按定点数解析，避免浮点误差。

## 5. 部署拓扑（建议）

```
[ ERP Web ] ──iframe/API──> [ 本系统 Nginx ] ──> [ FastAPI :8000 ]
                                      │
                                      └──> [ SQLite 卷 / 对象存储 (xlsx) ]
```

- 数据库：`SEA_FREIGHT_DB` 指向挂载卷，容器重启不丢数据。
- 横向扩展：当前为单实例 SQLite；如需多实例，将存储替换为 PostgreSQL（仓库层已参数化，
  替换 `storage/` 实现即可），或保持单实例 + 反向代理。
- 不依赖任何外部 SaaS / AI / 数据抓取服务，符合数据不出域内合规要求。
