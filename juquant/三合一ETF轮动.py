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
        if 'sim_trade' != context.run_params.type:
            return
        ok = bt_wrapper.qmt_is_ok()
        if not ok:
            send_message("QMT服务端异常，检查云服务器是否正常登录qmt")
    except Exception as e:
        print(f"before_trading_start检查qmt异常")
        
# =======================实盘配置End=======================================
BUY_SLIP = 0.001
def initialize(context):
    total_init_cash = context.portfolio.available_cash
    # 均线粘合策略资金
    g.s1_cash = total_init_cash // 5
    # N大宽基策略资金
    g.s2_cash = total_init_cash // 5 * 2
    # 全球ETF策略资金
    g.s3_cash = total_init_cash // 5 * 2
    set_subportfolios([SubPortfolioConfig(cash=g.s1_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s2_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s3_cash, type='stock')])
    if g.s1_cash > 0:
        log.info(f"启动【均线粘合策略1】,分配金额{g.s1_cash}")
        s1_initialize(context)
    if g.s2_cash > 0:
        log.info(f"启动【N大宽基ETF策略2】,分配金额{g.s2_cash}")
        s2_initialize(context)
    if g.s3_cash > 0:
        log.info(f"启动【全球ETF轮动策略3】,分配金额{g.s3_cash}")
        s3_initialize(context)

def after_trading_end(context):
    if g.s1_cash > 0:
        s1_after_trading_end(context)
    if g.s2_cash > 0:
        s2_after_trading_end(context)
    if g.s3_cash > 0:
        s3_after_trading_end(context)

def after_code_changed(context):
    unschedule_all()
    if g.s1_cash > 0:
        s1_after_code_changed(context)
    if g.s2_cash > 0:
        s2_after_code_changed(context)
    if g.s3_cash > 0:
        s3_after_code_changed(context)

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
    set_slippage(PriceRelatedSlippage(2/1000))

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

FIX_RATE_LIMITS = [0.03,0.03,0.03,0.03]
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
            log.info(f"pindex={pindex} {code}止盈触发：现价={current_price} 盈利={rate:.3%} 止盈阈值：{rate_limit:.3%}")
            safe_order_target_value(context,'sell',code, 0,pindex=pindex)

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
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(pos.closeable_amount, sell_amount)
            if a_amount >= 100:
                order(code, -a_amount, style,pindex = pindex)
                return -1
        elif diff_value > 0:
            buy_value = min(available_cash, diff_value)
            amount = int(abs(buy_value)  / price // 100) * 100
            if amount >= 200 or (amount>=100 and not is_kcb):
                order(code, amount, style,pindex = pindex)
                return 1
            else:
                log.warn(f"safe_order_target_value ignore,holding {code} {amount} {style} {available_cash} {pindex}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style,pindex = pindex)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {code} {amount} {style} {available_cash} {pindex}")
    return 0
# ======================聚宽框架代码Start=======================================

# ========== 策略1.均线粘合， 初始化函数 ==========
def s1_after_trading_end(context):
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context,0))

def s1_common_init(context):
    common_initialize(context)
    

def s1_set_params(context):
    # ---------- 策略核心参数 ----------
    g.s1_stock_num = 4                    # 最大持仓数
    g.s1_min_hold_days = 5                 # 最小持有天数
    g.s1_max_hold_days = 15                # 最大持有天数
    g.s1_max_cash_per_stock = 40*10000     # 单个标的最大金额
    g.s1_max_cash_ratio_per_stock = 1      # 单个标的占总仓比例
    g.s1_ma_short, g.s1_ma_mid, g.s1_ma_long = 5, 20, 60
    g.s1_convergence_threshold = 0.02     # 粘合阈值2%
    g.s1_consecutive_days = 2             # 连续N天均线粘合
    
    # 大盘风控参数
    g.s1_position_limit = 1.0 #上限满仓运行
    
    
    
