# GSP发布与智能回滚自动化平台 - 部署与使用指南

## 一、系统简介

药品批发 GSP 管理系统版本发布与智能回滚自动化平台，是一套专为药品批发企业设计的版本发布管理系统，严格遵循《药品经营质量管理规范》(GSP)要求，实现发布全流程的自动化管控。

### 核心功能
- **发布前置校验**：GSP规则校验、进销存一致性校验、冷链完整性校验、药监接口连通性校验
- **分级审批流转**：常规迭代串行审批、紧急热修复并行审批、事后补签
- **仓库灰度发布**：分阶段灰度、实时监控、自动熔断与智能回滚
- **合规审计报表**：全程审计追溯、发布复盘、GSP合规报表

---

## 二、环境要求

### 2.1 软件环境
| 软件 | 版本要求 | 说明 |
|-----|---------|------|
| Python | 3.9+ | 推荐 3.10 或以上 |
| pip | 最新版 | Python包管理工具 |

### 2.2 依赖包
```
PyYAML >= 6.0
```

### 2.3 操作系统
- Windows 10/11 / Windows Server 2016+
- Linux (CentOS 7+, Ubuntu 18.04+)
- macOS 10.15+

---

## 三、安装部署

### 3.1 快速安装

1. **解压程序包**
```bash
unzip gsp-release-platform.zip
cd gsp-release-platform
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **验证安装**
```bash
python gsp_release.py --help
```

### 3.2 目录结构

```
gsp-release-platform/
├── gsp_release.py              # 主入口脚本
├── config/
│   └── config.yaml             # 系统配置文件
├── src/
│   ├── __init__.py
│   ├── common/                 # 公共工具模块
│   │   ├── __init__.py
│   │   └── utils.py
│   ├── pre_check/              # 前置校验模块
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── gsp_checker.py
│   │   ├── inventory_checker.py
│   │   ├── cold_chain_checker.py
│   │   └── drug_admin_checker.py
│   ├── approval/               # 审批流转模块
│   │   ├── __init__.py
│   │   └── engine.py
│   ├── gray_release/           # 灰度发布模块
│   │   ├── __init__.py
│   │   ├── gray_engine.py
│   │   └── circuit_breaker.py
│   └── audit/                  # 审计报表模块
│       ├── __init__.py
│       └── engine.py
├── docs/
│   └── 系统架构设计.md
├── data/                       # 数据目录（运行时生成）
│   ├── pre_check/
│   ├── approvals/
│   ├── gray_release/
│   ├── circuit_breaker/
│   ├── audit/
│   └── reports/
├── logs/                       # 日志目录（运行时生成）
├── sample_data.json            # 示例数据文件
├── requirements.txt            # 依赖包列表
└── README.md                   # 本文件
```

---

## 四、配置说明

### 4.1 配置文件位置
配置文件位于 `config/config.yaml`

### 4.2 核心配置项

#### 系统配置
```yaml
system:
  name: "GSP发布与智能回滚自动化平台"
  version: "1.0.0"
  env: "production"          # 环境: development/test/production
  log_level: "INFO"          # 日志级别: DEBUG/INFO/WARNING/ERROR
  log_path: "./logs"         # 日志目录
  data_path: "./data"        # 数据存储目录
```

#### 前置校验配置
```yaml
pre_check:
  gsp:
    enabled: true
    near_expiry_warning_days: 90    # 近效期预警天数
    expired_lock_enabled: true       # 过期药品自动锁定
    fifo_rule_enabled: true          # 先进先出规则
    fefo_rule_enabled: true          # 近效期先出规则
```

#### 灰度发布配置
```yaml
gray_release:
  stages:
    - stage: 1
      name: "常温库/普通药品库"
      warehouse_types: ["normal_temperature", "common_drug"]
      observation_hours: 2          # 观察期（小时）
      risk_level: "low"

  monitor:
    interval_seconds: 300           # 监控间隔（秒）
    metrics:
      document:
        purchase_error_rate:
          warning: 0.01             # 告警阈值 1%
          circuit_breaker: 0.05     # 熔断阈值 5%
```

#### 审批配置
```yaml
approval:
  channels:
    normal:
      name: "常规迭代"
      approval_mode: "serial"       # 串行审批
      timeout_hours: 72             # 审批超时时间
    hotfix:
      name: "紧急热修复"
      approval_mode: "parallel"     # 并行审批
      timeout_hours: 2
      post_signoff_hours: 48        # 事后补签时限
