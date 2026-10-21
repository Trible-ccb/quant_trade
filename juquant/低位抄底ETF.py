# 聚宽低位反转ETF轮动策略（增加底背离条件）
# 标的：场内ETF、LOF
# 买入条件：
#   1. 日线MACD > 0
#   2. 最新DEA > 10日前的DEA
#   3. 昨日20日均线比20天前的20日均线低2%以上
#   4. 当前价格距一年内最高价跌幅 > 30%
#   5. 当日阳线
#   6. 最近一个月（20个交易日）内出现过MACD底背离（价格创新低但DIFF未创新低）
# 卖出：止损-10% / 止盈+25%
# 风控：成交额>1000万、价格<10元、最大持仓数10

from jqdata import *
import numpy as np
import pandas as pd

# =======================实盘配置（回测模式）===============================
Live_Type = False

def common_init(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.002))

def set_params(context):
    g.max_holdings = 4
    g.entry_price = {}
    g.ma_period = 20
    g.drop_threshold = 0.30
    g.stop_loss = 0.10
    g.take_profit = 0.25
    g.min_amount = 10000000
    g.max_price = 10.0
    g.divergence_lookback = 20   # 底背离检测窗口（一个月约20交易日）

def schedule_tasks(context):
    run_daily(etf_pool_and_filters, time='14:01')
    run_daily(trade_sell, time='14:44')
    run_daily(trade_buy, time='14:45')

def after_code_changed(context):
    common_init(context)
    set_params(context)
    schedule_tasks(context)

def initialize(context):
    common_init(context)
    set_params(context)
    schedule_tasks(context)
    g.etf_pool = []

