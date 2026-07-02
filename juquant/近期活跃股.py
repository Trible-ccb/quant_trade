# 聚宽策略：尾盘买入·早盘卖出（十日线缩量阴线策略）
# 作者：量化转换
# 说明：每天14:50选股买入，次日根据集合竞价及10点条件卖出，不持股超过2天

import talib
import numpy as np
import pandas as pd

# ==================== 初始化函数 ====================
def initialize(context):
    # ---------- 您指定的参数 ----------
    set_benchmark('510300.XSHG')              # 基准：沪深300ETF
    set_option("avoid_future_data", True)     # 避免未来数据
    set_option('use_real_price', True)        # 使用真实价格
    set_slippage(FixedSlippage(2.0/1000))     # 滑点0.2%
    set_order_cost(OrderCost(
        close_tax=0.001,                      # 印花税千分之一
        open_commission=1/10000,              # 买入佣金万分之一
        close_commission=1/10000,             # 卖出佣金万分之一
        min_commission=5
    ), type='stock')                           

    # ---------- 策略参数 ----------
    g.buy_time = '14:50'                      # 买入时刻
    g.morning_check_time = '09:45'            # 开盘检查（避开集合竞价，取09:31）
    g.ten_o_clock_time = '10:00'              # 十点卖出时刻
    g.tail_sell_time = '14:45'                # 尾盘最后卖出时刻
    g.ma_period = 10                          # 均线周期
    g.active_lookback = 20                    # 活跃检测回看天数
    g.active_threshold = 0.098                 # 活跃涨幅阈值9.8%
    g.active_threshold2 = 0.198                 # 活跃涨幅阈值19.8%
    g.buy_ma_tolerance = 0.01                 # 股价距离10日线偏差±1%
    g.sell_profit_threshold = 0.05           # 冲高3%即触发卖出
    g.volume_shrink_ratio = 0.9               # 缩量系数：当日量 < 过去5日均量 * 0.9
    
    # 记录当天买入的股票（用于次日快速定位）
    g.bought_today = set()
    
    # 定时运行函数
    run_daily(buy_stocks, time=g.buy_time)               # 每天14:55买入
    run_daily(morning_check_sell, time=g.morning_check_time)  # 09:31处理低开割肉
    run_daily(sell_at_10am, time=g.ten_o_clock_time)     # 10:00条件卖出
    run_daily(sell_at_tail, time=g.tail_sell_time)       # 14:50尾盘清仓（持股不超2天）

def filter_green_stocks(context, stocks):
    ret = []
    for stock in stocks:
        current_data = get_current_data()
        last_price = current_data[stock].last_price
        open_price = current_data[stock].day_open
        # 获取昨日收盘价
        hist = attribute_history(stock, 1, '1d', ['close'], df=False)
        if len(hist['close']) == 0:
            continue
        yesterday_close = hist['close'][0]
    
        # 2. 基础形态检查（阴线、涨幅<1%）
        if last_price >= open_price:
            continue
        daily_return = (last_price - yesterday_close) / yesterday_close
        if daily_return >= 0.01:
            continue
        ret.append(stock)
    log.info(f"filter_green_stocks 剩余{len(ret)}只")
    return ret

def filter_small_volumn_stocks(context, stocks):
    ret = []
    candidates = []
    for stock in stocks:
        # ---------- 缩量检查（修正核心） ----------
        # 3.1 获取今日分钟线累计成交量
        # 从当日9:31开始获取到目前的分钟线，用于计算累计成交量和均价
        bars = get_bars(stock, count=240, unit='1m', fields=['volume', 'money', 'close'], include_now=True)
        if bars is None or len(bars) == 0:
            continue
        
        # 累计当日成交量
        total_volume_today = sum(b['volume'] for b in bars)
        
        # 3.2 获取过去5日日均成交量
        vol_hist = attribute_history(stock, 5, '1d', ['volume'], df=False)
        if len(vol_hist['volume']) < 5:
            continue
        avg_vol_5 = np.mean(vol_hist['volume'])
        shrink_ratio = total_volume_today / avg_vol_5 if avg_vol_5 > 0 else 1.0
        # 缩量判断：当日累计量 < 过去5日均量 * 0.9
        if total_volume_today >= avg_vol_5 * g.volume_shrink_ratio:
            continue
        candidates.append((stock,shrink_ratio))
    candidates.sort(key=lambda x: x[1])
    MAX_BUY = 1
    for stock , r in candidates:
        if len(ret)<MAX_BUY:
            ret.append(stock)
    log.info(f"filter_small_volumn_stocks 剩余{len(ret)}只，{ret}")
    return ret

