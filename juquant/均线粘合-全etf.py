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
def s1_process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured(context,Live_Type)
 
def s1_after_trading_end(context):
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(context.portfolio.positions)
        
# =======================实盘配置End=======================================

def initialize(context):
    s1_initialize(context)

def before_trading_start(context):
    pass

def after_trading_end(context):
    s1_after_trading_end(context)

def after_code_changed(context):
    unschedule_all()
    s1_after_code_changed(context)

# =======================辅助函数：获取子账户信息===========================
def get_s1_portfolio(context):
    if len(context.subportfolios) > 1:
        return context.subportfolios[0]
    return context.subportfolios[0]

def get_s1_portfolio_positions(context):
    port = get_s1_portfolio(context)
    if hasattr(port, 'long_positions'):
        return port.long_positions
    return context.portfolio.positions
# ========================================================================

def s1_common_init(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(1/1000))
    

def s1_set_params(context):
    # ---------- 策略核心参数 ----------
    g.s1_stock_num = 4                    # 最大持仓数
    g.s1_min_hold_days = 4                 # 最小持有天数
    g.s1_max_hold_days = 15                # 最大持有天数
    g.s1_max_cash_per_stock = 20*10000     # 单个标的最大金额
    g.s1_max_cash_ratio_per_stock = 1      # 单个标的占总仓比例
    g.s1_ma_short, g.s1_ma_mid, g.s1_ma_long = 5, 20, 60
    g.s1_convergence_threshold = 0.02     # 粘合阈值2%
    g.s1_consecutive_days = 2             # 连续N天均线粘合
    g.s1_min_money = 2000 * 10000 #成交额最小阈值
    # 大盘风控参数
    g.s1_position_limit = 1.0 #上限满仓运行
    g.s1_fix_take_profit = 0.05
    
    
    
def s1_schedule_tasks(context):
    run_daily(s1_etf_pool_and_filters, time='14:01')   # 更新池
    run_daily(s1_trade_sell, time='14:44')     # 卖出交易判断
    run_daily(s1_trade_buy, time='14:45')     # 买入交易判断
    run_daily(s1_take_fix_profit, time='14:46')     # 止盈

def s1_take_fix_profit(context):
    # 固定止盈
    take_fix_profit_check(context,g.s1_fix_take_profit,pindex=0)

def take_fix_profit_check(context,rate_limit,pindex=0):
    """固定止盈法 每日检查持仓是否触发止盈"""
    current_data = get_current_data()
    positions = get_s1_portfolio_positions(context)
    for code, pos in positions.items():
        if pos.closeable_amount <= 0 or s1_can_not_deal(code):
            continue
        current_price = current_data[code].last_price
        cost = pos.avg_cost
        rate = (current_price - cost)/cost
        is_take_profit = rate>=rate_limit
        if  is_take_profit:
            log.info(f"pindex={pindex} {code}止盈触发：{current_price} rate={rate:.3%} 阈值:{rate_limit:.2%}")
            s1_safe_order_target_value(context,'sell',code, 0)

