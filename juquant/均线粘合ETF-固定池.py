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
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(2.0/1000))
    

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
    
    # 大盘风控参数
    g.s1_position_limit = 1.0 #上限满仓运行  
    g.s1_fix_take_profit = 0.07
    
def s1_schedule_tasks(context):
    run_daily(s1_etf_pool_and_filters, time='14:01')   # 更新池
    run_daily(s1_trade_sell, time='14:44')     # 卖出交易判断
    run_daily(s1_trade_buy, time='14:45')     # 买入交易判断
    run_daily(s1_take_fix_profit, time='14:46')     # 止盈
    # run_daily(s1_take_fix_profit, time='09:40')     # 止盈

def calc_take_profit(context,target):
    # 根据大盘行情，动态计算几档止盈比例[0.01,0.03,0.05,0.09,0.15]
    # 使用三根均线20,60,120趋势，三根都向上则去最高值
    rates = [0.01,0.03,0.05,0.09,0.15]
    security = "000001.XSHG" if target is None else target
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
    ma20_increase = ma20>last_ma20
    ma60_increase = ma60>last_ma60
    ma120_increase = ma120>last_ma120
    i=0
    if ma20_increase and ma60_increase and ma120_increase:
        # 短期，中期，长期都向上
        i=4
    elif ma60_increase and ma20_increase:
        # 中短期向上
        i=3
    elif ma60_increase:
        # 中期向上
        i=2
    elif ma20_increase:
        i = 1
    else:
        i = 0
    return rates[i]


def s1_take_fix_profit(context):
    # 固定止盈
    take_fix_profit_check(context,g.s1_fix_take_profit,pindex=0)

FIX_RATE_LIMITS = [0.03,0.03,0.015,0.015]
def take_fix_profit_check(context,rate_limit,pindex=0):
    """固定止盈法 每日检查持仓是否触发止盈"""
    current_data = get_current_data()
    # 按不同标的计算止盈
    
    positions = get_s1_portfolio_positions(context)
    for code, pos in positions.items():
        if pos.closeable_amount <= 0 or s1_can_not_deal(code):
            continue
        # rate_limit = calc_take_profit(context,code)
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
    # 历史粘合记录
    g.s1_ma_converged_history = {}

