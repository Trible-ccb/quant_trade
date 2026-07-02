# ************************************************************
# 策略名称：三层过滤·动态分批ETF轮动策略（V3.0）
# 平台：聚宽（JoinQuant）
# 版本：1.0
# 说明：本策略严格按照最终版策略描述实现，包含：
#       1. 流动性过滤（20日日均成交额 >= 1亿）
#       2. 三层买入过滤（500日高点折价、200日线、120日线突破）
#       3. 分层建仓机制（根据偏离度决定仓位比例）
#       4. 动态ATR止盈 + 20日线止损 + 时间效率止损
#       5. 按"成交量×涨幅"排序取前3
# ************************************************************

from jqdata import *
import numpy as np
import pandas as pd

# ==================== 全局参数配置 ====================

# 流动性门槛：20日日均成交额 >= 5000万
MIN_AVG_AMOUNT = 50000000

# 单只ETF最大仓位（占总资产比例）
MAX_SINGLE_POSITION_RATIO = 0.30

# 最大持仓数量
MAX_HOLDINGS = 3

# ATR计算周期
ATR_PERIOD = 14

# 动态止盈倍数（最高价回撤超过 N倍 ATR 则止盈）
ATR_STOP_MULTIPLIER = 2.5

# 时间效率止损：持有超过 N 个交易日
TIME_STOP_DAYS = 15*10

# 时间效率止损：区间振幅低于此值（百分比）视为横盘
TIME_STOP_AMPLITUDE = 0.05

# 时间效率止损：收益率低于此值（百分比）视为效率低下
TIME_STOP_RETURN = 0.02

# 回踩加仓：首次回踩10日线时追加仓位比例（占总资产）
PULLBACK_ADD_RATIO = 0.10

# ==================== 初始化函数 ====================

def initialize(context):
    """
    聚宽初始化函数，在回测开始时执行一次
    """
    # ----- 1. 设置基准 -----
    # 使用沪深300指数作为业绩基准
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))
    
    # ----- 3. 设置运行时间 -----
    # 每日09:00更新候选池（获取ETF列表并过滤流动性）
    run_daily(before_trading_start, time='09:00')
    # 每日14:55执行买卖信号判断与交易
    run_daily(do_sell, time='14:50')
    run_daily(do_add, time='14:51')
    run_daily(do_buy, time='14:52')
    
    # ----- 4. 初始化全局变量 -----
    # 候选ETF池（每日09:00更新）
    g.candidate_pool = []
    # 持仓记录：{security: {'buy_date': date, 'buy_price': float, 
    #                        'highest_price': float, 'ma10_add_used': bool}}
    g.positions_info = {}
    # 记录当日已处理的卖出（防止重复操作）
    g.sold_today = []


# ==================== 每日09:00：更新候选池 ====================

def before_trading_start(context):
    """
    每日09:00执行：获取全市场ETF，过滤流动性
    """
    # 获取当前日期
    current_date = context.current_dt.date()
    
    # 获取所有基金（包含ETF）
    # 注意：get_all_securities(['fund']) 返回所有基金，需要进一步过滤ETF
    all_funds = get_all_securities(['fund'], date=current_date)
    
    # 过滤出ETF：通常ETF的名称包含'ETF'或'etf'，且类型为'etf'
    # 更准确的方式：通过get_extras()获取基金类型，或使用预先定义的ETF列表
    # 这里采用名称过滤 + 上市天数过滤的简化方案
    etf_list = []
    for code, row in all_funds.iterrows():
        name = row['display_name']
        # 简单过滤：名称包含ETF（可根据需要扩充关键词）
        if 'ETF' in name.upper() or '指数' in name:
            # 检查上市天数（至少上市60天，确保数据充足）
            start_date = row['start_date']
            if start_date and (current_date - start_date).days >= 60:
                etf_list.append(code)
    
    # 进一步过滤：计算20日日均成交额 >= 5000万
    # 注意：attribute_history只能获取单只股票数据，这里用history批量获取
    qualified = []
    qualified_names = []
    if etf_list:
        # 分批获取数据，避免一次请求过多
        batch_size = 50
        for i in range(0, len(etf_list), batch_size):
            batch = etf_list[i:i+batch_size]
            try:
                # 获取过去20个交易日的成交额数据
                hist = history(20, unit='1d', field='money', 
                               security_list=batch, df=True, skip_paused=True)
                # 计算日均成交额
                avg_amount = hist.mean(axis=0)
                for code in batch:
                    if code in avg_amount.index:
                        if avg_amount[code] >= MIN_AVG_AMOUNT:
                            qualified.append(code)
                            qualified_names.append(mingcheng(code))
            except Exception as e:
                log.warning(f"获取{len(batch)}只ETF数据失败: {e}")
                continue
    
    g.candidate_pool = qualified
    log.info(f"候选池更新完成，共 {len(g.candidate_pool)} 只ETF")

