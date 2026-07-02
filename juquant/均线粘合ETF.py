# 聚宽ETF多周期均线粘合 + BOLL开口策略
# 标的：市场主流ETF基金
# 买入：日线MA5/20/60粘合 + 120分钟BOLL开口 + 月线MACD>0
# 卖出：60分钟收盘价跌破MA20
# 风控：大盘仓位管理、规模过滤、流动性过滤

from jqdata import *
import numpy as np
import pandas as pd

# ========== 1. 初始化函数 ==========
def initialize(context):
    # 回测基础设置
    set_benchmark('510300.XSHG')   # 基准：沪深300ETF
    set_option("avoid_future_data", True)
    set_option('use_real_price', True)
    set_slippage(FixedSlippage(2.0/1000))   # 0.2%滑点
    set_order_cost(OrderCost(
        close_tax=0.001,          # 印花税 千分之一
        open_commission=1/10000,   # 买入佣金 万分之1
        close_commission=1/10000,  # 卖出佣金 万分之1
        min_commission=5
    ), type='fund')               # 基金类型
    
    # ---------- 策略核心参数 ----------
    g.stock_num = 50                    # 最大持仓数
    g.min_hold_days = 5                # 最小持有天数
    g.max_hold_days = 15                # 最大持有天数
    g.max_cash_per_stock = 20*10000                # 单个标的最大金额
    g.max_cash_ratio_per_stock = 0.5                # 单个标的占总仓比例
    g.ma_short, g.ma_mid, g.ma_long = 5, 20, 60
    g.convergence_threshold = 0.03     # 粘合阈值3%
    g.consecutive_days = 2             # 连续N天均线粘合
    
    # 大盘风控参数
    g.position_limit = 1.0 #上限满仓运行
    
    # ---------- 缓存变量 ----------
    g.etf_pool = []                     # ETF池
    g.etf_scale_cache = {}              # 规模缓存
    g.ma_converged_etfs = set()         # 满足连续粘合的ETF
    g.macd_positive = set()      # 月线MACD>0的ETF
    g.buy_date = {}                     # 买入日期记录
    
    # 历史粘合记录
    g.ma_converged_history = {}
    
    # ---------- 定时任务 ----------
    run_daily(etf_pool_and_filters, time='09:01')   # 开盘前更新池
    run_daily(trade_sell, time='10:30')     # 卖出交易判断
    run_daily(trade_buy, time='11:00')     # 卖出交易判断

    run_daily(trade_sell, time='14:30')     # 卖出交易判断
    run_daily(trade_buy, time='14:45')     # 买入交易判断


