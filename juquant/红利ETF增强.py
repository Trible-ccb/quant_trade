# 克隆自聚宽文章：https://www.joinquant.com/post/80122
# 标题：红利布林带+ris择时策略年化21
# 作者：邱1233

# coding=utf-8
# 聚宽版：CCI + RSI + 布林带策略（空仓自动买入货币/国债ETF）
# 原掘金策略移植，逻辑保持一致
# 改造：信号计算 → 先卖 → 后买，三步按 1 分钟间隔分别调度

import numpy as np
import pandas as pd
from jqdata import *


# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper
# 默认下单函数
Live_Type = False  # 'True':启用实盘模式 只有模拟模式下生效，回测不生效,False：不实盘
(order,order_target_value,order_value,order_target)  = bt_wrapper.get_orders_func(order,order_target_value,order_value,order_target)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured(context,Live_Type)
# =======================实盘配置End=======================================

# ======================聚宽框架代码Start=======================================
def before_trading_start(context):
    try:
        if Live_Type:
            ok = bt_wrapper.qmt_is_ok()
            if not ok:
                send_message("QMT服务端异常，检查云服务器是否正常登录qmt")
    except Exception as e:
        print(f"before_trading_start检查qmt异常")
        
# =======================实盘配置End=======================================
M_DAYS = 25
MIN_MOM_SCORE = 0.1
MAX_MOM_SCORE = 3
BUY_SLIP = 0.001
MIN_GAP_DAYS = 5
MIN_HOLD_DAYS = 3
# 不同策略固定止损阈值,均线粘合、N宽基、全球宽基、自适应宽基
FIX_RATE_LIMITS = [0.05,0.03,0.03,0.03]
N = 10

# =======================公共辅助函数===========================
def common_initialize(context):
    log.set_level('order', 'warning')
    log.set_level('system', 'warning')
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='fund')
    set_order_cost(OrderCost(open_tax=0, close_tax=1/1000,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                                 open_commission=0, close_commission=0,
                                 close_today_commission=0, min_commission=0), type="mmf")
    set_slippage(PriceRelatedSlippage(BUY_SLIP))
    g.buy_date_history = {}
    g.sell_date_history = {}
    for i in range(0,N):
        g.buy_date_history[i] = {}
        g.sell_date_history[i] = {}


def is_red_line(context,code):
    # 当前最新是否阳线
    cur = get_current_data()
    lp = cur[code].last_price
    open = cur[code].day_open
    return lp > open

# ================== 下单辅助函数 ==================
def is_temporarily_suspended(security, context, minute_count=10):
    """
    判断ETF是否盘中临时停牌
    通过检查最近N分钟是否有成交来判断，若无成交则视为临时停牌
    """
    try:
        # 获取最近N分钟的分钟线数据
        minute_data = get_price(
            security,
            end_date=context.current_dt,
            count=minute_count,
            frequency='1m',
            fields=['volume'],
            skip_paused=False,
            fq='pre'
        )
        # 无数据或数据为空，视为停牌
        if minute_data is None or minute_data.empty:
            return True
        # 最近N分钟成交量都为0，视为临时停牌
        if (minute_data['volume'] == 0).all():
            return True
        return False
    except Exception as e:
        log.debug(f"临时停牌检测异常 {security}: {e}")
        return False  # 异常时默认认为正常，避免误判
    
def can_not_deal(code,action=''):
    cur_data = get_current_data()
    cur_price = cur_data[code].last_price
    no_price = cur_price is None or cur_price <=0
    is_paused = cur_data[code].paused
    is_st = cur_data[code].is_st
    is_high_limit = cur_price>=cur_data[code].high_limit
    is_low_limit = cur_price<=cur_data[code].low_limit 
    can_not_deal = (no_price or is_paused or is_st)
    if 'sell' == action:
        can_not_deal = can_not_deal or is_low_limit
    elif 'buy' == action:
        can_not_deal = can_not_deal or is_high_limit
    else:
        can_not_deal = can_not_deal or is_low_limit or is_high_limit

    # 检查接近涨跌停
    prev_close = cur_data[code].day_open
    if prev_close and prev_close > 0:
        if cur_price >= prev_close * (1+0.0985):   # 接近涨停
            log.info(f'{code} 当前接近涨停，暂停买入')
            if action == 'buy':
                can_not_deal = True
        if cur_price <= prev_close * (1-0.0985):   # 接近跌停
            log.info(f'{code} 当前接近跌停，暂停卖出')
            if action == 'sell':
                can_not_deal = True

    if can_not_deal:
        log.info(f"{code} can_not_deal={can_not_deal},{action} no_price={no_price} is_paused={is_paused} is_st={is_st} is_high_limit={is_high_limit} is_low_limit={is_low_limit}")
    return can_not_deal