def filter_near_ma_stocks(context, stocks):
    ret = []
    for stock in stocks:
        current_data = get_current_data()
        last_price = current_data[stock].last_price
        open_price = current_data[stock].day_open
        # ---------- 4. 10日线检查 ----------
        close_hist = attribute_history(stock, 20 + 1, '1d', ['close'], df=False)
        if len(close_hist['close']) < g.ma_period + 1:
            continue
        ma20_today = np.mean(close_hist['close'][-20:])
        ma10_today = np.mean(close_hist['close'][-g.ma_period:])
        ma10_yest = np.mean(close_hist['close'][-(g.ma_period+1):-1])
        if abs(last_price - ma10_today) / ma10_today > g.buy_ma_tolerance:
            continue
        if ma10_today <= ma10_yest and open_price >= ma20_today:
            continue
        
        ret.append(stock)
    log.info(f"filter_near_ma_stocks 剩余{len(ret)}只")
    return ret
    
def filter_active_stocks(context, stocks):
    ret = []
    for stock in stocks:
        # ---------- 前期活跃检查 ----------
        ret_hist = attribute_history(stock, g.active_lookback, '1d', ['close'], df=False)
        if len(ret_hist['close']) < 2:
            continue
        close_arr = ret_hist['close']
        rets = (close_arr[1:] - close_arr[:-1]) / close_arr[:-1]
        high_ret = [ret for ret in rets if (ret >= g.active_threshold and not (stock.startswith('300') or stock.startswith('688'))) ]
        
        if len(high_ret)==0:
            continue
        ret.append(stock)
    log.info(f"filter_active_stocks 剩余{len(ret)}只")
    return ret
        
    
# ==================== 选股与买入 ====================
def buy_stocks(context):
    """14:50 选股并买入"""
    current_dt = context.current_dt
    log.info('=== 开始选股 %s ===' % current_dt.strftime('%Y-%m-%d %H:%M'))
    
    # 1. 获取股票池（剔除ST、停牌、涨跌停）
    all_stocks = get_all_securities(['stock']).index.tolist()
    stocks = filter_stocks(context, all_stocks)
    # 2.1 过滤出阴线股
    stocks = filter_green_stocks(context,stocks)
    # 2.2 过滤出回落在均线附近股
    stocks = filter_near_ma_stocks(context,stocks)
    # 2.3 过滤出过去活跃股
    stocks = filter_active_stocks(context,stocks)
     # 2.4 过滤出缩量股
    stocks = filter_small_volumn_stocks(context,stocks)
    buy_list = stocks
    log.info(f"符合条件的股票个数：{len(buy_list)}")
    # 3. 执行买入（等权重分配资金）
    if len(buy_list) == 0:
        return
    
    cash_per_stock = context.portfolio.available_cash / len(buy_list)
    for stock in buy_list:
        safe_order_target_value(stock, cash_per_stock)
        g.bought_today.add(stock)
        log.info('买入 %s, 金额 %.2f' % (stock, cash_per_stock))
    
    log.info('共买入 %d 只股票' % len(buy_list))

def safe_order_target_value(stock,cash):
    current_data = get_current_data()
    current_price = current_data[stock].last_price
    if stock.startswith('688'):   # 科创板
        # 限价买入，价格设为当前价 * 1.001（略高于现价，确保成交）
        order_target_value(stock, cash, LimitOrderStyle(current_price * 1.001))
    else:
        order_target_value(stock, cash)
    if cash<=0:
        log.info(f"卖出{stock}委托单，目标金额：{cash}")
    else:
        log.info(f"买入{stock}委托单，目标金额：{cash}")

