# 克隆自聚宽文章：https://www.joinquant.com/post/70023
# 标题：一套带SAR逃顶的分时T+0小市值&ETF轮动量化策略
# 作者：乌恩
# 修复日期: 2026-07-16
# 修复内容:
#   V2(2026-07-16): 
#     1. 日历效应从固定月份(1/4/7/12月)改为三段精确日期区间:
#        12月15日~1月15日 / 3月20日~4月20日 / 6月15日~7月15日
#     2. 新增10日30%止盈切换逻辑(参照华泰肖涵动量轮动止盈策略)
#     3. 新增is_in_calendar_window()辅助函数,支持跨年区间判断
#   V1(2026-07-05): _fetch_ohlc()增加NaN数据防护; ETF池新增科创50+十年国债;
#                    日历效应1/4/7/12月; 剔除日经/恒生ETF,年化收益×R平方打分
#   V1(2026-07-06): 修复函数缺失报错、仓位切换不同步、资金闲置、SAR约束失效
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
import math
from six import StringIO, BytesIO
import talib

# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper
# 默认下单函数
Live_Type = False # 'True':启用实盘模式 只有模拟模式下生效，回测不生效,False：不实盘
(order,order_target_value,order_value,order_target)  = bt_wrapper.get_orders_func(order,order_target_value,order_value,order_target)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured(context,Live_Type)

# =======================实盘配置End=======================================

