# A 股全市场 DCF 估值系统 — 架构设计

## 1. 设计目标

在现有单股票 DCF 估值引擎的基础上，构建一个能够**自动化、批量化、持续化**覆盖 A 股全市场（约 5000 只股票）的估值系统。

| 维度 | 目标 |
|------|------|
| 覆盖度 | 全市场可估值标的（剔除 ST、金融行业等 DCF 不适用的类别） |
| 频次 | 每季度财报披露后触发全市场重估，日常增量更新股价 |
| 延迟 | 一次全市场扫描在 4 小时内完成 |
| 可追溯 | 每次估值结果持久化，支持历史对比和趋势分析 |
| 可扩展 | 分析师可介入修正参数、标记异常、覆盖默认假设 |

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        调度层 Scheduler                       │
│    cron / Airflow / 简单定时任务                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ 触发
┌──────────────────────▼──────────────────────────────────────┐
│                        队列层 Queue                          │
│    股票池生成 → 分批 → 优先级排序 → 失败重试队列              │
└──────────────────────┬──────────────────────────────────────┘
                       │ 分发
┌──────────────────────▼──────────────────────────────────────┐
│                        执行层 Worker                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ Worker 1   │  │ Worker 2   │  │ Worker N   │  (并行,N≤8)│
│  │ 单股票流程  │  │ 单股票流程  │  │ 单股票流程  │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└──────────────────────┬──────────────────────────────────────┘
                       │ 写入
┌──────────────────────▼──────────────────────────────────────┐
│                        存储层 Storage                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 数据缓存     │  │ 估值结果库    │  │ 报告产物(HTML/MD) │   │
│  │ (SQLite/DB) │  │ (SQLite/DB)  │  │ (文件系统)        │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 分层职责

| 层级 | 职责 | 技术选型 |
|------|------|---------|
| **调度层** | 定时触发、增量/全量切换、任务编排 | `APScheduler` 或简单 `cron` + shell |
| **队列层** | 股票池管理、优先级、分批、重试逻辑 | `queue.Queue` + JSON task 文件 |
| **执行层** | 并行执行 DCF 估值流程 | `concurrent.futures.ThreadPoolExecutor` |
| **存储层** | 数据缓存、结果持久化、报告归档 | `SQLite` + 文件系统 |
| **监控层** | 进度追踪、失败告警、统计看板 | 日志文件 + 简单聚合脚本 |

---

## 3. 数据流程

### 3.1 全量扫描流程

```
[触发] 季度财报披露后 / 手动触发
    │
    ▼
[1] 初始化 & 准备
    ├── 加载 config/assumptions.yaml（全局默认假设）
    ├── 拉取 stock_basic 全量列表（约 5000 只）
    ├── 过滤：剔除 ST、*ST、退市、金融行业
    └── 初始化 SQLite 连接 / 创建表结构
    │
    ▼
[2] 数据预取（缓存层）
    ├── 批量拉取 daily_basic（全市场一日，含市值/股价/PE/PB）
    ├── 批量拉取 fina_indicator（全市场最新一期，含 ROE/EPS/BPS）
    └── 存入缓存表，避免逐股票重复 API 调用
    │
    ▼
[3] 生成估值队列
    ├── 按市值排序（大盘股优先，稳定可靠）
    ├── 分批：每批 100 只，写入 task_queue
    └── 标记上次已估值且数据未变的股票可跳过
    │
    ▼
[4] 多 Worker 并行估值
    ├── N 个 Worker 从队列消费股票代码
    ├── 每个 Worker 执行现有 main.py 核心逻辑：
    │    ├── 拉取 individual 财务数据（3 年财报）
    │    ├── 计算 WACC（CAPM）
    │    ├── 运行蒙特卡洛模拟（5000 次）
    │    ├── 计算敏感性参数
    │    └── 生成 result dict
    ├── 异常处理：失败入重试队列（最多重试 3 次）
    └── 结果写入估值结果库
    │
    ▼
[5] 报告生成（可选后处理）
    ├── 只为特定股票生成 HTML/MD 报告
    ├── 或生成批量汇总报告（全市场估值分布统计）
    └── 生成估值排行榜（最高/最低估值、最大偏差等）
    │
    ▼
[6] 完成 & 通知
    ├── 写入扫描完成标记（时间戳、覆盖数、失败数）
    ├── 生成摘要统计
    └── 日志归档
```