def mingcheng(stock):
    try: return get_security_info(stock).display_name
    except: return stock

# ==================== 技术指标计算辅助函数 ====================

def get_ma(security, count, field='close', unit='1d'):
    """
    获取指定证券的N日均线值
    """
    data = attribute_history(security, count, unit=unit, 
                             fields=[field], skip_paused=True)
    if len(data) < count:
        return None
    return data[field].mean()


def get_high(security, count, unit='1d'):
    """
    获取指定证券的N日最高价
    """
    data = attribute_history(security, count, unit=unit, 
                             fields=['high'], skip_paused=True)
    if len(data) < count:
        return None
    return data['high'].max()


def get_atr(security, period=ATR_PERIOD):
    """
    计算指定证券的ATR（平均真实波幅）
    使用TA-Lib的ATR函数，若不可用则手动计算
    """
    try:
        # 尝试使用TA-Lib
        import talib
        data = attribute_history(security, period + 1, '1d', 
                                 fields=['high', 'low', 'close'], 
                                 skip_paused=True)
        if len(data) < period + 1:
            return None
        high = np.array(data['high'])
        low = np.array(data['low'])
        close = np.array(data['close'])
        atr = talib.ATR(high, low, close, timeperiod=period)
        return atr[-1]
    except:
        # 手动计算ATR
        data = attribute_history(security, period + 1, '1d',
                                 fields=['high', 'low', 'close'],
                                 skip_paused=True)
        if len(data) < period + 1:
            return None
        # 计算True Range
        high = data['high'].values
        low = data['low'].values
        close = data['close'].values
        tr = np.zeros(len(high))
        tr[0] = high[0] - low[0]
        for i in range(1, len(high)):
            tr[i] = max(high[i] - low[i],
                        abs(high[i] - close[i-1]),
                        abs(close[i-1] - low[i]))
        # 计算ATR（简单移动平均）
        atr = np.mean(tr[-period:])
        return atr


# ==================== 买入信号判断 ====================