def filter_stocks(context, stocks):
    """剔除ST、停牌、涨跌停、次新股（上市<60天）"""
    current_data = get_current_data()
    valid = []
    for s in stocks:
        # 停牌或ST
        if current_data[s].is_st or current_data[s].paused:
            continue
        # 涨跌停（防止无法买入）
        if current_data[s].last_price >= current_data[s].high_limit:
            continue
        if current_data[s].last_price <= current_data[s].low_limit:
            continue
        # 剔除上市不足60天 —— 修复：使用 get_security_info
        start_date = get_security_info(s).start_date
        days_public = (context.current_dt.date() - start_date).days
        if days_public < 60:
            continue
        valid.append(s)
    return valid

# ==================== 卖出逻辑 ====================
def morning_check_sell(context):
    """09:31 检查：低开+低于10日线 → 开盘割肉"""
    current_dt = context.current_dt
    # 仅对昨日买入的股票执行
    holdings = context.portfolio.positions
    to_sell = [s for s in holdings if holdings[s].closeable_amount > 0]
    for stock in to_sell:
        current_data = get_current_data()
        open_price = current_data[stock].day_open
        yesterday_close = attribute_history(stock, 1, '1d', ['close'], df=False)['close'][0]
        
        # 计算当日10日线（基于昨日及之前数据）
        close_hist = attribute_history(stock, g.ma_period, '1d', ['close'], df=False)['close']
        ma10_today = np.mean(close_hist)
        open_low = open_price<yesterday_close
        lower_ma = open_price < ma10_today
        # 条件：低开 且 开盘价 < 10日线
        if open_low and lower_ma:
            safe_order_target_value(stock, 0)
            log.info('【开盘割肉】%s 低开%.2f, 低于10日线%.2f' % (stock, open_price, ma10_today))
            g.bought_today.discard(stock)


def sell_at_10am(context):
    """10:00 条件卖出：冲高 或 跌破分时均价线"""
    current_dt = context.current_dt
    # 仅对仍持有的昨日买入股票
    holdings = context.portfolio.positions
    to_sell = [s for s in holdings if holdings[s].closeable_amount > 0]
    for stock in to_sell:
        # 获取从开盘到10:00的分钟线数据
        bars = get_bars(stock, count=30, unit='1m', fields=['open', 'close', 'high', 'volume', 'money'], include_now=True)
        if bars is None or len(bars) == 0:
            continue
        
        # 开盘价（第一根K线的open）
        open_price = bars[0]['open']
        # 最高价
        high_price = max(b['high'] for b in bars)
        # 当前价（最后一根close）
        current_price = bars[-1]['close']
        # 分时均价线 = 累计成交额 / 累计成交量
        total_money = sum(b['money'] for b in bars)
        total_volume = sum(b['volume'] for b in bars)
        vwap = total_money / total_volume if total_volume > 0 else current_price
        
        # 条件1：冲高超过1.5%
        profit_ratio = (high_price - open_price) / open_price
        # 条件2：跌破均价线
        is_below_vwap = current_price < (vwap)
        log.info(f"sell_at_10am {stock} {is_below_vwap} {current_price} vwap={vwap}")
        if profit_ratio >= g.sell_profit_threshold or is_below_vwap:
            safe_order_target_value(stock, 0)
            log.info('【10点卖出】%s 冲高%.2f%%, 跌破均价线:%s' % (stock, profit_ratio*100, is_below_vwap))
            g.bought_today.discard(stock)


def sell_at_tail(context):
    """14:57 尾盘清仓"""
    # 因为早晨和10点已经卖过一部分，剩下的必须尾盘清
    holdings = context.portfolio.positions
    to_sell = [s for s in holdings if holdings[s].closeable_amount>0]
    for stock in to_sell:
        safe_order_target_value(stock, 0)
        log.info('【尾盘清仓】%s' % stock)
        g.bought_today.discard(stock)


# ==================== 收盘后重置记录 ====================
def after_trading_end(context):
    """每天交易结束后，清空今日买入记录（因为次日已不需要）"""
    # 实际上，g.bought_today中保留的是当天买入的股票，会在次日卖出后清除。
    # 但为了保险，可强制清空
    g.bought_today.clear()