### 3.2 增量更新流程

```
[触发] 每日收盘后（可选）
    │
    ▼
[1] 获取今日 daily_basic（全市场）
    ├── 更新缓存中的股价和市值
    └── 筛选当前股价与估值时股价偏差 > 10% 的股票
    │
    ▼
[2] 仅对上述偏差股票重新估值
    └── 保留原有财务数据假设，仅更新股价输入
    │
    ▼
[3] 更新估值结果库
    └── 记录新估值结果，标记为增量更新
```

### 3.3 单股票数据依赖

```
对一个股票完成一次 DCF 估值所需的数据：

┌────────────────────────────────────────────────────────────┐
│  数据项            来源 API          缓存策略   频率        │
├────────────────────────────────────────────────────────────┤
│  公司名称/行业     stock_basic       全局缓存   季度        │
│  营业收入          income_vip        本地缓存   季度        │
│  净利润            income_vip        本地缓存   季度        │
│  经营现金流        cashflow_vip      本地缓存   季度        │
│  自由现金流        cashflow_vip      本地缓存   季度        │
│  总债务(有息)      balancesheet_vip  本地缓存   季度        │
│  现金              balancesheet_vip  本地缓存   季度        │
│  总股本            daily_basic       全局缓存   季度        │
│  总市值            daily_basic       全局缓存   日          │
│  收盘价            daily             不缓存     日          │
│  ROE               fina_indicator    全局缓存   季度        │
│  Beta              fina_indicator/   计算生成   季度        │
│                    历史日线回测                               │
│  无风险利率        配置或 SHIBOR     配置/缓存  季度        │
│  ERP               配置              配置       年度        │
└────────────────────────────────────────────────────────────┘
```

---

## 4. 存储设计

### 4.1 SQLite 表结构

```sql
-- 股票基础信息（全量列表）
CREATE TABLE stocks (
    ts_code       TEXT PRIMARY KEY,    -- 000858.SZ
    name          TEXT,                 -- 五粮液
    industry      TEXT,                 -- 白酒
    market        TEXT,                 -- 主板/创业板/科创板
    list_date     TEXT,                 -- 上市日期
    delist_date   TEXT,                 -- 退市日期（如有）
    is_active     INTEGER DEFAULT 1,    -- 是否正常交易
    created_at    TEXT,
    updated_at    TEXT
);

-- 财务数据缓存（避免重复拉取）
CREATE TABLE financial_cache (
    ts_code       TEXT,
    report_date   TEXT,                 -- 20241231
    revenue       REAL,
    net_profit    REAL,
    operating_cash_flow REAL,
    free_cash_flow      REAL,
    total_debt    REAL,
    cash          REAL,
    total_equity  REAL,
    total_assets  REAL,
    operating_margin REAL,
    roe           REAL,
    eps           REAL,
    cached_at     TEXT,
    PRIMARY KEY (ts_code, report_date)
);

-- 估值结果主表
CREATE TABLE valuation_results (
    ts_code           TEXT,
    valuation_date    TEXT,             -- 估值日期 20260428
    scan_batch_id     TEXT,             -- 批次 ID，关联某次全量扫描

    -- 输入快照
    current_price     REAL,
    report_date       TEXT,             -- 使用的财报日期

    -- 核心结果（MC）
    implied_price     REAL,             -- MC 均值（目标价）
    median_price      REAL,
    std_price         REAL,
    upside_pct        REAL,
    prob_upside       REAL,
    prob_upside_15pct REAL,

    -- 百分位
    p5_price          REAL,
    p10_price         REAL,
    p25_price         REAL,
    p50_price         REAL,
    p75_price         REAL,
    p90_price         REAL,
    p95_price         REAL,

    -- 模型参数（实际使用的值）
    wacc              REAL,
    cost_of_equity    REAL,
    beta_used         REAL,
    short_term_growth REAL,
    perpetual_growth  REAL,
    risk_free_rate    REAL,
    equity_risk_premium REAL,

    -- 企业价值明细
    enterprise_value  REAL,
    equity_value      REAL,
    pv_fcff_sum       REAL,
    pv_terminal_value REAL,

    -- 元数据
    n_simulations     INTEGER,
    is_incremental    INTEGER DEFAULT 0, -- 0=全量,1=增量
    status            TEXT DEFAULT 'success',  -- success/failed
    error_msg         TEXT,
    duration_seconds  REAL,
    created_at        TEXT,

    PRIMARY KEY (ts_code, valuation_date, scan_batch_id)
);

-- 估值历史对比表（视图或物化数据）
CREATE TABLE valuation_snapshots (
    batch_id          TEXT PRIMARY KEY, -- 2026Q1
    scan_type         TEXT,             -- full/incremental
    started_at        TEXT,
    completed_at      TEXT,
    total_stocks      INTEGER,
    success_count     INTEGER,
    failed_count      INTEGER,
    skipped_count     INTEGER,
    duration_minutes  REAL
);

-- 参数覆盖表（分析师可手动覆盖某股票的特定参数）
CREATE TABLE parameter_overrides (
    ts_code           TEXT,
    param_name        TEXT,             -- beta/perpetual_growth/etc
    param_value       REAL,
    reason            TEXT,
    set_by            TEXT,
    created_at        TEXT,
    PRIMARY KEY (ts_code, param_name)
);

-- 索引
CREATE INDEX idx_val_date ON valuation_results(valuation_date);
CREATE INDEX idx_val_upside ON valuation_results(upside_pct DESC);
CREATE INDEX idx_val_status ON valuation_results(status);
```