```

---

## 五、使用指南

### 5.1 命令总览

```bash
python gsp_release.py <命令> [子命令] [选项]
```

| 命令 | 子命令 | 说明 |
|-----|--------|------|
| `pre-check` | - | 发布前置校验 |
| `approval` | `create` | 创建审批流 |
| | `approve` | 审批通过 |
| | `reject` | 审批驳回 |
| | `status` | 查看审批状态 |
| `gray` | `start` | 启动灰度发布 |
| | `advance` | 推进灰度阶段 |
| | `status` | 查看灰度状态 |
| `rollback` | - | 触发熔断回滚 |
| `report` | `review` | 发布复盘报告 |
| | `monthly` | 月度成功率报表 |
| | `gsp` | GSP合规报表 |
| `audit` | `query` | 查询审计日志 |

### 5.2 发布前置校验

#### 基本用法
```bash
python gsp_release.py pre-check --version 2.0.0 --data-file sample_data.json
```

#### 输出示例
```
============================================================
GSP管理系统 - 发布前置校验报告
============================================================
发布ID: REL-20240120153000
版本号: 2.0.0
校验状态: 未通过
阻断级别: high

总检查项: 13
通过: 10
警告: 1
阻断: 2

各模块校验结果:
----------------------------------------
  ✗ GSP核心规则
    GSP规则校验未通过，2个核心指标不达标

  ✓ 进销存一致性 (含警告)
    进销存一致性校验通过，存在警告项

  ✓ 冷链记录完整性
    冷链记录完整性校验全部通过

  ✓ 药监接口连通性
    药监接口连通性校验全部通过

修复建议:
----------------------------------------
  1. 请补充以下企业资质文件: 山东新时代药业有限公司
  2. 过期药品锁定逻辑存在缺陷，2个过期批次未被锁定或仍可出库

============================================================
结论: 前置校验未通过，2个核心指标阻断发布，1个警告项，请修复后重新提交
============================================================
```

### 5.3 审批流程

#### 创建审批流（常规发布）
```bash
python gsp_release.py approval create --release-id REL-20240101 --channel normal --requester 开发部
```

#### 创建审批流（紧急热修复）
```bash
python gsp_release.py approval create --release-id REL-20240101 --channel hotfix --emergency-reason "生产环境单据生成失败，影响业务"
```

#### 审批通过
```bash
python gsp_release.py approval approve --flow-id APV-20240120153000 --node quality_manager --approver "李质量" --comment "GSP合规性审核通过，同意发布"
```

#### 审批驳回
```bash
python gsp_release.py approval reject --flow-id APV-20240120153000 --node quality_manager --approver "李质量" --reason "首营企业资质不完整，请补充后再提交"
```

#### 查看审批状态
```bash
python gsp_release.py approval status --flow-id APV-20240120153000
```

### 5.4 灰度发布

#### 启动灰度发布
```bash
python gsp_release.py gray start --release-id REL-20240101 --version 2.0.0 --target-version 1.9.0
```

#### 推进灰度阶段
```bash
python gsp_release.py gray advance --gray-id GRY-20240120153000
```

#### 查看灰度状态
```bash
python gsp_release.py gray status --gray-id GRY-20240120153000
```

### 5.5 熔断回滚

#### 手动触发熔断回滚
```bash
python gsp_release.py rollback --gray-id GRY-20240120153000 --reason "出库复核单据异常率超过5%，触发熔断" --level warehouse --target-version 1.9.0
```

#### 回滚级别说明
| 级别 | 适用场景 | 影响范围 |
|-----|---------|---------|
| `function` | 单一功能异常 | 仅回滚相关功能模块 |
| `warehouse` | 特定仓库异常 | 仅回滚受影响仓库版本 |
| `system` | 核心功能异常 | 整体回滚至上一稳定版本 |
| `data` | 数据异常或丢失 | 恢复数据备份 + 应用回滚 |

### 5.6 报表查询

#### 发布复盘报告
```bash
python gsp_release.py report review --release-id REL-20240101
```

#### 月度成功率报表
```bash
python gsp_release.py report monthly --month 2024-01
```

#### GSP合规报表
```bash
python gsp_release.py report gsp --period quarter
```

### 5.7 审计日志

#### 查询审计日志
```bash
python gsp_release.py audit query --start-date 2024-01-01 --end-date 2024-01-31
```

#### 按类型查询
```bash
python gsp_release.py audit query --log-type quality_gate
```

#### 按操作人查询
```bash
python gsp_release.py audit query --operator "李质量"
```

---

## 六、典型发布流程

### 6.1 常规迭代发布流程

```
1. 提交发布申请
   ↓