def check_buy_signal(security, current_data, context):
    """
    检查单只ETF是否触发买入信号
    返回: (是否触发, 偏离度, 建议仓位比例)
    """
    today = context.current_dt.date()
    # ----- 条件1：流动性过滤（已在候选池中，此处无需重复） -----
    if security not in g.candidate_pool:
        return False, 0, 0
    
    # ----- 条件2：绝对安全垫（距500日高点跌超30%） -----
    cur_price = current_data.last_price
    high_500 = get_high(security, 500)
    high_500_lower =  0.75 * high_500
    
    if high_500 is None:
        return False, 0, 0
    if cur_price > high_500_lower:
        return False, 0, 0
    
    # ----- 条件3：长期趋势保护（站上200日均线） -----
    ma120 = get_ma(security, 120)

    if ma120 is None:
        return False, 0, 0
    if cur_price < ma120:
        return False, 0, 0
    
    # ----- 条件4：120日线突破确认 -----
    # 获取昨日收盘价（从历史数据获取）
    hist = attribute_history(security, 2, '1d', 
                             fields=['close'], skip_paused=True)
    if len(hist) < 2:
        return False, 0, 0
    yesterday_close = hist['close'].iloc[-1]
    log.info(f"{security} 120日线突破确认 昨日={yesterday_close} ma120={ma120} 当前={cur_price}")
    # 昨日在线下，今日在线上 = 突破
    if not (yesterday_close < ma120 and cur_price > ma120):
        return False, 0, 0
    
    # 计算偏离度
    deviation = (cur_price - ma120) / ma120
    
    # ----- 条件5：均线多头排列（10 > 20）且20日线斜率向上 -----
    ma20 = get_ma(security, 20)
    ma10 = get_ma(security, 10)
    if ma20 is None or ma10 is None:
        return False, 0, 0
    if not (ma10 > ma20):
        return False, 0, 0
    open_price = current_data.day_open
    # 20日线斜率：今日20日线 > 5日前20日线
    ma20_5d_ago = get_ma(security, 20, field='close', unit='1d')
    # 需要获取5天前的20日均线：先获取25天数据，取前5天的均值
    data_25 = attribute_history(security, 25, '1d', 
                                fields=['close'], skip_paused=True)
    if len(data_25) < 25:
        return False, 0, 0
    ma20_5d_ago = data_25['close'].iloc[0:20].mean()
    if ma20 <= ma20_5d_ago:
        return False, 0, 0
    
    # ----- 条件6：量价配合（阳线 + 成交量放大） -----
    if cur_price <= open_price:
        return False, 0, 0
    # 成交量 > 5日均量
    vol_hist = attribute_history(security, 5, '1d', 
                                 fields=['volume'], skip_paused=True)
    if len(vol_hist) < 5:
        return False, 0, 0
    vol_ma5 = vol_hist['volume'].iloc[0:5].mean()  # 过去5天（不含今日）
    today_vol = get_current_data_volume(context,security)
    log.info(f"{security} 现价={cur_price} 开盘价={open_price} 放量确认 vol_ma5={vol_ma5} today_vol={today_vol} {deviation}")

    if today_vol <= vol_ma5:
        return False, 0, 0
    
    # ----- 所有条件通过，计算建议仓位比例（分层建仓） -----
    if 0 < deviation <= 0.03:
        # 温和突破：建仓70%
        target_ratio = 0.70
    elif 0.03 < deviation <= 0.08:
        # 强势突破：建仓30%（轻仓试错）
        target_ratio = 0.30
    else:
        # 偏离度 > 8%：放弃买入
        return False, 0, 0
    
    return True, deviation, target_ratio


# ==================== 卖出信号判断 ====================

def check_sell_signal(security, current_data, context):
    """
    检查单只ETF是否触发卖出信号
    返回: (是否触发, 原因)
    """
    today = context.current_dt.date()
    open_price = current_data.day_open
    holdings = context.portfolio.positions
    # 获取持仓记录
    if security not in g.positions_info:
        return False, ""
    
    info = g.positions_info[security]
    buy_price = info['buy_price']
    buy_date = info['buy_date']
    highest_price = info['highest_price']
    cur_price = current_data.last_price
    # 更新最高价
    if cur_price > highest_price:
        g.positions_info[security]['highest_price'] = cur_price
        highest_price = cur_price
    
    # ----- 卖出条件1：动态ATR止盈 -----
    atr = get_atr(security, ATR_PERIOD)
    if atr is not None:
        drawdown = highest_price - cur_price
        if drawdown > ATR_STOP_MULTIPLIER * atr:
            return True, f"{security} 动态止盈(回撤{drawdown/cur_price:.2%}%)"
    
    # ----- 卖出条件2：趋势破位止损（跌破20日线 + 阴线） -----
    ma20 = get_ma(security, 20)
    low_price = get_current_data_low_price(context,security)
    if ma20 is not None:
        if (cur_price < ma20 and 
            low_price < ma20 * 0.98 and 
            cur_price < open_price):
            return True, f"{security} 收阴线 且跌破20均线(收盘{cur_price:.2f}<MA20{ma20:.2f})"
    
    # ----- 卖出条件3：时间效率止损 -----
    hold_days = (today - buy_date).days
    if hold_days > TIME_STOP_DAYS:
        # 计算区间振幅
        hist = attribute_history(security, hold_days + 1, '1d',
                                 fields=['high', 'low'], skip_paused=True)
        if len(hist) >= hold_days:
            high_in_period = hist['high'].max()
            low_in_period = hist['low'].min()
            amplitude = (high_in_period - low_in_period) / low_in_period
            # 计算当前收益率
            return_rate = (cur_price - buy_price) / buy_price
            if amplitude < TIME_STOP_AMPLITUDE and return_rate < TIME_STOP_RETURN:
                return True, f"{security} 时间止损(持有{hold_days}天,收益{return_rate*100:.2f}%)"
    
    return False, ""


