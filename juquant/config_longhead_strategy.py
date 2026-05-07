# 龙头战法策略 - 参数配置示例

"""
本文件提供了龙头战法策略的常用参数配置方案。
可以根据市场环境和风险偏好选择相应的配置。
"""

# ========== 配置方案 1：平衡型（推荐） ==========
CONFIG_BALANCED = {
    'open_price_drop_low': -0.04,       # 开盘价下限 -4%
    'open_price_drop_high': -0.01,       # 开盘价上限 -1%
    'relative_low_threshold': 0.30,     # 相对位置阈值 30%
    'top_stock_count': 10,              # 选股数量 Top10
    'description': '平衡收益与风险，适合大多数市场环境'
}

# ========== 配置方案 2：激进型 ==========
CONFIG_AGGRESSIVE = {
    'open_price_drop_low': -0.06,       # 开盘价下限 -6%，范围更广
    'open_price_drop_high': -0.02,       # 开盘价上限 -2%，包含低开的龙头
    'relative_low_threshold': 0.25,     # 相对位置阈值 25%，选择更低位的股票
    'top_stock_count': 15,              # 选股数量 Top15，分散风险
    'description': '更积极的选股策略，追求更多的交易机会，风险较大'
}

# ========== 配置方案 3：保守型 ==========
CONFIG_CONSERVATIVE = {
    'open_price_drop_low': -0.02,       # 开盘价下限 -2%，只看平开或高开
    'open_price_drop_high': 0.0,         # 开盘价上限 0%，严格过滤
    'relative_low_threshold': 0.35,     # 相对位置阈值 35%，容忍范围更广
    'top_stock_count': 5,               # 选股数量 Top5，高度精选
    'description': '严格的选股标准，交易机会较少但质量更高'
}

# ========== 配置方案 4：高频型 ==========
CONFIG_HIGHFREQ = {
    'open_price_drop_low': -0.08,       # 开盘价下限 -8%，包含大幅低开
    'open_price_drop_high': -0.03,       # 开盘价上限 -3%，选择范围最大
    'relative_low_threshold': 0.40,     # 相对位置阈值 40%，最宽松的低位定义
    'top_stock_count': 20,              # 选股数量 Top20，每日交易数量多
    'description': '最大化交易频率，适合追求成交笔数的策略'
}

# ========== 配置方案 5：极端行情型 ==========
CONFIG_EXTREME = {
    'open_price_drop_low': -0.1,       # 开盘价下限 -10%，极端低开
    'open_price_drop_high': -0.05,       # 开盘价上限 -5%，极端高开
    'relative_low_threshold': 0.50,     # 相对位置阈值 50%，不限制低位
    'top_stock_count': 25,              # 选股数量 Top25，容量最大
    'description': '适应极端市场波动，如涨停潮时期'
}


# ========== 使用说明 ==========

def apply_config(strategy_context, config):
    """
    将配置应用到策略中
    
    使用方法：
    在 longhead_dragon_strategy.py 的 initialize() 函数中，
    在设置 g 变量前调用此函数：
    
        apply_config(g, CONFIG_BALANCED)
    
    或直接复制配置值到 initialize() 中。
    """
    strategy_context.open_price_drop_low = config['open_price_drop_low']
    strategy_context.open_price_drop_high = config['open_price_drop_high']
    strategy_context.relative_low_threshold = config['relative_low_threshold']
    strategy_context.top_stock_count = config['top_stock_count']


# ========== 市场环境适配建议 ==========

MARKET_RECOMMENDATIONS = {
    '强势行情（涨停多）': {
        'config': CONFIG_AGGRESSIVE,
        'reason': '涨停数量充足，可以更激进地筛选',
        'adjustment': '适当增加 top_stock_count 到 15-20'
    },
    '常规行情': {
        'config': CONFIG_BALANCED,
        'reason': '平衡的参数适应大多数市场',
        'adjustment': '根据回测结果微调 ±0.01 或 ±5'
    },
    '弱势行情（涨停少）': {
        'config': CONFIG_CONSERVATIVE,
        'reason': '严选高质量标的，避免过度交易',
        'adjustment': '降低 top_stock_count，提高 relative_low_threshold'
    },
    '极端行情（涨停潮）': {
        'config': CONFIG_EXTREME,
        'reason': '最大化参与度',
        'adjustment': '可进一步增加 top_stock_count'
    }
}