def s1_schedule_tasks(context):
    run_daily(s1_etf_pool_and_filters, time='14:01')   # 更新池
    run_daily(s1_trade_sell, time='14:44')     # 卖出交易判断
    run_daily(s1_trade_buy, time='14:45')     # 买入交易判断
    run_daily(s1_take_fix_profit, time='14:46')     # 止盈
    
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
    # log.info('市场ETF总数：{}'.format(len(all_etfs)))
    
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
            if can_not_deal(etf):
                continue
        except:
            continue
        valid_etfs.append(etf)
    
    g.s1_etf_pool = valid_etfs
    # log.info('上市时间过滤后ETF池{}只'.format(len(valid_etfs)))
    
    # ---------- 步骤3：缓存均线粘合连续状态（复用原策略逻辑） ----------
    # 获取今日各ETF是否粘合
    converged_set = set()
    for etf in valid_etfs:
        is_converged = s1_check_ma_convergence_daily(etf, context)
        if is_converged:
            converged_set.add(etf)
    
    # ---------- 步骤4：缓存MACD>0状态 ----------
    positive_set = set()
    for etf in valid_etfs:
        if s1_is_macd_positive(etf, context):
            positive_set.add(etf)
    g.s1_macd_positive = positive_set

    intersection = converged_set.intersection(positive_set)
    g.s1_etf_pool = intersection
    log.info('【策略1】连续{}天均线粘合ETF：{}只（共{}只），MACD>0：{}只，交集{}只，{}'.format(
        g.s1_consecutive_days, len(converged_set), len(valid_etfs), len(positive_set),len(intersection),intersection))
        

    
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
    return safe_order_target_value(context,action,code,target_value,pindex=0)


# ========== 8. 交易执行 ==========
def s1_take_fix_profit(context):
    # 固定止盈
    take_fix_profit_check(context,FIX_RATE_LIMITS[0],pindex=0)

def s1_trade_sell(context):
    # 获取当前持仓
    positions = get_portfolio_positions(context)
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    current_date = context.current_dt.date()
    
    # ---------- 卖出 ----------
    log.info(f"【策略1】卖出计算开始，current_holdings={current_holdings}")
    for etf in current_holdings:
        if can_not_deal(etf,'sell'):
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
            log.info('【策略1】{} 卖出，满足条件is_above={},hold_long_time={},盈亏：{:.2f}({:.2f}%)'.format(etf, is_above,hold_long_time,profit,profit_pct))
            s1_safe_order_target_value(context,'sell',etf, 0)
            if etf in g.s1_buy_date:
                del g.s1_buy_date[etf]
                
def s1_trade_buy(context):
    # 获取当前持仓
    current_date = context.current_dt.date()
    positions = get_portfolio_positions(context)
    portfolio = get_portfolio(context)
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
    
    log.info(f"【策略1】买入计算，仓位上限比例{g.s1_position_limit},标的数上限{g.s1_stock_num},今日买入金额上限{buy_cash_limit}，当前市值{total_assets},持仓市值{current_stock_value}")
    
    
    # 候选ETF筛选
    candidates = []
    for etf in g.s1_etf_pool:
        if can_not_deal(etf,'buy'):
            continue
        if etf in current_holdings:
            continue
        if s1_check_bollinger_breakout_120min(etf, context):
            candidates.append(etf)
        
        if len(candidates) >= g.s1_stock_num - len(current_holdings):
            break

    if len(current_holdings) >= g.s1_stock_num:
        return
    if not candidates:
        return

    # 动态分配资金
    cash_per_etf = buy_cash_limit / len(candidates)
    max_cash_per_stock = min(g.s1_max_cash_per_stock,total_assets*g.s1_max_cash_ratio_per_stock)
    cash_per_etf = min(cash_per_etf,max_cash_per_stock)
    cash_no_enough = cash_per_etf < 1000
    log.info(f"【策略1】满足条件的候选ETF列表{len(candidates)}，{candidates},cash={buy_cash_limit},ratio={g.s1_position_limit},cash_per_etf={cash_per_etf} cash_no_enough={cash_no_enough}")
    if cash_no_enough:
        text = f"【策略1】均线粘合忽略买入{len(candidates)}只：{candidates}，可用金额不足"
        send_message(text)
        return
    for etf in candidates:
        r = s1_safe_order_target_value(context,'buy',etf, cash_per_etf)
        if r>0:
            g.s1_buy_date[etf] = current_date