# 初始化函数
def initialize(context):
    set_benchmark('000985.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    g.slip_rate = 1/1000
    set_slippage(PriceRelatedSlippage(g.slip_rate))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    log.set_level('order', 'error')
    
    g.stock_num = 10
    g.hold_list = []
    g.yesterday_HL_list = []
    g.num = 1
    
    # ETF相关全局变量
    g.etf_pool = load_etf_pool()          # 权益类ETF池（参与动量轮动）
    g.bond_etf = '511090.XSHG'            # 十年期国债ETF（避险品种，不参与动量排序）
    g.etf_score_threshold = 0.05          # ETF动量得分最低阈值
    g.current_etf_target = None           # 当前ETF轮动目标标的
    g.industry_etf_mode = False           # 行业防御模式标志
    # ETF名称映射
    g.etf_names = {
        '518880.XSHG': '黄金ETF',
        '513100.XSHG': '纳指100ETF',
        '159949.XSHE': '创业板50ETF',
        '510880.XSHG': '红利ETF',
        '588000.XSHG': '科创50ETF',
        '511090.XSHG': '十年期国债ETF',
    }
    
    g.m_days = 23
    g.etf_info = initial_etf_info(g.etf_pool, 100)
    g.etf_pre = None
    
    # 做T参数
    g.t_vwap_up   = 0.02
    g.t_vwap_down = 0.02
    g.t_ratio     = 0.3
    g.t_record    = {}
    g.t_force_buy_done = False  # T+0强制买回标志，避免重复做T
    
    # SAR择时参数
    g.sar_index  = '932000.CSI'
    g.sar_120m   = True
    g.sar_daily  = True
    g.sar_ratio  = 1.0
    
    run_daily(update_etf_table, '7:00')
    run_daily(prepare_stock_list, '9:05')
    run_daily(check_sar_signal, '9:28')
    run_daily(daily_etf_rotation, '9:29')  # 每日固定一次ETF轮动，股票清仓后执行
    run_weekly(weekly_adjustment, 1, '9:30')
    run_daily(t_trade, 'every_bar')
    run_daily(t_force_buy, '14:45')
    run_daily(check_limit_up, '14:50')
    run_daily(log_daily_summary, '15:10')

# ─── ETF池与基础工具 ─────────────────────────────────────────────────────────
def load_etf_pool():
    return [
        '518880.XSHG',  # 黄金ETF
        '513100.XSHG',  # 纳指100
        '159949.XSHE',  # 创业板50
        '510880.XSHG',  # 红利
        '588000.XSHG',  # 科创50ETF
    ]

def initial_etf_info(etf_pool, ndays=100):
    etf_info = {}
    for etf in etf_pool:
        etf_df = attribute_history(etf, ndays, '1d', ['close'], skip_paused=True, df=True, fq='pre')
        etf_info[etf] = list(etf_df.close)
    return etf_info

def update_etf_table(context):
    for etf in g.etf_pool:
        etf_df = attribute_history(etf, 1, '1d', ['close'], skip_paused=True, df=True, fq='pre')
        g.etf_info[etf].append(etf_df.close[-1])
        g.etf_info[etf].pop(0)

def is_etf_available(context, etf):
    try:
        info = get_security_info(etf)
        if info is None:
            return False
        if info.start_date > context.previous_date:
            return False
        return True
    except:
        return False

def get_rank(context):
    score_list = []
    valid_etfs = []
    for etf in g.etf_pool:
        if not is_etf_available(context, etf):
            continue
        try:
            df = attribute_history(etf, g.m_days, '1d', ['close'], skip_paused=True, df=True)
            if len(df) < g.m_days:
                continue
            y = np.log(df['close'])
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            annualized_returns = math.pow(math.exp(slope), 250) - 1
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            score = annualized_returns * r_squared
            score_list.append(score)
            valid_etfs.append(etf)
        except Exception as e:
            continue
    if not valid_etfs:
        return [], -999
    df = pd.DataFrame({
        'etf': valid_etfs,
        'score': score_list,
        'name': [g.etf_names.get(etf, etf) for etf in valid_etfs]
    }).sort_values('score', ascending=False)
    score_info = []
    for etf in g.etf_pool:
        if etf in valid_etfs:
            s = df[df['etf'] == etf]['score'].values[0]
            score_info.append(f"{g.etf_names.get(etf, etf)}={s:.4f}")
        else:
            score_info.append(f"{g.etf_names.get(etf, etf)}=N/A")
    log.info("ETF得分: " + ", ".join(score_info))
    top_score = df.iloc[0]['score']
    return df['etf'].tolist(), top_score

def evaluate_etf_worth(m_etf, is_hold=1):
    is_worth = 0
    if m_etf is None:
        return is_worth
    cur_p     = g.etf_info[m_etf][-1]
    max10_p   = max(g.etf_info[m_etf][-10:])
    max_p     = max(g.etf_info[m_etf])
    cur2max   = cur_p / max_p
    cur2max10 = cur_p / max10_p
    cur2yes   = cur_p / g.etf_info[m_etf][-2]
    mean4     = np.mean(g.etf_info[m_etf][-4:])
    if is_hold == 1:
        is_worth = 0 if cur2yes <= 0.96 else 1
    else:
        is_worth = 1 if cur_p >= mean4 else 0
    return is_worth

# ─── 日历效应日期区间判断 (V2新增) ────────────────────────────────────────────
def is_in_calendar_window(context):
    """
    三段日历效应区间,在区间内强制切换至ETF轮动模式、股票仓位归零:
      区间1: 12月15日 ~ 1月15日（跨年）
      区间2:  3月20日 ~ 4月20日
      区间3:  6月15日 ~ 7月15日
    返回True表示当前处于日历效应区间。
    """
    dt = context.current_dt
    m = dt.month
    d = dt.day
    
    if m == 12 and d >= 15:
        return True
    if m == 1 and d <= 15:
        return True
    if m == 3 and d >= 20:
        return True
    if m == 4 and d <= 20:
        return True
    if m == 6 and d >= 15:
        return True
    if m == 7 and d <= 15:
        return True
    return False

# ─── 每日ETF动量轮动核心 ─────────────────────────────────────────────────────
def daily_etf_rotation(context):
    # 【V2修改】日历效应改为三段精确日期区间
    is_calendar_etf_month = is_in_calendar_window(context)
    
    if g.industry_etf_mode or is_calendar_etf_month:
        etf_target_value = context.portfolio.total_value
    else:
        etf_target_value = context.portfolio.total_value * (1 - g.sar_ratio)
    
    if etf_target_value < 1000:
        _clear_all_etf(context)
        g.current_etf_target = None
        return
    
    rank_list, top_score = get_rank(context)
    if not rank_list:
        _clear_all_etf(context)
        g.current_etf_target = None
        return
    top_etf = rank_list[0]
    
    if top_score >= g.etf_score_threshold:
        target_etf = top_etf
        mode_desc = "动量最强权益ETF"
    elif top_score >= 0:
        target_etf = g.bond_etf
        mode_desc = "得分不足阈值，切换国债避险"
    else:
        target_etf = None
        mode_desc = "得分为负，持有现金避险"
    
    log.info('[ETF轮动] 最高得分:%.4f | 模式:%s | 目标标的:%s | 目标金额:%.2f' 
             % (top_score, mode_desc, g.etf_names.get(target_etf, '现金') if target_etf else '现金', etf_target_value))
    
    # 【V2新增】10日30%止盈切换（参照华泰肖涵动量轮动止盈策略）
    if target_etf is not None and len(rank_list) > 1:
        current_pos = context.portfolio.positions.get(target_etf, None)
        if current_pos is not None and current_pos.total_amount > 0:
            try:
                hist = attribute_history(target_etf, 10, '1d', ['close'], skip_paused=True, df=True)
                if len(hist) >= 10:
                    increase = (hist['close'].iloc[-1] - hist['close'].iloc[0]) / hist['close'].iloc[0]
                    if increase > 0.3:
                        old_target = target_etf
                        target_etf = rank_list[1]
                        log.info('[止盈] %s近10日涨幅%.2f%%，触发止盈切换至%s' 
                                 % (g.etf_names.get(old_target, old_target), increase * 100,
                                    g.etf_names.get(target_etf, target_etf)))
            except Exception as e:
                log.warn('[止盈检查] 出错: %s' % str(e))
    
    if target_etf is None:
        _clear_all_etf(context)
        g.current_etf_target = None
    else:
        current_etfs = [s for s in context.portfolio.positions.keys() 
                        if s.startswith('5') or s.startswith('1')]
        for etf in current_etfs:
            if etf != target_etf:
                pos = context.portfolio.positions[etf]
                close_position(context, pos)
        current_pos = context.portfolio.positions.get(target_etf, None)
        if not current_pos or abs(current_pos.value - etf_target_value) / etf_target_value > 0.05:
            safe_order_target_value(context,'buy',target_etf,etf_target_value)
        g.current_etf_target = target_etf

def _clear_all_etf(context):
    for s in list(context.portfolio.positions.keys()):
        if s.startswith('5') or s.startswith('1'):
            pos = context.portfolio.positions[s]
            close_position(context, pos)

# ─── 行业映射 ─────────────────────────────────────────────────────────────────
SW1 = {
    '801010': '农林牧渔I', '801020': '采掘I',     '801030': '化工I',
    '801040': '钢铁I',     '801050': '有色金属I', '801060': '建筑建材I',
    '801070': '机械设备I', '801080': '电子I',     '801090': '交运设备I',
    '801100': '信息设备I', '801110': '家用电器I', '801120': '食品饮料I',
    '801130': '纺织服装I', '801140': '轻工制造I', '801150': '医药生物I',
    '801160': '公用事业I', '801170': '交通运输I', '801180': '房地产I',
    '801190': '金融服务I', '801200': '商业贸易I', '801210': '休闲服务I',
    '801220': '信息服务I', '801230': '综合I',     '801710': '建筑材料I',
    '801720': '建筑装饰I', '801730': '电气设备I', '801740': '国防军工I',
    '801750': '计算机I',   '801760': '传媒I',     '801770': '通信I',
    '801780': '银行I',     '801790': '非银金融I', '801880': '汽车I',
    '801890': '机械设备I', '801950': '煤炭I',     '801960': '石油石化I',
    '801970': '环保I',     '801980': '美容护理I',
}
industry_code = [
    '801010', '801020', '801030', '801040', '801050', '801080', '801110',
    '801120', '801130', '801140', '801150', '801160', '801170', '801180',
    '801200', '801210', '801230', '801710', '801720', '801730', '801740',
    '801750', '801760', '801770', '801780', '801790', '801880', '801890',
]

# ─── SAR择时模块 ──────────────────────────────────────────────────────────────
def _fetch_ohlc(freq, count):
    for ticker in [g.sar_index, '560000.XSHG']:
        try:
            h = attribute_history(ticker, count, freq, ['high', 'low', 'close'],
                                  skip_paused=True, df=True, fq='pre')
            if len(h) == 0:
                continue
            high_a  = h['high'].values.astype(float)
            low_a   = h['low'].values.astype(float)
            close_a = h['close'].values.astype(float)
            if np.all(np.isnan(close_a)):
                continue
            if np.all(np.isnan(high_a)) or np.all(np.isnan(low_a)):
                return (close_a, close_a, close_a)
            return (high_a, low_a, close_a)
        except Exception as e:
            continue
    return None

def _calc_sar(freq, count, label):
    data = _fetch_ohlc(freq, count)
    if data is None:
        return None
    high, low, close = data
    if len(close) == 0 or np.any(np.isnan(close)):
        return None
    sar = talib.SAR(high, low, acceleration=0.02, maximum=0.2)
    bullish = bool(close[-1] > sar[-1])
    return bullish

def _sar_reduce_positions(context, target_ratio):
    g.t_record.clear()
    positions = context.portfolio.positions
    stock_positions = {s:p for s,p in positions.items() 
                       if not s.startswith('5') and not s.startswith('1')}
    if not stock_positions:
        return
    if target_ratio == 0.0:
        log.error('>>> [SAR] 股票全部清仓 <<<')
        for stock in list(stock_positions.keys()):
            pos = stock_positions[stock]
            close_position(context, pos)
    else:
        target_total = context.portfolio.total_value * target_ratio
        per_stock    = target_total / len(stock_positions)
        for stock, pos in list(stock_positions.items()):
            if pos.value > per_stock * 1.05:
                # order_target_value(stock, per_stock)
                safe_order_target_value(context,'buy',stock,per_stock)
    # 【修复】移除此处的ETF轮动调用，统一由9:26执行，避免重复下单

def check_sar_signal(context):
    sig_120m  = _calc_sar('120m', 120, '120m')
    sig_daily = _calc_sar('1d',   60,  '日线')
    
    if sig_120m  is None: sig_120m  = g.sar_120m
    if sig_daily is None: sig_daily = g.sar_daily
    
    old_ratio = g.sar_ratio
    
    if sig_120m and sig_daily:
        new_ratio = 1.0
    elif sig_120m or sig_daily:
        new_ratio = 0.5
    else:
        new_ratio = 0.0
    
    # 【V2修改】日历效应改为三段精确日期区间
    if is_in_calendar_window(context):
        log.info('[日历效应] 当前处于ETF轮动专属区间，强制股票仓位归零')
        new_ratio = 0.0
    
    g.sar_120m  = sig_120m
    g.sar_daily = sig_daily
    g.sar_ratio = new_ratio
    
    log.info('[SAR] 120m:%s 日线:%s → 股票目标仓位:%d%%（上次:%d%%）' % (
        '红' if sig_120m else '绿', '红' if sig_daily else '绿',
        int(new_ratio * 100), int(old_ratio * 100)))
    
    if new_ratio < old_ratio:
        _sar_reduce_positions(context, new_ratio)

# ─── 每日持仓准备 ─────────────────────────────────────────────────────────────
def prepare_stock_list(context):
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        if not position.security.startswith('5') and not position.security.startswith('1'):
            g.hold_list.append(position.security)
    
    if g.hold_list:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []

# ─── 行业工具 ─────────────────────────────────────────────────────────────────
def getStockIndustry(p_stocks, p_industries_type, p_day):
    dict_stk_2_ind = {}
    stocks_industry_dict = get_industry(p_stocks, date=p_day)
    for stock in stocks_industry_dict:
        if p_industries_type in stocks_industry_dict[stock]:
            dict_stk_2_ind[stock] = stocks_industry_dict[stock][p_industries_type]['industry_code']
    return pd.Series(dict_stk_2_ind)

# ─── 选股逻辑 ─────────────────────────────────────────────────────────────────
def get_stock_list(context):
    yesterday = context.previous_date
    today     = context.current_dt
    p_count   = 1
    p_industries_type = 'sw_l1'
    
    initial_list = get_index_stocks('000985.XSHG', today)
    h = get_price(initial_list, end_date=yesterday, frequency='1d', fields=['close'],
                  count=p_count + 20, panel=False)
    h['date']  = pd.DatetimeIndex(h.time).date
    df_close   = h.pivot(index='code', columns='date', values='close').dropna(axis=0)
    df_ma20    = df_close.rolling(window=20, axis=1).mean().iloc[:, -p_count:]
    df_bias    = df_close.iloc[:, -p_count:] > df_ma20
    
    s_stk_2_ind = getStockIndustry(p_stocks=initial_list, p_industries_type=p_industries_type, p_day=yesterday)
    df_bias['industry_code'] = s_stk_2_ind
    df_ratio   = ((df_bias.groupby('industry_code').sum() * 100.0) /
                  df_bias.groupby('industry_code').count()).round()
    top_values = df_ratio[datetime.date(yesterday.year, yesterday.month, yesterday.day)].nlargest(g.num)
    I = top_values.index.tolist()
    
    defense_industries = {'801780', '801050', '801950', '801040'}
    if not defense_industries.intersection(set(I)):
        g.industry_etf_mode = False
        S_stocks = get_index_stocks('399101.XSHE', today)
        stocks = filter_kcbj_stock(S_stocks)
        choice = filter_st_stock(stocks)
        choice = filter_new_stock(context, choice)
        BIG_stock_list = get_fundamentals(query(
            valuation.code,
        ).filter(
            valuation.code.in_(choice),
            indicator.roe > 0.15,
            indicator.roa > 0.10,
        ).order_by(valuation.market_cap.asc()).limit(g.stock_num)).set_index('code').index.tolist()
        BIG_stock_list = filter_paused_stock(BIG_stock_list)
        BIG_stock_list = filter_limitup_stock(context, BIG_stock_list)
        L = filter_limitdown_stock(context, BIG_stock_list)
    else:
        g.industry_etf_mode = True
        sel_etf = get_rank(context)[0][0] if get_rank(context)[0] else None
        L = [sel_etf] if sel_etf else []
    return L

# ─── 周度调仓 ─────────────────────────────────────────────────────────────────
def weekly_adjustment(context):
    g.t_record.clear()
    target_B = get_stock_list(context)
    
    # 【V2修改】日历效应改为三段精确日期区间
    is_calendar_etf_month = is_in_calendar_window(context)
    
    # ETF模式下直接执行轮动，不买入股票
    if g.industry_etf_mode or is_calendar_etf_month or g.sar_ratio == 0:
        mode_name = '日历效应区间' if is_calendar_etf_month else ('行业防御模式' if g.industry_etf_mode else 'SAR空仓信号')
        log.info('=== 本周调仓：%s，不执行股票买入 ===' % mode_name)
        # 先清掉剩余股票持仓
        for stock in g.hold_list:
            if stock not in g.yesterday_HL_list:
                pos = context.portfolio.positions[stock]
                close_position(context, pos)
        daily_etf_rotation(context)
        return
    
    # 卖出不在目标列表的股票
    for stock in g.hold_list:
        if stock not in target_B and stock not in g.yesterday_HL_list:
            pos = context.portfolio.positions[stock]
            close_position(context, pos)
    
    # 先校准ETF仓位到目标比例，释放资金
    daily_etf_rotation(context)
    
    # 计算股票目标总仓位与单只金额
    stock_target_total = context.portfolio.total_value * g.sar_ratio
    current_stock_value = sum([pos.value for s, pos in context.portfolio.positions.items() 
                               if not s.startswith('5') and not s.startswith('1')])
    need_buy_total = max(0, stock_target_total - current_stock_value)
    
    buy_candidates = [s for s in target_B if s not in context.portfolio.positions]
    if not buy_candidates or need_buy_total < 1000:
        log.info('  无需新增股票买入')
        return
    
    per_stock_value = need_buy_total / len(buy_candidates)
    # 单只最低金额过滤，避免不足100股报错
    per_stock_value = max(per_stock_value, 1000)
    
    log.info('  股票目标总仓位:%.2f | 待买入总金额:%.2f | 单只目标:%.2f' 
             % (stock_target_total, need_buy_total, per_stock_value))
    
    for stock in buy_candidates:
        if open_position(context, stock, per_stock_value):
            if len([s for s in context.portfolio.positions 
                    if not s.startswith('5') and not s.startswith('1')]) >= g.stock_num:
                break

# ─── 日内做T模块 ─────────────────────────────────────────────────────────────
def get_daily_vwap(stock, context):
    try:
        now = context.current_dt
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed_min = int((now - market_open).total_seconds() / 60) + 1
        elapsed_min = min(max(elapsed_min, 1), 242)
        hist = get_price(stock, end_date=now, frequency='1m',
                         fields=['money', 'volume'], count=elapsed_min)
        total_vol = hist['volume'].sum()
        if total_vol == 0:
            return None
        return hist['money'].sum() / total_vol
    except:
        return None

def t_trade(context):
    if g.t_force_buy_done:
        # 已经执行过强制买回，避免重复做t
        return
    current_data = get_current_data()
    for stock in list(context.portfolio.positions.keys()):
        if stock[0] in ('1', '5'):
            continue
        if stock in g.yesterday_HL_list:
            continue
        if current_data[stock].last_price >= current_data[stock].high_limit:
            continue
        cur_price = current_data[stock].last_price
        if cur_price <= 0:
            continue
        vwap = get_daily_vwap(stock, context)
        if vwap is None or vwap <= 0:
            continue
        dev = (cur_price - vwap) / vwap
        
        if stock not in g.t_record:
            pos = context.portfolio.positions[stock]
            if pos.closeable_amount < 100:
                continue
            if dev >= g.t_vwap_up:
                sell_amount = int(pos.closeable_amount * g.t_ratio / 100) * 100
                if sell_amount < 100:
                    continue
                action = 'sell'
                slip = g.slip_rate
                limit_price = cur_price*(1+slip) if action == 'buy' else cur_price*(1-slip)
                style = MarketOrderStyle(limit_price)
                log.info('[T+0] %s 分时价 %.3f > VWAP %.3f 上浮 %.2f%%，卖出 %d股'
                            % (stock, cur_price, vwap, dev * 100, sell_amount))
                o = order(stock, -sell_amount,style)
                if o and o.filled > 0:
                    g.t_record[stock] = {
                        'price' : cur_price,
                        'vwap'  : vwap,
                        'amount': o.filled,
                    }
        else:
            if dev <= -g.t_vwap_down:
                rec    = g.t_record[stock]
                amount = rec['amount']
                action = 'buy'
                slip = g.slip_rate
                limit_price = cur_price*(1+slip) if action == 'buy' else cur_price*(1-slip)
                style = MarketOrderStyle(limit_price)
                log.info('[T+0] %s 分时价 %.3f < VWAP %.3f 下浮 %.2f%%，买回 %d股'
                            % (stock, cur_price, vwap, dev * 100, amount))
                o = order(stock, amount,style)
                if o and o.filled > 0:
                    g.t_record.pop(stock)

def t_force_buy(context):
    if not g.t_record:
        return
    current_data = get_current_data()
    for stock, rec in list(g.t_record.items()):
        amount = rec['amount']
        action = 'buy'
        cur_price = current_data[stock].last_price
        slip = g.slip_rate
        limit_price = cur_price*(1+slip) if action == 'buy' else cur_price*(1-slip)
        style = MarketOrderStyle(limit_price)
        log.info('[T+0] %s 强制买回 %d股' % (stock, amount))
        o = order(stock, amount,style)
    g.t_record.clear()
    g.t_force_buy_done = True

# ─── 收盘汇总与涨停检查 ───────────────────────────────────────────────────────
def log_daily_summary(context):
    p = context.portfolio
    g.t_force_buy_done = False
    log.info('=== 收盘汇总 [%s] ===' % context.current_dt.date())
    log.info('  总资产: %.2f | 可用现金: %.2f | 累计收益: %.2f%%'
             % (p.total_value, p.available_cash, p.returns * 100))
    
    stock_pos = []
    etf_pos = []
    for s, pos in p.positions.items():
        if s.startswith('5') or s.startswith('1'):
            etf_pos.append((s, pos))
        else:
            stock_pos.append((s, pos))
    
    if stock_pos:
        log.info('  --- 股票持仓 ---')
        for stock, pos in stock_pos:
            cost  = pos.avg_cost
            price = pos.price
            pnl   = (price - cost) / cost * 100 if cost > 0 else 0
            log.info('  %s | %d股 | 成本:%.3f | 收盘:%.3f | 盈亏:%.2f%% | 仓位:%.1f%%'
                     % (stock, pos.total_amount, cost, price, pnl,
                        pos.value / p.total_value * 100))
    
    if etf_pos:
        log.info('  --- ETF持仓 ---')
        for etf, pos in etf_pos:
            cost  = pos.avg_cost
            price = pos.price
            pnl   = (price - cost) / cost * 100 if cost > 0 else 0
            log.info('  %s | %d股 | 成本:%.3f | 收盘:%.3f | 盈亏:%.2f%% | 仓位:%.1f%%'
                     % (g.etf_names.get(etf, etf), pos.total_amount, cost, price, pnl,
                        pos.value / p.total_value * 100))

def check_limit_up(context):
    if g.yesterday_HL_list:
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=context.current_dt, frequency='1m',
                                     fields=['close', 'high_limit'], count=1, panel=False)
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                close_position(context,context.portfolio.positions[stock])

