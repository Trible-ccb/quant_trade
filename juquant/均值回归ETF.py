# -*- coding: utf-8 -*-
"""
基于布林带的ETF均值回归策略（聚宽回测版 · 买卖分离）
流程：9:31计算信号 -> 9:32执行卖出 -> 9:33执行买入
标的池：宽基ETF + 行业ETF + QDII ETF
过滤：布林带宽度 >= 15%（上轨至少比下轨大15%）
"""

import numpy as np
import pandas as pd
import datetime
from jqdata import *


# =======================实盘配置Start=======================================
import ths_jq_wrapper as ths_wrapper
# 默认下单函数
Live_Type = False  # 'True':启用实盘模式 只有模拟模式下生效，回测不生效,False：不实盘
(order,order_target_value,order_value,order_target)  = ths_wrapper.get_orders_func(order,order_target_value,order_value,order_target)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    # 初始化链接，同时覆盖默认下单函数
    ths_wrapper.configured(context, live=Live_Type)
# =======================实盘配置End=======================================

# ======================聚宽框架代码Start=======================================
def before_trading_start(context):
    try:
        if Live_Type:
            ok = ths_wrapper.is_ok()
            if not ok:
                send_message("同花顺服务端异常，检查云是否正常登录")
    except Exception as e:
        print(f"before_trading_start检查同花顺异常")
        
# =======================实盘配置End=======================================
M_DAYS = 25
MIN_MOM_SCORE = 0.1
MAX_MOM_SCORE = 3
BUY_SLIP = 0.005
MIN_GAP_DAYS = 5
MIN_HOLD_DAYS = 3
# 不同策略固定止损阈值,均线粘合、N宽基、全球宽基、自适应宽基,弱转强，红利增强，均线粘合个股，小市值
FIX_RATE_LIMITS = [0.05,0.035,0.035,0.035,0.035,0.035,0.05,0.035]

def after_trading_end(context):
    log_portfolio(context)
    log_status(context)

def init_histroy_status(context):
    total_init_cash = context.portfolio.available_cash
    g.total_init_cash = total_init_cash
    N = 10
    g.buy_date_history = {}
    g.sell_date_history = {}
    for i in range(0, N):
        g.buy_date_history[i] = {}
        g.sell_date_history[i] = {}

    g.subportfolio_infos = [
        
        ]
    # 根据上一次的策略终止态恢复状态
    g.sell_date_history={0: {'513100.XSHG': datetime.date(2026, 10, 7), '563300.XSHG': datetime.date(2026, 9, 28)}, 1: {'512890.XSHG': datetime.date(2026, 9, 21)}, 2: {'159509.XSHE': datetime.date(2026, 10, 7),'513100.XSHG': datetime.date(2026, 10, 7)}, 3: {'159509.XSHE': datetime.date(2026, 10, 7)}, 4: {}, 5: {}, 6: {}, 7: {}, 8: {}, 9: {}}
# =======================公共辅助函数===========================
def log_status(context):
    # 对需要记录的状态打印日志，方便改代码后恢复使用
    clear_old_date_status(context,g.buy_date_history)
    clear_old_date_status(context,g.sell_date_history)
    log.info(f"g.buy_date_history={g.buy_date_history}")
    log.info(f"g.sell_date_history={g.sell_date_history}")

def clear_old_date_status(context,hist):
    now = context.current_dt.date()
    for idx in hist:
        dates = hist.get(idx)
        for code in list(dates.keys()):
            date = dates.get(code)
            valid = 0 <= (now - date).days < (30 * 2)
            if not valid:
                del dates[code]

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


def is_red_line(context,code):
    # 当前最新是否阳线
    cur = get_current_data()
    lp = cur[code].last_price
    open = cur[code].day_open
    return lp > open

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

