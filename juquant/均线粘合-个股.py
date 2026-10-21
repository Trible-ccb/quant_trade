# 聚宽ETF多周期均线粘合 + BOLL开口策略
# 标的：市场主流ETF基金
# 买入：日线MA5/20/60粘合 + 120分钟BOLL开口 + 月线MACD>0
# 卖出：60分钟收盘价跌破MA20
# 风控：大盘仓位管理、规模过滤、流动性过滤

from jqdata import *
import numpy as np
import pandas as pd

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
FIX_RATE_LIMITS = [0.05,0.03,0.03,0.03,0.03,0.03,0.05]
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
                log.warn(f"safe_order_target_value ignore {action} {code} pindex={pindex}, closeable_amount=0")
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
                log.warn(f"safe_order_target_value ignore,holding {code} {amount} {style} {available_cash} pindex={pindex}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style,pindex = pindex)
            record_history(context,'buy',code,pindex)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {code} {amount} {style} {available_cash} pindex={pindex}")
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
def initialize(context):
    s7_initialize(context)

def before_trading_start(context):
    pass

def after_trading_end(context):
    log_portfolio(context)

def after_code_changed(context):
    unschedule_all()
    s7_after_code_changed(context)

def s7_set_params(context):
    # ---------- 策略核心参数 ----------
    g.s7_stock_num = 2                    # 最大持仓数
    g.s7_min_hold_days = 4                 # 最小持有天数
    g.s7_max_hold_days = 15                # 最大持有天数
    g.s7_max_cash_per_stock = 10*10000     # 单个标的最大金额
    g.s7_max_cash_ratio_per_stock = 1      # 单个标的占总仓比例
    g.s7_ma_short, g.s7_ma_mid, g.s7_ma_long = 5, 20, 60
    g.s7_convergence_threshold = 0.02     # 粘合阈值2%
    g.s7_consecutive_days = 2             # 连续N天均线粘合
    
    # 大盘风控参数
    g.s7_position_limit = 1.0 #上限满仓运行
    g.s7_fix_take_profit = 0.05
    
    
    
def s7_schedule_tasks(context):
    run_daily(s7_etf_pool_and_filters, time='14:01')   # 更新池
    run_daily(s7_trade_sell, time='14:44')     # 卖出交易判断
    run_daily(s7_trade_buy, time='14:45')     # 买入交易判断
    run_daily(s7_take_fix_profit, time='14:46')     # 止盈
    run_daily(s7_take_fix_profit, time='09:40')     # 止盈

def s7_take_fix_profit(context):
    # 固定止盈
    take_fix_profit_check(context,FIX_RATE_LIMITS[6],pindex=6)

# ========= 120日线均线上涨或当前价大于120日均线 ==========
def s7_check_ma120_increase(security, context):
    df = attribute_history(security, 150, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 120:
        return False
    cur_data = get_current_data()
    price = cur_data[security].last_price
    ma120_roll = df['close'].rolling(120).mean()
    ma120 = ma120_roll.iloc[-1]
    last_ma120 = ma120_roll.iloc[-2]
    is_above_ma120 = price > ma120 * (1+0.01)  # 当前价大于120日均线1%
    increase = ma120 > last_ma120
    return is_above_ma120 or increase

def s7_after_code_changed(context):
    s7_set_params(context)
    s7_schedule_tasks(context)
    
# ========== 1. 初始化函数 ==========   
def s7_initialize(context):
    common_initialize(context)
    s7_set_params(context)
    s7_schedule_tasks(context)
    
    # ---------- 缓存变量 ----------
    g.s7_etf_pool = []                     # ETF池
    g.s7_macd_positive = set()      # 月线MACD>0的ETF
    # 前一日历史粘合记录
    g.s7_ma_converged_pre_day = []


def s7_get_index_stocks_list(context):
    zz1000stocks = []
    hs300stocks = get_index_stocks('000300.XSHG',date=context.current_dt)
    zz500stocks = get_index_stocks('000905.XSHG',date=context.current_dt)
    # zz1000stocks = get_index_stocks('399852.XSHE',date=context.current_dt)
    all_stocks = list(set(hs300stocks + zz500stocks + zz1000stocks))
    log.info('【策略7】指数标的总数：{}'.format(len(all_stocks)))
    return all_stocks

def s7_filter_stocks_by_time_name(context, stocks):
    valid_stocks = []
    for stock in stocks:
        try:
            info = get_security_info(stock)
            if info is None or info.start_date is None:
                continue
            days_since_listed = (context.current_dt.date() - info.start_date).days
            if days_since_listed < 60:
                continue
            if can_not_deal(stock,'buy'):
                continue
            if 'st' in info.name.lower():
                continue
        except:
            continue
        valid_stocks.append(stock)
    return valid_stocks

def s7_filter_stocks_by_today_convergence(context, stocks):
    valid_stocks = []
    for stock in stocks:
        if s7_check_ma_convergence_daily(stock, context,from_day=0,to_day=1):
            valid_stocks.append(stock)
    return valid_stocks

# ========== 2. ETF池构建与过滤（开盘前执行） ==========
def s7_etf_pool_and_filters(context):
    """
    每天开盘前执行：
    1. 市场股票列表
    2. 规模过滤（>1亿元）
    3. 流动性过滤（成交量足够）
    4. 上市时间过滤（>60天）
    5. 计算日线均线粘合连续状态
    6. 计算MACD>0状态
    """
    all_stocks = s7_get_index_stocks_list(context)
    # 获取今日粘合的股票列表,是明日的候选列表
    yesterday_convergence = g.s7_ma_converged_pre_day
    convergence_today = s7_filter_stocks_by_today_convergence(context, all_stocks)
    if len(convergence_today) > 0:
        g.s7_ma_converged_pre_day = convergence_today
    if len(yesterday_convergence) == 0:
        yesterday_convergence = all_stocks
    valid_stocks = s7_filter_stocks_by_time_name(context, yesterday_convergence)
    g.s7_etf_pool = valid_stocks
    log.info('【策略7】上市时间、涨跌停、st过滤后，{}只，今日粘合：{}只'.format(len(valid_stocks), len(convergence_today)))
    
    # ---------- 步骤3：缓存均线粘合连续状态（复用原策略逻辑） ----------
    # 获取今日各ETF是否粘合
    converged_set = set()
    for etf in valid_stocks:
        ma120 = s7_check_ma120_increase(etf, context)
        if ma120:
            is_converged = s7_check_ma_convergence_daily(etf, context,0,g.s7_consecutive_days)
            if is_converged:
                converged_set.add(etf)
    
    # ---------- 步骤4：缓存MACD>0状态 ----------
    positive_set = set()
    for etf in converged_set:
        if s7_is_macd_positive(etf, context):
            positive_set.add(etf)
    g.s7_macd_positive = positive_set

    intersection = converged_set.intersection(positive_set)
    g.s7_etf_pool = intersection
    log.info('【策略7】连续{}天均线粘合ETF：{}只，MACD>0：{}只，交集{}只，{}'.format(
        g.s7_consecutive_days, len(converged_set), len(positive_set),len(intersection),intersection))
    
# ========== 3. 日线均线粘合判断（与原策略相同，直接复用） ==========
def s7_check_ma_convergence_daily(security, context,from_day=0,to_day=1):
    """判断日线级别均线是否粘合，返回True/False"""
    df = attribute_history(security, 80, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 60:
        return False
    is_convergence = True
    for i in range(from_day,to_day):
        ma5 = df['close'].rolling(g.s7_ma_short).mean().iloc[-(i+1)]
        ma20 = df['close'].rolling(g.s7_ma_mid).mean().iloc[-(i+1)]
        ma60 = df['close'].rolling(g.s7_ma_long).mean().iloc[-(i+1)]
        
        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            return False
        
        ma_max = max(ma5, ma20, ma60)
        ma_min = min(ma5, ma20, ma60)
        deviation = (ma_max - ma_min) / ma_min if ma_min != 0 else 1
        is_convergence = is_convergence and (deviation <= g.s7_convergence_threshold)
        
    return is_convergence

# ========== 4. MACD判断 ==========
def s7_calc_macd(close_prices, fast=12, slow=26, signal=9):
    """计算MACD柱值"""
    if len(close_prices) < slow + signal:
        return None, None, None
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = dif - dea
    return dif, dea, macd_bar

def s7_is_macd_positive(security, context):
    """判断最新月线MACD柱是否大于0"""
    bars = get_bars(security, count=50, unit='1M', fields=['close'],
                    include_now=False, fq_ref_date=context.current_dt.date(), df=True)
    if bars is None or len(bars) < 35:
        return False
    close = bars['close']
    _, _, macd_bar = s7_calc_macd(close)
    if macd_bar is None:
        return False
    latest_macd = macd_bar.iloc[-1]
    return latest_macd > 0


# ========== 5. 120分钟BOLL开口判断（与原策略相同，复用） ==========
def s7_check_bollinger_breakout_120min(security, context):
    """判断120分钟周期BOLL开口（突破上轨）"""
    bars = get_bars(security, count=40, unit='120m', fields=['close'],
                    include_now=False, fq_ref_date=context.current_dt.date(), df=True)
    if bars is None or len(bars) < 20:
        return False
    
    close = bars['close']
    ma20 = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    latest_ma20 = ma20.iloc[-1]
    latest_close = close.iloc[-1]
    latest_upper = upper.iloc[-1]
    latest_lower = lower.iloc[-1]
    latest_std = std20.iloc[-1]
    if pd.isna(latest_upper):
        return False
    
    is_breakout = latest_close > latest_ma20
    prev_upper = None
    is_opening = None
    ret = is_breakout
    if len(upper) >= 2 and len(lower)>=2:
        prev_upper = upper.iloc[-2]
        prev_lower = lower.iloc[-2]
        r = 0.1
        is_opening = latest_upper > (prev_upper+r*latest_std) and latest_lower<(prev_lower-r*latest_std)
        ret = is_breakout and is_opening
    return ret



# ========== 6. 跌破指定均线卖出 ==========
def s7_check_break_ma_60min(security, context):
    """返回True表示仍在MA20上方，False表示跌破需卖出"""
    bars = get_bars(security, count=40, unit='60m', fields=['close'],
                    include_now=False, fq_ref_date=context.current_dt.date(), df=True)
    if bars is None or len(bars) < 20:
        return True
    close = bars['close']
    ma = close.rolling(20).mean()
    if pd.isna(ma.iloc[-1]):
        return True
    return close.iloc[-1] > ma.iloc[-1]


# ========== 8. 交易执行 ==========
def s7_trade_sell(context):
    s7_trade_sell_by_lightning_rod(context)
    # 获取当前持仓
    positions = get_portfolio_positions(context,pindex=6)
    current_holdings = [s for s in positions if positions[s].closeable_amount > 0]
    current_date = context.current_dt.date()
    
    # ---------- 卖出 ----------
    log.info(f"【策略7】卖出计算，current_holdings={current_holdings}")
    for etf in current_holdings:
        if can_not_deal(etf,'sell'):
            continue
        # 最小持有期检查
        hold_long_time = False
        buy_date = get_history(context,'buy',etf,pindex=6)
        if buy_date:
            hold_days = (current_date - buy_date).days
            hold_long_time = hold_days >= g.s7_max_hold_days
            if hold_days <= g.s7_min_hold_days:
                continue
        is_above = s7_check_break_ma_60min(etf, context) 
        # 跌破或者持有太久
        if not is_above or hold_long_time:
            # 获取卖出前盈亏信息
            pos = positions[etf]
            cost = pos.avg_cost
            total_amount = pos.total_amount
            current_price = get_current_data()[etf].last_price
            profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
            profit = (cost * total_amount) * profit_pct / 100
            log.info('【策略7】{} 卖出，满足条件is_above={},hold_long_time={},盈亏：{:.2f}({:.2f}%)'.format(etf, is_above,hold_long_time,profit,profit_pct))
            safe_order_target_value(context,'sell',etf, 0,pindex=6)

def s7_trade_sell_by_lightning_rod(context):
    """
    避雷针卖出法（独立止盈）
    每日14:44执行，使用盘中实时数据，无未来函数。
    条件（同时满足）：
      1. 当前价 < 开盘价（盘中阴线）
      2. 今日最高价 ≥ 过去20日（不含今日）最高价
      3. 开盘价 < (今日最高价 + 今日最低价) / 2
    """
    positions = get_portfolio_positions(context,pindex=6)
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    cur_data = get_current_data()

    for etf in current_holdings:
        if can_not_deal(etf,'sell'):
            continue

        # ---------- 当日开盘价和最新价 ----------
        sec = cur_data[etf]
        if sec is None:
            continue
        day_open = sec.day_open
        last_price = sec.last_price

        # 条件1：阴线（当前价低于开盘0.2%以上）
        if last_price >= day_open*(1-0.2/100):
            continue

        # ---------- 通过1分钟线获取今日最高最低（已完成的分钟） ----------
        # 明确 fields 包含 'date' 以过滤今日数据
        bars = get_bars(etf, count=600, unit='1m', fields=['date', 'high', 'low'],
                        include_now=False, df=True)

        # 检查是否有 'date' 列
        if 'date' not in bars.columns:
            continue

        today_date = context.current_dt.date()
        # 过滤出今天的分钟线
        today_bars = bars[bars['date'].dt.date == today_date]
        if len(today_bars) == 0:
            continue

        high_today = today_bars['high'].max()
        low_today = today_bars['low'].min()
        if high_today is None or low_today is None:
            continue

        # ---------- 过去20日（不含今日）最高价 ----------
        hist_df = attribute_history(etf, 20, '1d', ['high'], skip_paused=True, df=True)
        if len(hist_df) < 20:
            continue
        hist_high = hist_df['high'].max()

        # 条件2：今日最高价 ≥ 过去20日最高（创新高）
        if high_today < hist_high:
            continue

        # 条件3：开盘价低于当日振幅中点
        if day_open >= (high_today + low_today) / 2:
            continue

        # ---------- 全部满足，清仓 ----------
        log.info('【策略7】避雷针卖出 {}，当前价{:.3f}<开盘{:.3f}，今日最高{:.3f}≥20日最高{:.3f}，开盘{:.3f}<中点{:.3f}'.format(
            etf, last_price, day_open, high_today, hist_high,
            day_open, (high_today + low_today) / 2))
        safe_order_target_value(context, 'sell', etf, 0,pindex=6)

def s7_sort_stocks_by_market_cap(context, stocks, ascending=False, cap_type='market_cap'):
    """
    根据市值对股票列表进行排序。
    """
    if not stocks:
        return []

    yesterday = context.previous_date

    if cap_type == 'circulating_market_cap':
        q = query(
            valuation.code,
            valuation.circulating_market_cap
        ).filter(valuation.code.in_(stocks))
    else:
        q = query(
            valuation.code,
            valuation.market_cap
        ).filter(valuation.code.in_(stocks))

    df = get_fundamentals(q, date=yesterday)

    if df is None or df.empty:
        return stocks

    # 关键修复：用 code 列建立 {股票代码: 市值} 映射
    cap_dict = df.set_index('code')[cap_type].to_dict()

    sorted_stocks = sorted(
        stocks,
        key=lambda s: cap_dict.get(s, 0),
        reverse=not ascending
    )

    return sorted_stocks

def s7_trade_buy(context):
    # 获取当前持仓
    positions = get_portfolio_positions(context,pindex=6)
    portfolio = get_portfolio(context,pindex=6)
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    # ---------- 买入 ----------
    # 计算仓位上限
    total_assets = portfolio.total_value
    current_stock_value = portfolio.positions_value
    current_ratio = current_stock_value / total_assets if total_assets > 0 else 0
    remaining_ratio = max(0, g.s7_position_limit - current_ratio)
    max_new_cash = total_assets * remaining_ratio
    cash_available = portfolio.available_cash
    buy_cash_limit = min(cash_available, max_new_cash)
    
    log.info(f"【策略7】买入计算，仓位上限比例{g.s7_position_limit},标的数上限{g.s7_stock_num},今日买入金额上限{buy_cash_limit}，当前市值{total_assets},持仓市值{current_stock_value}")
    
    # 候选ETF筛选
    candidates = []
    for etf in g.s7_etf_pool:
        if can_not_deal(etf,'buy'):
            continue
        if etf in current_holdings:
            continue
        if s7_check_bollinger_breakout_120min(etf, context):
            candidates.append(etf)

    candidates = s7_sort_stocks_by_market_cap(context, candidates)

    if len(current_holdings) >= g.s7_stock_num:
        if candidates:
            text = f"【策略7】均线粘合标的已满，以下候选标的被忽略：{candidates}"
            log.info(text)
            send_message(text)
        return
    
    if not candidates:
        return
    new_size = g.s7_stock_num - len(current_holdings)
    if new_size>0:
        candidates = candidates[:new_size]
    
    # 动态分配资金
    cash_per_etf = buy_cash_limit / len(candidates)
    max_cash_per_stock = min(g.s7_max_cash_per_stock,total_assets*g.s7_max_cash_ratio_per_stock)
    cash_per_etf = min(cash_per_etf,max_cash_per_stock)
    log.info(f"【策略7】满足条件的候选ETF列表{len(candidates)}，{candidates},cash={buy_cash_limit},ratio={g.s7_position_limit},cash_per_etf={cash_per_etf}")

    for etf in candidates:
        if cash_per_etf < 1000:
            continue
        safe_order_target_value(context,'buy',etf, cash_per_etf,pindex=6)