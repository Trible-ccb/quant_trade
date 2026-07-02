# -*- coding: utf-8 -*-
# 主流大宽基轮动 · 最终优化版
from jqdata import *
import numpy as np



# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper
import datetime

# 默认下单函数
TRADE_TYPE = 'no_live'  # 'live':实盘模式,其他值：用聚宽平台默认下单函数
(order,order_target_value,order_value,order_target)  = bt_wrapper.wrap_orders(order, order_target_value, order_value, order_target,TRADE_TYPE,log_func=log.info)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    log.info(f"process_initialize 重建配置 {datetime.datetime.now()}")
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured()

# =======================实盘配置End=======================================


def initialize(context):
    
    g.assets = [
        '510300.XSHG',   # 沪深300
        '513500.XSHG',   # 标普500
        '159915.XSHE',   # 创业板
        '513100.XSHG',    # 纳指100
        '518880.XSHG',  # 黄金ETF
        '588880.XSHG',  # 科创板
        '501018.XSHG',   # 南方原油
        '513400.XSHG',   # 道琼斯
        '510050.XSHG',   # 50ETF
        '512890.XSHG',   # 红利ETF
    ]
    g.cash_etf = '511880.XSHG'
    
    # 基础参数
    g.ma_trend = 60
    g.mom_day = 20
    g.position_count = 2
    
    # 仓位动态调整参数（原版）
    g.base_position = 1.0
    g.max_position = 1.0
    g.min_position = 0
    g.momentum_threshold_high = 0.03
    g.momentum_threshold_low = -0.02
    
    # ========== 优化5参数（市场强度过滤） ==========
    g.ma_slope_threshold = -0.01
    g.enable_cross_market_filter = True
    
    g.weak_market_min_position = 0.05
    
    g.holding_high_price = {}
    
    # ========== 改进1参数（波动率目标调整） ==========
    g.vol_target_lookback = 20        # 波动率计算窗口
    g.target_annual_vol = 0.18        # 目标年化波动率 18%
    g.max_vol_adj = 1.5               # 最大上调系数
    
    # ========== 改进2参数（排名缓冲） ==========
    g.rebalance_threshold = 0.05      # 得分变化超过5%才强制调仓（预留，当前只做持仓比较）
    g.skip_rebalance = False           # 是否跳过本次调仓
    
    # ========== 改进5参数（相对动量） ==========
    # 使用 rel_mom 替代绝对动量，权重更高
    
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))
    
    # 主调仓：每周一执行
    run_weekly(calc_signals_and_clear, weekday=1, time='09:30')
    run_weekly(buy_signals, weekday=1, time='09:31')


# ================= 优化5：市场强度过滤 =================
def get_market_trend_strength(context):
    """判断整体市场强弱，返回 -1(弱势)、0(中性)、1(强势)"""
    sh_index = '000300.XSHG'
    us_index = '513500.XSHG'
    try:
        sh_df = get_price(sh_index, end_date=context.previous_date, count=g.ma_trend+10, fields='close', fq='pre')
        us_df = get_price(us_index, end_date=context.previous_date, count=g.ma_trend+10, fields='close', fq='pre')
        sh_close = sh_df['close'].dropna()
        us_close = us_df['close'].dropna()
        if len(sh_close) < g.ma_trend or len(us_close) < g.ma_trend:
            return 0
        sh_ma = sh_close.rolling(g.ma_trend).mean().iloc[-1]
        us_ma = us_close.rolling(g.ma_trend).mean().iloc[-1]
        sh_current = sh_close.iloc[-1]
        us_current = us_close.iloc[-1]
        sh_above = sh_current > sh_ma
        us_above = us_current > us_ma
        
        sh_ma_series = sh_close.rolling(g.ma_trend).mean()
        if len(sh_ma_series) >= 5:
            sh_slope = (sh_ma_series.iloc[-1] - sh_ma_series.iloc[-5]) / sh_ma_series.iloc[-5]
        else:
            sh_slope = 0
        us_ma_series = us_close.rolling(g.ma_trend).mean()
        if len(us_ma_series) >= 5:
            us_slope = (us_ma_series.iloc[-1] - us_ma_series.iloc[-5]) / us_ma_series.iloc[-5]
        else:
            us_slope = 0
        
        if (not sh_above and sh_slope < g.ma_slope_threshold) and (not us_above and us_slope < g.ma_slope_threshold):
            return -1
        if sh_above and us_above and sh_slope > 0 and us_slope > 0:
            return 1
        return 0
    except:
        return 0