# ========== 2. ETF池构建与过滤（开盘前执行） ==========
def s1_etf_pool_and_filters(context):
    """
    每天开盘前执行：
    1. 市场ETF列表
    2. 规模过滤（>1亿元）
    3. 流动性过滤（成交量足够）
    4. 上市时间过滤（>60天）
    5. 计算日线均线粘合连续状态
    6. 计算MACD>0状态
    """
    current_date = context.current_dt.strftime('%Y-%m-%d')
    
    # ---------- 步骤1：获取全市场ETF ----------
    etf_dict = {
        "512100.XSHG":"1000ETF",
        "515180.XSHG":"100红利",
        "510300.XSHG":"300ETF",
        "562080.XSHG":"300现金流ETF",
        "510500.XSHG":"500ETF",
        "561550.XSHG":"500指增",
        "510050.XSHG":"50ETF",
        "515050.XSHG":"5GETF",
        "515800.XSHG":"800ETF",
        "561230.XSHG":"A50",
        "159361.XSHE":"A500ETF易方达",
        "159249.XSHE":"A500增强ETF工银",
        "560350.XSHG":"A50指数",
        "512930.XSHG":"AIETF",
        "563330.XSHG":"A股ETF",
        "560050.XSHG":"MSCIA50",
        "510760.XSHG":"上证ETF",
        "588060.XSHG":"上证科创",
        "513730.XSHG":"东南亚",
        "513050.XSHG":"中概互联",
        "560080.XSHG":"中药ETF",
        "159680.XSHE":"中证1000增强ETF招商",
        "563300.XSHG":"中证2000",
        "159552.XSHE":"中证2000增强ETF招商",
        "512500.XSHG":"中证500",
        "560510.XSHG":"中证A500ETF",
        "513310.XSHG":"中韩芯片",
        "516510.XSHG":"云计算",
        "515980.XSHG":"人工智能",
        "512980.XSHG":"传媒ETF",
        "515630.XSHG":"保险证券",
        "159939.XSHE":"信息技术ETF广发",
        "516880.XSHG":"光伏50",
        "159865.XSHE":"养殖ETF国泰",
        "512660.XSHG":"军工ETF",
        "159825.XSHE":"农业ETF富国",
        "159949.XSHE":"创业板50ETF华安",
        "159952.XSHE":"创业板ETF广发",
        "515120.XSHG":"创新药",
        "512000.XSHG":"券商ETF",
        "516120.XSHG":"化工50",
        "512170.XSHG":"医疗ETF",
        "159898.XSHE":"医疗器械ETF招商",
        "512010.XSHG":"医药ETF",
        "159929.XSHE":"医药ETF汇添富",
        "512480.XSHG":"半导体",
        "159516.XSHE":"半导体设备ETF国泰",
        "563230.XSHG":"卫星ETF",
        "588400.XSHG":"双创50",
        "512670.XSHG":"国防ETF",
        "512200.XSHG":"地产ETF",
        "511220.XSHG":"城投ETF",
        "516970.XSHG":"基建50",
        "515400.XSHG":"大数据",
        "159996.XSHE":"家电ETF国泰",
        "560860.XSHG":"工业有色",
        "159667.XSHE":"工业母机ETF国泰",
        "560280.XSHG":"工程机械",
        "159745.XSHE":"建材ETF国泰",
        "513030.XSHG":"德国ETF",
        "513600.XSHG":"恒指ETF",
        "513180.XSHG":"恒指科技",
        "159920.XSHE":"恒生ETF华夏",
        "159688.XSHE":"恒生互联网ETF华安",
        "513060.XSHG":"恒生医疗",
        "520500.XSHG":"恒生新药",
        "513970.XSHG":"恒生消费",
        "520690.XSHG":"恒生港药",
        "513280.XSHG":"恒生生物",
        "513130.XSHG":"恒生科技",
        "513690.XSHG":"恒生股息",
        "159259.XSHE":"成长ETF易方达",
        "159768.XSHE":"房地产ETF银华",
        "513360.XSHG":"教育ETF",
        "516160.XSHG":"新能源",
        "562510.XSHG":"旅游ETF",
        "513880.XSHG":"日经225",
        "515250.XSHG":"智能汽车",
        "512400.XSHG":"有色ETF",
        "159980.XSHE":"有色ETF大成",
        "562500.XSHG":"机器人",
        "159663.XSHE":"机床ETF华夏",
        "513500.XSHG":"标普500",
        "513650.XSHG":"标普ETF",
        "159518.XSHE":"标普油气ETF嘉实",
        "159529.XSHE":"标普消费ETF景顺",
        "159502.XSHE":"标普生物科技ETF嘉实",
        "562060.XSHG":"标普红利ETF",
        "516110.XSHG":"汽车ETF",
        "159565.XSHE":"汽车零部件ETF易方达",
        "520830.XSHG":"沙特ETF",
        "159329.XSHE":"沙特ETF南方",
        "513350.XSHG":"油气ETF",
        "562950.XSHG":"消电50",
        "515650.XSHG":"消费50",
        "510150.XSHG":"消费ETF",
        "159212.XSHE":"深100ETF南方",
        "516010.XSHG":"游戏ETF",
        "515220.XSHG":"煤炭ETF",
        "512580.XSHG":"环保ETF",
        "159399.XSHE":"现金流ETF国泰",
        "159859.XSHE":"生物医药ETF天弘",
        "561560.XSHG":"电力ETF",
        "159997.XSHE":"电子ETF天弘",
        "561100.XSHG":"电子龙头",
        "561910.XSHG":"电池ETF",
        "561380.XSHG":"电网ETF",
        "516670.XSHG":"畜牧养殖",
        "561360.XSHG":"石油ETF",
        "561330.XSHG":"矿业ETF",
        "159790.XSHE":"碳中和ETF华夏",
        "588190.XSHG":"科创100",
        "588000.XSHG":"科创50",
        "588730.XSHG":"科创AI",
        "588050.XSHG":"科创ETF",
        "588910.XSHG":"科创价值",
        "589770.XSHG":"科创全指",
        "588170.XSHG":"科创半导",
        "588110.XSHG":"科创成长",
        "589960.XSHG":"科创新源",
        "589720.XSHG":"科创新药",
        "588010.XSHG":"科创材料",
        "588090.XSHG":"科创板",
        "588080.XSHG":"科创板50",
        "515000.XSHG":"科技ETF",
        "516780.XSHG":"稀土ETF",
        "562800.XSHG":"稀有金属",
        "510880.XSHG":"红利ETF",
        "512890.XSHG":"红利低波",
        "520900.XSHG":"红利香港",
        "513110.XSHG":"纳指100",
        "513100.XSHG":"纳指ETF",
        "513290.XSHG":"纳指生物",
        "510210.XSHG":"综指ETF",
        "561170.XSHG":"绿电50",
        "513850.XSHG":"美国50",
        "159930.XSHE":"能源ETF汇添富",
        "159981.XSHE":"能源化工ETF建信",
        "159232.XSHE":"自由现金流ETF南方",
        "159267.XSHE":"航天ETF华安",
        "516350.XSHG":"芯片50",
        "512760.XSHG":"芯片ETF",
        "512720.XSHG":"计算机",
        "512880.XSHG":"证券ETF",
        "512070.XSHG":"证券保险",
        "159985.XSHE":"豆粕ETF华夏",
        "511380.XSHG":"转债ETF",
        "515230.XSHG":"软件ETF",
        "515880.XSHG":"通信ETF",
        "563320.XSHG":"通用航空",
        "513400.XSHG":"道琼斯",
        "512690.XSHG":"酒ETF",
        "510230.XSHG":"金融ETF",
        "516860.XSHG":"金融科技",
        "515210.XSHG":"钢铁ETF",
        "512800.XSHG":"银行ETF",
        "515710.XSHG":"食品ETF",
        "515170.XSHG":"食品饮料",
        "513090.XSHG":"香港证券",
        "518880.XSHG":"黄金ETF",
        "159562.XSHE":"黄金股ETF华夏",
    }
    all_etfs = list(etf_dict.keys())
    log.info('市场ETF总数：{}'.format(len(all_etfs)))
    
    # ---------- 步骤2：上市时间过滤 ----------
    valid_etfs = []
    for etf in all_etfs:
        # 检查上市时间
        try:
            info = get_security_info(etf)
            if info is None or info.start_date is None:
                continue
            days_since_listed = (context.current_dt.date() - info.start_date).days
            if days_since_listed < 60:
                continue
            if s1_can_not_deal(etf):
                continue
        except:
            continue
        valid_etfs.append(etf)
    
    g.s1_etf_pool = valid_etfs
    log.info('上市时间过滤后ETF池{}只'.format(len(valid_etfs)))
    
    # ---------- 步骤3：缓存均线粘合连续状态（复用原策略逻辑） ----------
    # 获取今日各ETF是否粘合
    converged_set = set()
    for etf in valid_etfs:
        is_converged = s1_check_ma_convergence_daily(etf, context)
        if is_converged:
            ma120 = s1_check_ma_increase(etf, context)
            if ma120:
                converged_set.add(etf)
    
    # ---------- 步骤4：缓存MACD>0状态 ----------
    positive_set = set()
    for etf in valid_etfs:
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
            log.info(f'{code} 当前接近涨停，暂停买入')
            can_not_deal = True
        if cur_price <= prev_close * 0.902:   # 接近跌停
            log.info(f'{code} 当前接近跌停，暂停买入')
            can_not_deal = True
    if can_not_deal:
        log.info(f"{code} can_not_deal={can_not_deal},no_price={no_price} is_paused={is_paused} is_st={is_st} is_limit={is_limit}")
    return can_not_deal
    
# ========== 3. 日线均线粘合判断（与原策略相同，直接复用） ==========
def s1_check_ma_convergence_daily(security, context):
    """判断日线级别均线是否粘合，返回True/False"""
    df = attribute_history(security, 80, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 60:
        return False
    is_convergence = True
    for i in range(0,g.s1_consecutive_days):
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