# ========== 策略2核心代码 ==========        
def s2_after_trading_end(context):
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context,1))

def s2_set_targets(context):
    g.s2_assets = [
        '510300.XSHG',  # 沪深300
        '513500.XSHG',  # 标普500
        '159915.XSHE',  # 创业板
        '513100.XSHG',  # 纳指100
        '518880.XSHG',  # 黄金ETF
        '588080.XSHG',  # 科创板
        '159518.XSHE',  # 原油
        '513400.XSHG',  # 道琼斯
        '159920.XSHE',  #恒生ETF
        '512890.XSHG',  # 红利ETF

        # "159980.XSHE",  # 有色ETF
        # "159985.XSHE",  # 豆粕ETF
        # "159981.XSHE",  # 能源化工ETF
        # "501018.XSHG",  # 南方原油LOF
        # '510050.XSHG',  # 50ETF
        # '512500.XSHG',  # 500ETF
        # '159845.XSHE',  # 1000ETF
        # '159628.XSHE',  # 2000ETF
        # '513520.XSHG',  #日经ETF
    ]
    g.s2_cash_etf = '511880.XSHG'
    

def s2_common_init(context):
    common_initialize(context)

def s2_set_params(context):
    g.s2_ma_trend = 60
    g.s2_mom_day = 20
    g.s2_position_count = 2
    
    # 仓位动态调整参数（原版）
    g.s2_base_position = 1.0
    g.s2_max_position = 1.0
    g.s2_min_position = 0
    g.s2_momentum_threshold_high = 0.03
    g.s2_momentum_threshold_low = -0.02
    
    # ========== 优化5参数（市场强度过滤） ==========
    g.s2_ma_slope_threshold = -0.01
    g.s2_enable_cross_market_filter = True
    
    g.s2_weak_market_min_position = 0.05
    
    # ========== 优化6参数（单只ETF止盈） ==========
    g.s2_take_profit_up = 0.2
    
    # ========== 改进1参数（波动率目标调整） ==========
    g.s2_vol_target_lookback = 20        # 波动率计算窗口
    g.s2_target_annual_vol = 0.18        # 目标年化波动率 18%
    g.s2_max_vol_adj = 1.5               # 最大上调系数
    
    # ========== 改进2参数（排名缓冲） ==========
    g.s2_rebalance_threshold = 0.05      # 得分变化超过5%才强制调仓（预留，当前只做持仓比较）
    g.s2_skip_rebalance = False           # 是否跳过本次调仓
    
def s2_schedule_tasks(context):
    # 主调仓：每周一执行
    run_weekly(s2_calc_signals_and_clear, 1, time='13:30')
    run_weekly(s2_buy_signals, 1, time='13:31')
    run_daily(s2_take_fix_profit, time='14:46')     # 止盈

def s2_take_fix_profit(context):
    take_fix_profit_check(context,FIX_RATE_LIMITS[1],pindex=1)

def s2_after_code_changed(context):
    # 修复模拟盘热更新时，新增参数未初始化的报错
    s2_common_init(context)
    s2_set_targets(context)
    s2_set_params(context)
    s2_schedule_tasks(context)
    
def s2_initialize(context):
    s2_common_init(context)
    s2_set_targets(context)
    s2_set_params(context)
    s2_schedule_tasks(context)
    g.s2_holding_high_price = {}