def common_filter_stocks(context,stocks,st=True,kcb=True,cyb=True,days=60,paused=True):
    # 股票统一过滤函数
    filtered = []
    current_data = get_current_data()
    
    for s in stocks:
        if kcb and s.startswith('68'):
            continue
        if cyb and s.startswith('30'):
            continue
        if s.startswith('8') or s.startswith('4') or s.startswith('920'):
            continue
        info = get_security_info(s)
        name = info.display_name
        if st and (('ST' in name or '退' in name) or current_data[s].is_st):
            continue
        start_date = info.start_date
        if (context.current_dt.date() - start_date).days < days:
            continue
        if paused and current_data[s].paused:
            continue
        filtered.append(s)
    log.info(f"common_filter_stocks,before={len(stocks)},after={len(filtered)}")
    return filtered

# ================== 下单辅助函数 ==================
    
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
    subportfolio_infos = g.subportfolio_infos
    lens = len(subportfolio_infos)
    if Live_Type:
        log.info(f"打印整体账户收益和持仓情况"+"="*20)
        # 实盘模拟盘对比
        for i in range(0,lens):
            pindex = i
            bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context,pindex))
    # 模拟盘子账户记录
    total_init_cash = g.total_init_cash
    total_value = 0
    total_cash = 0
    for i in range(0,lens):
        info = subportfolio_infos[i]
        pindex = i
        init_cash = info.get('cash')
        name = info.get('name')
        if init_cash<=0:
            continue
        portfolio = get_portfolio(context,pindex)
        # 计算本策略的收益率
        portfolio_value = portfolio.total_value
        returns = (portfolio_value - init_cash) / init_cash
        cash = portfolio.available_cash
        total_cash = total_cash + cash
        total_value = total_value + portfolio_value
        cangwei = (1 - cash / portfolio_value) if portfolio_value>0 else 0
        log.info(f"|策略{pindex}.{name}，累计收益率={returns:.2%},总资产={portfolio_value:.2f}，仓位={cangwei:.2%}, 可用现金={cash:.2f}, 初始资金={init_cash:.2f}|")
        positions = get_portfolio_positions(context, pindex)
        for code, pos in positions.items():
            pnl = (pos.price / pos.avg_cost - 1) if pos.avg_cost else 0
            pos_cw = pos.value / portfolio_value if portfolio_value > 0 else 0
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
        if i == 4:
            record(弱转强=returns)
        if i == 5:
            record(红利增强=returns)
        if i == 6:
            record(均线粘合个股版=returns)
        if i == 7:
            record(小市值=returns)
    # 整体账户情况
    total_cw = 1 - total_cash / total_value if total_value>0 else 0
    total_returns = (total_value - total_init_cash) / total_init_cash
    log.info(f"整体账户情况,初始金额={total_init_cash}元，当前总资产={total_value:.2f}元，可用金额={total_cash:.2f},仓位={total_cw:.2%},收益率={total_returns:.2%}")
    record(仓位=total_cw)
    
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
        if code in g.sell_date_history[pindex]:
            del g.sell_date_history[pindex][code]
    elif action == 'sell':
        g.sell_date_history[pindex][code] = context.current_dt.date()
        if code in g.buy_date_history[pindex]:
            del g.buy_date_history[pindex][code]
            
def get_history(context,action,code,pindex=0):
    if action == 'buy':
        return g.buy_date_history[pindex].get(code, None)
    elif action == 'sell':
        return g.sell_date_history[pindex].get(code, None)
    return None

def is_buy_in_gaps_day(context,code,gaps,pindex=0):
    # 判断买入后，是否在gaps天内
    last_buy_date = get_history(context, 'buy', code, pindex)
    if last_buy_date:
        diff = (context.current_dt.date() - last_buy_date).days
        if  0 <= diff < gaps:
            return True
            log.info(f"【策略{pindex+1}】{code} 买入日期 {last_buy_date}，间隔不足{gaps}天，跳过")
        return False
    return True

def is_sell_in_gaps_day(context,code,gaps,pindex=0):
    # 判断卖出后，是否在gaps天内
    last_sell_date = get_history(context, 'sell', code, pindex)
    if last_sell_date:
        diff = (context.current_dt.date() - last_sell_date).days
        if  0 <= diff < gaps:
            return True
            log.info(f"【策略{pindex+1}】{code} 上次卖出日期 {last_sell_date}，间隔不足{gaps}天，跳过")
        return False
    return True
    
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
        diff_value = target_value - had_value
        if action == 'sell' and diff_value < 0:
            if target_value==0:
                order(code, -pos.closeable_amount, style,pindex = pindex)
                record_history(context,action,code,pindex)
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(pos.closeable_amount, sell_amount)
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

