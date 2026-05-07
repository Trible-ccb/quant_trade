# 龙头战法策略 - 快速启动示例

"""
这个文件展示了如何快速使用龙头战法策略。
选择下方任意一个方案，复制到聚宽回测/实盘环境即可运行。
"""

# ========== 方案 1：直接使用默认配置（最简单） ==========

"""
直接复制 longhead_dragon_strategy.py 的全部内容到聚宽环境，不需要任何修改。
该文件已包含平衡型配置，适合大多数市场环境。

优点：
  - 无需修改任何代码
  - 开箱即用
  
缺点：
  - 无法快速调整参数
"""


# ========== 方案 2：使用配置方案快速切换 ==========

"""
步骤 1：在聚宽环境新建策略文件，复制以下代码框架

步骤 2：根据市场环境，选择合适的配置方案

步骤 3：运行回测或实盘
"""

# -------- 框架代码开始 --------

# 【注意】此代码需在聚宽环境中修改以下部分后使用：
# 1. 解注释 from config_longhead_strategy import ... 相关行
# 2. 或直接复制配置值

from jqdata import *
import numpy as np
import pandas as pd
import datetime

# ===== 选择配置方案 =====
# 取消下方某一行的注释，选择要用的配置方案

# CONFIG_TYPE = 'BALANCED'      # 推荐：平衡型
CONFIG_TYPE = 'AGGRESSIVE'     # 激进型
# CONFIG_TYPE = 'CONSERVATIVE'   # 保守型
# CONFIG_TYPE = 'HIGHFREQ'      # 高频型
# CONFIG_TYPE = 'EXTREME'       # 极端型

# ===== 配置参数定义 =====
CONFIGS = {
    'BALANCED': {
        'open_price_drop_low': -0.04,
        'open_price_drop_high': -0.01,
        'relative_low_threshold': 0.30,
        'top_stock_count': 10
    },
    'AGGRESSIVE': {
        'open_price_drop_low': -0.06,
        'open_price_drop_high': -0.02,
        'relative_low_threshold': 0.25,
        'top_stock_count': 15
    },
    'CONSERVATIVE': {
        'open_price_drop_low': -0.02,
        'open_price_drop_high': 0.0,
        'relative_low_threshold': 0.35,
        'top_stock_count': 5
    },
    'HIGHFREQ': {
        'open_price_drop_low': -0.08,
        'open_price_drop_high': -0.03,
        'relative_low_threshold': 0.40,
        'top_stock_count': 20
    },
    'EXTREME': {
        'open_price_drop_low': -0.1,
        'open_price_drop_high': -0.05,
        'relative_low_threshold': 0.50,
        'top_stock_count': 25
    }
}

def initialize(context):
    """策略初始化"""
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, 
                             close_commission=0.0003, close_today_commission=0, min_commission=5), type='stock')
    log.set_level('order', 'error')
    
    # 加载选中的配置
    config = CONFIGS[CONFIG_TYPE]
    g.open_price_drop_low = config['open_price_drop_low']
    g.open_price_drop_high = config['open_price_drop_high']
    g.relative_low_threshold = config['relative_low_threshold']
    g.top_stock_count = config['top_stock_count']
    
    # 初始化其他变量
    g.yesterday_limit_up_list = []
    g.target_list = []
    g.hold_list = []
    g.buy_prices = {}
    g.buy_dates = {}
    g.buy_executed_today = False
    g.last_buy_date = None
    
    # 设置交易时间
    run_daily(execute_buy_order, '9:28')
    run_daily(check_profit_at_11_28, '11:28')
    run_daily(close_all_positions, '14:50')
    
    log.info(f"龙头战法策略启动 【{CONFIG_TYPE}配置】")
    log.info(f"参数：开盘{config['open_price_drop_low']*100:+.1f}%~{config['open_price_drop_high']*100:+.1f}% "
            f"低位{config['relative_low_threshold']*100:.0f}% Top{config['top_stock_count']}")

# -------- 框架代码结束 --------

# 【后续】复制 longhead_dragon_strategy.py 中的所有函数
# （从 get_yesterday_limit_up_stocks() 开始，到最后）

# ========== 方案 3：自定义参数微调 ==========

"""
如果您想在某个配置基础上微调参数，可以这样做：

1. 在 initialize() 函数的最后添加：

    # 在 AGGRESSIVE 基础上微调
    g.open_price_drop_high = 0.05      # 改成 5%（原本 6%）
    g.top_stock_count = 12              # 改成 12（原本 15）
    
2. 这样就可以快速测试新参数的效果
"""


# ========== 方案 4：参数网格搜索（回测优化） ==========