# ================= 优化5：市场强度过滤 =================
def s2_get_market_trend_strength(context):
    """判断整体市场强弱，返回 -1(弱势)、0(中性)、1(强势)"""
    sh_index = '000300.XSHG'
    us_index = '513500.XSHG'
    try:
        sh_df = get_price(sh_index, end_date=context.previous_date, count=g.s2_ma_trend+10, fields='close', fq='pre')
        us_df = get_price(us_index, end_date=context.previous_date, count=g.s2_ma_trend+10, fields='close', fq='pre')
        sh_close = sh_df['close'].dropna()
        us_close = us_df['close'].dropna()
        if len(sh_close) < g.s2_ma_trend or len(us_close) < g.s2_ma_trend:
            return 0
        sh_ma = sh_close.rolling(g.s2_ma_trend).mean().iloc[-1]
        us_ma = us_close.rolling(g.s2_ma_trend).mean().iloc[-1]
        sh_current = sh_close.iloc[-1]
        us_current = us_close.iloc[-1]
        sh_above = sh_current > sh_ma
        us_above = us_current > us_ma
        
        sh_ma_series = sh_close.rolling(g.s2_ma_trend).mean()
        if len(sh_ma_series) >= 5:
            sh_slope = (sh_ma_series.iloc[-1] - sh_ma_series.iloc[-5]) / sh_ma_series.iloc[-5]
        else:
            sh_slope = 0
        us_ma_series = us_close.rolling(g.s2_ma_trend).mean()
        if len(us_ma_series) >= 5:
            us_slope = (us_ma_series.iloc[-1] - us_ma_series.iloc[-5]) / us_ma_series.iloc[-5]
        else:
            us_slope = 0
        
        if (not sh_above and sh_slope < g.s2_ma_slope_threshold) and (not us_above and us_slope < g.s2_ma_slope_threshold):
            return -1
        if sh_above and us_above and sh_slope > 0 and us_slope > 0:
            return 1
        return 0
    except:
        return 0
            
def s2_apply_market_filter(position_ratio, market_strength):
    """根据市场强度调整仓位"""
    if market_strength == -1:
        new_ratio = min(position_ratio, g.s2_weak_market_min_position)
        log.info("【策略2】优化5触发：市场弱势，仓位从 %.2f 降至 %.2f" % (position_ratio, new_ratio))
        return new_ratio
    elif market_strength == 1:
        return min(position_ratio, g.s2_max_position)
    else:
        return position_ratio


# ================= 改进1：波动率目标调整 =================
def s2_apply_volatility_target(position_ratio, context, selected_with_weights):
    """
    根据已选中ETF的加权波动率调整整体仓位，使策略预期波动率接近目标值
    selected_with_weights: list of (code, weight)
    """
    if not selected_with_weights:
        return position_ratio
    total_vol = 0
    for code, weight in selected_with_weights:
        prices = get_price(code, end_date=context.previous_date, count=g.s2_vol_target_lookback+1, 
                           fields='close', fq='pre')['close']
        rets = prices.pct_change().dropna()
        if len(rets) < 5:
            vol = 0.2  # 默认20%
        else:
            vol = rets.std() * np.sqrt(252)
        total_vol += weight * vol
    if total_vol <= 0:
        return position_ratio
    adj = g.s2_target_annual_vol / total_vol
    adj = min(adj, g.s2_max_vol_adj)   # 避免过度加仓
    new_ratio = position_ratio * adj
    new_ratio = max(g.s2_min_position, min(g.s2_max_position, new_ratio))
    log.info(f"【策略2】波动率目标: 组合波动率{total_vol:.2%}, 调整系数{adj:.2f}, 仓位{position_ratio:.2f}->{new_ratio:.2f}")
    return new_ratio