### 4.2 缓存策略

| 缓存级别 | 存储 | 内容 | 刷新 |
|---------|------|------|------|
| **全局缓存** | SQLite `financial_cache` | 全市场批量拉取的财务指标 | 季度（财报披露后） |
| **个股缓存** | SQLite `financial_cache` | 补漏的个股详细财报 | 按需，TTL 7 天 |
| **日频缓存** | SQLite（临时表） | `daily_basic` 全市场快照 | 每个交易日收盘后 |
| **计算结果** | SQLite `valuation_results` | 估值结果 | 每次扫描写入 |

### 4.3 文件产物

```
report/
├── batch/                         # 批量报告
│   ├── 2026Q1_full_scan_summary.html
│   ├── 2026Q1_valuation_ranking_top50.csv
│   └── 2026Q1_sector_aggregation.csv
├── individual/                    # 个股报告（按需生成）
│   ├── 000858_SZ/
│   │   ├── 20260428_report.html
│   │   ├── 20260428_report.md
│   │   └── 20260701_update.html
│   └── ...
└── archive/                       # 历史归档
    └── ...
```

---

## 5. 股票池管理

### 5.1 筛选规则

全市场约 5000 只，实际可 DCF 估值的子集：

```
全量 A 股 (约 5300)
  ├── 剔除 ST / *ST                          → -约 150
  ├── 剔除退市 / 停牌 > 3 个月                → -约 50
  ├── 剔除金融行业（银行/保险/券商）（DCF 不适用）→ -约 120
  ├── 剔除上市 < 3 年（历史数据不足）          → -约 800
  ├── 剔除 FCFF 持续为负（最近 3 年均为负）    → -约 600
  ├── 剔除营收 < 1 亿（太小无意义）            → -约 200
  └── 可估值池                                → ~3300 只
```

### 5.2 优先级排序

按以下优先级决定估值顺序（排名靠前的优先估值）：

1. **沪深 300 成分股**（大盘蓝筹，更适合 DCF）
2. **北向资金持仓TOP 200**
3. **市值 > 100 亿**（中大盘，财务数据质量较高）
4. **分析师覆盖 >= 3 家**（市场关注度高）
5. **其余股票**按市值降序

---

## 6. 执行层设计

### 6.1 Worker 架构