# ========== 候选池更新 ==========
def etf_pool_and_filters(context):
    etf_dict = {
        "510300.XSHG": "沪深300ETF",
        "510500.XSHG": "中证500ETF",
        "510050.XSHG": "上证50ETF",
        "588000.XSHG": "科创50ETF",
        "159915.XSHE": "创业板ETF",
        "159949.XSHE": "创业板50ETF",
        "512100.XSHG": "中证1000ETF",
        "159901.XSHE": "深100ETF",
        "159601.XSHE": "MSCI中国A50ETF",
        "159920.XSHE": "恒生ETF",
        "513130.XSHG": "恒生科技ETF易方达",
        "513330.XSHG": "恒生互联ETF",
        "159776.XSHE": "港股通医药ETF",
        "159712.XSHE": "港股通50ETF",
        "513990.XSHG": "港股通ETF",
        "159941.XSHE": "纳指ETF",
        "513500.XSHG": "标普500ETF",
        "513400.XSHG": "道琼斯ETF",
        "159529.XSHE": "标普消费ETF",
        "159518.XSHE": "标普油气ETF",
        "162411.XSHE": "华宝油气LOF",
        "159655.XSHE": "纳指生物科技ETF",
        "161127.XSHE": "标普生物科技LOF",
        "513880.XSHG": "日经ETF",
        "513030.XSHG": "德国ETF",
        "513080.XSHG": "法国CAC40ETF",
        "513730.XSHG": "东南亚科技ETF",
        "159687.XSHE": "亚太精选ETF",
        "513310.XSHG": "中韩半导体ETF",
        "520580.XSHG": "新兴亚洲ETF",
        "164824.XSHE": "印度基金LOF",
        "520830.XSHG": "沙特ETF",
        "513050.XSHG": "中概互联ETF",
        "159980.XSHE": "有色ETF",
        "159985.XSHE": "豆粕ETF",
        "159981.XSHE": "能源化工ETF",
        "161226.XSHE": "白银LOF",
        "512480.XSHG": "半导体ETF",
        "159995.XSHE": "芯片ETF",
        "588170.XSHG": "科创半导体ETF",
        "159516.XSHE": "半导体设备ETF",
        "159819.XSHE": "人工智能ETF",
        "159246.XSHE": "创业板人工智能ETF",
        "515880.XSHG": "通信ETF",
        "515050.XSHG": "5G通信ETF",
        "516510.XSHG": "云计算ETF",
        "159739.XSHE": "大数据ETF",
        "512980.XSHG": "传媒ETF",
        "159869.XSHE": "游戏ETF",
        "159851.XSHE": "金融科技ETF",
        "159530.XSHE": "机器人ETF",
        "516090.XSHG": "新能源ETF",
        "159790.XSHE": "碳中和ETF",
        "159175.XSHE": "电池ETF",
        "159566.XSHE": "储能电池ETF",
        "515030.XSHG": "新能源车ETF",
        "159611.XSHE": "电力ETF",
        "560390.XSHG": "电网设备ETF",
        "512010.XSHG": "医药ETF",
        "516080.XSHG": "创新药ETF",
        "512170.XSHG": "医疗ETF",
        "159883.XSHE": "医疗器械ETF",
        "512290.XSHG": "生物医药ETF",
        "560080.XSHG": "中药ETF",
        "513200.XSHG": "港股通医药ETF",
        "512690.XSHG": "酒ETF",
        "159843.XSHE": "食品饮料ETF",
        "159798.XSHE": "消费ETF",
        "562580.XSHG": "可选消费ETF",
        "159996.XSHE": "家电ETF",
        "562510.XSHG": "旅游ETF",
        "159825.XSHE": "农业ETF",
        "516670.XSHG": "养殖ETF",
        "510230.XSHG": "金融ETF",
        "512880.XSHG": "证券ETF",
        "512800.XSHG": "银行ETF",
        "512070.XSHG": "非银ETF",
        "159768.XSHE": "房地产ETF",
        "512660.XSHG": "军工ETF",
        "159227.XSHE": "航天航空ETF",
        "512670.XSHG": "国防ETF",
        "159667.XSHE": "工业母机ETF",
        "560280.XSHG": "工程机械ETF",
        "588220.XSHG": "科创100ETF",
        "512400.XSHG": "有色金属ETF",
        "515220.XSHG": "煤炭ETF",
        "515210.XSHG": "钢铁ETF",
        "516120.XSHG": "化工50ETF",
        "159930.XSHE": "能源ETF",
        "516970.XSHG": "基建ETF",
        "516750.XSHG": "建材ETF",
        "159666.XSHE": "交通运输ETF",
        "561230.XSHG": "物流ETF",
        "510880.XSHG": "红利ETF",
        "515080.XSHG": "中证红利ETF",
        "159905.XSHE": "深证红利ETF",
        "159222.XSHE": "自由现金流ETF",
        "516720.XSHG": "ESGETF",
        "561580.XSHG": "央企红利ETF",
        "517090.XSHG": "国企共赢ETF",
        "515990.XSHG": "一带一路ETF",
        "159852.XSHE": "软件ETF",
    }
    all_codes = list(etf_dict.keys())
    log.info('全市场标的数：{}'.format(len(all_codes)))
    
    valid_codes = []
    for code in all_codes:
        try:
            info = get_security_info(code)
            if info is None or info.start_date is None:
                continue
            if (context.current_dt.date() - info.start_date).days < 60:
                continue
        except:
            continue
        
        bars = get_bars(code, count=5, unit='1d', fields=['money'], include_now=False, df=True)
        if bars is None or len(bars) < 5 or bars['money'].mean() < g.min_amount:
            continue
        
        cur_data = get_current_data()
        price = cur_data[code].last_price
        if price is None or price <= 0 or price >= g.max_price:
            continue
        if cur_data[code].paused:
            continue
        
        valid_codes.append(code)
    
    g.etf_pool = valid_codes
    log.info('候选池最终数量：{}'.format(len(g.etf_pool)))

# ========== 底背离检测函数 ==========
def has_bearish_divergence(close, dif, lookback=20):
    """
    检测最近lookback个交易日内是否出现底背离。
    底背离定义：价格创阶段新低，但对应的DIFF指标未创新低。
    具体比较最近lookback天的最低价与前lookback天的最低价，
    如果价格新低且DIFF高于前低对应的DIFF，则返回True。
    """
    if len(close) < 2 * lookback:
        return False
    # 取最近lookback天和前lookback天
    recent_close = close.iloc[-lookback:]
    prev_close = close.iloc[-2*lookback:-lookback]
    recent_dif = dif.iloc[-lookback:]
    prev_dif = dif.iloc[-2*lookback:-lookback]
    
    # 找最近窗口最低价及其索引
    idx_recent_min = recent_close.idxmin()
    idx_prev_min = prev_close.idxmin()
    
    price_recent_min = recent_close[idx_recent_min]
    price_prev_min = prev_close[idx_prev_min]
    dif_recent_min = recent_dif[idx_recent_min]
    dif_prev_min = prev_dif[idx_prev_min]
    
    # 如果价格创新低且DIFF未创新低（即DIFF抬高）
    if price_recent_min < price_prev_min and dif_recent_min > dif_prev_min:
        return True
    return False