# ================= 改进2 & 改进5：信号计算与排名缓冲 =================
def s2_calc_signals_and_clear(context):
    # 获取收盘价数据
    close_data = {}
    for code in g.s2_assets:
        df = get_price(code, end_date=context.previous_date,
                       count=g.s2_ma_trend + g.s2_mom_day + 10, fields='close', fq='pre')
        close_data[code] = df
    
    # 获取基准序列（用于相对动量）
    bench_df = get_price('000300.XSHG', end_date=context.previous_date,
                         count=g.s2_ma_trend + g.s2_mom_day + 10, fields='close', fq='pre')
    bench_close = bench_df['close'].dropna()
    cur_data = get_current_data()
    signals = []
    for code in g.s2_assets:
        df = close_data.get(code)
        is_pause = cur_data[code].paused
        if is_pause or df is None or len(df.dropna()) < g.s2_ma_trend + 1:
            continue
        close = df['close'].dropna()
        current = close.iloc[-1]
        ma = close.rolling(g.s2_ma_trend).mean().iloc[-1]
        
        trend_dev = (current / ma) - 1
        
        # 改进5：计算相对动量（相对于沪深300的20日超额收益）
        etf_ret = current / close.iloc[-g.s2_mom_day-1] - 1
        bench_ret = bench_close.iloc[-1] / bench_close.iloc[-g.s2_mom_day-1] - 1
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
    
    selected = qualified[:min(g.s2_position_count, len(qualified))]
    
    # ---------- 改进2：排名缓冲，避免频繁调仓 ----------
    # 获取当前持仓（不含货币基金）
    positions = get_portfolio_positions(context,1)
    current_holdings = [code for code, pos in positions.items() 
                        if pos.total_amount > 0 and code != g.s2_cash_etf]
    new_selected_codes = [s['code'] for s in selected]
    
    # 如果持仓与候选完全相同，且得分差异不大（可选），则跳过调仓
    if set(current_holdings) == set(new_selected_codes):
        g.s2_skip_rebalance = True
        log.info("【策略2】：持仓未变，跳过本次调仓")
        return
    else:
        g.s2_skip_rebalance = False
    
    # 计算仓位比例（基于原版绝对动量最大值，保留原有逻辑）
    # 注意：这里仍然使用原版 calculate_position_ratio，后续会经过市场过滤和波动率调整
    def calculate_position_ratio(signals):
        if not signals:
            return g.s2_min_position
        max_mom = max(s.get('rel_mom', s.get('mom', 0)) for s in signals)   # 使用相对动量代替原mom
        if max_mom >= g.s2_momentum_threshold_high:
            ratio = g.s2_max_position
        elif max_mom <= g.s2_momentum_threshold_low:
            ratio = g.s2_min_position
        else:
            ratio = g.s2_min_position + (max_mom - g.s2_momentum_threshold_low) / \
                    (g.s2_momentum_threshold_high - g.s2_momentum_threshold_low) * (g.s2_max_position - g.s2_min_position)
        return max(g.s2_min_position, min(g.s2_max_position, ratio))
    
    position_ratio = calculate_position_ratio(signals)
    
    # 优化5：市场强度过滤
    market_strength = s2_get_market_trend_strength(context)
    position_ratio = s2_apply_market_filter(position_ratio, market_strength)
    
    # 改进1：波动率目标调整（需要传入权重，先计算临时权重）
    total_score = sum(s['score'] for s in selected)
    selected_with_weights = []
    for s in selected:
        if total_score == 0:
            weight = 1.0 / len(selected)
        else:
            weight = min(s['score'] / total_score, 0.7)
        selected_with_weights.append((s['code'], weight))
    position_ratio = s2_apply_volatility_target(position_ratio, context, selected_with_weights)
    
    # 保存全局变量供买入使用
    g.s2_selected = selected
    g.s2_position_ratio = position_ratio
    # 保存权重
    for s, (_, w) in zip(selected, selected_with_weights):
        s['weight'] = w
    
    log.info(f"【策略2】最终信号: {[(s['code'], s['score']) for s in selected]}, 仓位{position_ratio:.2f}")
    
    # 清仓（仅当需要调仓时）
    if not g.s2_skip_rebalance:
        s2_clear_stocks(context)

    
def s2_clear_stocks(context):
    positions = get_portfolio_positions(context,1)
    new_selected_codes = []
    if g.s2_selected:
        new_selected_codes = [s['code'] for s in g.s2_selected]
    for code in positions:
        if code in new_selected_codes:
            continue
        if can_not_deal(code,''):
            continue
        log.info(f"【策略2】清仓{code}")
        ret = s2_safe_order_target_value(context,'sell',code, 0)
        if ret < 0:
            g.s2_holding_high_price[code] = None
    