# ==================== 回踩加仓检查 ====================

def check_pullback_add(security, current_data, context):
    """
    检查是否触发回踩加仓（首次回踩10日线）
    返回: (是否触发, 加仓比例)
    """
    if security not in g.positions_info:
        return False, 0
    
    info = g.positions_info[security]
    
    # 已经加仓过则不再加
    if info.get('ma10_add_used', False):
        return False, 0
    
    # 当前仓位是否已达到30%上限
    current_pos = context.portfolio.positions[security]
    if current_pos.total_amount > 0:
        current_value = current_pos.total_amount * current_pos.price
        total_value = context.portfolio.total_value
        if current_value / total_value >= MAX_SINGLE_POSITION_RATIO:
            return False, 0
    cur_price = current_data.last_price
    # 检查是否回踩10日线
    ma10 = get_ma(security, 10)
    if ma10 is None:
        return False, 0
    low_price = get_current_data_low_price(context,security)
    # 今日最低价触碰10日线，且收盘站上10日线（典型的支撑确认）
    if low_price <= ma10 <= cur_price:
        # 且今日收阳线
        if cur_price > current_data.day_open:
            return True, PULLBACK_ADD_RATIO
    
    return False, 0

def get_current_data_low_price(context,code):
    # 获取今日内的最低价
    timeStr = context.current_dt.strftime("%Y-%m-%d %H:%M:00")
    prices = get_bars(code, count=8, unit='30m', fields=['date', 'low'],
include_now=False, end_dt=timeStr)
    low_price = 9999
    if len(prices): 
        for i in range(0,len(prices)):
            if low_price>prices[i]['low']:
                low_price = prices[i]['low']
    log.info(f"{code} get_current_data_low_price {low_price}")
    return low_price

def get_current_data_volume(context,code):
    # 获取今日截止当前的成交量
    timeStr = context.current_dt.strftime("%Y-%m-%d %H:%M:00")
    prices = get_bars(code, count=240, unit='1m', fields=['date','volume'],
include_now=False, end_dt=timeStr)
    vol = 0
    if len(prices): 
        for i in range(0,len(prices)):
            vol += prices[i]['volume']
    log.info(f"{code} get_current_data_volume {vol}")
    return vol
    
# ==================== 核心交易逻辑（每日14:55） ====================
def do_sell(context):
    today = context.current_dt.date()
    log.info(f"do_sell check {today}")
    # ----- Step 1: 检查现有持仓的卖出信号 -----
    for security in list(context.portfolio.positions.keys()):
        # 跳过已经卖出的
        if security in g.sold_today:
            continue
        
        pos = context.portfolio.positions[security]
        if pos.closeable_amount == 0:
            continue
        
        # 获取当前数据
        current_data = get_current_data()[security]
        
        # 检查卖出信号
        sell_signal, reason = check_sell_signal(security, current_data, context)
        if sell_signal:
            # 执行卖出（清仓）
            order_target(security, 0)
            g.sold_today.append(security)
            # 清除持仓记录
            if security in g.positions_info:
                del g.positions_info[security]
            log.info(f"{today} 卖出 {security}: {reason}")

