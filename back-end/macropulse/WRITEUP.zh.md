# MacroPulse — 央行通讯解析与事件-波动归因

*English version: [WRITEUP.md](WRITEUP.md)*

> 一条 LLM 驱动的流水线：把 Fed FOMC 的声明与纪要解析成结构化的鹰鸽计量，
> 追踪相邻会议的措辞变化，用校准过的标尺给每次发布打分，再把这些分数与黄金市场
> 的真实价格反应对齐回测——并把一套评估闭环挂进 CI，作为整个项目的脊梁。

它是 **FXLab**（一条建在 AWS S3/Lambda/EC2 上的市场数据流水线）的二期，复用其
数据湖与分钟级 XAU 价格源。

---

## 为什么做这个

央行的政策立场，藏在声明的**措辞**里。市场反应的是这次会议相对上次的语言差。
本项目的命题是：这个差是可度量的，而且模型给出的鹰鸽读数可以拿真实价格反应当
ground truth 来检验，而不是凭感觉打分。

所以 MacroPulse 不是"一个给央行打分的 LLM 玩具"，而是一个带**评估回路**的打分
系统：每个分数都 (a) 溯源到一句逐字原文，(b) 在 prompt 改动时跑回归检验漂移，
(c) 与市场对齐回测、当二者打脸时自动进人工复核。

---

## 架构（五层）

```
 抓取        →  Diff 引擎    →  抽取        →  归因         →  服务化
 (S3 raw)      (红线对比)     (鹰鸽打分)     (vs XAU)       (FastAPI + React)
                                  ↑
                          评估 harness（CI 回归 + 漂移测试 + 人工裁决队列）
```

### 1. 抓取（`macropulse/`）
一个 Lambda 式抓取器从 FOMC 日历页拉取 Fed 的**声明**与**纪要全文**——这是唯一
可靠的单一源（年度 press 存档不含声明，而"纪要已发布"的新闻稿**不是**纪要正文）。
文档按 content hash 去重，写入 S3 raw 层并维护幂等清单。

回填覆盖近三年：**44 篇声明 + 43 篇纪要**（约 230 万字符）。这里踩到一个真实 bug：
Fed 页面不声明 charset，`requests` 把 UTF-8 当成 Latin-1 解，把 en-dash
（`April 28–29`）解成乱码——通过探测真实编码修掉。这很要紧，因为下游 schema
要求逐字引用。

### 2. Diff 引擎（`diff.py`）——确定性，不用 LLM
对相邻两期声明做 Needleman-Wunsch 段落对齐 + 词级 diff，渲染成 wdiff 风格的红线。
FOMC 声明结构高度平行（同样约 8 段），所以对齐很干净。这是"AI 红线"的骨架——
LLM 之后只标注每处变化的**方向**，从不转写正文（省 token，也消除一个转写出错面）。

### 3. 抽取（`extraction/`）——Claude API，结构化输出
每篇声明/纪要按校准标尺打进 Pydantic schema：`overall_score ∈ [-5,+5]`、四个维度
（通胀 / 就业 / 缩表 / 前瞻指引）各含 `score + key_quote + confidence`，外加逐处
diff 的方向标注。几个关键设计：

- **逐字溯源**：每个 `key_quote` 都校验为原文子串；非逐字引用自动标
  `needs_human_review`。这是前端展示所依赖的溯源保证。
- **校准锚点**：三篇立场公认的声明（2022-06-15 极鹰、2024-09-18 鸽、2024-01-31
  中性）作为 few-shot 锚点，放在 prompt-cache 断点处，回归重跑时以约 0.1× 成本读缓存。
- **幂等 + Batch**：回填走 Batch API（5 折）；清单按 `(content_hash, prompt_hash)`
  键控——prompt 未变则一篇都不重打。