# ========== 买入条件判断 ==========
def check_buy_conditions(security, context):
    # 获取250天日线数据
    df = attribute_history(security, 250, '1d', ['close', 'open', 'high'], skip_paused=True, df=True)
    if df is None or len(df) < 60:
        return False
    
    close = df['close']
    open_price = df['open']
    high = df['high']
    
    # 计算MACD指标（获取DIFF、DEA、MACD柱）
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    dif = exp1 - exp2
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = dif - dea
    
    # 1. MACD > 0
    if macd.iloc[-1] <= 0:
        return False
    
    # 2. 最新DEA > 10日前的DEA
    dea_not_match = dea.iloc[-1] <= dea.iloc[-21]
    
    # 3. 昨日20日均线比20天前的20日均线低2%以上
    ma20 = close.rolling(window=g.ma_period).mean()
    if len(ma20) < 22:
        return False
    ma20_yesterday = ma20.iloc[-1]
    ma20_20d_ago = ma20.iloc[-21]
    ma20_not_match = (ma20_yesterday - ma20_20d_ago) / ma20_20d_ago >= -0.01
    
    # 4. 距一年内最高点跌幅 > 30%
    max_high = high.max()
    current_price = close.iloc[-1]
    high_not_match = max_high <= 0 or (max_high - current_price) / max_high <= g.drop_threshold
    
    # 5. 当日阳线
    if close.iloc[-1] <= open_price.iloc[-1]:
        return False
    red_not_match = close.iloc[-1] <= open_price.iloc[-1]
    # 6. 最近一个月出现底背离（使用DIFF）
    diff_not_match = not has_bearish_divergence(close, dif, lookback=g.divergence_lookback)
    final_not_match = dea_not_match or ma20_not_match or high_not_match or red_not_match or diff_not_match
    match = not final_not_match
    if '159852.XSHE' == security:
        log.info(f"check_buy_conditions {security} {mingcheng(security)} 满足={match} dea={dea_not_match} ma20={ma20_not_match} high={high_not_match} red={red_not_match} diff_not_match={diff_not_match}")
        
    return match

# ========== 卖出条件 ==========
def check_sell_conditions(security, context):
    if security not in g.entry_price:
        return None
    entry = g.entry_price[security]
    price = get_current_data()[security].last_price
    if price is None or price <= 0:
        return None
    pnl = (price - entry) / entry
    if pnl <= -g.stop_loss:
        return 'stop_loss'
    elif pnl >= g.take_profit:
        return 'take_profit'
    return None

# ========== 交易辅助 ==========
def can_not_deal(code):
    cur_data = get_current_data()
    price = cur_data[code].last_price
    if price is None or price <= 0:
        return True
    if cur_data[code].paused:
        return True
    if cur_data[code].high_limit and price >= cur_data[code].high_limit * 0.99:
        return True
    if cur_data[code].low_limit and price <= cur_data[code].low_limit * 1.01:
        return True
    return False

def safe_order_target_percent(context, code, target_percent):
    if can_not_deal(code):
        return 0
    price = get_current_data()[code].last_price
    if price is None or price <= 0:
        return 0
    target_value = context.portfolio.total_value * target_percent
    amount = int(target_value / price / 100) * 100
    if amount <= 0:
        return 0
    if code[:2] == '68' and amount < 200:
        return 0
    order(code, amount, MarketOrderStyle())
    return amount

# ========== 交易执行 ==========
def trade_sell(context):
    positions = context.portfolio.positions
    for sec in list(positions.keys()):
        if positions[sec].total_amount == 0:
            continue
        if can_not_deal(sec):
            continue
        signal = check_sell_conditions(sec, context)
        if signal:
            log.info('{} 触发卖出信号：{}'.format(sec, signal))
            order_target(sec, 0)
            if sec in g.entry_price:
                del g.entry_price[sec]

def trade_buy(context):
    positions = context.portfolio.positions
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    if len(current_holdings) >= g.max_holdings:
        return
    
    candidates = []
    for sec in g.etf_pool:
        if sec in current_holdings:
            continue
        if check_buy_conditions(sec, context):
            candidates.append(sec)
        if len(candidates) >= g.max_holdings - len(current_holdings):
            break
    
    if not candidates:
        return
    
    used_ratio = context.portfolio.positions_value / context.portfolio.total_value
    remaining_ratio = 1 - used_ratio
    max_percent = 1.0 / g.max_holdings
    per_ratio = min(remaining_ratio / len(candidates), max_percent)
    if per_ratio <= 0:
        return
    
    for sec in candidates:
        amount = safe_order_target_percent(context, sec, per_ratio)
        if amount > 0:
            price = get_current_data()[sec].last_price
            g.entry_price[sec] = price
            log.info('买入 {} 比例 {:.2%}，价格 {:.3f}'.format(sec, per_ratio, price))

def mingcheng(stock):
    try: return get_security_info(stock).display_name
    except: return stock