# ======================= 新增辅助函数（多账户支持） =======================
def log_portfolio(context):
    log.info(f"打印整体账户收益和持仓情况"+"="*20)
    if not hasattr(g,'subportfolio_infos'):
        return
    subportfolio_infos = g.subportfolio_infos
    lens = len(subportfolio_infos)
    if Live_Type:
        # 实盘模拟盘对比
        for i in range(0,lens):
            pindex = i
            bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context,pindex))
    # 模拟盘子账户记录
    for i in range(0,lens):
        info = subportfolio_infos[i]
        pindex = i
        init_cash = info.get('cash')
        name = info.get('name')
        if init_cash<=0:
            continue
        portfolio = get_portfolio(context,pindex)
        # 计算本策略的收益率
        returns = (portfolio.total_value - init_cash) / init_cash
        cash = portfolio.available_cash
        cangwei = (1 - cash / portfolio.total_value) if portfolio.total_value>0 else 0
        log.info(f"|策略{pindex}.{name}，累计收益率={returns:.2%},总资产={portfolio.total_value:.2f}，仓位={cangwei:.2%}, 可用现金={cash:.2f}, 初始资金={init_cash:.2f}|")
        positions = get_portfolio_positions(context, pindex)
        for code, pos in positions.items():
            pnl = (pos.price / pos.avg_cost - 1) if pos.avg_cost else 0
            pos_cw = pos.value / portfolio.total_value if portfolio.total_value > 0 else 0
            pos_name = get_security_name(code)
            log.info(f" -{code}/{pos_name}  持有{pos.total_amount}股 市值={pos.value:.2f}元 仓位={pos_cw:.1%}  均价={pos.avg_cost:.3f}  现价={pos.price:.3f}  盈亏={pnl:+5.2%}")
        if i == 0:
            record(均线收益率=returns)
        if i == 1:
            record(N宽基收益率=returns)
        if i == 2:
            record(全球宽基收益率=returns)
        if i == 3:
            record(自适应收益率=returns)
    
def has_subportfolio(context, pindex):
    return len(context.subportfolios) >= (pindex + 1)

def get_portfolio(context, pindex=0):
    if has_subportfolio(context, pindex):
        return context.subportfolios[pindex]
    return context.subportfolios[0]

def get_portfolio_positions(context, pindex=0):
    port = get_portfolio(context, pindex)
    if hasattr(port, 'long_positions'):
        return port.long_positions
    return context.portfolio.positions

def get_security_name(security):
    try:
        return get_security_info(security).display_name
    except Exception:
        return f"{security}-未知"

def record_history(context,action,code,pindex=0):
    if action == 'buy':
        g.buy_date_history[pindex][code] = context.current_dt.date()
    elif action == 'sell':
        g.sell_date_history[pindex][code] = context.current_dt.date()

def get_history(context,action,code,pindex=0):
    if action == 'buy':
        return g.buy_date_history[pindex].get(code, None)
    elif action == 'sell':
        return g.sell_date_history[pindex].get(code, None)
    return None