def s2_buy_signals(context):
    if not g.s2_selected or g.s2_skip_rebalance:
        return
    selected = g.s2_selected
    position_ratio = g.s2_position_ratio
    portfolio = get_portfolio(context,1)
    available_value = portfolio.available_cash * position_ratio
    
    log.info("="*50)
    log.info(f"【策略2】市场状态: 仓位{position_ratio*100:.0f}%, 可用资金{available_value:.0f}")
    log.info(f"【策略2】选中标的: {[s['code'] for s in selected]}")
    cur_data = get_current_data()
    for s in selected:
        code = s['code']
        if can_not_deal(code,''):
            continue
        target_value = available_value * s['weight']
        current_price = cur_data[code].last_price
        amount = target_value / current_price
        log.info(f"【策略2】  {code}: 趋势{s['trend_dev']*100:.1f}%, 相对动量{s['rel_mom']*100:.2f}%, "
                 f"得分{s['score']:.2f}, 权重{s['weight']*100:.0f}%, 金额{target_value:.0f} 价格{current_price} 股数{amount}")
        if amount>100:
            s2_safe_order_target_value(context,'buy',code, target_value)
            g.s2_holding_high_price[code] = current_price
    
    # 剩余资金买货币基金
    # cash_to_buy = portfolio.available_cash
    # if cash_to_buy > 100:
    #     s2_safe_order_target_value(context,'buy',g.s2_cash_etf, cash_to_buy)
        
def s2_safe_order_target_value(context,action,code,target_value):
    return safe_order_target_value(context,action,code,target_value,pindex=1)
#==================== 策略2 end =================

# ==================== 策略3：全球宽基ETF轮动策略 =================

# ----- 策略基本参数 -----
STRATEGY_PARAMS = {
    'stock_sum': 1,      # 持仓ETF数量
    'm_days': 25,        # 动量参考天数
    'min_money': 500,    # 最小交易金额（低于此金额不交易）
}

# ----- ETF池（v1.2 修订：19只，不包含行业主题ETF）-----
ETF_POOL = [
    # ── 境外 ──
    "513100.XSHG",  # 纳指ETF
    "513500.XSHG",  # 标普500ETF
    "159509.XSHE",  # 纳指科技ETF
    "513520.XSHG",  # 日经ETF
    "513030.XSHG",  # 德国ETF
    # ── 商品 ──
    "518880.XSHG",  # 黄金ETF
    "159980.XSHE",  # 有色ETF
    "159985.XSHE",  # 豆粕ETF
    "159981.XSHE",  # 能源化工ETF
    "501018.XSHG",  # 南方原油LOF
    '159518.XSHE',  # 标普原油ETF
    # ── 债券/货币 ──
    "511090.XSHG",  # 30年国债ETF
    "511360.XSHG",  # 短融ETF
    # ── 香港 ──
    "513130.XSHG",  # 恒生科技
    "513690.XSHG",  # 港股红利
    # ── 国内宽基 ──
    "510180.XSHG",  # 上证180
    "159922.XSHE",  # 中证500ETF
    "159531.XSHE",  # 中证2000ETF
    "159915.XSHE",  # 创业板ETF
    "588080.XSHG",  # 科创板50ETF
]

# ----- 过滤条件 -----
FILTER_PARAMS = {
    'max_score': 2.5,           # score 上限（超出归零）
    'min_score': 0.085,           # score 下限
    'drop_threshold': 0.95,   # 近3日跌幅阈值（<0.95 的 score 归零）
    'r2_weight': True,        # 是否用 R² 加权年化收益作为 score
}

# ----- 交易参数 -----
TRADE_PARAMS = {
    'adjust_sell_time': "11:00",     # 调仓，卖出执行时间
    'adjust_buy_time': "11:01",     # 买入执行时间
    'end_trade_time': "14:55",  # 尾盘处理时间
    'slippage_fund': 0.0001,   # 基金滑点
    'slippage_stock': 0.003,   # 股票滑点
    'commission': 0.0003,      # 佣金
    'tax': 0.001,              # 印花税
}
# ==================== 参数调整区域结束 ====================



# ============================================================
# 运行调度函数
# ============================================================


def s3_initialize(context):
    log.info("ETF轮动V1.2 启动（19只ETF池）")

    # 滑点 & 交易成本
    common_initialize(context)

    # 注册定时任务
    s3_schedule_tasks(context)

    # 创建策略对象
    g.s3_strategy = Etf_Rotation_Strategy(context, index=0, name="核心资产轮动策略")