def apply_market_filter(position_ratio, market_strength):
    """根据市场强度调整仓位"""
    if market_strength == -1:
        new_ratio = min(position_ratio, g.weak_market_min_position)
        log.info("优化5触发：市场弱势，仓位从 %.2f 降至 %.2f" % (position_ratio, new_ratio))
        return new_ratio
    elif market_strength == 1:
        return min(position_ratio, g.max_position)
    else:
        return position_ratio


# ================= 改进1：波动率目标调整 =================
def apply_volatility_target(position_ratio, context, selected_with_weights):
    """
    根据已选中ETF的加权波动率调整整体仓位，使策略预期波动率接近目标值
    selected_with_weights: list of (code, weight)
    """
    if not selected_with_weights:
        return position_ratio
    total_vol = 0
    for code, weight in selected_with_weights:
        prices = get_price(code, end_date=context.previous_date, count=g.vol_target_lookback+1, 
                           fields='close', fq='pre')['close']
        rets = prices.pct_change().dropna()
        if len(rets) < 5:
            vol = 0.2  # 默认20%
        else:
            vol = rets.std() * np.sqrt(252)
        total_vol += weight * vol
    if total_vol <= 0:
        return position_ratio
    adj = g.target_annual_vol / total_vol
    adj = min(adj, g.max_vol_adj)   # 避免过度加仓
    new_ratio = position_ratio * adj
    new_ratio = max(g.min_position, min(g.max_position, new_ratio))
    log.info(f"波动率目标: 组合波动率{total_vol:.2%}, 调整系数{adj:.2f}, 仓位{position_ratio:.2f}->{new_ratio:.2f}")
    return new_ratio


