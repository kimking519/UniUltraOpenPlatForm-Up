# Agent · Skill · OpenLaw 个人助手架构设计

> **版本** v2.1 · 生产级 · 解耦优化 · 并行执行

---

## 目录

1. [架构总览](#1-架构总览)
2. [分层设计](#2-分层设计)
3. [Skill Contract — 解耦核心](#3-skill-contract--解耦核心)
4. [DataQuery 抽象层](#4-dataquery-抽象层)
5. [智能路由器](#5-智能路由器)
6. [并行执行引擎](#6-并行执行引擎)
7. [Skill 实现层](#7-skill-实现层)
8. [Adapter 隔离层](#8-adapter-隔离层)
9. [缓存策略](#9-缓存策略)
10. [OpenLaw 双轨检索](#10-openlaw-双轨检索)
11. [韧性设计](#11-韧性设计)
12. [扩展性：新增 Skill 三步接入](#12-扩展性新增-skill-三步接入)
13. [目录结构](#13-目录结构)
14. [设计原则总结](#14-设计原则总结)

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                   用户自然语言输入                    │
└──────────────────────┬──────────────────────────────┘
                       │ Intent Object + Vec
                       ▼
┌─────────────────────────────────────────────────────┐
│               Agent Core                            │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ 智能路由器     │  │  上下文管理   │  │  Memory  │ │
│  │ O(1) 向量匹配 │  │  Context Mgr │  │  Store   │ │
│  └───────┬───────┘  └──────────────┘  └──────────┘ │
│          │ DAG Schedule                             │
│  ┌───────▼────────────────────────────────────────┐ │
│  │            并行执行引擎 (DAG Executor)           │ │
│  └───────┬──────────────┬─────────────────────────┘ │
└──────────┼──────────────┼─────────────────────────  ┘
           │              │          ← Skill Contract ─
    ┌──────▼──────┐ ┌─────▼──────┐ ┌───────────────┐
    │ System Skill│ │OpenLaw Skill│ │Personal Skill │
    └──────┬──────┘ └─────┬──────┘ └───────┬───────┘
           │              │                │
    ┌──────▼──────────────▼────────────────▼───────┐
    │               Adapter 隔离层                  │
    │  MySQLAdapter  │  RESTAdapter  │  LawAdapter  │
    └──────┬──────────────┬──────────────┬──────────┘
           │              │              │
    ┌──────▼──────────────▼──────────────▼──────────┐
    │  MySQL/PG  │  Redis  │  Qdrant  │  OpenLaw API │
    └────────────────────────────────────────────────┘
```

---

## 2. 分层设计

| 层级 | 名称 | 职责 | 解耦关键点 |
|------|------|------|-----------|
| L0 | 用户意图层 | 自然语言 → Intent Object + 语义向量 | 统一意图格式 |
| L1 | Agent Core | 路由、上下文、并发调度 | 不感知具体 Skill 实现 |
| L2 | Skill Contract | 统一接口定义 | **所有 Skill 实现同一契约** |
| L3 | Skill 实现层 | System / OpenLaw / Personal | 相互独立，可热插拔 |
| L4 | Adapter 层 | DataQuery → 具体系统调用 | **Skill 不感知底层系统** |
| L5 | 数据层 | DB、Cache、向量库、外部 API | 可随意替换 |

---

## 3. Skill Contract — 解耦核心

所有 Skill 必须实现以下统一契约，这是解耦的基础。

```typescript
interface SkillContract {
  // ── 元信息（路由器使用）──
  meta: {
    name:    string
    version: string                          // semver，支持多版本共存
    domain:  'system' | 'openlaw' | 'personal'
    cost:    'low' | 'medium' | 'high'      // 预估执行代价
  }

  // ── 能力向量（O(1) 路由匹配用）──
  capabilityVector: Float32Array

  // ── 唯一执行入口 ──
  execute(intent: Intent, ctx: Context): Promise<SkillResult>

  // ── 声明式权限（不在内部自行鉴权）──
  permissions: DataPermission[]

  // ── 心跳探测（故障自动下线）──
  healthCheck(): Promise<boolean>
}
```

**契约带来的好处：**

- 任意 Skill 可热插拔，Agent 无需修改
- 路由器只依赖 `capabilityVector`，不感知 Skill 逻辑
- 权限声明前置，统一在 Agent 层校验，Skill 专注业务

---

## 4. DataQuery 抽象层

**核心原则：Skill 只声明"我需要什么数据"，不关心底层如何取。**

```typescript
// Skill 侧 —— 只描述意图，不依赖任何具体系统
const query: DataQuery = {
  entity: 'contract',
  filter: { userId: ctx.userId, status: 'active' },
  fields: ['id', 'title', 'expireAt'],
  limit:  20,
}
const result = await this.adapter.execute(query)  // 不关心底层是 SQL 还是 REST

// ──────────────────────────────────────────────

// Adapter 侧 —— 处理系统差异（Skill 不可见）
class MySQLAdapter implements IAdapter {
  translate(q: DataQuery): SQL {
    return `SELECT ${q.fields.join(',')} FROM ${q.entity}
            WHERE userId = ? AND status = ? LIMIT ${q.limit}`
  }
}

class RESTAdapter implements IAdapter {
  translate(q: DataQuery): HttpRequest {
    return { method: 'GET', url: `/api/${q.entity}`, params: q.filter }
  }
}
```

> **切换底层系统时，只改 Adapter，Skill 代码零改动。**

---

## 5. 智能路由器

路由完全基于向量匹配，**不走 LLM 推理**，延迟 < 5ms。

```
用户意图
  │
  ▼ Intent Parser
Intent Object
  │
  ▼ Vec Embed（轻量本地模型）
intentVector: Float32Array
  │
  ▼ cosine_sim(intentVector, skill.capabilityVector[])
匹配得分排序
  │
  ├── 单 Skill 意图   → 直接执行
  └── 多 Skill 意图   → 构建 DAG → 并行调度
```

### 路由器的三项优化

| 优化点 | 说明 |
|--------|------|
| O(1) 向量匹配 | cosine_sim 本地计算，无 API 消耗，< 5ms |
| cost 预判 | `cost=high` 的 Skill 自动触发用户二次确认 |
| 多版本选择 | 按 semver 策略选版本，支持 A/B 灰度发布 |

---

## 6. 并行执行引擎

当多个 Skill 无依赖关系时，自动并发执行。

### 典型场景：合同风险分析

```
用户："帮我分析这份合同的违约风险"
        │
        ├──────────────────────────────┐
        ▼                              ▼
System Skill                    OpenLaw Skill
拉取合同内容                    检索违约相关法条
   ~80ms                            ~400ms
        │                              │
        └──────────────┬───────────────┘
                       ▼
                  Result Merger
              风险报告（含法条引用）

总耗时 = max(80ms, 400ms) = 400ms
串行耗时 = 80 + 400 = 480ms  ← 节省 17%（越多 Skill 收益越大）
```

### 执行引擎特性

```typescript
class DAGExecutor {
  async run(skills: SkillNode[]): Promise<MergedResult> {
    const dag   = this.buildDAG(skills)       // 分析依赖关系
    const waves = this.topologicalSort(dag)   // 拓扑排序 → 执行波次

    let results: SkillResult[] = []
    for (const wave of waves) {
      // 同一波次内的 Skill 并发执行
      const waveResults = await Promise.allSettled(
        wave.map(skill => this.executeWithTimeout(skill))
      )
      results = [...results, ...this.extractFulfilled(waveResults)]
    }
    return this.merge(results)
  }
}
```

---

## 7. Skill 实现层

### 7.1 System Skill

```typescript
class SystemSkill implements SkillContract {
  meta = { name: 'system', domain: 'system', cost: 'low', version: '1.0.0' }
  capabilityVector = embed(['read_data', 'write_data', 'search', 'notify'])
  permissions = [Permission.READ_CONTRACT, Permission.WRITE_TASK]

  async execute(intent: Intent, ctx: Context): Promise<SkillResult> {
    const query = DataQuery.fromIntent(intent)
    const data  = await this.adapter.execute(query)  // 不直连 DB
    return SkillResult.ok(data)
  }
}
```

**能力标签：** `read_data` · `write_data` · `search` · `notify`

### 7.2 OpenLaw Skill

```typescript
class OpenLawSkill implements SkillContract {
  meta = { name: 'openlaw', domain: 'openlaw', cost: 'medium', version: '1.0.0' }
  capabilityVector = embed(['law_query', 'case_search', 'citation_gen', 'rag'])

  async execute(intent: Intent, ctx: Context): Promise<LawSkillResult> {
    // 双轨检索（见第 10 节）
    const track = this.detectTrack(intent)
    const raw   = track === 'exact'
                    ? await this.exactSearch(intent)
                    : await this.semanticRAG(intent)

    return {
      answer:     raw.text,
      citations:  raw.citations,    // 法条 + 条文编号
      confidence: raw.score,        // 0–1 置信度
      relatedCases: raw.cases,      // 关联案例
    }
  }
}
```

**能力标签：** `law_query` · `case_search` · `citation_chain` · `rag_retrieve`

### 7.3 Personal Skill

```typescript
class PersonalSkill implements SkillContract {
  meta = { name: 'personal', domain: 'personal', cost: 'low', version: '1.0.0' }
  capabilityVector = embed(['memory_rw', 'schedule', 'preference', 'reminder'])

  async execute(intent: Intent, ctx: Context): Promise<SkillResult> {
    // 跨 Skill 联动示例：合同到期 → 自动触发 OpenLaw
    if (intent.type === 'contract_expiry_reminder') {
      await this.triggerSkill('openlaw', { query: '合同到期违约责任' })
    }
    return SkillResult.ok(await this.memory.read(intent))
  }
}
```

**能力标签：** `memory_rw` · `schedule` · `preference` · `reminder`

---

## 8. Adapter 隔离层

Adapter 是 Skill 与底层系统之间唯一的耦合点。

```
Skill 层              Adapter 层              系统层
   │                      │                     │
   │  DataQuery            │                     │
   ├─────────────────────► │   translate()        │
   │                       ├────────────────────►│  SQL / HTTP / API
   │                       │◄────────────────────┤
   │◄──────────────────────┤                     │
   │  SkillResult          │                     │
```

```typescript
interface IAdapter {
  execute(query: DataQuery): Promise<RawData>
}

// 注册表：运行时按 domain 选择 Adapter
const adapterRegistry = {
  system:  new MySQLAdapter(dbConfig),
  openlaw: new OpenLawAdapter(apiKey),
  // 切换系统只需在这里换实现类
}
```

---

## 9. 缓存策略

```
L1  Context 内存缓存     < 1ms    会话级    命中率目标 > 70%
L2  Redis 热数据缓存     < 10ms   跨会话    TTL 按数据类型配置
L3  系统 DB             ~100ms   持久化    冷数据兜底
LV  向量索引缓存         < 50ms   跨会话    OpenLaw RAG 专用
```

**缓存查找顺序：**

```typescript
async getData(key: string): Promise<Data> {
  return await this.l1.get(key)          // Context 内存
      ?? await this.l2.get(key)          // Redis
      ?? await this.l3.get(key)          // DB（并回填 L2）
}
```

---

## 10. OpenLaw 双轨检索

```
用户意图
  │
  ▼ 意图分类
  ├── 精确意图（含法条号 / 案号）
  │       │
  │       ▼ 直接索引查询
  │     法条内容                     < 80ms
  │
  └── 语义意图（"违约怎么赔"）
          │
          ▼ 向量化
        queryVec
          │
          ▼ Qdrant 近似检索（Top-K）
        候选法条集
          │
          ▼ Cross-Encoder Rerank
        精排结果
          │
          ▼ LLM 生成答案 + 引用链     < 500ms
```

### 输出格式

```typescript
interface LawSkillResult {
  answer:       string           // 自然语言回答
  citations: {
    articleId:  string           // 法条编号，如 "《合同法》第 107 条"
    text:       string           // 法条原文摘要
    confidence: number           // 0–1
  }[]
  relatedCases: CaseRef[]        // 相关判例
}
```

---

## 11. 韧性设计

### 超时熔断

```typescript
async executeWithTimeout(skill: Skill, ms = 3000): Promise<SkillResult> {
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new TimeoutError()), ms)
  )
  try {
    return await Promise.race([skill.execute(...), timeout])
  } catch (e) {
    if (e instanceof TimeoutError) return skill.fallback()  // 降级返回
    throw e
  }
}
```

### 指数退避重试

```typescript
async withRetry(fn: () => Promise<T>, maxRetries = 3): Promise<T> {
  for (let i = 0; i < maxRetries; i++) {
    try { return await fn() }
    catch {
      if (i === maxRetries - 1) throw e
      await sleep(100 * Math.pow(3, i))  // 100ms → 300ms → 900ms
    }
  }
}
```

### 健康探测

每个 Skill 暴露 `healthCheck()`，Agent 定时探测，故障自动从路由注册表下线。

---

## 12. 扩展性：新增 Skill 三步接入

**无需修改 Agent 任何代码。**

```typescript
// Step 1：实现 SkillContract
class CalendarSkill implements SkillContract {
  meta = { name: 'calendar', domain: 'system', cost: 'low', version: '1.0.0' }

  // Step 2：声明能力向量
  capabilityVector = embed(['schedule_read', 'schedule_write', 'reminder'])

  async execute(intent: Intent, ctx: Context) { /* 业务逻辑 */ }
  permissions = [Permission.READ_CALENDAR]
  async healthCheck() { return true }
}

// Step 3：注册
registry.register(new CalendarSkill())
// ↑ 完成，路由器自动发现，无需重启
```

---

## 13. 目录结构

```
personal-assistant/
├── agent/
│   ├── router.ts           # 向量路由器
│   ├── context.ts          # 上下文 + 会话管理
│   ├── executor.ts         # DAG 并行执行引擎
│   └── registry.ts         # Skill 注册表
│
├── skills/
│   ├── _base/
│   │   └── contract.ts     # SkillContract 接口定义
│   ├── system/
│   │   ├── skill.ts        # SystemSkill 实现
│   │   └── queries.ts      # DataQuery 定义
│   ├── openlaw/
│   │   ├── skill.ts        # OpenLawSkill 实现
│   │   └── retriever.ts    # 双轨检索器
│   └── personal/
│       └── skill.ts        # PersonalSkill 实现
│
├── adapters/               # Adapter 实现（唯一耦合点）
│   ├── mysql.adapter.ts
│   ├── rest.adapter.ts
│   └── openlaw.adapter.ts
│
└── cache/
    ├── l1-context.ts       # 会话级内存缓存
    ├── l2-redis.ts         # Redis 热数据
    └── lv-vector.ts        # 向量索引缓存
```

---

## 14. 设计原则总结

| 目标 | 实现手段 | 效果 |
|------|----------|------|
| **Skill 解耦** | SkillContract 统一接口 | 热插拔，Agent 零感知 |
| **系统解耦** | DataQuery + Adapter 隔离 | 换系统只改 Adapter |
| **执行效率** | 能力向量路由（< 5ms） | 路由不耗 LLM token |
| **并发性能** | DAG 并行调度 | 总耗时 = max 而非 sum |
| **热数据** | 三层缓存（L1/L2/L3） | 命中率 > 70% 不走 DB |
| **OpenLaw** | 双轨检索 + 引用链 | 精确 < 80ms，语义 < 500ms |
| **可观测性** | healthCheck + cost 预判 | 故障自动下线，用户感知成本 |
| **扩展性** | 3 步接入新 Skill | 不重启，不改 Agent |

> **最关键的一条：** Skill 永远不直接调用系统，只通过 `DataQuery` 声明数据需求。Adapter 是系统耦合唯一入口，可随时替换。