# ========== 2. ETF池构建与过滤（开盘前执行） ==========
def etf_pool_and_filters(context):
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
        # 沪深300
        "510300.XSHG": "沪深300ETF",       # 华泰柏瑞, 最活跃, 规模最大
        # 中证500
        "510500.XSHG": "中证500ETF",       # 南方
        # 上证50
        "510050.XSHG": "上证50ETF",        # 华夏, 最活跃, 规模最大
        # 科创50
        "588000.XSHG": "科创50ETF",        # 华夏, 最活跃
        # 创业板指
        "159915.XSHE": "创业板ETF",        # 易方达, 最活跃
        # 创业板50
        "159949.XSHE": "创业板50ETF",      # 华安
        # 中证1000
        "512100.XSHG": "中证1000ETF",      # 南方
        # 深证100
        "159901.XSHE": "深100ETF",         # 易方达
        # MSCI A50
        "159601.XSHE": "MSCI中国A50ETF",   # 华夏
        # ========== 港股市场 ==========
        "159920.XSHE": "恒生ETF",           # 华夏恒生指数ETF
        "513130.XSHG": "恒生科技ETF易方达",
        "513330.XSHG": "恒生互联ETF",       # 华夏恒生互联网科技业
        "159776.XSHE": "港股通医药ETF",     # 华夏中证港股通医药
        "159712.XSHE": "港股通50ETF",       # 国泰中证港股通50
        "513990.XSHG": "港股通ETF",         # 博时中证港股通综合
        # ========== 美股市场（宽基） ==========
        "159941.XSHE": "纳指ETF",           # 广发纳斯达克100ETF
        "513500.XSHG": "标普500ETF",        # 博时标普500ETF
        "513400.XSHG": "道琼斯ETF",         # 鹏华道琼斯工业平均
        # ========== 美股市场（行业主题） ==========
        "159529.XSHE": "标普消费ETF",       # 景顺长城标普500消费精选
        "159518.XSHE": "标普油气ETF",       # 景顺长城标普油气
        "162411.XSHE": "华宝油气LOF",       # 跟踪标普全球石油指数
        "159655.XSHE": "纳指生物科技ETF",   # 华夏纳斯达克生物科技
        "161127.XSHE": "标普生物科技LOF",
        # ========== 日本市场 ==========
        "513880.XSHG": "日经ETF",           # 华安日经225ETF
        # ========== 欧洲市场 ==========
        "513030.XSHG": "德国ETF",           # 华安德国DAX30ETF
        "513080.XSHG": "法国CAC40ETF",      # 华安法国CAC40ETF
        # ========== 亚太其他市场 ==========
        "513730.XSHG": "东南亚科技ETF",     # 华泰柏瑞新交所泛东南亚科技
        "159687.XSHE": "亚太精选ETF",       # 南方富时亚太低碳精选
        "513310.XSHG": "中韩半导体ETF",     # 华泰柏瑞中证韩交所中韩半导体
        "520580.XSHG": "新兴亚洲ETF",       # 华泰柏瑞新交所新兴亚洲精选
        "164824.XSHE": "印度基金LOF",       # 工银印度NIFTY50
        # ========== 中东市场 ==========
        "520830.XSHG": "沙特ETF",           # 华泰柏瑞富时沙特阿拉伯
        # ========== 中概互联 ==========
        "513050.XSHG": "中概互联ETF",       # 易方达中证海外中国互联网50
        # ========== 黄金（跟踪AU9999现货/上海金） ==========
        # "518880.XSHG": "黄金ETF",           # 华安黄金ETF，AU9999，规模最大
        # ========== 有色金属期货 ==========
        "159980.XSHE": "有色ETF",           # 大成有色金属期货ETF
        # ========== 豆粕期货（农产品） ==========
        "159985.XSHE": "豆粕ETF",           # 华夏豆粕期货ETF
        # ========== 能源化工期货 ==========
        "159981.XSHE": "能源化工ETF",       # 建信易盛郑商所能源化工期货ETF
        "161226.XSHE": "白银LOF",           # 国投白银LOF
        # ========== 芯片/半导体（核心赛道） ==========
        "512480.XSHG": "半导体ETF",           # 国联安，跟踪中证全指半导体
        "159995.XSHE": "芯片ETF",             # 华夏，跟踪国证半导体芯片
        "588170.XSHG": "科创半导体ETF",       # 华夏，跟踪上证科创板半导体
        "159516.XSHE": "半导体设备ETF",       # 国泰，跟踪中证半导体材料设备
        # ========== 人工智能 ==========
        "159819.XSHE": "人工智能ETF",         # 易方达，跟踪中证人工智能，规模最大
        "159246.XSHE": "创业板人工智能ETF",   # 富国，跟踪创业板人工智能
        # ========== 通信/5G ==========
        "515880.XSHG": "通信ETF",             # 国泰，跟踪中证全指通信设备，规模最大
        "515050.XSHG": "5G通信ETF",           # 华夏，跟踪中证5G通信主题
        # ========== 云计算/大数据 ==========
        "516510.XSHG": "云计算ETF",           # 易方达，跟踪中证云计算与大数据
        "159739.XSHE": "大数据ETF",           # 鹏华，跟踪中证云计算与大数据
        # ========== 传媒/游戏/互联网 ==========
        "512980.XSHG": "传媒ETF",             # 广发，跟踪中证传媒
        "159869.XSHE": "游戏ETF",             # 华夏，跟踪中证动漫游戏
        # ========== 金融科技 ==========
        "159851.XSHE": "金融科技ETF",         # 华宝，跟踪中证金融科技主题
        # ========== 机器人 ==========
        "159530.XSHE": "机器人ETF",           # 易方达，跟踪国证机器人产业，规模靠前
        # ========== 综合新能源 ==========
        "516090.XSHG": "新能源ETF",           # 易方达，跟踪中证新能源
        "159790.XSHE": "碳中和ETF",           # 华夏，跟踪中证内地低碳经济
        # ========== 电池 ==========
        "159175.XSHE": "电池ETF",             # 易方达，跟踪国证新能源电池
        "159566.XSHE": "储能电池ETF",         # 易方达，跟踪国证新能源电池
        # ========== 新能源汽车 ==========
        "515030.XSHG": "新能源车ETF",         # 华夏，跟踪CS新能车
        # ========== 电力/电网设备 ==========
        "159611.XSHE": "电力ETF",             # 广发，跟踪中证全指电力
        "560390.XSHG": "电网设备ETF",         # 易方达，跟踪中证电网设备
        # ========== 综合医药 ==========
        "512010.XSHG": "医药ETF",             # 易方达，跟踪沪深300医药
        # ========== 创新药 ==========
        "516080.XSHG": "创新药ETF",           # 易方达，跟踪中证创新药产业
        # ========== 医疗/医疗器械 ==========
        "512170.XSHG": "医疗ETF",             # 华宝，跟踪中证医疗
        "159883.XSHE": "医疗器械ETF",         # 永赢，跟踪中证全指医疗器械
        # ========== 生物医药 ==========
        "512290.XSHG": "生物医药ETF",         # 国泰，跟踪中证生物医药
        # ========== 中药 ==========
        "560080.XSHG": "中药ETF",             # 汇添富，跟踪中证中药
        # ========== 港股通医药 ==========
        "513200.XSHG": "港股通医药ETF",       # 易方达，跟踪中证港股通医药
        # ========== 食品饮料/酒 ==========
        "512690.XSHG": "酒ETF",               # 鹏华，跟踪中证酒
        "159843.XSHE": "食品饮料ETF",         # 招商，跟踪国证食品饮料
        # ========== 综合消费 ==========
        "159798.XSHE": "消费ETF",             # 易方达，聚焦A股消费核心资产
        # ========== 可选消费 ==========
        "562580.XSHG": "可选消费ETF",         # 华夏，跟踪中证全指可选消费
        # ========== 家电 ==========
        "159996.XSHE": "家电ETF",             # 国泰，跟踪中证全指家用电器
        # ========== 旅游 ==========
        "562510.XSHG": "旅游ETF",             # 华夏，跟踪中证细分旅游
        # ========== 农业/养殖 ==========
        "159825.XSHE": "农业ETF",             # 富国，跟踪中证农业
        "516670.XSHG": "养殖ETF",             # 招商，跟踪中证畜牧养殖
        "510230.XSHG": "金融ETF",             # 国泰，跟踪上证180金融
        # ========== 证券 ==========
        "512880.XSHG": "证券ETF",             # 国泰，跟踪中证全指证券公司，规模最大
        # ========== 银行 ==========
        "512800.XSHG": "银行ETF",             # 华宝，跟踪中证银行，规模最大
        # ========== 保险 ==========
        "512070.XSHG": "非银ETF",             # 易方达，跟踪沪深300非银（保险+券商）
        # ========== 房地产 ==========
        "159768.XSHE": "房地产ETF",           # 银华，跟踪中证全指房地产
        # ========== 军工 ==========
        "512660.XSHG": "军工ETF",             # 国泰，跟踪中证军工，规模最大
        # ========== 航天航空 ==========
        "159227.XSHE": "航天航空ETF",         # 华夏，跟踪国证航天航空
        "512670.XSHG": "国防ETF",             # 鹏华，跟踪中证国防
        # ========== 工业母机/高端制造 ==========
        "159667.XSHE": "工业母机ETF",         # 国泰，跟踪中证机床
        "560280.XSHG": "工程机械ETF",         # 广发，跟踪中证工程机械主题
        # ========== 科创板高端制造（科创细分） ==========
        "588220.XSHG": "科创100ETF",          # 鹏华，科创板100指数
        # ========== 有色金属 ==========
        "512400.XSHG": "有色金属ETF",         # 南方，跟踪中证申万有色
        # ========== 煤炭 ==========
        "515220.XSHG": "煤炭ETF",             # 国泰，跟踪中证煤炭
        # ========== 钢铁 ==========
        "515210.XSHG": "钢铁ETF",             # 国泰，跟踪中证钢铁
        # ========== 化工 ==========
        "516120.XSHG": "化工50ETF",           # 富国，跟踪中证细分化工
        # ========== 石油/能源 ==========
        "159930.XSHE": "能源ETF",             # 汇添富，跟踪中证能源
        # ========== 基建/建材 ==========
        "516970.XSHG": "基建ETF",             # 广发，跟踪中证基建工程
        "516750.XSHG": "建材ETF",             # 富国，跟踪中证全指建筑材料
        # ========== 交通运输 ==========
        "159666.XSHE": "交通运输ETF",         # 华夏，跟踪中证全指运输
        "561230.XSHG": "物流ETF",             # 中银，跟踪中证现代物流
        # ========== 红利 ==========
        "510880.XSHG": "红利ETF",             # 华泰柏瑞，跟踪上证红利，规模最大
        "515080.XSHG": "中证红利ETF",         # 招商，跟踪中证红利
        "159905.XSHE": "深证红利ETF",         # 工银瑞信，跟踪深证红利
        "159222.XSHE": "自由现金流ETF",       # 易方达，跟踪国证自由现金流
        # ========== ESG / 社会责任 ==========
        "516720.XSHG": "ESGETF",              # 浦银安盛，跟踪中证ESG120策略
        # ========== 央企/国企改革 ==========
        "561580.XSHG": "央企红利ETF",         # 华泰柏瑞，跟踪中证中央企业红利
        "517090.XSHG": "国企共赢ETF",         # 富国，跟踪富时中国国企开放共赢
        # ========== 一带一路 ==========
        "515990.XSHG": "一带一路ETF",         # 富国，跟踪中证国企一带一路
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
        except:
            continue
        valid_etfs.append(etf)
    
    g.etf_pool = valid_etfs
    log.info('上市时间过滤后ETF池{}只'.format(len(valid_etfs)))
    
    # ---------- 步骤3：缓存均线粘合连续状态（复用原策略逻辑） ----------
    # 获取今日各ETF是否粘合
    converged_set = set()
    for etf in valid_etfs:
        is_converged = check_ma_convergence_daily(etf, context)
        if is_converged:
            converged_set.add(etf)
    
    # ---------- 步骤4：缓存MACD>0状态 ----------
    positive_set = set()
    for etf in valid_etfs:
        if is_macd_positive(etf, context):
            positive_set.add(etf)
    g.macd_positive = positive_set

    intersection = converged_set.intersection(positive_set)
    g.etf_pool = intersection
    log.info('连续{}天均线粘合ETF：{}只,{}，MACD>0：{}只,{}，交集{}只，{}'.format(
        g.consecutive_days, len(converged_set),converged_set, len(positive_set),positive_set,len(intersection),intersection))
        