# ============================================================
# 一、初始化
# ============================================================
def initialize(context):
    # ---- 系统设置 ----
    common_initialize(context)
    init_histroy_status(context)

    # ---- 策略参数 ----
    g.boll_period = 20
    g.boll_std = 2.0
    g.rsi_period = 14
    g.rsi_threshold = 30
    g.ma_long = 200
    g.band_width_min = 0.15       # 布林带宽度下限
    g.adx_threshold = 25
    g.max_hold_days = 20

    # ---- 仓位控制 ----
    g.max_positions = 8
    g.single_position_pct = 0.10
    g.batch_ratio = [0.4, 0.3, 0.3]

    # ---- 风控 ----
    g.stop_loss_pct = 0.05
    g.zscore_stop = -3.5
    g.consecutive_loss_limit = 3
    g.pause_days = 10

    # ---- 策略状态 ----
    g.consecutive_losses = 0
    g.pause_until = None
    g.entry_info = {}
    # 信号容器（每日9:31重置）
    g.sell_signals = []           # [(code, reason, is_loss)]
    g.buy_signals = []            # [dict, ...]

    # ---- 标的池 ----
    g.broad_etfs = [
        '510300.XSHG', '510500.XSHG', '512100.XSHG', '588000.XSHG',
    ]
    g.industry_etfs = [
        '512480.XSHG', '512010.XSHG', '512660.XSHG',
        '516160.XSHG', '159928.XSHE', '512400.XSHG',
    ]
    g.qdii_etfs = [
        '513100.XSHG', '513130.XSHG', '513030.XSHG',
    ]
    g.all_etfs = g.broad_etfs + g.industry_etfs + g.qdii_etfs

    # ---- 三段式定时任务 ----
    run_daily(before_market_open, time='before_open')
    run_daily(calc_signals,       time='09:31')   # 计算信号
    run_daily(execute_sell,       time='09:32')   # 仅卖出
    run_daily(execute_buy,        time='09:33')   # 仅买入


# ============================================================
# 二、盘前准备
# ============================================================
def before_market_open(context):
    if g.pause_until is not None:
        if context.current_dt.date() >= g.pause_until:
            g.pause_until = None
            g.consecutive_losses = 0
            log.info('策略暂停期结束，重新激活')