```
主进程 (Main Process)
    │
    ├── StockQueue (线程安全队列)
    │
    ├── Worker-1 (线程/进程)
    │   ├── get_stock_from_queue()
    │   ├── run_valuation(ts_code)
    │   │   ├── check_cache()          // 检查缓存命中
    │   │   ├── fetch_individual_data() // 缺失数据补拉
    │   │   ├── compute_dcf()          // 核心估值
    │   │   └── store_result()         // 写入数据库
    │   └── report_status()
    │
    ├── Worker-2 (同上)
    ├── ...
    └── Worker-N (N ≤ 8，受 Tushare 并发限制)
```

### 6.2 并发控制

```python
# 关键约束
MAX_WORKERS = min(8, cpu_count() * 2)
TUSHARE_QPS_LIMIT = 3  # Tushare 每秒请求数限制
BATCH_SIZE = 100        # 每批处理数量
RETRY_MAX = 3           # 最大重试次数
CACHE_TTL_DAYS = 7      # 缓存过期天数
```

Tushare API 限速策略：
- 全局 `rate_limiter`（`time.sleep(1/QPS)` 或令牌桶）
- 按 endpoint 分别限速（`daily_basic` 可高频，`income_vip` 低频）
- 失败时指数退避重试：1s → 3s → 9s

### 6.3 单股票估值耗时预估

| 阶段 | 耗时 | 说明 |
|------|------|------|
| 数据拉取（命中缓存） | 0.1-0.5s | 从 SQLite 读取 |
| 数据拉取（未命中缓存） | 2-5s | 3-5 次 Tushare API 调用 |
| WACC 计算 | <0.01s | 纯计算 |
| 蒙特卡洛 5000 次 | 0.5-1.5s | NumPy 向量化 |
| 结果写入 | 0.05s | SQLite INSERT |
| **合计（缓存命中）** | **~1s** | |
| **合计（缓存未命中）** | **~5s** | |

全量 3300 只扫描：8 Worker 并行，约 **3300 × 1s / 8 ≈ 7 分钟**（缓存命中率 > 90% 时）。

### 6.4 失败处理

| 失败类型 | 处理策略 |
|---------|---------|
| Tushare API 超时 | 重试 3 次，指数退避 |
| 财务数据缺失 | 标记为 `failed`，记录原因 |
| FCFF 为负 | 正常估值（模型会输出负目标价），标记警告 |
| WACC <= g_perp | 跳过该股票，记录异常 |
| 股价数据不存在 | 跳过（可能停牌） |

---

## 7. 配置与参数管理

### 7.1 全局默认参数（现有 `assumptions.yaml`）

保持不变，作为所有股票的基准假设。

### 7.2 行业级参数覆盖

```yaml
# config/industry_overrides.yaml
industry_defaults:
  白酒:
    beta: 0.95
    short_term_growth: 0.12
    perpetual_growth: 0.035
    operating_margin: 0.40
  医药生物:
    beta: 1.05
    short_term_growth: 0.15
    perpetual_growth: 0.04
  煤炭:
    beta: 1.10
    short_term_growth: 0.03
    perpetual_growth: 0.02
```

### 7.3 个股参数覆盖

存储在 SQLite `parameter_overrides` 表，供分析师手动修正。

参数解析优先级：
```
个股级覆盖 > 行业级默认 > 全局默认
```

---

## 8. 模块改动清单

| 模块 | 改动类型 | 说明 |
|------|---------|------|
| `main.py` | 重构 | 拆分为 CLI 入口 + 核心库函数 `run_single_valuation()` |
| `data/tushare_client.py` | 增强 | 增加 `batch_get_daily_basic()`、`batch_get_fina_indicator()` |
| `data/fetch_financials.py` | 增强 | 增加缓存检查逻辑、批量获取接口 |
| `data/cache.py` | **新建** | SQLite 缓存层，统一管理缓存的读写和过期 |
| `data/stock_pool.py` | **新建** | 股票池管理：筛选、排序、增量检测 |
| `engine/scheduler.py` | **新建** | 调度器：全量/增量任务编排 |
| `engine/worker.py` | **新建** | Worker 池：并行执行、重试、进度汇报 |
| `engine/batch_runner.py` | **新建** | 批处理主控：协调调度、执行、存储 |
| `storage/database.py` | **新建** | SQLite 数据库初始化和连接管理 |
| `storage/repository.py` | **新建** | 估值结果 CRUD 操作 |
| `report/generator.py` | 增强 | 增加批量汇总报告生成 |
| `analysis/sensitivity.py` | 增强 | 增加跨股票对比分析 |