def s3_after_code_changed(context):
    s3_schedule_tasks(context)
    g.s3_strategy = Etf_Rotation_Strategy(context, index=0, name="核心资产轮动策略")

def s3_schedule_tasks(context):
    run_daily(s3_rotation_sell, TRADE_PARAMS['adjust_sell_time'])
    run_daily(s3_do_buy, TRADE_PARAMS['adjust_buy_time'])
    run_daily(s3_take_fix_profit,'14:46')
    

# ============================================================
# 模块级函数
# ============================================================
def s3_take_fix_profit(context):
    # 固定止盈
    take_fix_profit_check(context,FIX_RATE_LIMITS[2],pindex=2)

def s3_rotation_sell(context):
    """每日调仓入口"""
    targets = g.s3_strategy.adjust()
    g.s3_targets = targets

def s3_do_buy(context):
    """每日调仓入口"""
    g.s3_strategy.adjust_buy(g.s3_targets)


# ============================================================
# 策略实现
# ============================================================

class Etf_Rotation_Strategy:
    """核心资产轮动策略：动量评分 → 选Top N → 等权调仓"""

    def __init__(self, context, index, name):
        self.context = context
        self.index = index
        self.name = name
        self.etf_pool = ETF_POOL

    # ------------------------------------------------------------------
    # 评分 & 选股
    # ------------------------------------------------------------------

    def filter(self):
        """计算ETF池中每只标的的动量得分，返回排序后代码列表"""
        m_days = STRATEGY_PARAMS['m_days']
        r2_weight = FILTER_PARAMS['r2_weight']
        drop_threshold = FILTER_PARAMS['drop_threshold']
        min_score = FILTER_PARAMS['min_score']
        max_score = FILTER_PARAMS['max_score']

        data = pd.DataFrame(
            index=self.etf_pool,
            columns=["annualized_returns", "r2", "score"]
        )
        current_data = get_current_data()

        # 逐ETF评分
        for etf in self.etf_pool:
            df = attribute_history(etf, m_days, "1d", ["close", "high"])
            prices = np.append(df["close"].values, current_data[etf].last_price)

            y = np.log(prices)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))  # 近端权重更高

            slope, _ = np.polyfit(x, y, 1, w=weights)
            annual_ret = math.exp(slope * 250) - 1
            data.loc[etf, "annualized_returns"] = annual_ret

            ss_res = np.sum(weights * (y - np.polyval([slope, _], x)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            data.loc[etf, "r2"] = r2

            score = annual_ret * r2 if r2_weight else annual_ret
            data.loc[etf, "score"] = score

            # 近3日存在大幅下跌 → 得分归零
            if min(prices[-1] / prices[-2],
                   prices[-2] / prices[-3],
                   prices[-3] / prices[-4]) < drop_threshold:
                data.loc[etf, "score"] = 0

        # 打印全量得分表
        try:
            scored = []
            for etf in self.etf_pool:
                name = current_data[etf].name
                s = data.loc[etf, "score"]
                sort_key = s if isinstance(s, (int, float)) and s == s else float("-inf")
                scored.append((etf, name, s, sort_key))
            scored.sort(key=lambda x: x[3], reverse=True)

            lines = ["──── 策略3 ETF 得分排名（全量）────"]
            lines.append(f"{'代码':<14s} {'名称':<12s} {'得分':>8s}")
            lines.append("─" * 40)
            for code, name, s, _ in scored:
                s_str = f"{float(s):.4f}" if isinstance(s, (int, float)) else "NaN"
                lines.append(f"{code:<14s} {name:<12s} {s_str:>8s}")
            log.info("\n".join(lines))
        except Exception as e:
            log.error(f"打印ETF得分列表失败：{e}")

        # 过滤并排序
        data = data.query(f"{min_score} < score < {max_score}")
        data = data.sort_values(by="score", ascending=False)
        return data.index.tolist()

    # ------------------------------------------------------------------
    # 调仓执行
    # ------------------------------------------------------------------

    def adjust(self):
        """选Top N → 等权调仓"""
        stock_sum = STRATEGY_PARAMS['stock_sum']
        candidates = self.filter()
        targets = candidates[:stock_sum]

        if not targets:
            log.info("无符合条件的ETF，跳过调仓")
            return

        weight = round(1.0 / len(targets), 4)
        target_map = {etf: weight for etf in targets}

        log.info(f"【策略3】调仓目标: {', '.join(t + '(' + str(w) + ')' for t, w in target_map.items())}")
        self._adjust_sell(target_map)
        return target_map

    def _adjust_sell(self, targets):
        if not targets:
            return
        """执行调仓：先卖，等权分配"""
        current_data = get_current_data()
        min_money = STRATEGY_PARAMS['min_money']
        portfolio = get_portfolio(self.context, 2)

        positions = get_portfolio_positions(self.context,2)
        target_value = portfolio.total_value

        # 清仓被调出的
        for stock in positions:
            if stock not in targets:
                self._order_to_target(stock, 0)

        # 先卖后买
        for stock, weight in targets.items():
            target_val = target_value * weight
            price = current_data[stock].last_price
            current_val = positions.get(stock).total_amount * price

            if current_val - target_val > max(min_money, price * 100):
                self._order_to_target(stock, target_val) 
    
    def adjust_buy(self, targets):
        """执行调仓：后买，等权分配"""
        if not targets:
            return
        current_data = get_current_data()
        min_money = STRATEGY_PARAMS['min_money']
        portfolio = get_portfolio(self.context, 2)
        positions = get_portfolio_positions(self.context,2)
        target_value = portfolio.total_value

        for stock, weight in targets.items():
            target_val = target_value * weight
            price = current_data[stock].last_price
            current_val = current_val = positions.get(stock).total_amount * price
            gap = target_val - current_val

            if min(gap, portfolio.available_cash) > max(min_money, price * 100):
                self._order_to_target(stock, target_val)   
    

    # ------------------------------------------------------------------
    # 下单封装
    # ------------------------------------------------------------------

    def _order_to_target(self, security, target_value):
        """以目标市值为导向下单，处理停牌/涨跌停/100股取整"""
        current_data = get_current_data()
        pindex = 2
        if pindex > 0 and not has_subportfolio(self.context, pindex):
            pindex = 0
        if can_not_deal(security):
            return False
        positions = get_portfolio_positions(self.context,pindex=pindex)
        current_shares = positions.get(security).total_amount
        last_price = current_data[security].last_price
        target_shares = (int(target_value / last_price) // 100) * 100 if last_price > 0 else 0
        delta = target_shares - current_shares
        slip = BUY_SLIP
        limit_price = last_price*(1+slip) if delta > 0 else last_price*(1-slip)
        style = MarketOrderStyle(limit_price)
        if delta == 0:
            return False
        closeable = (positions[security].closeable_amount
                        if security in positions else 0)
        if delta < 0 and closeable == 0:
            log.info(f"{security} 当日买入不可卖出，跳过")
            return False

        order_obj = order(security, delta, style=style, pindex=pindex)
        if order_obj:
            return True
        return False


# ============================================================
# 收盘统计
# ============================================================

def s3_after_trading_end(context):
    """收盘后输出当日的持仓与盈亏"""
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context, 2))
    port = get_portfolio(context, 2)
    total_value = port.total_value
    cash = port.available_cash
    log.info("【策略3】"+"─" * 45)
    log.info(f"收盘 {context.current_dt.date()}  总资产={total_value:.0f}  现金={cash:.0f}")
    positions = get_portfolio_positions(context, 2)
    for code, pos in positions.items():
        pnl = (pos.price / pos.avg_cost - 1) * 100 if pos.avg_cost else 0
        log.info(f"  {code}  {pos.total_amount}股  均价={pos.avg_cost:.3f}  现价={pos.price:.3f}  盈亏={pnl:+5.2f}%")
    log.info("【策略3】"+"─" * 45)

# =====================策略3 end=======================================