# ========== 参数调整工具函数 ==========

def create_custom_config(open_low=-0.01, open_high=0.04, 
                        relative_threshold=0.30, stock_count=10):
    """
    创建自定义配置
    
    示例：
        my_config = create_custom_config(
            open_low=-0.02,
            open_high=0.05,
            relative_threshold=0.25,
            stock_count=12
        )
    """
    return {
        'open_price_drop_low': open_low,
        'open_price_drop_high': open_high,
        'relative_low_threshold': relative_threshold,
        'top_stock_count': stock_count,
        'description': f'Custom: 开盘{open_low*100:+.0f}%~{open_high*100:+.0f}% 低位{relative_threshold*100:.0f}% Top{stock_count}'
    }


def print_config(config):
    """打印配置信息"""
    print("\n" + "="*60)
    print("当前配置：")
    print("="*60)
    print(f"开盘价涨跌幅范围: {config['open_price_drop_low']*100:+.1f}% ~ {config['open_price_drop_high']*100:+.1f}%")
    print(f"相对低位阈值: {config['relative_low_threshold']*100:.1f}%")
    print(f"选股数量: Top {config['top_stock_count']}")
    print(f"说明: {config['description']}")
    print("="*60 + "\n")


# ========== 参数对比分析 ==========

PARAMETER_ANALYSIS = {
    'open_price_drop_high': {
        '增加（如 0.06）': [
            '✓ 增加选股数量和交易机会',
            '✓ 适应高开龙头的机会',
            '✗ 可能选入高开后下跌的低质股'
        ],
        '减少（如 0.02）': [
            '✓ 提高选股质量，避免虚假龙头',
            '✓ 降低交易风险',
            '✗ 可能错过真实龙头的高开机会'
        ]
    },
    'relative_low_threshold': {
        '增加（如 0.40）': [
            '✓ 选股范围更广，交易机会多',
            '✓ 不排除中位股票',
            '✗ 相对低位定义模糊，质量下降'
        ],
        '减少（如 0.20）': [
            '✓ 严格要求底部位置，风险小',
            '✓ 选股质量高',
            '✗ 可能导致选股数量不足'
        ]
    },
    'top_stock_count': {
        '增加（如 15-20）': [
            '✓ 每日交易笔数多，提高成交机会',
            '✓ 分散风险',
            '✗ 每只股票分到的资金减少，收益下降'
        ],
        '减少（如 5）': [
            '✓ 集中在最好的标的，收益可能更高',
            '✓ 成交费用降低',
            '✗ 单只股票风险大，波动大'
        ]
    }
}


# ========== 集成到策略的代码片段 ==========

"""
要在 longhead_dragon_strategy.py 中使用此配置文件，
将以下代码添加到 initialize() 函数开始处：

    # 导入配置
    from config_longhead import CONFIG_BALANCED, apply_config
    
    # 应用配置
    apply_config(g, CONFIG_BALANCED)
    
    # 或手动设置
    g.open_price_drop_low = CONFIG_BALANCED['open_price_drop_low']
    g.open_price_drop_high = CONFIG_BALANCED['open_price_drop_high']
    g.relative_low_threshold = CONFIG_BALANCED['relative_low_threshold']
    g.top_stock_count = CONFIG_BALANCED['top_stock_count']
"""

if __name__ == '__main__':
    # 测试打印各配置
    print("龙头战法策略 - 参数配置方案汇总\n")
    
    for name, config in [
        ('平衡型', CONFIG_BALANCED),
        ('激进型', CONFIG_AGGRESSIVE),
        ('保守型', CONFIG_CONSERVATIVE),
        ('高频型', CONFIG_HIGHFREQ),
        ('极端型', CONFIG_EXTREME),
    ]:
        print(f"\n【{name}】")
        print_config(config)
    
    # 参数对比示例
    print("\n" + "="*60)
    print("参数调整建议")
    print("="*60)
    print("\n相对低位阈值影响：")
    for key, values in PARAMETER_ANALYSIS['relative_low_threshold'].items():
        print(f"\n  {key}:")
        for v in values:
            print(f"    {v}")