# ========= 120日线均线上涨或当前价大于120日均线 ==========
def s1_check_ma_increase(security, context):
    df = attribute_history(security, 150, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 120:
        return False
    cur_data = get_current_data()
    price = cur_data[security].last_price
    ma120_roll = df['close'].rolling(120).mean()
    ma60_roll = df['close'].rolling(60).mean()
    ma20_roll = df['close'].rolling(20).mean()
    ma20 = ma20_roll.iloc[-1]
    ma60 = ma60_roll.iloc[-1]
    ma120 = ma120_roll.iloc[-1]
    # 去前一天和前三天比，避免钝化
    last_ma120 = ma120_roll.iloc[-3]
    last_ma60 = ma60_roll.iloc[-3]
    last_ma20 = ma20_roll.iloc[-3]
    ma20_not_down = ma20>=last_ma20
    is_above_ma120 = price > ma120 * (1+0.01)  # 当前价大于120日均线1%
    ma120_increase = ma120 > last_ma120
    return (is_above_ma120 or ma120_increase) and  ma20_not_down

def s1_after_code_changed(context):
    s1_common_init(context)
    s1_set_params(context)
    s1_schedule_tasks(context)
    
# ========== 1. 初始化函数 ==========   
def s1_initialize(context):
    s1_common_init(context)
    s1_set_params(context)
    s1_schedule_tasks(context)
    
    # ---------- 缓存变量 ----------
    g.s1_etf_pool = []                     # ETF池
    g.s1_etf_scale_cache = {}              # 规模缓存
    g.s1_ma_converged_etfs = set()         # 满足连续粘合的ETF
    g.s1_macd_positive = set()      # 月线MACD>0的ETF
    g.s1_buy_date = {}                     # 买入日期记录
    # 前一日历史粘合记录
    g.s1_ma_converged_pre_day = []


def get_index_stocks_list(context):
    all_etfs = get_all_securities(types=['etf','lof'], date=context.current_dt).index.tolist()
    all_high_vol_etfs = filter_by_amount(all_etfs,g.s1_min_money)
    log.info('指数标的总数：{}, 高成交量标的数：{}'.format(len(all_etfs), len(all_high_vol_etfs)))
    return all_high_vol_etfs

def filter_by_amount(stocks, threshold=20000000):
    """
    筛选昨日成交额大于指定阈值的股票。

    参数:
        stocks: 股票代码列表，如 ['000001.XSHE', '600000.XSHG']
        threshold: 成交额阈值，单位元，默认 2000 万

    返回:
        list: 满足条件的股票代码列表
    """
    result = []
    for stock in stocks:
        # 获取昨日（前1个交易日）的成交额数据
        # attribute_history 会自动跳过停牌日，避免未来数据
        hist = attribute_history(
            stock,
            count=1,          # 只取前1个单位时间
            unit='1d',        # 以“日”为单位
            fields=['money'], # 只需成交额字段
            skip_paused=True  # 跳过停牌日期
        )
        # hist['money'] 返回的是 DataFrame/Series，取最后一个值
        # 若数据为空（如新股尚未有昨日数据），则跳过
        if len(hist) == 0:
            continue
        yesterday_amount = hist['money'][-1]
        if yesterday_amount > threshold:
            result.append(stock)

    return result

def filter_stocks_by_time_name(context, stocks):
    valid_stocks = []
    cur_data = get_current_data()
    
    for stock in stocks:
        try:
            info = get_security_info(stock)
            if info is None or info.start_date is None:
                continue
            days_since_listed = (context.current_dt.date() - info.start_date).days
            if days_since_listed < 60:
                continue
            if 'st' in info.name.lower():
                continue
            if s1_can_not_deal(stock):
                continue
            price = cur_data[stock].last_price
            if price is None or price <= 0 or price>20:
                continue
        except:
            continue
        valid_stocks.append(stock)
    return valid_stocks

def filter_stocks_by_today_convergence(context, stocks):
    valid_stocks = []
    for stock in stocks:
        if s1_check_ma_convergence_daily(stock, context,from_day=0,to_day=1):
            valid_stocks.append(stock)
    return valid_stocks

def get_display_name(security):
    info = get_security_info(security)
    if info is not None:
        return info.display_name
    return None

def get_etf_prefix(security):
    """
    获取 ETF 标的的前缀名称。
    
    参数:
        security: ETF 代码（如 '510300.XSHG'）
    
    返回:
        str: 前缀名称（如 '沪深300'），若无法识别则返回原名称或 None
    """
    # 判断传入的是否为证券代码
    name = get_display_name(security)
    
    # 以 'ETF' 为分隔符，取前面的部分
    idx = name.find('ETF')
    if idx != -1:
        return name[:idx].strip()
    
    # 兼容没有 'ETF' 字样的名称，去掉常见后缀
    for suffix in ['基金', '联接', 'LOF']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()

def deduplicate_etf_by_prefix(code_list):
    """
    对 ETF 代码列表去重：根据 ETF 前缀（如沪深300）去重，
    相同前缀的 ETF 只保留昨日成交额最高的一个。
    
    参数:
        code_list: ETF 代码列表，如 ['510300.XSHG', '159919.XSHE', ...]
    
    返回:
        list: 去重后的 ETF 代码列表
    """
    if not code_list:
        return []
    
    # 1. 获取每个 ETF 的前缀（依赖已定义的 get_etf_prefix 函数）
    prefix_map = {}  # code -> prefix
    for code in code_list:
        prefix = get_etf_prefix(code)   # 传入代码，函数内部会获取名称并提取前缀
        if prefix:
            prefix_map[code] = prefix
        else:
            # 无法识别前缀时，用代码自身作为唯一前缀，避免误合并
            prefix_map[code] = code
    
    # 2. 批量获取所有 ETF 昨日成交额（单位：元）
    h = history(
        count=1,
        unit='1d',
        field='money',
        security_list=list(prefix_map.keys()),
        df=True,
        skip_paused=True
    )
    
    # 若获取失败或为空，退化为仅按前缀去重（保留第一个出现的）
    if h is None or h.empty:
        seen = set()
        result = []
        for code in code_list:
            p = prefix_map.get(code)
            if p not in seen:
                seen.add(p)
                result.append(code)
        return result
    
    # 昨日成交额：取最后一行（Series，index 为代码）
    yesterday_amount = h.iloc[-1]
    
    # 3. 按前缀分组，保留成交额最大的代码
    prefix_best = {}  # prefix -> (code, amount)
    for code in code_list:
        prefix = prefix_map.get(code)
        if prefix is None:
            continue
        
        # 获取昨日成交额，处理 NaN 和缺失
        amount = yesterday_amount.get(code, 0)
        if pd.isna(amount):
            amount = 0
        
        # 若该前缀尚未记录，或当前成交额更大，则更新
        if prefix not in prefix_best or amount > prefix_best[prefix][1]:
            # if prefix in prefix_best:
                # log.info(f"ETF {prefix} 被更新，更新前：{prefix_best.get(prefix, ('-', 0))}，更新后：({code}, {amount})")
            prefix_best[prefix] = (code, amount)
    
    # 4. 返回去重后的代码列表
    result = [v[0] for v in prefix_best.values()]
    return result

# ========== 2. ETF池构建与过滤（开盘前执行） ==========
def s1_etf_pool_and_filters(context):
    """
    每天开盘前执行：
    1. 市场股票列表
    2. 规模过滤（>1亿元）
    3. 流动性过滤（成交量足够）
    4. 上市时间过滤（>60天）
    5. 计算日线均线粘合连续状态
    6. 计算MACD>0状态
    """
    all_etfs = get_index_stocks_list(context)
    # 获取今日粘合的股票列表,是明日的候选列表
    yesterday_convergence = g.s1_ma_converged_pre_day
    convergence_today = filter_stocks_by_today_convergence(context, all_etfs)
    if len(convergence_today) > 0:
        g.s1_ma_converged_pre_day = convergence_today
    if len(yesterday_convergence) == 0:
        yesterday_convergence = all_etfs
    valid_stocks = filter_stocks_by_time_name(context, yesterday_convergence)
    g.s1_etf_pool = valid_stocks
    log.info('上市时间、涨跌停、st过滤后，{}只，今日粘合：{}只'.format(len(valid_stocks), len(convergence_today)))
    
    # ---------- 步骤3：缓存均线粘合连续状态（复用原策略逻辑） ----------
    # 获取今日各ETF是否粘合
    converged_set = set()
    for etf in valid_stocks:
        ma120 = s1_check_ma_increase(etf, context)
        if ma120:
            is_converged = s1_check_ma_convergence_daily(etf, context,0,g.s1_consecutive_days)
            if is_converged:
                converged_set.add(etf)
    
    # ---------- 步骤4：缓存MACD>0状态 ----------
    positive_set = set()
    for etf in converged_set:
        if s1_is_macd_positive(etf, context):
            positive_set.add(etf)
    g.s1_macd_positive = positive_set

    intersection = converged_set.intersection(positive_set)
    g.s1_etf_pool = intersection
    log.info('连续{}天均线粘合ETF：{}只，MACD>0：{}只，交集{}只，{}'.format(
        g.s1_consecutive_days, len(converged_set), len(positive_set),len(intersection),intersection))
        

def s1_can_not_deal(code):
    cur_data = get_current_data()
    cur_price = cur_data[code].last_price
    no_price = cur_price is None or cur_price <=0
    is_paused = cur_data[code].paused
    is_st = cur_data[code].is_st
    is_limit = cur_price>=cur_data[code].high_limit or cur_price<=cur_data[code].low_limit 
    can_not_deal = (no_price or is_paused or is_st or is_limit)
    
    # 检查接近涨跌停
    prev_close = cur_data[code].day_open
    if prev_close and prev_close > 0:
        if cur_price >= prev_close * 1.098:   # 接近涨停
            # log.info(f'{code} 当前接近涨停，暂停买入')
            can_not_deal = True
        if cur_price <= prev_close * 0.902:   # 接近跌停
            # log.info(f'{code} 当前接近跌停，暂停买入')
            can_not_deal = True
    # if can_not_deal:
        # log.info(f"{code} can_not_deal={can_not_deal},no_price={no_price} is_paused={is_paused} is_st={is_st} is_limit={is_limit}")
    return can_not_deal
    
# ========== 3. 日线均线粘合判断（与原策略相同，直接复用） ==========
def s1_check_ma_convergence_daily(security, context,from_day=0,to_day=1):
    """判断日线级别均线是否粘合，返回True/False"""
    df = attribute_history(security, 80, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 60:
        return False
    is_convergence = True
    for i in range(from_day,to_day):
        ma5 = df['close'].rolling(g.s1_ma_short).mean().iloc[-(i+1)]
        ma20 = df['close'].rolling(g.s1_ma_mid).mean().iloc[-(i+1)]
        ma60 = df['close'].rolling(g.s1_ma_long).mean().iloc[-(i+1)]
        
        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            return False
        
        ma_max = max(ma5, ma20, ma60)
        ma_min = min(ma5, ma20, ma60)
        deviation = (ma_max - ma_min) / ma_min if ma_min != 0 else 1
        is_convergence = is_convergence and (deviation <= g.s1_convergence_threshold)
        
    return is_convergence

# ========== 4. MACD判断 ==========
def s1_calc_macd(close_prices, fast=12, slow=26, signal=9):
    """计算MACD柱值"""
    if len(close_prices) < slow + signal:
        return None, None, None
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = dif - dea
    return dif, dea, macd_bar

def s1_is_macd_positive(security, context):
    """判断最新月线MACD柱是否大于0"""
    bars = get_bars(security, count=50, unit='1M', fields=['close'],
                    include_now=False, fq_ref_date=context.current_dt.date(), df=True)
    if bars is None or len(bars) < 35:
        return False
    close = bars['close']
    _, _, macd_bar = s1_calc_macd(close)
    if macd_bar is None:
        return False
    latest_macd = macd_bar.iloc[-1]
    return latest_macd > 0


# ========== 5. 120分钟BOLL开口判断（与原策略相同，复用） ==========
def s1_check_bollinger_breakout_120min(security, context):
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
    prev_lower = None
    ret = is_breakout
    if len(upper) >= 2 and len(lower)>=2:
        prev_upper = upper.iloc[-2]
        prev_lower = lower.iloc[-2]
        r = 0.1
        is_opening = latest_upper > (prev_upper+r*latest_std) and latest_lower<(prev_lower-r*latest_std)
        ret = is_breakout and is_opening
    return ret



# ========== 6. 跌破指定均线卖出 ==========
def s1_check_break_ma_60min(security, context):
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

    
def s1_safe_order_target_value(context,action,code,target_value):
    style = None
    if s1_can_not_deal(code):
        return 0
    positions = get_s1_portfolio_positions(context)
    portfolio = get_s1_portfolio(context)
    available_cash = portfolio.available_cash
    cur_data = get_current_data()
    price = cur_data[code].last_price
    is_kcb = code[:2] == '68'
    limit_price = price*(1+0.005) if action == 'buy' else price*(1-0.005)
    style = MarketOrderStyle(limit_price)

    if code in positions:
        pos = positions[code]
        had_value = pos.value
        diff_value = target_value - had_value
        if action == 'sell' and diff_value < 0:
            if target_value==0:
                order(code, -pos.closeable_amount, style)
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(pos.closeable_amount, sell_amount)
            if a_amount >= 100:
                order(code, -a_amount, style)
                return -1
        elif diff_value > 0:
            buy_value = min(available_cash, diff_value)
            amount = int(abs(buy_value)  / price // 100) * 100
            if amount >= 200 or (amount>=100 and not is_kcb):
                order(code, amount, style)
                return 1
            else:
                log.warn(f"s1_safe_order_target_value ignore,holding {code} {amount} {style} {available_cash}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style)
            return 1
        else:
            log.warn(f"s1_safe_order_target_value ignore, {code} {amount} {style} {available_cash}")
    return 0


# ========== 8. 交易执行 ==========
def s1_trade_sell(context):
    s1_trade_sell_by_lightning_rod(context)
    # 获取当前持仓
    positions = get_s1_portfolio_positions(context)
    current_holdings = [s for s in positions if positions[s].closeable_amount > 0]
    current_date = context.current_dt.date()
    
    # ---------- 卖出 ----------
    log.info(f"卖出计算，current_holdings={current_holdings}")
    for etf in current_holdings:
        if s1_can_not_deal(etf):
            continue
        # 最小持有期检查
        hold_long_time = False
        if etf in g.s1_buy_date:
            hold_days = (current_date - g.s1_buy_date[etf]).days
            hold_long_time = hold_days >= g.s1_max_hold_days
            if hold_days < g.s1_min_hold_days:
                continue
        is_above = s1_check_break_ma_60min(etf, context) 
        # 跌破或者持有太久
        if not is_above or hold_long_time:
            # 获取卖出前盈亏信息
            pos = positions[etf]
            cost = pos.avg_cost
            total_amount = pos.total_amount
            current_price = get_current_data()[etf].last_price
            profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
            profit = (cost * total_amount) * profit_pct / 100
            log.info('{} 卖出，满足条件is_above={},hold_long_time={},盈亏：{:.2f}({:.2f}%)'.format(etf, is_above,hold_long_time,profit,profit_pct))
            s1_safe_order_target_value(context,'sell',etf, 0)
            if etf in g.s1_buy_date:
                del g.s1_buy_date[etf]

def s1_trade_sell_by_lightning_rod(context):
    """
    避雷针卖出法（独立止盈）
    每日14:44执行，使用盘中实时数据，无未来函数。
    条件（同时满足）：
      1. 当前价 < 开盘价（盘中阴线）
      2. 今日最高价 ≥ 过去20日（不含今日）最高价
      3. 开盘价 < (今日最高价 + 今日最低价) / 2
    """
    positions = get_s1_portfolio_positions(context)
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    cur_data = get_current_data()

    for etf in current_holdings:
        if s1_can_not_deal(etf):
            continue

        # ---------- 当日开盘价和最新价 ----------
        sec = cur_data[etf]
        if sec is None:
            continue
        day_open = sec.day_open
        last_price = sec.last_price

        # ---------- 通过1分钟线获取今日最高最低（已完成的分钟） ----------
        # 明确 fields 包含 'date' 以过滤今日数据
        bars = get_bars(etf, count=600, unit='1m', fields=['date', 'high', 'low'],
                        include_now=False, df=True)

        today_date = context.current_dt.date()
        # 过滤出今天的分钟线
        today_bars = bars[bars['date'].dt.date == today_date]
        if len(today_bars) == 0:
            log.info(f"no today_bars")
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

        match = False
        green_line = last_price < day_open*(1-0.2/100)
        red_line = last_price >= day_open*(1-0.2/100)
        # 如果是阴线，需要收盘价低于中点
        # 如果是阳线，需要收盘价低于1/3
        if red_line:
            match = last_price < (low_today + (high_today - low_today) / 3)
        if green_line:
            match = last_price < (low_today + (high_today - low_today) / 2)
        if not match:
            continue
        # 条件1：阴线（当前价低于开盘0.2%以上）
        # ---------- 全部满足，清仓 ----------
        log.info('避雷针卖出 {}，当前价{:.3f}<开盘{:.3f}，今日最高{:.3f}≥20日最高{:.3f}，开盘{:.3f}<中点{:.3f}'.format(
            etf, last_price, day_open, high_today, hist_high,
            day_open, (high_today + low_today) / 2))
        s1_safe_order_target_value(context, 'sell', etf, 0)
        if etf in g.s1_buy_date:
            del g.s1_buy_date[etf]

def s1_trade_buy(context):
    # 获取当前持仓
    current_date = context.current_dt.date()
    positions = get_s1_portfolio_positions(context)
    portfolio = get_s1_portfolio(context)
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    # ---------- 买入 ----------
    # 计算仓位上限
    total_assets = portfolio.total_value
    current_stock_value = portfolio.positions_value
    current_ratio = current_stock_value / total_assets if total_assets > 0 else 0
    remaining_ratio = max(0, g.s1_position_limit - current_ratio)
    max_new_cash = total_assets * remaining_ratio
    cash_available = portfolio.available_cash
    buy_cash_limit = min(cash_available, max_new_cash)
    
    log.info(f"买入计算，仓位上限比例{g.s1_position_limit},标的数上限{g.s1_stock_num},今日买入金额上限{buy_cash_limit}，当前市值{total_assets},持仓市值{current_stock_value}")
    
    
    # 候选ETF筛选
    candidates = []
    candidates_to_buy = []
    candidates_ignore = []
    for etf in g.s1_etf_pool:
        if s1_can_not_deal(etf):
            continue
        if etf in current_holdings:
            continue
        if s1_check_bollinger_breakout_120min(etf, context):
            candidates.append(etf)

    after_candidates = deduplicate_etf_by_prefix(candidates)
    log.info(f"候选ETF筛选后，{len(candidates)}只，去重后{len(after_candidates)}只，{after_candidates}")
    candidates = after_candidates
    
    if not candidates:
        return
    new_size = g.s1_stock_num - len(current_holdings)
    if new_size>0:
        candidates_to_buy = candidates[:new_size]
    if len(candidates)>new_size:
        candidates_ignore = candidates[new_size:]
    if not candidates_to_buy:
        return
    # 动态分配资金
    cash_per_etf = buy_cash_limit / len(candidates_to_buy)
    max_cash_per_stock = min(g.s1_max_cash_per_stock,total_assets*g.s1_max_cash_ratio_per_stock)
    cash_per_etf = min(cash_per_etf,max_cash_per_stock)
    cash_too_small = cash_per_etf < 1000
    log.info(f"满足条件的候选ETF列表{len(candidates_to_buy)}，{candidates_to_buy},cash={buy_cash_limit},cash_per_etf={cash_per_etf},cash_too_small={cash_too_small}")
    if cash_too_small:
        candidates_ignore = candidates
        candidates_to_buy = []
        
    for etf in candidates_to_buy:
        r = s1_safe_order_target_value(context,'buy',etf, cash_per_etf)
        if r>0:
            g.s1_buy_date[etf] = current_date

    if candidates_ignore:
        text = f"均线粘合候选标的被忽略：{candidates_ignore}"
        log.info(text)
        send_message(text)