# ========== 3. 日线均线粘合判断（与原策略相同，直接复用） ==========
def check_ma_convergence_daily(security, context):
    """判断日线级别均线是否粘合，返回True/False"""
    df = attribute_history(security, 80, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 60:
        return False
    is_convergence = True
    for i in range(0,g.consecutive_days):
        ma5 = df['close'].rolling(g.ma_short).mean().iloc[-(i+1)]
        ma20 = df['close'].rolling(g.ma_mid).mean().iloc[-(i+1)]
        ma60 = df['close'].rolling(g.ma_long).mean().iloc[-(i+1)]
        
        if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            return False
        
        ma_max = max(ma5, ma20, ma60)
        ma_min = min(ma5, ma20, ma60)
        deviation = (ma_max - ma_min) / ma_min if ma_min != 0 else 1
        is_convergence = is_convergence and (deviation <= g.convergence_threshold)
        
    return is_convergence


# ========== 4. MACD判断 ==========
def calc_macd(close_prices, fast=12, slow=26, signal=9):
    """计算MACD柱值"""
    if len(close_prices) < slow + signal:
        return None, None, None
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = dif - dea
    return dif, dea, macd_bar

def is_macd_positive(security, context):
    """判断最新月线MACD柱是否大于0"""
    bars = get_bars(security, count=50, unit='1w', fields=['close'],
                    include_now=False, fq_ref_date=context.current_dt.date(), df=True)
    if bars is None or len(bars) < 35:
        return False
    close = bars['close']
    _, _, macd_bar = calc_macd(close)
    if macd_bar is None:
        return False
    latest_macd = macd_bar.iloc[-1]
    return latest_macd > 0


# ========== 5. 120分钟BOLL开口判断（与原策略相同，复用） ==========
def check_bollinger_breakout_120min(security, context):
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
def check_break_ma_60min(security, context):
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

# ========== 7. ETF下单函数（简化，无股票特定的复杂处理） ==========
def order_etf_target_value(security, target_value, context):
    """
    ETF安全下单：
    - 无200股限制（ETF单位是份，最小100份）
    - 无科创板/非科创板区分
    - 涨停/跌停处理（ETF有±10%限制）
    """
    current_data = get_current_data()
    
    current_price = current_data[security].last_price
    if current_price is None or current_price <= 0:
        return 0
    
    # 最小买入份额（ETF：100份起）
    min_shares = 100
    min_amount = min_shares * current_price
    
    if target_value < min_amount:
        log.debug('{} 最低买入金额{:.2f} > 分配{:.2f}，跳过'.format(security, min_amount, target_value))
        return 0
    
    # 计算可买份额（100的倍数）
    shares = int(target_value / current_price)
    shares = (shares // 100) * 100
    if shares < 100:
        return 0
    
    # 检查涨跌停
    prev_close = current_data[security].day_open
    if prev_close and prev_close > 0:
        if current_price >= prev_close * 1.098:   # 接近涨停
            log.info('{} 当前接近涨停，暂停买入'.format(security))
            return 0
        if current_price <= prev_close * 0.902:   # 接近跌停
            log.info('{} 当前接近跌停，暂停买入'.format(security))
            return 0
    
    adjusted_target = shares * current_price
    order_target_value(security, adjusted_target)
    return adjusted_target

def order_etf_target(security, target_amount, context):
    """ETF清仓卖出"""
    if target_amount == 0:
        order_target(security, 0)
        return

# ========== 8. 交易执行 ==========
def trade_sell(context):
    # 获取当前持仓
    positions = context.portfolio.positions
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    current_date = context.current_dt.date()
    
    # ---------- 卖出 ----------
    log.info(f"卖出计算，current_holdings={current_holdings}")
    for etf in current_holdings[:]:
        # 最小持有期检查
        hold_long_time = False
        if etf in g.buy_date:
            hold_days = (current_date - g.buy_date[etf]).days
            hold_long_time = hold_days >= g.max_hold_days
            if hold_days < g.min_hold_days:
                continue
        is_above = check_break_ma_60min(etf, context) 
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
            order_etf_target(etf, 0, context)
            if etf in g.buy_date:
                del g.buy_date[etf]
                
def trade_buy(context):
    # 获取当前持仓
    current_date = context.current_dt.date()
    positions = context.portfolio.positions
    current_holdings = [s for s in positions if positions[s].total_amount > 0]
    # ---------- 买入 ----------
    # 计算仓位上限
    total_assets = context.portfolio.total_value
    current_stock_value = context.portfolio.positions_value
    current_ratio = current_stock_value / total_assets if total_assets > 0 else 0
    remaining_ratio = max(0, g.position_limit - current_ratio)
    max_new_cash = total_assets * remaining_ratio
    cash_available = context.portfolio.available_cash
    buy_cash_limit = min(cash_available, max_new_cash)
    
    log.info(f"买入计算，仓位上限比例{g.position_limit},标的数上限{g.stock_num},今日买入金额上限{buy_cash_limit}，当前市值{total_assets},持仓市值{current_stock_value}")
    if len(current_holdings) >= g.stock_num:
        return
    
    # 候选ETF筛选
    candidates = []
    for etf in g.etf_pool:
        if etf in current_holdings:
            continue
        if check_bollinger_breakout_120min(etf, context):
            candidates.append(etf)
        
        if len(candidates) >= g.stock_num - len(current_holdings):
            break
    
    if not candidates:
        return

    # 动态分配资金
    cash_per_etf = buy_cash_limit / len(candidates)
    max_cash_per_stock = max(g.max_cash_per_stock,total_assets*g.max_cash_ratio_per_stock)
    cash_per_etf = min(cash_per_etf,max_cash_per_stock)
    log.info(f"满足条件的候选ETF列表{len(candidates)}，{candidates},cash={buy_cash_limit},ratio={g.position_limit},cash_per_etf={cash_per_etf}")

    for etf in candidates:
        if cash_per_etf < 1000:
            continue
        used = order_etf_target_value(etf, cash_per_etf, context)
        if used > 0:
            g.buy_date[etf] = current_date
            log.info('{} 买入成功，使用资金 {:.2f}'.format(etf, used))

    
    