**Provider 取舍（实测，而非假设）**：我把全部 87 篇用相同 prompt 在
`claude-opus-4-8` 和 `deepseek-v4-pro` 各跑一遍。总分相关 r≈0.9、>90% 落在 ±1 内
——但 DeepSeek 在**纪要上的逐字引用违规率 42%，Opus 仅 5%**，而 schema 的硬要求
就是逐字引用。结论：生产打分留在 Opus（量很低，<$1/年，成本不是因素）；DeepSeek
作为评估队列的廉价第二意见保留。（FXLab 另一条**高频新闻摘要**路径**确实**迁到了
DeepSeek v4-flash——那里成本账反过来。）

### 4. 归因（`attribution/`）——ground truth = 市场
对每篇有价格覆盖的声明，把释放时刻（`t0` = 14:00 America/New_York，处理夏令时）
对齐到分钟级 XAU K 线，度量 15min / 1h / 1d 收益。方向约定：鹰派→黄金跌。回测输出
各窗口的方向命中率与 Pearson(分数, 收益)。

**诚实的局限，在每个出现的地方都讲明**：FXLab 目前只有 XAU（无 DXY/US2Y），且 XAU
分钟历史从 2025-10 起——44 篇声明里只有约 5 篇有价格覆盖。命中率在 N=4 时是 50%：
管线是对的，信号尚不显著。每次新 FOMC 自动累积一个事件。这是带 small-N 声明的方法论
演示，局限文字印在 API 返回、UI 与本文里。

### 5. 服务化
- **后端**：一个只读 FastAPI 路由（`routers/macro_router.py`，前缀 `/api/macro`）
  挂进既有应用，从 S3 以 5 分钟缓存供给分数 / 红线 diff / 归因 / 裁决队列——与其他
  analytics 路由同一模式。
- **前端**：既有 React/Vite 应用里的一个 `MacroPulse` 页——分数时间线（鹰红/鸽青
  发散条）、最新红线、归因表、裁决队列，浅色编辑式终端风格，双语 CN/EN。

---

## 评估 harness（真正的重点）

三层评估，因为"LLM 打得对不对"才是全部风险所在：

1. **第一层 结构/校准回归** —— 每次 push 在 CI 上跑，纯离线（不碰 API/S3/网络）。
   它用一份 committed 的全部 87 篇生产分数 golden 快照校验 schema/范围不变量，并断言
   三个校准锚点仍落在期望带内。若 prompt 改动动摇了打分标尺，CI 变红。这是仓库的
   **第一个 CI workflow**（`.github/workflows/macropulse-eval.yml`）。
2. **第二层 漂移测试** —— gated（花 API）。重打锚点，断言 `|Δ overall| ≤ 1` 且方向
   不翻转。改完 prompt 后手动或定时跑。
3. **人工裁决队列** —— 拉取每篇生产分数，挑出不可信的：模型自标 `needs_review`、
   低置信、逐字违规，以及**价格冲突**（与归因结果联表——例如一篇打了中性分却仍把
   黄金日内推动了 −5.67%）。裁决回流为校准数据。首跑捞出 8 项，每一项都确实值得人看。

---

## 技术栈

Python · FastAPI · Claude API（结构化输出、prompt caching、Batch）· DeepSeek
（对比 + 高频路径）· Pydantic · AWS（S3 数据湖、Lambda 式抓取、EC2）· React + Vite ·
pytest（78 个 hermetic 测试）· GitHub Actions CI。

---

## 诚实条款

- Fed 声明/纪要是公开出版物（FOIA / 公共领域）；抓取器自报身份并限速。RBA/ECB
  尚未接入（需先确认各自的 robots.txt 与使用条款）。
- 归因结论在当前样本量下**不具统计显著性**，且价格反应存在混杂因素（同日数据发布、
  流动性时段）。每个展示它的界面都如实声明。
- 这个项目不解决"几年 AI 产品工作经验"这类硬筛。它做到的，是把叙事从"设计过架构"
  推进到"shipped 过一个带评估回路、带 CI 回归门、带可量化 provider 取舍、并如实
  声明局限的系统"。