# ============================================================
# 三、9:31 —— 计算买卖信号
# ============================================================
def calc_signals(context):
    """计算当日全部买卖信号，不执行任何交易"""
    g.sell_signals = []
    g.buy_signals = []

    # ---- 策略暂停检查 ----
    if g.pause_until is not None:
        return

    # ---- 1. 计算卖出信号 ----
    for code in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[code]
        if pos.total_amount == 0:
            continue

        current_price = get_current_price(code)
        info = g.entry_info.get(code)
        if info is None or current_price is None:
            continue

        # 止盈：价格回归中轨
        if current_price >= info['take_profit_price']:
            g.sell_signals.append((code, '止盈', False))
            continue

        # 硬性止损
        if current_price <= info['entry_price'] * (1 - g.stop_loss_pct):
            g.sell_signals.append((code, '硬性止损', True))
            continue

        # 均值失效止损
        zscore = calc_zscore(code)
        if zscore is not None and zscore <= g.zscore_stop:
            g.sell_signals.append((code, '均值失效止损', True))
            continue

        # 时间止损
        hold_days = len(get_trade_days(
            start_date=info['entry_date'],
            end_date=context.current_dt.date()
        ))
        if hold_days >= g.max_hold_days:
            g.sell_signals.append((code, '时间止损', False))

    # ---- 2. 计算买入信号 ----
    # 预估卖出后剩余持仓数
    current_positions = sum(
        1 for c in context.portfolio.positions
        if context.portfolio.positions[c].total_amount > 0
    )
    sell_codes = set(s[0] for s in g.sell_signals)
    remaining_positions = current_positions - len(sell_codes)
    slots = g.max_positions - remaining_positions

    if slots <= 0:
        return

    # 预估可用资金（当前现金 + 卖出回笼资金）
    total_value = context.portfolio.total_value
    available_cash = context.portfolio.available_cash
    for code in sell_codes:
        pos = context.portfolio.positions[code]
        px = get_current_price(code)
        if px is not None:
            available_cash += pos.total_amount * px * 0.998   # 扣除手续费

    # 遍历标的池
    candidates = []
    for code in g.all_etfs:
        # 跳过已持仓且未计划卖出的标的
        if code in context.portfolio.positions and \
           context.portfolio.positions[code].total_amount > 0 and \
           code not in sell_codes:
            continue

        df = get_history_data(code, g.boll_period + 1)
        if df is None or len(df) < g.boll_period:
            continue

        boll = calc_bollinger(df, g.boll_period, g.boll_std)
        if boll is None:
            continue

        upper, middle, lower, std = (
            boll['upper'], boll['middle'], boll['lower'], boll['std']
        )
        current_price = df['close'].iloc[-1]

        # ---- 布林带宽度过滤 ----
        if lower <= 0:
            continue
        band_width = (upper - lower) / lower
        if band_width < g.band_width_min:
            continue

        # ---- 价格跌破下轨 ----
        if current_price > lower:
            continue

        # ---- Z-Score ----
        if std <= 0:
            continue
        zscore = (current_price - middle) / std
        if zscore > -2.0:
            continue

        # ---- RSI ----
        rsi = calc_rsi(df['close'], g.rsi_period)
        if rsi is None or rsi >= g.rsi_threshold:
            continue

        # ---- 趋势过滤 ----
        if not check_trend_filter(code):
            continue

        # ---- QDII 溢价率过滤 ----
        if code in g.qdii_etfs:
            premium = get_qdii_premium(code)
            if premium is not None and abs(premium) > 3.0:
                continue

        candidates.append({
            'code': code,
            'zscore': zscore,
            'price': current_price,
            'middle': middle,
            'band_width': band_width,
        })

    # 按Z-Score升序（最超卖优先）
    candidates.sort(key=lambda x: x['zscore'])

    # 生成买入信号（按仓位约束截断）
    for cand in candidates[:slots]:
        position_value = total_value * g.single_position_pct * g.batch_ratio[0]
        position_value = min(position_value, available_cash * 0.5)
        if position_value < 1000:
            continue

        cand['target_value'] = position_value
        cand['take_profit_price'] = cand['middle']
        g.buy_signals.append(cand)
        available_cash -= position_value

    log.info('信号计算完成 | 卖出:%d 买入:%d' % (
        len(g.sell_signals), len(g.buy_signals)
    ))


# ============================================================
# 四、9:32 —— 仅执行卖出
# ============================================================
def execute_sell(context):
    """执行9:31计算出的卖出信号"""
    if not g.sell_signals:
        return

    for code, reason, is_loss in g.sell_signals:
        pos = context.portfolio.positions.get(code)
        if pos is None or pos.total_amount == 0:
            continue

        # 涨跌停/停牌检查
        if not can_trade_now(code):
            log.info('无法卖出 %s（停牌/涨跌停），跳过' % code)
            continue

        order = order_target_value(code, 0)
        if order is not None and order.filled > 0:
            log.info('卖出 %s | 原因:%s | 成交价:%.3f' % (
                code, reason, order.price
            ))
            if code in g.entry_info:
                del g.entry_info[code]
            if is_loss:
                record_loss()
        else:
            log.info('卖出失败 %s | 原因:%s' % (code, reason))