2. 触发前置校验
   ├─ GSP规则校验
   ├─ 进销存一致性校验
   ├─ 冷链完整性校验
   └─ 药监接口连通性校验
   ↓
3. 校验通过？
   ├─ 否 → 阻断发布，生成修复建议
   └─ 是 → 进入审批
   ↓
4. 四级串行审批
   ├─ 质量负责人审批
   ├─ 业务部门审批
   ├─ 质管部审批
   └─ IT部门审批
   ↓
5. 全部审批通过？
   ├─ 否 → 驳回，返回修改
   └─ 是 → 进入灰度发布
   ↓
6. 仓库灰度发布
   ├─ 第一阶段：常温库（观察2小时）
   ├─ 第二阶段：阴凉库（观察4小时）
   ├─ 第三阶段：冷藏库（观察8小时）
   └─ 第四阶段：特药库（持续监控）
   ↓
7. 监控指标正常？
   ├─ 是 → 进入下一阶段
   └─ 否 → 触发熔断 → 自动回滚
   ↓
8. 发布完成
   ↓
9. 生成复盘报告
```

### 6.2 紧急热修复发布流程

```
1. 发现严重问题
   ↓
2. 提交紧急发布申请
   ↓
3. 简化前置校验（核心指标）
   ↓
4. 并行审批（任一通过即可发布）
   ├─ 质量负责人
   ├─ 业务部门
   ├─ 质管部
   └─ IT部门
   ↓
5. 快速灰度/全量发布
   ↓
6. 发布后48小时内补签所有审批
   ↓
7. 生成偏差报告与复盘
```

---

## 七、外部系统集成

### 7.1 支持的外部系统
- WMS（仓储管理系统）
- ERP（企业资源计划系统）
- 冷链监控平台
- 药监追溯平台
- GSP管理系统

### 7.2 集成方式
系统通过标准HTTP API接口与外部系统集成，支持：
- 配置化接口地址
- API密钥认证
- 可配置超时时间
- 失败重试机制

配置示例：
```yaml
external_systems:
  wms:
    base_url: "http://wms.example.com/api"
    api_key: "your-api-key"
    timeout: 30
```

---

## 八、消息通知

系统支持多种消息通知渠道：

### 8.1 钉钉通知
```yaml
notification:
  dingtalk:
    enabled: true
    webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
    secret: "SECxxx"
```

### 8.2 企业微信通知
```yaml
notification:
  wechat_work:
    enabled: true
    webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
```

### 8.3 邮件通知
```yaml
notification:
  email:
    enabled: true
    smtp_host: "smtp.example.com"
    smtp_port: 465
    sender: "gsp-release@example.com"
    password: "your-password"
```

---

## 九、数据存储与安全

### 9.1 数据存储
- 配置数据：YAML文件
- 业务数据：JSON文件（按类型分目录存储）
- 审计日志：JSONL格式（按日期归档）
- 日志文件：按天滚动

### 9.2 安全特性
- 敏感数据加密存储
- 操作日志不可篡改
- 审计追溯完整记录
- 支持电子签名验证

---

## 十、常见问题

### Q1: 如何修改校验阈值？
A: 编辑 `config/config.yaml` 文件，找到对应模块的阈值配置进行修改。

### Q2: 如何新增审批节点？
A: 在配置文件的 `approval.serial_flow` 和 `approval.parallel_flow` 中添加节点ID，并在 `approvers` 中配置节点信息。

### Q3: 数据存储在哪里？
A: 默认存储在 `./data` 目录下，可通过配置文件中的 `system.data_path` 修改。

### Q4: 如何查看详细日志？
A: 日志文件存储在 `./logs` 目录下，按天生成日志文件。

### Q5: 支持多环境部署吗？
A: 支持。可以使用 `--config` 参数指定不同的配置文件，或通过环境变量覆盖配置。

---

## 十一、版本历史

| 版本 | 日期 | 说明 |
|-----|------|------|
| 1.0.0 | 2024-01-20 | 初始版本，实现四大核心模块功能 |

---

## 十二、技术支持

如有问题或建议，请联系技术支持团队。

---

**文档版本**: 1.0.0
**最后更新**: 2024-01-20