# ================= 改进2 & 改进5：信号计算与排名缓冲 =================
def calc_signals_and_clear(context):
    # 获取收盘价数据
    close_data = {}
    for code in g.assets:
        df = get_price(code, end_date=context.previous_date,
                       count=g.ma_trend + g.mom_day + 10, fields='close', fq='pre')
        close_data[code] = df
    
    # 获取基准序列（用于相对动量）
    bench_df = get_price('000300.XSHG', end_date=context.previous_date,
                         count=g.ma_trend + g.mom_day + 10, fields='close', fq='pre')
    bench_close = bench_df['close'].dropna()
    
    signals = []
    for code in g.assets:
        df = close_data.get(code)
        if df is None or len(df.dropna()) < g.ma_trend + 1:
            continue
        close = df['close'].dropna()
        current = close.iloc[-1]
        ma = close.rolling(g.ma_trend).mean().iloc[-1]
        
        trend_dev = (current / ma) - 1
        
        # 改进5：计算相对动量（相对于沪深300的20日超额收益）
        etf_ret = current / close.iloc[-g.mom_day-1] - 1
        bench_ret = bench_close.iloc[-1] / bench_close.iloc[-g.mom_day-1] - 1
        rel_mom = etf_ret - bench_ret
        
        signals.append({
            'code': code,
            'trend_dev': trend_dev,
            'rel_mom': rel_mom
        })
    
    # 改进2：使用相对强度百分位作为得分（基于rel_mom）
    # 先收集所有rel_mom，计算百分位
    mom_values = [s['rel_mom'] for s in signals]
    for s in signals:
        # 相对强度百分位（过去20日相对动量的排名百分位）
        rank = sum(1 for v in mom_values if v < s['rel_mom']) / len(mom_values)
        s['rs_percentile'] = rank   # 0~1之间
    
    # 最终得分 = 趋势分 * (1 + 相对动量权重)
    for s in signals:
        # 趋势分沿用原逻辑
        if -0.05 <= s['trend_dev'] <= 0.10:
            trend_score = 1.0
        elif s['trend_dev'] > 0.10:
            trend_score = 0.7
        else:
            trend_score = 0.5 + (s['trend_dev'] + 0.05) * 5
        
        # 改进5：相对动量乘数放大（原绝对动量系数5改为相对动量系数10）
        s['score'] = trend_score * (1 + s['rel_mom'] * 10)
        # 同时保留百分位得分作为备用，这里直接用上述score
    
    signals.sort(key=lambda x: -x['score'])
    
    # 合格标的筛选（得分>0.8）
    qualified = [s for s in signals if s['score'] > 0.8]
    if len(qualified) == 0 and signals[0]['score'] > 0.5:
        qualified = [signals[0]]
    
    selected = qualified[:min(g.position_count, len(qualified))]
    
    # ---------- 改进2：排名缓冲，避免频繁调仓 ----------
    # 获取当前持仓（不含货币基金）
    current_holdings = [code for code, pos in context.portfolio.positions.items() 
                        if pos.total_amount > 0 and code != g.cash_etf]
    new_selected_codes = [s['code'] for s in selected]
    
    # 如果持仓与候选完全相同，且得分差异不大（可选），则跳过调仓
    if set(current_holdings) == set(new_selected_codes):
        g.skip_rebalance = True
        log.info("改进2：持仓未变，跳过本次调仓")
        return
    else:
        g.skip_rebalance = False
    
    # 计算仓位比例（基于原版绝对动量最大值，保留原有逻辑）
    # 注意：这里仍然使用原版 calculate_position_ratio，后续会经过市场过滤和波动率调整
    def calculate_position_ratio(signals):
        if not signals:
            return g.min_position
        max_mom = max(s.get('rel_mom', s.get('mom', 0)) for s in signals)   # 使用相对动量代替原mom
        if max_mom >= g.momentum_threshold_high:
            ratio = g.max_position
        elif max_mom <= g.momentum_threshold_low:
            ratio = g.min_position
        else:
            ratio = g.min_position + (max_mom - g.momentum_threshold_low) / \
                    (g.momentum_threshold_high - g.momentum_threshold_low) * (g.max_position - g.min_position)
        return max(g.min_position, min(g.max_position, ratio))
    
    position_ratio = calculate_position_ratio(signals)
    
    # 优化5：市场强度过滤
    market_strength = get_market_trend_strength(context)
    position_ratio = apply_market_filter(position_ratio, market_strength)
    
    # 改进1：波动率目标调整（需要传入权重，先计算临时权重）
    total_score = sum(s['score'] for s in selected)
    selected_with_weights = []
    for s in selected:
        if total_score == 0:
            weight = 1.0 / len(selected)
        else:
            weight = min(s['score'] / total_score, 0.7)
        selected_with_weights.append((s['code'], weight))
    position_ratio = apply_volatility_target(position_ratio, context, selected_with_weights)
    
    # 保存全局变量供买入使用
    g.selected = selected
    g.position_ratio = position_ratio
    # 保存权重
    for s, (_, w) in zip(selected, selected_with_weights):
        s['weight'] = w
    
    log.info(f"最终信号: {[(s['code'], s['score']) for s in selected]}, 仓位{position_ratio:.2f}")
    
    # 清仓（仅当需要调仓时）
    if not g.skip_rebalance:
        holdings = context.portfolio.positions
        for code in holdings:
            log.info(f"清仓{code}")
            order_target_value(code, 0)
        g.holding_high_price.clear()   # 重置止损记录


def buy_signals(context):
    if not g.selected or g.skip_rebalance:
        return
    selected = g.selected
    position_ratio = g.position_ratio
    available_value = context.portfolio.available_cash * position_ratio
    
    log.info("="*50)
    log.info(f"市场状态: 仓位{position_ratio*100:.0f}%, 可用资金{available_value:.0f}")
    log.info(f"选中标的: {[s['code'] for s in selected]}")
    
    for s in selected:
        target_value = available_value * s['weight']
        log.info(f"  {s['code']}: 趋势{s['trend_dev']*100:.1f}%, 相对动量{s['rel_mom']*100:.2f}%, "
                 f"得分{s['score']:.2f}, 权重{s['weight']*100:.0f}%, 金额{target_value:.0f}")
        order_target_value(s['code'], target_value)
        # 初始化止损最高价
        current_price = get_current_data()[s['code']].last_price
        g.holding_high_price[s['code']] = current_price
    
    # 剩余资金买货币基金
    cash_to_buy = context.portfolio.available_cash
    if cash_to_buy > 100:
        order_target_value(g.cash_etf, cash_to_buy)
        
def after_trade(context):
    log.info(f"after_trade")
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'backtest' not in context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(context.portfolio.positions)