---

## 9. 协作规范

### 9.1 代码组织

```
dcf/
├── main.py                    # CLI 入口（兼容旧命令）
├── config/
│   ├── assumptions.yaml       # 全局默认假设
│   └── industry_overrides.yaml # 行业参数覆盖
├── data/
│   ├── __init__.py
│   ├── tushare_client.py      # Tushare API 封装
│   ├── fetch_financials.py    # 财务数据获取和标准化
│   ├── cache.py               # 缓存层（新建）
│   └── stock_pool.py          # 股票池管理（新建）
├── models/
│   ├── __init__.py
│   ├── wacc.py
│   ├── dcf_model.py
│   └── monte_carlo.py
├── engine/
│   ├── __init__.py            # 新建
│   ├── scheduler.py           # 任务调度（新建）
│   ├── worker.py              # 并行执行（新建）
│   └── batch_runner.py        # 批处理主控（新建）
├── storage/
│   ├── __init__.py            # 新建
│   ├── database.py            # 数据库初始化（新建）
│   └── repository.py          # 数据访问层（新建）
├── analysis/
│   ├── __init__.py
│   └── sensitivity.py
├── report/
│   ├── __init__.py
│   ├── generator.py
│   └── template.html
├── scripts/
│   ├── run_full_scan.sh       # 全量扫描入口脚本
│   └── run_daily_update.sh    # 增量更新入口脚本
├── requirements.txt
└── README.md
```

### 9.2 开发规范

| 规范 | 要求 |
|------|------|
| Python 版本 | 3.10+ |
| 代码风格 | `ruff` + `black`，line-length=100 |
| 类型注解 | 所有新函数必须包含 type hints |
| 日志 | 使用 `logging` 模块，禁止 `print()` |
| 测试 | `pytest`，核心模型函数覆盖率 > 80% |
| 提交信息 | Conventional Commits（feat/fix/chore/docs） |

### 9.3 数据变更流程

```
分析师发现某股票参数不合理
    │
    ├── 写入 parameter_overrides 表
    │   (ts_code, param_name, param_value, reason)
    │
    ├── 下次扫描自动读取覆盖
    │
    └── 或触发单股票重估：
        python main.py --ts_code 000858.SZ --override beta=0.85
```

### 9.4 发布检查清单

- [ ] `assumptions.yaml` 参数经团队评审
- [ ] 行业覆盖参数配置完毕
- [ ] 缓存表已初始化
- [ ] 测试批跑 200 只股票，验证无系统性异常
- [ ] 全量扫描完成后验证估值分布合理性
- [ ] 增量更新逻辑验证通过
- [ ] 日志和监控就绪

---

## 10. 约束与风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Tushare API 限频 | 扫描速度受限 | 缓存 + 并发控制 + 令牌桶 |
| 财务数据延迟 | 使用旧季报数据 | 财报披露日历跟踪，标记数据时效 |
| FCFF 为负的股票 | DCF 模型失效 | 标记 warning，改用其他估值法参照 |
| Beta 默认值 1.0 不合理 | 行业偏差 | 行业级覆盖 + 历史 Beta 回测 |
| 永续增长假设敏感 | 估值波动大 | 蒙特卡洛已部分解决，报告加敏感性提示 |
| SQLite 并发写入冲突 | 数据一致性问题 | WAL 模式 + 连接池 |

---

## 11. 未来可扩展方向

1. **Beta 自动计算**：基于历史 60 个月日收益率 vs 沪深 300 回归
2. **行业基准自动调整**：根据同行业公司估值分布校准参数
3. **Web 看板**：FastAPI + ECharts，展示全市场估值热力图和排行榜
4. **邮件/钉钉推送**：扫描完成通知 + 异常告警
5. **多数据源**：接入 Wind/同花顺作为 Tushare 补充
6. **估值合理性校验**：对比当前 PE/PB 分位数、分析师目标价
