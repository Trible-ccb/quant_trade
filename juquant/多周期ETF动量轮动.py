import numpy as np
import pandas as pd
from jqdata import *

def initialize(context):
    # 设置基准
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)

    # ETF交易成本：佣金万0.5，最低0.1元，无印花税
    set_order_cost(OrderCost(open_commission=0.00005,
                             close_commission=0.00005,
                             close_tax=0.0,
                             min_commission=0.1), type='fund')

    # 策略参数
    g.etf_pool = [
        '510300.XSHG',  # 沪深300ETF
        '510500.XSHG',  # 中证500ETF
        '159915.XSHE',  # 创业板ETF
        '588000.XSHG',  # 科创50ETF
        '512880.XSHG',  # 证券ETF
        '512010.XSHG',  # 医药ETF
        '515790.XSHG',  # 光伏ETF
        '512690.XSHG',  # 酒ETF
        '516160.XSHG',  # 新能源ETF
        '512480.XSHG',  # 半导体ETF
        '513100.XSHG',  # 纳指ETF
        '159920.XSHE',  # 恒生ETF
        '511010.XSHG',  # 国债ETF
        '518880.XSHG',  # 黄金ETF
    ]
    g.hold_num = 4                 # 持有ETF数量
    g.ma_days = 200                # 趋势过滤均线天数
    g.bull_ratio = 0.95            # 牛市仓位比例
    g.bear_ratio = 0.3             # 熊市仓位比例
    g.stop_profit = 0.15           # 止盈阈值
    g.stop_loss = 0.08             # 止损阈值
    g.cooldown_days = 10           # 止盈止损后冷却期（自然日）
    g.liquidity_threshold = 5e7    # 流动性阈值：日均成交额5000万元
    g.blocked = {}                 # 冷却期记录：{证券代码: 卖出日期}

    # 每日止盈止损检查（开盘后）
    run_daily(daily_stop_check, time='09:35')
    # 每周一调仓（在止盈止损检查之后）
    run_weekly(rebalance, weekday=1, time='09:40')


def daily_stop_check(context):
    """每日检查持仓止盈止损"""
    for sec in list(context.portfolio.positions.keys()):
        position = context.portfolio.positions[sec]
        if position.total_amount == 0:
            continue
        # 计算盈亏比例
        pnl_ratio = position.price / position.avg_cost - 1
        if pnl_ratio >= g.stop_profit or pnl_ratio <= -g.stop_loss:
            # 触发止盈或止损，全部卖出
            order_target(sec, 0)
            # 记录冷却期起始日期
            g.blocked[sec] = context.current_dt.date()
            log.info('止盈止损卖出 %s，盈亏比例 %.2f%%' % (sec, pnl_ratio * 100))


def rebalance(context):
    """每周调仓：先卖后买"""
    # 1. 市场趋势过滤
    index_data = get_price('000300.XSHG', count=g.ma_days + 1,
                           fields='close', skip_paused=True)
    if len(index_data) < g.ma_days + 1:
        return
    ma200 = index_data['close'][:-1].mean()
    current_close = index_data['close'][-1]
    target_ratio = g.bear_ratio if current_close < ma200 else g.bull_ratio

    # 2. 过滤流动性不足和冷却期内的ETF
    pool = filter_etf_pool(context)

    # 3. 计算动量得分
    if len(pool) == 0:
        # 无可用标的，清仓
        sell_all(context)
        return
    score = calc_momentum_score(pool, context)
    if score.empty:
        sell_all(context)
        return

    # 4. 选取目标持仓
    if score.max() < 0:
        # 所有ETF动量均为负，转入国债ETF（若可用且不在冷却期）
        if '511010.XSHG' in pool and not is_in_cooldown('511010.XSHG', context):
            selected = ['511010.XSHG']
        else:
            selected = []
    else:
        selected = score.nlargest(g.hold_num).index.tolist()

    # 5. 先卖后买
    # 先卖出所有不在目标列表中的持仓
    for sec in list(context.portfolio.positions.keys()):
        if sec not in selected:
            order_target(sec, 0)
    # 再买入目标ETF，按目标仓位等权分配
    if len(selected) > 0:
        weight = target_ratio / len(selected)
        total_value = context.portfolio.total_value
        for sec in selected:
            target_value = total_value * weight
            order_target_value(sec, target_value)
    # 若selected为空，持仓已全部卖出，保持空仓


def filter_etf_pool(context):
    """过滤流动性不足或处于冷却期的ETF"""
    etf_list = g.etf_pool
    # 获取过去20日成交额
    money_df = history(count=20, unit='1d', field='money',
                       security_list=etf_list, skip_paused=True,
                       df=True, fq=None)
    if money_df.empty:
        return []
    avg_money = money_df.mean()
    pool = []
    for etf in etf_list:
        # 流动性过滤
        if avg_money.get(etf, 0) < g.liquidity_threshold:
            continue
        # 冷却期过滤
        if is_in_cooldown(etf, context):
            continue
        pool.append(etf)
    return pool


def is_in_cooldown(sec, context):
    """判断证券是否处于止盈止损后的冷却期"""
    if sec in g.blocked:
        sell_date = g.blocked[sec]
        days_diff = (context.current_dt.date() - sell_date).days
        if days_diff < g.cooldown_days:
            return True
        else:
            # 冷却期结束，移除记录
            del g.blocked[sec]
    return False


def calc_momentum_score(etf_list, context):
    """计算动量得分：20/60/120日收益率加权，减去波动率惩罚"""
    close_df = history(count=121, unit='1d', field='close',
                       security_list=etf_list, skip_paused=True,
                       df=True, fq='pre')
    if close_df.empty:
        return pd.Series(dtype=float)
    score = {}
    for etf in etf_list:
        prices = close_df[etf].dropna()
        if len(prices) < 121:
            continue
        ret_20 = prices.iloc[-1] / prices.iloc[-21] - 1
        ret_60 = prices.iloc[-1] / prices.iloc[-61] - 1
        ret_120 = prices.iloc[-1] / prices.iloc[-121] - 1
        # 计算20日年化波动率
        returns = prices.pct_change().dropna()
        vol = returns.tail(20).std() * np.sqrt(252) if len(returns) >= 20 else 0
        # 合成得分（波动率惩罚系数0.3）
        momentum = 0.3 * ret_20 + 0.4 * ret_60 + 0.3 * ret_120
        score[etf] = momentum - 0.3 * vol
    if not score:
        return pd.Series(dtype=float)
    return pd.Series(score)


def sell_all(context):
    """清空所有持仓"""
    for sec in list(context.portfolio.positions.keys()):
        order_target(sec, 0)