# ============================================================
# 五、9:33 —— 仅执行买入
# ============================================================
def execute_buy(context):
    """执行9:31计算出的买入信号（此时卖出资金已回笼）"""
    if not g.buy_signals:
        return

    # 实时持仓数再次校验（防止卖出失败导致超仓）
    current_positions = sum(
        1 for c in context.portfolio.positions
        if context.portfolio.positions[c].total_amount > 0
    )

    for cand in g.buy_signals:
        if current_positions >= g.max_positions:
            break

        code = cand['code']

        # 已持仓则跳过
        pos = context.portfolio.positions.get(code)
        if pos is not None and pos.total_amount > 0:
            continue

        if not can_trade_now(code):
            log.info('无法买入 %s（停牌/涨跌停），跳过' % code)
            continue

        # 用最新可用资金校验
        target_value = min(
            cand['target_value'],
            context.portfolio.available_cash * 0.95
        )
        if target_value < 1000:
            continue

        order = order_target_value(code, target_value)
        if order is not None and order.filled > 0:
            g.entry_info[code] = {
                'entry_price': order.price,
                'entry_date': context.current_dt.date(),
                'take_profit_price': cand['take_profit_price'],
                'batch': 1,
                'zscore_entry': cand['zscore'],
            }
            current_positions += 1
            log.info('买入 %s | 价:%.3f | Z:%.2f | 带宽:%.2f%% | 止盈:%.3f' % (
                code, order.price, cand['zscore'],
                cand['band_width'] * 100, cand['take_profit_price']
            ))


# ============================================================
# 六、技术指标
# ============================================================
def calc_bollinger(df, period, num_std):
    if len(df) < period:
        return None
    close = df['close']
    middle = close.iloc[-period:].mean()
    std = close.iloc[-period:].std()
    if std == 0:
        return None
    return {
        'upper': middle + num_std * std,
        'middle': middle,
        'lower': middle - num_std * std,
        'std': std,
    }


def calc_rsi(close_series, period=14):
    if len(close_series) < period + 1:
        return None
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.iloc[-period:].mean()
    avg_loss = loss.iloc[-period:].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_zscore(code):
    df = get_history_data(code, g.boll_period)
    if df is None or len(df) < g.boll_period:
        return None
    boll = calc_bollinger(df, g.boll_period, g.boll_std)
    if boll is None or boll['std'] == 0:
        return None
    return (df['close'].iloc[-1] - boll['middle']) / boll['std']


# ============================================================
# 七、辅助函数
# ============================================================
def check_trend_filter(code):
    df = get_history_data(code, g.ma_long)
    if df is None or len(df) < g.ma_long:
        return False
    ma200 = df['close'].iloc[-g.ma_long:].mean()
    return df['close'].iloc[-1] > ma200


def get_history_data(code, count):
    try:
        df = attribute_history(
            code, count, '1d',
            ['close', 'high', 'low', 'volume'],
            skip_paused=True, df=True, fq='pre'
        )
        return df if df is not None and len(df) > 0 else None
    except Exception:
        return None


def get_current_price(code):
    try:
        data = get_current_data()
        if code in data:
            return data[code].last_price
    except Exception:
        pass
    return None


def can_trade_now(code):
    """检查标的当前是否可交易（非停牌、非涨跌停）"""
    try:
        data = get_current_data()
        d = data[code]
        if d.paused:
            return False
        if d.last_price >= d.high_limit * 0.999:
            return False
        if d.last_price <= d.low_limit * 1.001:
            return False
        return True
    except Exception:
        return False


def get_qdii_premium(code):
    """获取QDII ETF溢价率（%）。如JQData不提供，可返回None跳过过滤"""
    try:
        nav = get_fund_nav(code)
        if nav is not None and len(nav) > 0:
            current_nav = nav['nav'].iloc[-1]
            current_price = get_current_price(code)
            if current_nav > 0 and current_price is not None:
                return (current_price - current_nav) / current_nav * 100
    except Exception:
        pass
    return None


def record_loss():
    g.consecutive_losses += 1
    if g.consecutive_losses >= g.consecutive_loss_limit:
        g.pause_until = get_trade_days(
            start_date=datetime.date.today(),
            count=g.pause_days
        )[-1]
        log.warn('连续止损 %d 次，策略暂停至 %s' % (
            g.consecutive_losses, g.pause_until
        ))