"""
如果您想在聚宽的参数优化功能中使用，可以这样做：

1. 修改 initialize() 中的配置加载为参数变量
2. 在聚宽"参数优化"中设置搜索范围

示例代码：

    # 将此段代码替换 initialize() 中的配置加载部分
    
    config = {
        'open_price_drop_low': params.open_drop_low,        # 参数化
        'open_price_drop_high': params.open_drop_high,      # 参数化
        'relative_low_threshold': params.rel_threshold,     # 参数化
        'top_stock_count': params.stock_count               # 参数化
    }
    
3. 在聚宽参数优化界面中设置：
    - open_drop_low: -0.03 to -0.01 step 0.01
    - open_drop_high: 0.02 to 0.08 step 0.02
    - rel_threshold: 0.20 to 0.40 step 0.05
    - stock_count: 5 to 20 step 5
"""


# ========== 方案 5：常见修改场景 ==========

"""
【场景 1】我想增加交易频率

修改以下参数：
    g.open_price_drop_low = -0.03       # 扩大下限（允许更低开）
    g.open_price_drop_high = 0.08       # 扩大上限（允许更高开）
    g.top_stock_count = 20              # 增加选股数量

【场景 2】我想降低风险

修改以下参数：
    g.open_price_drop_low = 0.0         # 只看平开或高开
    g.open_price_drop_high = 0.02       # 严格限制高开
    g.relative_low_threshold = 0.35     # 允许更宽松的"低位"定义
    g.top_stock_count = 5               # 减少选股数量，精选质量

【场景 3】我只想看特定行业的龙头

在 select_target_stocks() 函数中添加：
    # 获取行业列表
    industries = ['汽车', '电子', '医药']
    
    # 在过滤时添加行业检查
    for stock in filtered_list:
        current_data = get_current_data()
        if current_data[stock].industry in industries:
            # 继续处理该股票

【场景 4】我想添加成交量过滤

在 calculate_relative_position() 后添加：
    # 过滤成交量不足的股票
    for stock in valid_list:
        vol_data = get_price(stock, frequency='daily', fields=['volume'], count=60)
        if vol_data['volume'].mean() < 10000000:  # 日均成交量 < 1000万
            valid_list.remove(stock)
"""


# ========== 方案 6：A/B 测试对比 ==========

"""
如果您想同时回测两个配置方案进行对比，可以：

1. 创建两个策略副本，分别使用不同配置
2. 在聚宽"对比分析"功能中并排查看两个策略的表现
3. 根据对比结果选择最优配置

推荐对比组合：
  - BALANCED vs AGGRESSIVE  （稳健 vs 激进）
  - BALANCED vs CONSERVATIVE （标准 vs 保守）
  - 实际最优参数 vs BALANCED （优化后 vs 默认）
"""


# ========== 方案 7：本地验证测试 ==========

"""
如果您想在部署到聚宽前做本地测试，可以：

1. 在本地聚宽研究环境创建新 notebook
2. 执行此代码验证配置加载是否正确

代码示例：

    # 在聚宽 Notebook 中运行
    
    from jqdata import *
    
    # 配置参数
    CONFIG = {
        'open_price_drop_low': -0.01,
        'open_price_drop_high': 0.04,
        'relative_low_threshold': 0.30,
        'top_stock_count': 10
    }
    
    # 验证配置
    print("配置已加载：")
    for key, value in CONFIG.items():
        print(f"  {key}: {value}")
    
    # 测试 2026-05-03 的选股效果
    auth('your_username', 'your_password')
    # ... 调用选股函数测试
"""


# ========== 快速对标配置选择决策树 ==========

"""
使用以下决策树快速选择配置方案：

                    ┌─ 市场行情？
                    │
        ┌───────────┼───────────┐
        │           │           │
       涨停多      常规      涨停少
        │           │           │
        │         ║►BALANCED   │
        │           │      ◄──┘
        │           │
        ├─强势？────┤
        │ ║►AGGRESSIVE
        │           │
        │        否 ├─► CONSERVATIVE
        │           │
        │        ║►EXTREME
        │
        └─ 继续拆分：
            ├─ 需要高频交易？  ──► HIGHFREQ
            ├─ 需要精准选择？  ──► CONSERVATIVE
            └─ 需要最大参与？  ──► EXTREME
"""


# ========== 监控指标对标表 ==========

"""
根据实际效果调整配置的监控指标：

指标              < 期望           正常            > 期望
─────────────────────────────────────────────────────────
日均交易笔数      增加参数范围    保持现状         减少参数范围
日均收益率        调整低位阈值    保持现状         调整参数
胜率（%）        >= 45%          50-60%          考虑优化
最大单日亏损      设置更严格      保持现状         放宽参数
"""

print("""
╔════════════════════════════════════════════════════════════════╗
║           龙头战法策略 - 快速启动指南                             ║
║                                                                ║
║ 推荐流程：                                                      ║
║  1. 复制 longhead_dragon_strategy.py 到聚宽（最简单）            ║
║  2. 或根据市场环境选择配置方案（方案 2）                        ║
║  3. 在聚宽进行回测验证                                           ║
║  4. 根据回测结果微调参数（方案 3）                               ║
║  5. 启动实盘或继续优化                                           ║
║                                                                ║
║ 需要帮助？参考 龙头战法_README.md                                 ║
╚════════════════════════════════════════════════════════════════╝
""")