def safe_order_target_value(context,action,code,target_value,pindex=0):
    style = None
    if pindex > 0 and not has_subportfolio(context, pindex):
        pindex = 0

    positions = get_portfolio_positions(context,pindex)
    portfolio = get_portfolio(context,pindex)
    available_cash = portfolio.available_cash
    cur_data = get_current_data()
    price = cur_data[code].last_price
    is_kcb = code[:2] == '68'
    slip = BUY_SLIP
    limit_price = price*(1+slip) if action == 'buy' else price*(1-slip)
    style = MarketOrderStyle(limit_price)

    if code in positions:
        pos = positions[code]
        had_value = pos.value
        closeable_amount = pos.closeable_amount
        diff_value = target_value - had_value
        if action == 'sell' and diff_value < 0:
            if closeable_amount<=0:
                log.warn(f"safe_order_target_value ignore {action} {code} {pindex}, closeable_amount=0")
                return 0
            if target_value==0:
                order(code, -closeable_amount, style,pindex = pindex)
                record_history(context,action,code,pindex)
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(closeable_amount, sell_amount)
            if a_amount >= 100:
                order(code, -a_amount, style,pindex = pindex)
                record_history(context,action,code,pindex)
                return -1
        elif diff_value > 0:
            buy_value = min(available_cash, diff_value)
            amount = int(abs(buy_value)  / price // 100) * 100
            if amount >= 200 or (amount>=100 and not is_kcb):
                order(code, amount, style,pindex = pindex)
                record_history(context,action,code,pindex)
                return 1
            else:
                log.warn(f"safe_order_target_value ignore,holding {code} {amount} {style} {available_cash} {pindex}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style,pindex = pindex)
            record_history(context,'buy',code,pindex)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {code} {amount} {style} {available_cash} {pindex}")
    return 0

def take_fix_profit_check(context,rate_limit,pindex=0):
    """固定止盈法 每日检查持仓是否触发止盈"""
    current_data = get_current_data()
    positions = get_portfolio_positions(context,pindex)
    for code, pos in positions.items():
        if pos.closeable_amount <= 0 or can_not_deal(code,'sell'):
            continue
        current_price = current_data[code].last_price
        cost = pos.avg_cost
        rate = (current_price - cost)/cost
        is_take_profit = rate>=rate_limit
        if  is_take_profit:
            log.info(f"pindex={pindex} {code}止盈触发：{current_price} rate={rate:.3%}%")
            safe_order_target_value(context,'sell',code, 0,pindex=pindex)
# ======================聚宽框架代码Start=======================================

def after_code_changed(context):
    unschedule_all()
    s6_scheduler_tasks(context)

def initialize(context):
    s6_initialize(context)
    set_benchmark('512040.XSHG')


def s6_set_params(context):
    # ---------- 全局参数 ----------
    g.s6_trade_symbol = '512040.XSHG'   # 目标ETF（价值国富ETF）
    g.s6_money_symbol = '511880.XSHG'   # 空仓替代ETF（国债ETF，对应511260，银华511880）
    g.s6_cci_period = 14
    g.s6_rsi_period = 14
    g.s6_bb_period = 20
    g.s6_bb_std = 2
    g.s6_cci_buy_threshold = -180
    g.s6_rsi_sell_threshold = 74
    g.s6_data_count = 120

    # ---------- 当日信号缓存 ----------
    g.s6_signal = None          # 'SELL_TRADE_BUY_MONEY' / 'SELL_MONEY_BUY_TRADE'
                                # 'BUY_TRADE' / 'BUY_MONEY' / 'HOLD_TRADE' / 'HOLD_MONEY'
    g.s6_today_str = None
    g.s6_prev_date = None

def s6_scheduler_tasks(context):
    # ---------- 调度：计算信号 → 卖 → 买，间隔 1 分钟 ----------
    run_daily(s6_calc_signal, time='09:30')
    run_daily(s6_do_sell,     time='09:31')
    run_daily(s6_do_buy,      time='09:32')

def s6_initialize(context):
    # ---------- 系统设置 ----------
    common_initialize(context)
    s6_set_params(context)
    s6_scheduler_tasks(context)

# ================================================================
# 第一步：09:35 计算信号（只计算，不下单）
# ================================================================
def s6_calc_signal(context):
    g.s6_today_str = context.current_dt.strftime('%Y-%m-%d')
    g.s6_prev_date = context.previous_date.strftime('%Y-%m-%d')
    g.s6_signal = None

    # 拉取到前一个交易日为止的完整日线数据（前复权）
    data = attribute_history(g.s6_trade_symbol, g.s6_data_count, '1d',
                             ['high', 'low', 'close'],
                             skip_paused=True, df=True, fq='pre')
    if len(data) < max(g.s6_cci_period, g.s6_rsi_period, g.s6_bb_period) + 10:
        log.info('>>> [策略6] [%s] 数据不足（仅%d条），跳过' % (g.s6_today_str, len(data)))
        return
    data = data.ffill().bfill().dropna()

    closes = data['close'].values.astype(float)
    highs = data['high'].values.astype(float)
    lows = data['low'].values.astype(float)

    # ========== 1. 计算 CCI ==========
    tp = (highs + lows + closes) / 3.0
    ma_tp = pd.Series(tp).rolling(window=g.s6_cci_period).mean().values
    md = pd.Series(np.abs(tp - ma_tp)).rolling(window=g.s6_cci_period).mean().values
    cci = np.where(md != 0, (tp - ma_tp) / (0.015 * md), 0.0)
    cci = np.where(np.isnan(cci), 0.0, cci)

    # ========== 2. 计算 RSI ==========
    def calc_rsi(c, period):
        c = pd.Series(c).ffill().bfill().values.astype(float)
        deltas = np.diff(c)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = pd.Series(gains).rolling(period).mean().values
        avg_loss = pd.Series(losses).rolling(period).mean().values
        with np.errstate(divide='ignore', invalid='ignore'):
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        # 兼容旧版 NumPy：手动填充 NaN 为 50
        rsi = np.where(np.isnan(rsi), 50.0, rsi)
        return rsi

    rsi = calc_rsi(closes, g.s6_rsi_period)

    # ========== 3. 计算布林带 ==========
    ma = pd.Series(closes).rolling(window=g.s6_bb_period).mean().values
    std = pd.Series(closes).rolling(window=g.s6_bb_period).std().values
    upper_band = ma + g.s6_bb_std * std

    # ========== 信号计算（基于前一日） ==========
    prev_close = closes[-1]
    prev_cci = cci[-1]
    prev_rsi = rsi[-1]
    prev_upper = upper_band[-1]

    if len(closes) >= 2:
        prev2_close = closes[-2]
        prev2_upper = upper_band[-2]
        break_upper = (prev2_close >= prev2_upper) and (prev_close < prev_upper)
    else:
        break_upper = False

    buy_signal = prev_cci < g.s6_cci_buy_threshold
    sell_signal = (prev_rsi > g.s6_rsi_sell_threshold) and break_upper

    # ---------- 持仓查询 ----------
    pos_trade = 0
    pos_money = 0
    positions = get_portfolio_positions(context,pindex=5)
    if g.s6_trade_symbol in positions:
        pos_trade = positions[g.s6_trade_symbol].total_amount
    if g.s6_money_symbol in positions:
        pos_money = positions[g.s6_money_symbol].total_amount

    log.info('>>> [策略6][%s] 基于%s数据：收盘:%.4f CCI:%.2f RSI:%.2f 上轨:%.4f 持仓(%s):%d 货币:%d'
             % (g.s6_today_str, g.s6_prev_date, prev_close, prev_cci, prev_rsi, prev_upper,
                g.s6_trade_symbol, pos_trade, pos_money))
    log.info('>>> [策略6]  买入信号:%s | 卖出信号:%s (RSI>%d:%s 跌破上轨:%s)'
             % (buy_signal, sell_signal, g.s6_rsi_sell_threshold,
                prev_rsi > g.s6_rsi_sell_threshold, break_upper))

    # ---------- 生成操作指令（不执行） ----------
    if pos_trade > 0:
        if sell_signal:
            g.s6_signal = 'SELL_TRADE_BUY_MONEY'   # 卖目标ETF → 买货币ETF
        else:
            g.s6_signal = 'HOLD_TRADE'
    else:
        if buy_signal:
            if pos_money > 0:
                g.s6_signal = 'SELL_MONEY_BUY_TRADE'  # 卖货币ETF → 买目标ETF
            else:
                g.s6_signal = 'BUY_TRADE'             # 直接买目标ETF
        else:
            if pos_money == 0:
                g.s6_signal = 'BUY_MONEY'             # 空仓 → 买货币ETF
            else:
                g.s6_signal = 'HOLD_MONEY'

    log.info('>>> [策略6]  [09:35] 信号计算完成，当日指令：%s' % g.s6_signal)


# ================================================================
# 第二步：09:36 执行卖出
# ================================================================
def s6_do_sell(context):
    if g.s6_signal is None:
        log.info('>>> [策略6] [%s] 无有效信号，跳过卖出步骤' % g.s6_today_str)
        return

    if g.s6_signal == 'SELL_TRADE_BUY_MONEY':
        log.info('>>> [策略6] [09:36] 卖出目标ETF <<<')
        safe_order_target_value(context,'sell',g.s6_trade_symbol,0,pindex=5)
    elif g.s6_signal == 'SELL_MONEY_BUY_TRADE':
        log.info('>>> [策略6] [09:36] 卖出货币ETF <<<')
        safe_order_target_value(context,'sell',g.s6_money_symbol,0,pindex=5)
    else:
        log.info('>>> [策略6]  [09:36] 无需卖出操作（信号：%s）' % g.s6_signal)


# ================================================================
# 第三步：09:37 执行买入
# ================================================================
def s6_do_buy(context):
    if g.s6_signal is None:
        log.info('>>> [策略6] [%s] 无有效信号，跳过买入步骤' % g.s6_today_str)
        return
    portfolio = get_portfolio(context,pindex=5)
    total_value = portfolio.total_value

    if g.s6_signal == 'SELL_TRADE_BUY_MONEY':
        log.info('>>> [策略6] [09:37] 买入货币ETF <<<')
        safe_order_target_value(context,'buy',g.s6_money_symbol,total_value,pindex=5)

    elif g.s6_signal in ('SELL_MONEY_BUY_TRADE', 'BUY_TRADE'):
        log.info('>>> [策略6] [09:37] 买入目标ETF <<<')
        safe_order_target_value(context,'buy',g.s6_trade_symbol,total_value,pindex=5)

    elif g.s6_signal == 'BUY_MONEY':
        log.info('>>> [策略6] [09:37] 空仓，买入货币ETF <<<')
        safe_order_target_value(context,'buy',g.s6_money_symbol,total_value,pindex=5)

    else:
        log.info('>>> [策略6]  [09:37] 无需买入操作（信号：%s）' % g.s6_signal)
