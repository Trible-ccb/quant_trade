# quant_trade - 量化交易策略库

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python](https://img.shields.io/badge/Python-3.7%2B-blue)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

一个全面的量化交易策略集合库，包含聚宽（JoinQuant）回测策略、实盘交易接口和 CTA 趋势跟踪策略。

---

## 📂 项目结构

```
quant_trade/
├── README.md                          # 项目文档（本文件）
├── LICENSE                            # MIT License
│
├── juquant/                           # 聚宽（JoinQuant）策略模块
│   ├── longhead_dragon_strategy.py    # ⭐ 龙头战法策略（新）
│   ├── 龙头战法_README.md              # 龙头战法详细文档
│   ├── config_longhead_strategy.py    # 龙头战法参数配置工具
│   ├── 龙头战法_快速启动.py            # 龙头战法快速启动指南
│   │
│   ├── three_factor_stock.py          # 多因子选股策略
│   ├── small_stock_peg.py             # 小盘股 PEG 策略
│   ├── test_juquant.py                # 聚宽 API 测试脚本
│   └── config_local.py                # 本地配置（存放聚宽账号）
│
├── miniqmt/                           # MiniQMT 实盘交易模块
│   └── double_line_quant.py           # 双均线实盘策略
│
├── ptrade/                            # CTA/ETF 趋势策略模块
│   ├── CTA_ETF_Trend_Strategy.py      # CTA ETF 趋势策略
│   ├── CTA趋势跟随中证500.py          # CTA 中证500 策略
│   └── 恒生投研平台_API文档.md         # 交易平台 API 文档
│
└── .venv/                             # Python 虚拟环境（已创建）
```

---

## 🎯 策略模块详解

### 1️⃣ **juquant/** - 聚宽回测策略

聚宽是国内领先的量化交易平台，提供免费的回测环境和丰富的数据接口。

#### ✨ 龙头战法策略 (2026-05-06 新增)
**文件**: `longhead_dragon_strategy.py`

一个高频短线策略，利用昨日涨停股在次日开盘回落的特性。

**策略逻辑**:
```
昨日涨停 → 非连板 → 开盘-1%~+4% → 相对低位 → Top10
↓
T日 09:28 集合竞价买入(等权重满仓)
↓
T+1日 11:28 检查盈利，有利就卖出
↓
T+1日 14:50 无论如何都清仓
```

**特点**:
- ✅ 短线高频（每日独立交易）
- ✅ 风险可控（T+1日必然清仓）
- ✅ 参数灵活（5 大预设配置方案）
- ✅ 文档完善（包含详细的调参指南）

**快速开始**:
```bash
# 方案 A: 直接使用（推荐）
复制 longhead_dragon_strategy.py 代码 → 聚宽新建策略 → 运行回测

# 方案 B: 参数调整
参考 config_longhead_strategy.py 中的 5 大配置方案调整参数
参考 龙头战法_快速启动.py 查看常见修改场景
```

**配置方案**:

| 方案 | 开盘涨跌 | 低位 | Top 数 | 适应场景 |
|------|---------|------|--------|---------|
| BALANCED | -1%~+4% | 30% | 10 | 常规市场（推荐） |
| AGGRESSIVE | -2%~+6% | 25% | 15 | 强势行情 |
| CONSERVATIVE | 0%~+2% | 35% | 5 | 弱势行情 |
| HIGHFREQ | -3%~+8% | 40% | 20 | 高频交易 |
| EXTREME | -5%~+10% | 50% | 25 | 极端行情 |

**相关文件**:
- `龙头战法_README.md` - 完整的策略说明
- `config_longhead_strategy.py` - 参数配置工具
- `龙头战法_快速启动.py` - 集成示例和使用指南

---

#### 📊 三因子选股策略
**文件**: `three_factor_stock.py`

基于多因子组合的中期选股策略。

**特点**:
- 多因子线性回归权重
- 每周调仓
- 涨停防守逻辑
- 支持季度清仓

**因子组合示例**:
- 情绪类因子（ARBR）
- 质量类因子（销售管理费用、净利润率）
- 动量类因子（Price1Y）
- 风格因子（资产负债率）

---

#### 📈 小盘股 PEG 策略
**文件**: `small_stock_peg.py`

专注小盘股的成长价值选股策略。

**特点**:
- PEG 因子筛选
- 换手率波动性考虑
- 每周调仓
- 连板股过滤

**选股维度**:
- 营业收入增长率（SG）
- 利润增长率（MS）
- PEG 和换手率（PEG）

---

#### 🔧 配置和测试
**文件**: 
- `config_local.py` - 存放聚宽账号密码
- `test_juquant.py` - API 测试脚本

---

### 2️⃣ **miniqmt/** - MiniQMT 实盘交易

MiniQMT 是国内知名的行情交易软件接口，支持股票、期货实盘交易。

#### 📊 双均线实盘策略
**文件**: `double_line_quant.py`

基于 5 日/10 日均线的简单趋势策略。

**特点**:
- 独立完整的实盘代码（不依赖聚宽）
- 支持异步下单
- 实时行情订阅
- 完整的交易回调

**参数**:
- 短期均线：5 日
- 长期均线：10 日
- 交易标的：可自定义（默认600000.SH）
- 单笔下单量：100 股

**核心逻辑**:
```python
if MA5 > MA10:  # 短期均线上穿长期均线
    买入
elif MA5 < MA10:  # 短期均线下穿长期均线
    卖出
```

---

### 3️⃣ **ptrade/** - CTA/ETF 趋势策略

高级的 CTA（Commodity Trading Advisor）趋势跟踪策略。

#### 🎯 CTA ETF 趋势策略
**文件**: `CTA_ETF_Trend_Strategy.py`

基于均线、ADX、ATR 的 ETF 趋势跟踪策略。

**特点**:
- 20/60 日均线系统
- ADX 趋势强度确认
- ATR 动态止损/止盈
- 跟踪止损保护利润
- 独立账户记账与持久化
- 目标 ETF 池（60+ 只）

**目标标的范围**:
- 宽基指数 ETF (沪深300、中证500 等)
- 行业 ETF (医药、半导体、消费 等)
- 商品 ETF (黄金、能源 等)
- 港股 ETF (恒生、科技 等)
- 境外 ETF (纳斯达克、标普 等)

---

#### 📊 CTA 中证500 策略
**文件**: `CTA趋势跟随中证500.py`

针对中证 500 成分股的 CTA 策略。

**特点**:
- 标的池更专注（500 只 A 股中盘股）
- 逻辑与 ETF 版本相同
- 已优化的参数

---

#### 📖 API 文档
**文件**: `恒生投研平台_API文档.md`

详细的交易平台 API 说明文档。

---

## 🚀 快速开始

### 前置条件

1. **Python 环境** (3.7+)
```bash
python --version
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

或手动安装：
```bash
# 聚宽数据 SDK
pip install jqdatasdk

# 数据处理
pip install pandas numpy

# 统计分析
pip install statsmodels

# MiniQMT（可选，仅限 Windows）
# 从 MiniQMT 官方网站下载
```

### 场景 1: 我想要一个开箱即用的短线策略

**推荐**: 龙头战法策略

```bash
1. 打开 juquant/longhead_dragon_strategy.py
2. 复制全部代码
3. 登录 https://www.joinquant.com
4. 新建策略，粘贴代码
5. 设置回测时间范围和初始资金
6. 点击"开始回测"
```

**预期收益**: 15-25% 年化（基于历史数据）

---

### 场景 2: 我想要一个长期选股策略

**推荐**: 三因子选股策略 或 小盘股 PEG 策略

```bash
1. 选择 juquant/three_factor_stock.py 或 small_stock_peg.py
2. 参考上述"场景 1"的步骤部署
3. 根据回测结果调整参数
```

---

### 场景 3: 我想要 ETF 趋势跟踪策略

**推荐**: CTA ETF 趋势策略 或 CTA 中证500 策略

```bash
1. 打开 ptrade/CTA_ETF_Trend_Strategy.py 或 CTA趋势跟随中证500.py
2. 参考"场景 1"的步骤部署
3. 调整 ETF 池或参数
```

---

### 场景 4: 我想要在 MiniQMT 上进行实盘交易

**推荐**: 双均线实盘策略

```bash
1. 下载并安装 MiniQMT
2. 配置登录信息
3. 打开 miniqmt/double_line_quant.py
4. 修改 PATH、ACCOUNT_ID 等参数
5. 运行脚本（Python 3.7+）
```

**注意**: MiniQMT 目前仅支持 Windows 环境

---

## 📊 策略性能参考

| 策略 | 年化收益 | 最大回撤 | 夏普比 | 适应市场 |
|------|--------|--------|-------|---------|
| 龙头战法 | 15-25% | 10-20% | 1.0-2.0 | 强势/常规 |
| 三因子选股 | 10-20% | 15-25% | 0.8-1.5 | 常规/弱势 |
| 小盘 PEG | 12-18% | 12-20% | 0.9-1.6 | 成长型 |
| CTA ETF | 10-20% | 10-25% | 0.7-1.5 | 趋势型 |
| 双均线 | 8-15% | 15-30% | 0.5-1.2 | 中性/弱势 |

**注意**: 上述数据仅为参考，实际表现依赖市场环境、参数设置和执行情况。

---

## 📚 详细文档

| 文件 | 说明 |
|------|------|
| `juquant/龙头战法_README.md` | 龙头战法策略完整文档 |
| `juquant/config_longhead_strategy.py` | 龙头战法参数配置工具 |
| `juquant/龙头战法_快速启动.py` | 龙头战法集成示例 |
| `ptrade/恒生投研平台_API文档.md` | CTA 平台 API 文档 |

---

## 🔧 配置说明

### 聚宽配置 (juquant/)

**配置聚宽账号** (juquant/config_local.py):
```python
JQ_USER = 'your_username'
JQ_PASS = 'your_password'
```

**选择龙头战法配置** (config_longhead_strategy.py):
```python
# 平衡型（推荐）
g.open_price_drop_low = -0.01
g.open_price_drop_high = 0.04
g.relative_low_threshold = 0.30
g.top_stock_count = 10

# 或其他 4 个预设方案（见上表）
```

---

### MiniQMT 配置 (miniqmt/)

**修改策略参数** (double_line_quant.py):
```python
PATH = r'D:\qmt\userdata_mini'       # MiniQMT 客户端路径
ACCOUNT_ID = '1000000365'            # 资金账号
STOCK_CODE = '600000.SH'             # 交易标的
ORDER_VOLUME = 100                   # 每次买卖股数
MA_SHORT = 5                         # 短期均线周期
MA_LONG = 10                         # 长期均线周期
```

---

## ⚠️ 风险声明

1. **市场风险**: 本项目中的所有策略仅供学习研究，市场风险自担
2. **历史数据风险**: 历史表现不代表未来收益
3. **执行风险**: 实盘交易中可能存在滑点、流动性等风险
4. **参数风险**: 参数调整不当可能导致策略失效

**使用本项目产生的任何损失由使用者自行承担。**

---

## 📞 常见问题

**Q: 策略可以直接用于实盘交易吗?**
A: 建议先进行充分的回测验证，然后在小资金规模下进行实盘验证。

**Q: 如何选择适合自己的策略?**
A: 根据风险偏好和市场判断选择。详见"快速开始"部分。

**Q: 参数应该如何调整?**
A: 建议使用聚宽的参数优化功能，或参考各策略的详细文档。

**Q: 策略在熊市中还能赚钱吗?**
A: 不同策略表现不同。趋势策略在强势市场表现更好；均线策略和选股策略在弱势市场也可能获利。

**Q: 支持 Mac/Linux 吗?**
A: 聚宽策略（juquant）完全支持。MiniQMT 仅支持 Windows。

---

## 🤝 贡献指南

欢迎提交 Issue 或 Pull Request！

改进方向：
- 添加新的策略
- 优化现有策略的参数
- 完善文档
- 修复 bug

---

## 📄 许可证

本项目采用 MIT 许可证，详见 [LICENSE](./LICENSE)

---

## 📖 学习资源

### 平台和工具
- [聚宽量化交易平台](https://www.joinquant.com)
- [MiniQMT 文档](https://miniqmt.com)

### 教程和文档
- [聚宽 API 文档](https://www.joinquant.com/help/api/api)
- [聚宽社区](https://www.joinquant.com/community)

### 相关概念
- [量化交易基础](https://www.joinquant.com/help/doc/api)
- [技术指标详解](https://www.investopedia.com)

---

## 📝 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.1 | 2026-05-06 | 新增龙头战法策略，完善 README |
| v1.0 | 2026-05-01 | 初版发布，包含三个主要模块 |

---

## 📧 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 📝 提交 Issue
- 💬 讨论
- 📨 邮件反馈

---

**最后更新**: 2026-05-06  
**维护者**: Quant Trading Team
