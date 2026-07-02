# -*- coding: utf-8 -*-
# 《ETF全球投资指南》四大宽基轮动 · 仓位动态调整版
from jqdata import *

def initialize(context):
    g.assets = [
        '510300.XSHG',
        '513500.XSHG',
        '159915.XSHE',
        '513100.XSHG'
    ]
    g.cash_etf = '511880.XSHG'
    
    # 参数
    g.ma_trend = 60
    g.mom_day = 20
    g.position_count = 2
    
    # 仓位动态调整参数
    g.base_position = 1.0       # 基准仓位100%
    g.max_position = 1.0        # 最大仓位100%
    g.min_position = 0.1        # 最小仓位10%
    g.momentum_threshold_high = 0.03   # 动量>3%满仓
    g.momentum_threshold_low = -0.015   # 动量<-2%减仓
    
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))
    
    run_weekly(calc_signals_and_clear, weekday=1, time='09:31')
    run_weekly(buy_signals, weekday=1, time='09:32')
    

def calculate_position_ratio(signals):
    """根据市场整体动量计算仓位比例"""
    if not signals:
        return g.min_position
    
    # 取平均动量作为市场状态指标
    avg_mom = sum(s['mom'] for s in signals) / len(signals)
    max_mom = max(s['mom'] for s in signals)
    
    # 仓位计算公式
    if max_mom >= g.momentum_threshold_high:
        # 强势市场，满仓
        ratio = g.max_position
    elif max_mom <= g.momentum_threshold_low:
        # 弱势市场，减仓到最低
        ratio = g.min_position
    else:
        # 线性插值
        ratio = g.min_position + (max_mom - g.momentum_threshold_low) / \
                (g.momentum_threshold_high - g.momentum_threshold_low) * (g.max_position - g.min_position)
        ratio = max(g.min_position, min(g.max_position, ratio))
    
    return ratio

def calculate_individual_weight(signal, total_score):
    """根据得分分配个股权重"""
    if total_score == 0:
        return 1.0 / g.position_count
    
    # 按得分比例分配，但限制单只最大权重
    base_weight = signal['score'] / total_score
    return min(base_weight, 0.7)  # 单只最大70%
        
def calc_signals_and_clear(context):
    close_data = {}
    for code in g.assets:
        df = get_price(code, end_date=context.previous_date,
                       count=g.ma_trend + g.mom_day + 10, fields='close', fq='pre')
        close_data[code] = df

    # 计算信号
    signals = []
    for code in g.assets:
        df = close_data.get(code)
        if df is None or len(df.dropna()) < g.ma_trend + 1:
            continue
        close = df['close'].dropna()
        current = close.iloc[-1]
        ma = close.rolling(g.ma_trend).mean().iloc[-1]
        
        trend_dev = (current / ma) - 1
        mom = (current / close.iloc[-g.mom_day-1]) - 1
        
        signals.append({
            'code': code,
            'trend_dev': trend_dev,
            'mom': mom
        })

    # 综合打分
    for s in signals:
        if -0.05 <= s['trend_dev'] <= 0.10:
            trend_score = 1.0
        elif s['trend_dev'] > 0.10:
            trend_score = 0.7
        else:
            trend_score = 0.5 + (s['trend_dev'] + 0.05) * 5
        
        s['score'] = trend_score * (1 + s['mom'] * 5)

    signals.sort(key=lambda x: -x['score'])
    
    # 选取合格标的
    qualified = [s for s in signals if s['score'] > 0.8]
    
    if len(qualified) == 0:
        if signals[0]['score'] > 0.5:
            qualified = [signals[0]]
        

    # 动态仓位计算
    position_ratio = calculate_position_ratio(signals)
    
    
    # 动态权重分配
    selected = qualified[:min(g.position_count, len(qualified))]
    total_score = sum(s['score'] for s in selected)
    
    for s in selected:
        s['weight'] = calculate_individual_weight(s, total_score)
    g.selected = selected
    g.position_ratio = position_ratio
    log.info(f"calc_signals_and_clear {selected} 仓位上限{position_ratio}")
    if len(selected)>0:
        # 有交易信号，先清仓，后买入
        holdings = context.portfolio.positions
        for code in holdings:
            log.info(f"清仓{code}")
            order_target_value(code, 0)

def buy_signals(context):
    if not g.selected:
        return 
    selected = g.selected
    position_ratio = g.position_ratio
    available_value = context.portfolio.available_cash * position_ratio
    
    # 买入
    log.info("="*50)
    log.info(f"市场状态: 仓位{position_ratio*100:.0f}%, 可用资金{available_value:.0f}")
    log.info(f"选中标的: {[s['code'] for s in selected]}")
    
    for s in selected:
        target_value = available_value * s['weight']
        log.info(f"  {s['code']}: 趋势{s['trend_dev']*100:.1f}%, 动量{s['mom']*100:.1f}%, 得分{s['score']:.2f}, 权重{s['weight']*100:.0f}%, 金额{target_value:.0f}")
        order_target_value(s['code'], target_value)
    
    # 剩余资金买货币基金
    holdings = context.portfolio.positions
    stock_value = sum(holdings[s['code']].value for s in selected if s['code'] in holdings)
    cash_to_buy = context.portfolio.available_cash
    if cash_to_buy > 100:
        order_target_value(g.cash_etf, cash_to_buy)
        