def do_add(context):
    log.info(f"do_add 加仓 check")
    # ----- Step 2: 检查现有持仓的回踩加仓 -----
    for security in list(context.portfolio.positions.keys()):
        if security in g.sold_today:
            continue
        pos = context.portfolio.positions[security]
        if pos.total_amount == 0:
            continue
        
        current_data = get_current_data()[security]
        
        add_signal, add_ratio = check_pullback_add(security, current_data, context)
        if add_signal:
            # 计算加仓金额
            total_value = context.portfolio.total_value
            add_cash = total_value * add_ratio
            # 确保不超过单只30%上限
            current_value = pos.total_amount * pos.price
            if (current_value + add_cash) / total_value <= MAX_SINGLE_POSITION_RATIO:
                order_value(security, add_cash)
                g.positions_info[security]['ma10_add_used'] = True
                log.info(f"{today} 回踩加仓 {security}: +{add_ratio*100:.1f}%仓位")
    
def do_buy(context):
    """
    每日14:55执行：买卖信号判断与交易
    """
    today = context.current_dt.date()
    g.sold_today = []
    log.info(f"handle_data_0 check {today}")
    
    # ----- Step 3: 检查新买入信号（仅当持仓数 < MAX_HOLDINGS） -----
    current_holdings = [s for s in context.portfolio.positions.keys() 
                        if context.portfolio.positions[s].total_amount > 0]
    if len(current_holdings) >= MAX_HOLDINGS:
        return
    
    # 收集所有触发买入信号的ETF
    buy_candidates = []
    for security in g.candidate_pool:
        # 跳过已经持有的（不重复买入）
        if security in current_holdings:
            continue
        # 跳过今日已卖出的（当日不买回）
        if security in g.sold_today:
            continue
        
        current_data = get_current_data()[security]
        signal, deviation, target_ratio = check_buy_signal(security, current_data, context)
        if signal:
            # 计算得分 = 成交量 × 涨幅
            yesterday_close = attribute_history(security, 2, '1d', 
                                                fields=['close'], skip_paused=True)
            if len(yesterday_close) >= 2:
                yesterday_close_val = yesterday_close['close'].iloc[-1]
                change = (current_data.last_price - yesterday_close_val) / yesterday_close_val
                score = get_current_data_volume(context,security) * change
                buy_candidates.append((security, score, target_ratio, deviation))
    
    # 按得分降序排序
    buy_candidates.sort(key=lambda x: x[1], reverse=True)
    
    # 取前N个（不超过剩余仓位数）
    remaining_slots = MAX_HOLDINGS - len(current_holdings)
    selected = buy_candidates[:remaining_slots]
    
    # ----- Step 4: 执行买入 -----
    total_value = context.portfolio.total_value
    available_cash = context.portfolio.available_cash
    
    for security, score, target_ratio, deviation in selected:
        # 计算该标的分配金额（等权分配，但不超过单只上限）
        slot_cash = available_cash / len(selected) if selected else 0
        max_cash = total_value * MAX_SINGLE_POSITION_RATIO
        # 应用分层建仓比例
        allocate_cash = min(slot_cash * target_ratio, max_cash)
        
        if allocate_cash > 0:
            current_data = get_current_data()[security]
            # 执行买入
            order_value(security, allocate_cash)
            # 记录持仓信息
            g.positions_info[security] = {
                'buy_date': today,
                'buy_price': current_data.last_price,
                'highest_price': current_data.last_price,
                'ma10_add_used': False
            }
            log.info(f"{today} 买入 {security}: 金额{allocate_cash} 偏离度{deviation*100:.2f}%, "
                    f"仓位{allocate_cash/total_value*100:.1f}%, 得分{score:.2e}")

def after_trading_end(context):
    g.sold_today = []
    
# ==================== 回测后分析（可选） ====================

def after_code_changed(context):
    """
    代码修改后重新运行
    """
    pass