# ─── 交易工具函数 ─────────────────────────────────────────────────────────────
def order_target_value_(security, value):
    return order_target_value(security, value)

def open_position(context,security, value):
    safe_order_target_value(context, 'buy', security, value)
    return True

def close_position(context,position):
    security  = position.security
    ret = safe_order_target_value(context, 'sell', security, 0)
    return ret

# ─── 股票过滤器 ───────────────────────────────────────────────────────────────
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [s for s in stock_list if not current_data[s].paused]

def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [s for s in stock_list
            if not current_data[s].is_st
            and 'ST' not in current_data[s].name
            and '*'  not in current_data[s].name
            and '退' not in current_data[s].name]

def filter_kcbj_stock(stock_list):
    return [s for s in stock_list
            if s[0] not in ('4', '8', '3') and s[:2] != '68']

def filter_limitup_stock(context, stock_list):
    last_prices  = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [s for s in stock_list
            if s in context.portfolio.positions.keys()
            or last_prices[s][-1] < current_data[s].high_limit]

def filter_limitdown_stock(context, stock_list):
    last_prices  = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [s for s in stock_list
            if s in context.portfolio.positions.keys()
            or last_prices[s][-1] > current_data[s].low_limit]

def filter_new_stock(context, stock_list):
    yesterday = context.previous_date
    return [s for s in stock_list
            if not yesterday - get_security_info(s).start_date < datetime.timedelta(days=375)]

# ─── 交易工具函数 ─────────────────────────────────────────────────────────────
def safe_order_target_value(context,action,code,target_value,pindex=0):
    style = None

    positions = context.portfolio.positions
    portfolio = context.portfolio
    available_cash = portfolio.available_cash
    cur_data = get_current_data()
    price = cur_data[code].last_price
    is_kcb = code[:2] == '68'
    slip = g.slip_rate
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
                log.warn(f"safe_order_target_value ignore,holding {action} {code} {amount}股 {target_value}元 {style} 可用金额={available_cash} {pindex}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style,pindex = pindex)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {action} {code} {amount}股 {target_value}元 {style} 可用金额={available_cash} {pindex}")
    return 0