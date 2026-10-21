## 八合一-七律版本，个股禁用科创板和创业板
# 实盘改造点：
# 1、改g.变量名、函数名
# 2、增加common函数
# 3、修改positions,和portfolio
# 4、修统一下单函数
# 5、买卖限制
# 6、禁止买卖创业版or科创板标的-可选

# 聚宽ETF多周期均线粘合 + BOLL开口策略
# 标的：市场主流ETF基金
# 买入：日线MA5/20/60粘合 + 120分钟BOLL开口 + 月线MACD>0
# 卖出：60分钟收盘价跌破MA20
# 风控：大盘仓位管理、规模过滤、流动性过滤

from jqdata import *
import numpy as np
import pandas as pd
import datetime

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
    bt_wrapper.configured(context,Live_Type,'123.57.67.16','mGyVzscJ')
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
BUY_SLIP = 0.005
MIN_GAP_DAYS = 5
MIN_HOLD_DAYS = 3
# 不同策略固定止损阈值,均线粘合、N宽基、全球宽基、自适应宽基,弱转强，红利增强，均线粘合个股，小市值
FIX_RATE_LIMITS = [0.05,0.035,0.035,0.035,0.035,0.035,0.05,0.035]

def initialize(context):
    total_init_cash = context.portfolio.available_cash
    g.total_init_cash = total_init_cash
    # 均线粘合策略资金
    g.s1_cash = total_init_cash // 10 * 3
    # N大宽基策略资金
    g.s2_cash = total_init_cash // 10 * 2
    # 全球ETF策略资金
    g.s3_cash = total_init_cash * 0
    # 自适应ETF轮动
    g.s4_cash = total_init_cash * 0
    # 弱转强
    g.s5_cash = total_init_cash // 10 * 3
    # 红利ETF增强
    g.s6_cash = total_init_cash // 10
    # 均线粘合-个股版
    g.s7_cash = total_init_cash // 10
    # 小市值
    g.s8_cash = total_init_cash * 0

    set_subportfolios([SubPortfolioConfig(cash=g.s1_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s2_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s3_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s4_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s5_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s6_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s7_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s8_cash, type='stock')])
    if g.s1_cash > 0:
        log.info(f"启动【均线粘合策略1】,分配金额{g.s1_cash}")
        s1_initialize(context)
    if g.s2_cash > 0:
        log.info(f"启动【N大宽基ETF策略2】,分配金额{g.s2_cash}")
        s2_initialize(context)
    if g.s3_cash > 0:
        log.info(f"启动【全球ETF轮动策略3】,分配金额{g.s3_cash}")
        s3_initialize(context)
    if g.s4_cash > 0:
        log.info(f"启动【自适应ETF轮动策略4】,分配金额{g.s4_cash}")
        s4_initialize(context)
    if g.s5_cash > 0:
        s5_initialize(context)
        log.info(f"启动【弱转强策略5】,分配金额{g.s5_cash}")
    if g.s6_cash > 0:
        s6_initialize(context)
        log.info(f"启动【红利增强策略6】,分配金额{g.s6_cash}")
    if g.s7_cash > 0:
        s7_initialize(context)
        log.info(f"启动【均线粘合-个股版本策略7】,分配金额{g.s7_cash}")
    if g.s8_cash > 0:
        s8_initialize(context)
        log.info(f"启动【小市值策略】,分配金额{g.s8_cash}")

    N = 10
    g.buy_date_history = {}
    g.sell_date_history = {}
    for i in range(0, N):
        g.buy_date_history[i] = {}
        g.sell_date_history[i] = {}

    g.subportfolio_infos = [
        {'cash':g.s1_cash,'name':'均线粘合'},
        {'cash':g.s2_cash,'name':'N大宽基ETF'},
        {'cash':g.s3_cash,'name':'全球宽基ETF'},
        {'cash':g.s4_cash,'name':'自适应ETF'},
        {'cash':g.s5_cash,'name':'弱转强'},
        {'cash':g.s6_cash,'name':'红利ETF增强'},
        {'cash':g.s7_cash,'name':'均线粘合-个股版'},
        {'cash':g.s8_cash,'name':'小市值'},
        ]
    # 根据上一次的策略终止态恢复状态
    init_histroy_status()

def after_trading_end(context):
    log_portfolio(context)

def after_code_changed(context):
    log_status(context)
    unschedule_all()
    if g.s1_cash > 0:
        s1_after_code_changed(context)
    if g.s2_cash > 0:
        s2_after_code_changed(context)
    if g.s3_cash > 0:
        s3_after_code_changed(context)
    if g.s4_cash > 0:
        s4_schedule_tasks(context)
    if g.s5_cash > 0:
        s5_scheduler_task(context)
    if g.s6_cash > 0:
        s6_scheduler_tasks(context)
    if g.s7_cash > 0:
        s7_after_code_changed(context)
    if g.s8_cash > 0:
        s8_scheduler_tasks(context)

def init_histroy_status():
    g.sell_date_history={0: {'513100.XSHG': datetime.date(2026, 10, 7), '563300.XSHG': datetime.date(2026, 9, 28), '513880.XSHG': datetime.date(2026, 10, 13), '159930.XSHE': datetime.date(2026, 10, 15)}, 1: {'513500.XSHG': datetime.date(2026, 10, 19)}, 2: {'159509.XSHE': datetime.date(2026, 10, 7), '513100.XSHG': datetime.date(2026, 10, 7)}, 3: {'159509.XSHE': datetime.date(2026, 10, 7)}, 4: {'600513.XSHG': datetime.date(2026, 10, 13), '002242.XSHE': datetime.date(2026, 10, 15), '000892.XSHE': datetime.date(2026, 10, 15)}, 5: {}, 6: {}, 7: {'002253.XSHE': datetime.date(2026, 10, 13), '002715.XSHE': datetime.date(2026, 10, 19), '002494.XSHE': datetime.date(2026, 10, 19)}, 8: {}, 9: {}}

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
    total_cw = 1 - total_cash / total_value
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

# ========== 策略1.均线粘合， 初始化函数 ==========
def s1_after_trading_end(context):
    pass

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
    run_daily(s1_take_fix_profit,time='every_bar')  # 每分钟检查止盈
    # run_daily(s1_take_fix_profit,time='09:40')

    
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
            ma120 = s1_check_ma120_increase(etf, context)
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

# ========= 120日线均线上涨或当前价大于120日均线 ==========
def s1_check_ma120_increase(security, context):
    df = attribute_history(security, 150, '1d', ['close'], skip_paused=True, df=True)
    if len(df) < 120:
        return False
    cur_data = get_current_data()
    price = cur_data[security].last_price
    ma120_roll = df['close'].rolling(120).mean()
    ma120 = ma120_roll.iloc[-1]
    last_ma120 = ma120_roll.iloc[-2]
    is_above_ma120 = price > ma120
    increase = ma120 >= last_ma120
    return is_above_ma120 or increase

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

def s1_trade_sell_by_lightning_rod(context):
    """
    避雷针卖出法（独立止盈）
    每日14:44执行，使用盘中实时数据，无未来函数。
    条件（同时满足）：
      1. 当前价 < 开盘价（盘中阴线）
      2. 今日最高价 ≥ 过去20日（不含今日）最高价
      3. 开盘价 < (今日最高价 + 今日最低价) / 2
    """
    positions = get_portfolio_positions(context,pindex=0)
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
            log.info(f"no date")
            continue

        today_date = context.current_dt.date()
        # 过滤出今天的分钟线
        today_bars = bars[bars['date'].dt.date == today_date]
        if len(today_bars) == 0:
            log.info(f"no today_bars")
            continue

        high_today = today_bars['high'].max()
        low_today = today_bars['low'].min()
        if high_today is None or low_today is None:
            log.info(f"no high_today low")
            continue

        # ---------- 过去50日（不含今日）最高价 ----------
        hist_df = attribute_history(etf, 50, '1d', ['high'], skip_paused=True, df=True)
        if len(hist_df) < 20:
            continue
        hist_high = hist_df['high'].max()

        # 条件2：今日最高价 ≥ 过去50日最高（创新高）
        if high_today < hist_high:
            continue

        # 条件3：开盘价低于当日振幅中点
        if day_open >= (high_today + low_today) / 2:
            continue

        # ---------- 全部满足，清仓 ----------
        log.info('【策略1】避雷针卖出 {}，当前价{:.3f}<开盘{:.3f}，今日最高{:.3f}≥20日最高{:.3f}，开盘{:.3f}<中点{:.3f}'.format(
            etf, last_price, day_open, high_today, hist_high,
            day_open, (high_today + low_today) / 2))
        s1_safe_order_target_value(context, 'sell', etf, 0)
        if etf in g.s1_buy_date:
            del g.s1_buy_date[etf]

def s1_trade_sell(context):
    s1_trade_sell_by_lightning_rod(context)
    # 获取当前持仓
    positions = get_portfolio_positions(context,pindex=0)
    current_holdings = [s for s in positions if positions[s].closeable_amount > 0]
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
    positions = get_portfolio_positions(context,pindex=0)
    portfolio = get_portfolio(context,pindex=0)
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
    
    log.info(f"【策略1】买入计算，仓位上限比例{g.s1_position_limit},标的数上限{g.s1_stock_num},今日可用金额上限{buy_cash_limit}，当前市值{total_assets},持仓市值{current_stock_value}")
    
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
    if len(candidates) <= 0:
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
    pass

def s2_set_targets(context):
    g.s2_assets = [
        '510300.XSHG',  # 沪深300
        '513500.XSHG',  # 标普500
        '159915.XSHE',  # 创业板
        '513100.XSHG',  # 纳指100
        '518880.XSHG',  # 黄金ETF
        '588080.XSHG',  # 科创板
        '159518.XSHE',  # 标普原油
        '513400.XSHG',  # 道琼斯
        '159920.XSHE',  #恒生ETF
        '512890.XSHG',  # 红利ETF
        '510050.XSHG',  # 50ETF
        '512500.XSHG',  # 500ETF
        '159845.XSHE',  # 1000ETF
        '159628.XSHE',  # 2000ETF
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
    run_daily(s2_take_fix_profit,time='every_bar')
    # run_daily(s2_take_fix_profit,time='09:40')

    
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
        log.info(f"【策略2】：持仓未变，跳过本次调仓，{new_selected_codes}")
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

def s2_take_fix_profit(context):
    # 止盈设置
    take_fix_profit_check(context,FIX_RATE_LIMITS[1],pindex=1)

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

STRATEGY_PARAMS = {
    'stock_sum': 1,      # 持仓ETF数量
    'm_days': M_DAYS,        # 动量参考天数
    'min_money': 500,    # 最小交易金额（低于此金额不交易）
}

# ----- 过滤条件 -----
FILTER_PARAMS = {
    'max_score': MAX_MOM_SCORE,           # score 上限（超出归零）
    'min_score': MIN_MOM_SCORE,           # score 下限
    'drop_threshold': 0.95,   # 近3日跌幅阈值（<0.95 的 score 归零）
    'r2_weight': True,        # 是否用 R² 加权年化收益作为 score
}

# ----- 交易参数 -----
TRADE_PARAMS = {
    'adjust_sell_time': "11:00",     # 调仓，卖出执行时间
    'adjust_buy_time': "11:01",     # 买入执行时间
    'end_trade_time': "14:55",  # 尾盘处理时间
    'slippage_fund': 0.001,   # 基金滑点
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
    run_daily(s3_rotation_sell, '11:00')
    run_daily(s3_do_buy, '11:01')
    run_daily(s3_take_fix_profit,'every_bar')
    # run_daily(s3_take_fix_profit,'09:40')
    

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
        targets = []
        
        for etf in candidates:
            # 同一个标的至少间隔上一次卖出N天后再买
            is_in_gaps_day = is_sell_in_gaps_day(self.context,etf,MIN_GAP_DAYS,pindex=2)
            if is_in_gaps_day:
                continue
            targets.append(etf)
        targets = targets[:stock_sum]

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
                # 至少持有N天间隔后才卖出
                is_in_gaps_day = is_buy_in_gaps_day(self.context,stock,MIN_HOLD_DAYS,pindex=2)
                if is_in_gaps_day:
                    continue
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
        action = 'buy' if delta > 0 else 'sell'
        order_obj = order(security, delta, style=style, pindex=pindex)
        record_history(self.context, action, security, pindex)
        if order_obj:
            return True
        return False


# ============================================================
# 收盘统计
# ============================================================

def s3_after_trading_end(context):
    """收盘后输出当日的持仓与盈亏"""
    pass

# =====================策略3 end=======================================

#=========策略4 start=====

def s4_after_trading_end(context):
    pass
    

def s4_schedule_tasks(context):
    # ==================== 定时任务 ====================
    run_daily(s4_morning_routine, time='09:00')            # 09:00 晨间流水线：持仓检查→回撤监控→流动性阈值计算
    run_daily(s4_check_weak_period_daily, time='09:40')    # 09:40 走弱期判断+池子更新
    run_daily(s4_afternoon_routine, time='13:02')          #  动量计算与排序（需早于卖出时间）         
    run_daily(s4_sell_routine, time='13:03')               #  卖出流水线（需早于买入时间）
    run_daily(s4_buy_routine, time='13:04')                #  买入流水线
    run_daily(s4_reset_daily_flags, time='15:10')          # 15:10 收盘流水线：重置价格缓存
    run_daily(s4_minute_level_stop_loss, time='every_bar') # 分钟级固定止损
    run_daily(s4_take_fix_profit, time='every_bar')                #  每日止盈检查
    # run_daily(s4_take_fix_profit, time='09:40')                #  每日止盈检查
    

def s4_initialize(context):
    common_initialize(context)                                               # 公共初始化：设置滑点、交易成本、日志级别等

    # ==================== ETF池定义 ====================
    # 全球/海外ETF池（含大宗商品和海外市场ETF）
    g.s4_global_etf_pool = [
#大宗商品ETF：
        '518880.XSHG',  # (黄金ETF) [ETF]-日均成交额：51.35亿元-上市日期：2013-07-29
        # '501018.XSHG',  # (南方原油) [LOF]-日均成交额：24.38亿元-上市日期：2016-06-28
        # '161226.XSHE',  # (国投白银LOF) [LOF]-日均成交额：5.44亿元-上市日期：2015-08-17
        '159985.XSHE',  # (豆粕ETF华夏) [ETF]-日均成交额：4.63亿元-上市日期：2019-12-05
        '159980.XSHE',  # (有色ETF大成) [ETF]-日均成交额：3.84亿元-上市日期：2019-12-24
#海外ETF：       
        '513310.XSHG',  # (中韩芯片) [ETF]-日均成交额：59.37亿元-上市日期：2022-12-22
        '159518.XSHE',  # (标普油气ETF嘉实) [ETF]-日均成交额：27.93亿元-上市日期：2023-11-15
        '159509.XSHE',  # (纳指科技ETF景顺) [ETF]-日均成交额：7.24亿元-上市日期：2023-08-08
        '513100.XSHG',  # (纳指ETF) [ETF]-日均成交额：5.02亿元-上市日期：2013-05-15
        '513520.XSHG',  # (日经ETF) [ETF]-日均成交额：3.72亿元-上市日期：2019-06-25
        '513500.XSHG',  # (标普500) [ETF]-日均成交额：2.89亿元-上市日期：2014-01-15
        '159502.XSHE',  # (标普生物科技ETF嘉实) [ETF]-日均成交额：1.80亿元-上市日期：2024-01-10
        '513400.XSHG',  # (道琼斯) [ETF]-日均成交额：1.70亿元-上市日期：2024-02-02
        '513030.XSHG',  # (德国ETF) [ETF]-日均成交额：0.95亿元-上市日期：2014-09-05
        '513290.XSHG',  # (纳指生物) [ETF]-日均成交额：0.78亿元-上市日期：2022-08-29
        '520830.XSHG',  # (沙特ETF) [ETF]-日均成交额：0.62亿元-上市日期：2024-07-16
        '159529.XSHE',  # (标普消费ETF景顺) [ETF]-日均成交额：0.50亿元-上市日期：2024-02-02
    ]
    # 中国ETF池（含港股、指数、行业ETF）
    g.s4_china_etf_pool = [
#港股ETF：
        '513090.XSHG',  # (香港证券) [ETF]-日均成交额：54.24亿元-上市日期：2020-03-26
        '513120.XSHG',  # (HK创新药) [ETF]-日均成交额：52.34亿元-上市日期：2022-07-12
        '513180.XSHG',  # (恒指科技) [ETF]-日均成交额：36.66亿元-上市日期：2021-05-25
        '513330.XSHG',  # (恒生互联) [ETF]-日均成交额：20.45亿元-上市日期：2021-02-08
        '513750.XSHG',  # (港股非银) [ETF]-日均成交额：9.55亿元-上市日期：2023-11-27
        '159892.XSHE',  # (恒生医药ETF华夏) [ETF]-日均成交额：7.90亿元-上市日期：2021-10-19
        '513190.XSHG',  # (H股金融) [ETF]-日均成交额：3.74亿元-上市日期：2023-10-11
        '159605.XSHE',  # (中概互联ETF广发) [ETF]-日均成交额：3.19亿元-上市日期：2021-12-02
        '513630.XSHG',  # (香港红利) [ETF]-日均成交额：2.84亿元-上市日期：2023-12-08
        '159323.XSHE',  # (港股通汽车ETF华夏) [ETF]-日均成交额：1.98亿元-上市日期：2025-01-08
        '510900.XSHG',  # (恒生中国) [ETF]-日均成交额：1.46亿元-上市日期：2012-10-22
        '513920.XSHG',  # (央企40) [ETF]-日均成交额：1.38亿元-上市日期：2024-01-05
        '513970.XSHG',  # (恒生消费) [ETF]-日均成交额：0.82亿元-上市日期：2023-04-21
#指数ETF：        
        '511380.XSHG',  # (转债ETF) [ETF]-日均成交额：115.92亿元-上市日期：2020-04-07
        '512050.XSHG',  # (A500E) [ETF]-日均成交额：48.05亿元-上市日期：2024-11-15
        '510500.XSHG',  # (500ETF) [ETF]-日均成交额：45.45亿元-上市日期：2013-03-15
        '159915.XSHE',  # (创业板ETF易方达) [ETF]-日均成交额：43.55亿元-上市日期：2011-12-09
        '510300.XSHG',  # (300ETF) [ETF]-日均成交额：34.60亿元-上市日期：2012-05-28
        '512100.XSHG',  # (1000ETF) [ETF]-日均成交额：25.26亿元-上市日期：2016-11-04
        '159949.XSHE',  # (创业板50ETF华安) [ETF]-日均成交额：16.52亿元-上市日期：2016-07-22
        '588080.XSHG',  # (科创板50) [ETF]-日均成交额：13.32亿元-上市日期：2020-11-16
        '159967.XSHE',  # (创业板成长ETF华夏) [ETF]-日均成交额：5.29亿元-上市日期：2019-07-15
        '588220.XSHG',  # (科创100F) [ETF]-日均成交额：5.01亿元-上市日期：2023-09-15
        '563300.XSHG',  # (中证2000) [ETF]-日均成交额：4.13亿元-上市日期：2023-09-14
        '510760.XSHG',  # (上证ETF) [ETF]-日均成交额：1.45亿元-上市日期：2020-09-09
#行业ETF：
        '588200.XSHG',  # (科创芯片) [ETF]-日均成交额：28.07亿元-上市日期：2022-10-26
        '515880.XSHG',  # (通信ETF) [ETF]-日均成交额：22.39亿元-上市日期：2019-09-06
        '159981.XSHE',  # (能源化工ETF建信) [ETF]-日均成交额：21.63亿元-上市日期：2020-01-17
        '512880.XSHG',  # (证券ETF) [ETF]-日均成交额：16.21亿元-上市日期：2016-08-08
        '513350.XSHG',  # (油气ETF) [ETF]-日均成交额：15.66亿元-上市日期：2023-11-28
        '159326.XSHE',  # (电网设备ETF华夏) [ETF]-日均成交额：14.86亿元-上市日期：2024-09-09
        '159516.XSHE',  # (半导体设备ETF国泰) [ETF]-日均成交额：14.23亿元-上市日期：2023-07-27
        '159206.XSHE',  # (卫星ETF永赢) [ETF]-日均成交额：13.87亿元-上市日期：2025-03-14
        '512480.XSHG',  # (半导体) [ETF]-日均成交额：13.07亿元-上市日期：2019-06-12
        '159363.XSHE',  # (创业板人工智能ETF华宝) [ETF]-日均成交额：10.50亿元-上市日期：2024-12-16
        '159870.XSHE',  # (化工ETF鹏华) [ETF]-日均成交额：10.03亿元-上市日期：2021-03-03
        '512400.XSHG',  # (有色ETF) [ETF]-日均成交额：9.97亿元-上市日期：2017-09-01
        '159755.XSHE',  # (电池ETF广发) [ETF]-日均成交额：8.58亿元-上市日期：2021-06-24
        '588170.XSHG',  # (科创半导) [ETF]-日均成交额：7.74亿元-上市日期：2025-04-08
        '159992.XSHE',  # (创新药ETF银华) [ETF]-日均成交额：7.59亿元-上市日期：2020-04-10
        '159995.XSHE',  # (芯片ETF华夏) [ETF]-日均成交额：7.51亿元-上市日期：2020-02-10
        '512890.XSHG',  # (红利低波) [ETF]-日均成交额：6.79亿元-上市日期：2019-01-18
        '515220.XSHG',  # (煤炭ETF) [ETF]-日均成交额：6.44亿元-上市日期：2020-03-02
        '159566.XSHE',  # (储能电池ETF易方达) [ETF]-日均成交额：6.31亿元-上市日期：2024-02-08
        '159819.XSHE',  # (人工智能ETF易方达) [ETF]-日均成交额：6.26亿元-上市日期：2020-09-23
        '512800.XSHG',  # (银行ETF) [ETF]-日均成交额：6.13亿元-上市日期：2017-08-03
        '512690.XSHG',  # (酒ETF) [ETF]-日均成交额：5.99亿元-上市日期：2019-05-06
        '515050.XSHG',  # (5GETF) [ETF]-日均成交额：5.93亿元-上市日期：2019-10-16
        '562500.XSHG',  # (机器人) [ETF]-日均成交额：5.83亿元-上市日期：2021-12-29
        '512170.XSHG',  # (医疗ETF) [ETF]-日均成交额：5.63亿元-上市日期：2019-06-17
        '517520.XSHG',  # (黄金股) [ETF]-日均成交额：5.01亿元-上市日期：2023-11-01
        '159869.XSHE',  # (游戏ETF华夏) [ETF]-日均成交额：4.77亿元-上市日期：2021-03-05
        '512070.XSHG',  # (证券保险) [ETF]-日均成交额：4.61亿元-上市日期：2014-07-18
        '159611.XSHE',  # (电力ETF广发) [ETF]-日均成交额：4.42亿元-上市日期：2022-01-07
        '562800.XSHG',  # (稀有金属) [ETF]-日均成交额：4.39亿元-上市日期：2021-09-27
        '515120.XSHG',  # (创新药) [ETF]-日均成交额：4.34亿元-上市日期：2021-01-04
        '512010.XSHG',  # (医药ETF) [ETF]-日均成交额：4.27亿元-上市日期：2013-10-28
        '510880.XSHG',  # (红利ETF) [ETF]-日均成交额：3.97亿元-上市日期：2007-01-18
        '515790.XSHG',  # (光伏ETF) [ETF]-日均成交额：3.87亿元-上市日期：2020-12-18
        '515980.XSHG',  # (人工智能) [ETF]-日均成交额：3.78亿元-上市日期：2020-02-10
        '512660.XSHG',  # (军工ETF) [ETF]-日均成交额：3.75亿元-上市日期：2016-08-08
        '159928.XSHE',  # (消费ETF汇添富) [ETF]-日均成交额：3.66亿元-上市日期：2013-09-16
        '512710.XSHG',  # (军工龙头) [ETF]-日均成交额：3.60亿元-上市日期：2019-08-26
        '560860.XSHG',  # (工业有色) [ETF]-日均成交额：3.57亿元-上市日期：2023-03-13
        '515030.XSHG',  # (新汽车) [ETF]-日均成交额：3.33亿元-上市日期：2020-03-04
        '159766.XSHE',  # (旅游ETF富国) [ETF]-日均成交额：3.30亿元-上市日期：2021-07-23
        '159218.XSHE',  # (卫星ETF招商) [ETF]-日均成交额：3.21亿元-上市日期：2025-05-22
        '159852.XSHE',  # (软件ETF嘉实) [ETF]-日均成交额：3.19亿元-上市日期：2021-02-09
        '516160.XSHG',  # (新能源) [ETF]-日均成交额：3.07亿元-上市日期：2021-02-04
        '516150.XSHG',  # (稀土基金) [ETF]-日均成交额：3.03亿元-上市日期：2021-03-17
        '159227.XSHE',  # (航空航天ETF华夏) [ETF]-日均成交额：2.98亿元-上市日期：2025-05-16
        '159583.XSHE',  # (通信ETF富国) [ETF]-日均成交额：2.93亿元-上市日期：2024-07-08
        '588790.XSHG',  # (科创智能) [ETF]-日均成交额：2.62亿元-上市日期：2025-01-09
        '159865.XSHE',  # (养殖ETF国泰) [ETF]-日均成交额：2.44亿元-上市日期：2021-03-08
        '512980.XSHG',  # (传媒ETF) [ETF]-日均成交额：2.43亿元-上市日期：2018-01-19
        '159851.XSHE',  # (金融科技ETF华宝) [ETF]-日均成交额：2.27亿元-上市日期：2021-03-19
        '561360.XSHG',  # (石油ETF) [ETF]-日均成交额：2.04亿元-上市日期：2023-10-31
        '561980.XSHG',  # (芯片设备) [ETF]-日均成交额：2.01亿元-上市日期：2023-09-01
        '562590.XSHG',  # (半导材料) [ETF]-日均成交额：1.76亿元-上市日期：2023-10-18
        '512200.XSHG',  # (地产ETF) [ETF]-日均成交额：1.71亿元-上市日期：2017-09-25
        '159732.XSHE',  # (消费电子ETF华夏) [ETF]-日均成交额：1.62亿元-上市日期：2021-08-23
        '159667.XSHE',  # (工业母机ETF国泰) [ETF]-日均成交额：1.58亿元-上市日期：2022-10-26
        '516510.XSHG',  # (云计算) [ETF]-日均成交额：1.49亿元-上市日期：2021-04-07
        '159840.XSHE',  # (锂电池ETF工银) [ETF]-日均成交额：1.42亿元-上市日期：2021-08-20
        '159998.XSHE',  # (计算机ETF天弘) [ETF]-日均成交额：1.30亿元-上市日期：2020-04-13
        '159825.XSHE',  # (农业ETF富国) [ETF]-日均成交额：1.15亿元-上市日期：2020-12-29
        '512670.XSHG',  # (国防ETF) [ETF]-日均成交额：1.12亿元-上市日期：2019-08-01
        '159883.XSHE',  # (医疗器械ETF永赢) [ETF]-日均成交额：1.05亿元-上市日期：2021-04-30
        '515210.XSHG',  # (钢铁ETF) [ETF]-日均成交额：1.01亿元-上市日期：2020-03-02
        '515400.XSHG',  # (大数据) [ETF]-日均成交额：0.94亿元-上市日期：2021-01-20
        '159256.XSHE',  # (创业板软件ETF华夏) [ETF]-日均成交额：0.83亿元-上市日期：2025-08-04
        '561330.XSHG',  # (矿业ETF) [ETF]-日均成交额：0.83亿元-上市日期：2022-11-01
        '515170.XSHG',  # (食品饮料) [ETF]-日均成交额：0.67亿元-上市日期：2021-01-13
        '159638.XSHE',  # (高端装备ETF嘉实) [ETF]-日均成交额：0.56亿元-上市日期：2022-08-12
        '516520.XSHG',  # (智能驾驶) [ETF]-日均成交额：0.47亿元-上市日期：2021-03-01
        '513360.XSHG',  # (教育ETF) [ETF]-日均成交额：0.43亿元-上市日期：2021-06-17
        '516190.XSHG',  # (文娱ETF) [ETF]-日均成交额：0.18亿元-上市日期：2021-09-17
    ]
    # 固定ETF池 = 全球池 + 中国池（正常期使用）
    g.s4_fixed_etf_pool = g.s4_global_etf_pool + g.s4_china_etf_pool

    g.s4_avg_etf_money_threshold = None
    g.s4_filtered_fixed_pool = []
    g.s4_dynamic_etf_pool = []
    g.s4_merged_etf_pool = []
    g.s4_ranked_etfs_result = []
    g.s4_filtered_global_pool = []
    g.s4_global_threshold_divisor = 20000  # 全市场ETF流动性阈值除数，资金大建议改为3000避免买到盘子小的etf
    
    g.s4_is_a_share_weak = False
    g.s4_weak_period_ma_lookback = 10
    g.s4_weak_start_date = None
    g.s4_weak_days_count = 0
    g.s4_max_weak_days = 20

    g.s4_holdings_num = 1
    g.s4_defensive_etf = "511880.XSHG"
    g.s4_min_money = 10
    g.s4_target_etfs_list = []
    g.s4_etf_names_dict = {}
    g.s4_cache_date = None
    g.s4_yesterday_close_cache = {}

    g.s4_lookback_days = M_DAYS
    g.s4_min_score_threshold = MIN_MOM_SCORE
    g.s4_max_score_threshold = MAX_MOM_SCORE
    g.s4_score_threshold_ratio = 0.9

    g.s4_enable_r2_filter = True
    g.s4_r2_threshold = 0.4
    g.s4_enable_ma_filter = True
    g.s4_ma_lookback = 10
    g.s4_ma_threshold = 1.0
    g.s4_enable_volume_check = True
    g.s4_volume_lookback = 5
    g.s4_volume_threshold = 1.8
    g.s4_enable_loss_filter = True
    g.s4_loss = 0.97

    g.s4_max_portfolio_value = 0
    g.s4_drawdown_threshold = 0.03
    g.s4_drawdown_records = []
    
    g.s4_use_fixed_stop_loss = True
    g.s4_fixedStopLossThreshold = 0.95

    s4_schedule_tasks(context)


def s4_check_weak_period_daily(context):
    s4_check_a_share_weak_period(context)
    s4_midday_routine(context)


def s4_morning_routine(context):
    log.info("【策略4】 " + ("★" * 80))
    log.info("【策略4】 ▶️ 【晨间流水线】启动...")
    log.info("【策略4】 【持仓检查】检查当前持仓状态...")
    s4_check_positions(context)    
    log.info("【策略4】 【回撤监控】监控策略回撤...")
    s4_monitor_drawdown(context)
    log.info("【策略4】 【流动性阈值】计算全市场ETF流动性阈值...")
    s4_calculate_global_etf_threshold(context)
    log.info("【策略4】 ⏸️ 【晨间流水线】执行完毕！")


def s4_midday_routine(context):
    log.info("【策略4】 " + ("★" * 80))
    log.info("【策略4】 ▶️ 【早盘流水线】启动...")
    if g.s4_is_a_share_weak:
        log.info(f"【策略4】 🔴 【走弱期池更新】仅对全球/海外ETF池进行流动性过滤...")
        s4_filter_global_pool_by_volume(context)
        log.info(f"【策略4】 【走弱期池更新完成】过滤后全球池: {len(g.s4_filtered_global_pool)}只")
    else:
        log.info(f"【策略4】 🟢 【正常期池更新】执行动态池更新、固定池过滤、合并池...")
        log.info("【策略4】 【动态池更新】更新行业ETF动态池（各行业流动性最佳ETF）...")
        s4_update_sector_pool(context)
        log.info("【策略4】 【固定池过滤】过滤固定ETF池流动性...")
        s4_filter_fixed_pool_by_volume(context)
        log.info("【策略4】 【合并池】合并固定池与动态池...")
        s4_daily_merge_etf_pools(context)
        log.info(f"【策略4】 【正常期池更新完成】合并池: {len(g.s4_merged_etf_pool)}只")
    log.info("【策略4】 ⏸️ 【早盘流水线】执行完毕！")


def s4_afternoon_routine(context):
    log.info("【策略4】 " + ("★" * 80))
    log.info("【策略4】 ▶️ 【午盘流水线】启动...")
    if g.s4_is_a_share_weak:
        if hasattr(g, 's4_filtered_global_pool') and g.s4_filtered_global_pool:
            g.s4_merged_etf_pool = list(set(g.s4_filtered_global_pool))
        else:
            g.s4_merged_etf_pool = list(set(g.s4_global_etf_pool))
        g.s4_merged_etf_pool.sort()
        log.info(f"【策略4】 🔴 【大A走弱期】使用过滤后全球/海外ETF池，共{len(g.s4_merged_etf_pool)}只")
    else:
        log.info(f"【策略4】 🟢 【大A正常期】使用合并池，共{len(g.s4_merged_etf_pool)}只")
    log.info("【策略4】 【动量计算】计算ETF动量得分与排序...")
    s4_calculate_and_log_ranked_etfs(context)
    log.info("【策略4】 ⏸️ 【午盘流水线】执行完毕！")
def s4_sell_routine(context):
    log.info("【策略4】 " + ("★" * 80))
    log.info("【策略4】 ▶️ 【卖出流水线】启动...")
    s4_execute_sell_trades(context)
    log.info("【策略4】 ⏸️ 【卖出流水线】执行完毕！")
def s4_buy_routine(context):
    log.info("【策略4】 " + ("★" * 80))
    log.info("【策略4】 ▶️ 【买入流水线】启动...")
    s4_execute_buy_trades(context)
    log.info("【策略4】 ⏸️ 【买入流水线】执行完毕！")

def s4_reset_daily_flags(context):
    g.s4_cache_date = None
    g.s4_yesterday_close_cache = {}
    log.info("【策略4】 🔄 收盘缓存重置完成")


def s4_check_positions(context):
    current_data = get_current_data()
    positions = get_portfolio_positions(context,pindex=3)
    for security in positions:
        position = positions[security]
        if position.total_amount > 0:
            security_name = s4_get_security_name(security)
            log.info(f"【策略4】 📊 【持仓检查】{security} {security_name}, 数量: {position.total_amount}, 成本: {position.avg_cost:.3f}, 当前价: {position.price:.3f}")
            if current_data[security].paused:
                log.info(f"【策略4】 ⚠️ {security} {security_name} 今日停牌")


def s4_monitor_drawdown(context):
    try:
        portfolio = get_portfolio(context,pindex=3)
        current_value = portfolio.total_value
        if current_value > g.s4_max_portfolio_value:
            g.s4_max_portfolio_value = current_value
        if g.s4_max_portfolio_value > 0:
            current_drawdown = (g.s4_max_portfolio_value - current_value) / g.s4_max_portfolio_value
            if current_drawdown >= g.s4_drawdown_threshold:
                record = {
                    'date': context.current_dt.strftime('%Y-%m-%d'),
                    'drawdown': current_drawdown,
                    'portfolio_value': current_value,
                    'max_value': g.s4_max_portfolio_value,
                    'is_weak': g.s4_is_a_share_weak
                }
                positions_info = []
                positions = get_portfolio_positions(context,pindex=3)
                for security in positions:
                    position = positions[security]
                    if position.total_amount > 0:
                        security_name = s4_get_security_name(security)
                        positions_info.append(f"{security_name}:{position.total_amount}股")
                record['positions'] = positions_info
                g.s4_drawdown_records.append(record)
                log.info(f"【策略4】 【回撤预警】回撤达到 {current_drawdown:.2%} (阈值: {g.s4_drawdown_threshold:.0%})")
                log.info(f"【策略4】   当前净值: {current_value:,.0f}  |  最高净值: {g.s4_max_portfolio_value:,.0f}")
                log.info(f"【策略4】   大A状态: {'走弱期' if g.s4_is_a_share_weak else '正常期'}")
                log.info(f"【策略4】   持仓: {', '.join(positions_info) if positions_info else '空仓'}")
    except Exception as e:
        log.error(f"【回撤监控】计算异常: {e}")


def s4_calculate_global_etf_threshold(context):
    log.info("【策略4】 【全局阈值更新】开始计算全市场ETF流动性门槛")
    try:
        df_etf = get_all_securities(['etf'], date=context.previous_date)
        etf_list = df_etf.index.tolist()
        if not etf_list:
            log.warning("未找到任何场内ETF，使用保守阈值1000万")
            g.s4_avg_etf_money_threshold = 10000000
            return
        log.info(f"【策略4】 全市场ETF总数: {len(etf_list)}只")
        trade_days = get_trade_days(end_date=context.previous_date, count=3)
        start_day = trade_days[0]
        df = get_price(security=etf_list, start_date=start_day, end_date=context.previous_date, frequency='daily', fields=['money'], panel=False, skip_paused=True)
        if df is None or df.empty:
            log.warning("无法获取历史成交额数据，使用保守阈值1000万")
            g.s4_avg_etf_money_threshold = 10000000
            return
        daily_totals = df.groupby('time')['money'].sum()
        daily_counts = df[df['money'] > 0].groupby('time')['code'].nunique()
        for day, money in daily_totals.items():
            count = daily_counts.get(day, 0)
            log.info(f"【策略4】   {day.date()} 全市场ETF总成交额: {money/1e8:.2f}亿元 ({count}只ETF有成交)")
        if len(daily_totals) < 3:
            log.warning(f"仅有{len(daily_totals)}个有效交易日，使用保守阈值1000万")
            g.s4_avg_etf_money_threshold = 10000000
            return
        avg_total_money = daily_totals.mean()
        threshold = avg_total_money / g.s4_global_threshold_divisor
        g.s4_avg_etf_money_threshold = threshold
        log.info(f"【策略4】 【全局阈值更新完成】近{len(daily_totals)}日全市场ETF日均总成交额={avg_total_money/1e8:.2f}亿元，阈值={threshold/1e4:.0f}万元({threshold:,.0f}元)")
    except Exception as e:
        log.warning(f"计算全局阈值异常: {e}，使用保守阈值1000万")
        g.s4_avg_etf_money_threshold = 10000000


def s4_filter_global_pool_by_volume(context):
    log.info("【策略4】 【全球池过滤】开始执行")
    if getattr(g, 's4_avg_etf_money_threshold', None) is None:
        log.info("【策略4】 【全球池过滤】阈值未初始化，立即计算")
        s4_calculate_global_etf_threshold(context)
    if not g.s4_global_etf_pool:
        log.info("【策略4】 【全球池过滤】全球池为空，跳过过滤")
        g.s4_filtered_global_pool = []
        return
    dynamic_threshold = g.s4_avg_etf_money_threshold
    log.info(f"【策略4】 【全球池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    try:
        price_data = get_price(g.s4_global_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
        if price_data is None or price_data.empty:
            log.warning("【全球池过滤】无法获取成交额数据，使用原始全球池")
            g.s4_filtered_global_pool = g.s4_global_etf_pool[:]
            return
        total_money = price_data.groupby('code')['money'].sum()
        avg_daily_money = total_money / TRADE_DAYS_COUNT
        qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
        new_global_pool = qualified.index.tolist()
        removed = set(g.s4_global_etf_pool) - set(new_global_pool)
        if removed:
            removed_info = []
            for code in removed:
                try:
                    name = getattr(g, 's4_etf_names_dict', {}).get(code, str(code))
                    money = avg_daily_money.get(code, 0)
                    removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                except:
                    removed_info.append(code)
            log.info(f"【策略4】 【全球池过滤】剔除低流动性ETF({len(removed)}只)")
        g.s4_filtered_global_pool = new_global_pool
        sorted_qualified = qualified.sort_values(ascending=False)
        log.info(f"【策略4】 【全球池过滤】保留高流动性ETF({len(new_global_pool)}只)")
    except Exception as e:
        log.warning(f"【全球池过滤】异常: {e}")
        g.s4_filtered_global_pool = g.s4_global_etf_pool[:]


def s4_update_sector_pool(context):
    log.info("【策略4】 【动态池更新】开始执行")
    if g.s4_avg_etf_money_threshold is None:
        log.info("【策略4】 【动态池更新】阈值未初始化，立即计算")
        s4_calculate_global_etf_threshold(context)
    
    FUND_COMPANIES = sorted(list(set([
        '易方达', '广发', '华夏', '华安', '嘉实', '富国', '招商', '鹏华', '南方', '汇添富', '国泰', '平安',
        '银华', '天弘', '建信', '工银', '华泰柏瑞', '博时', '景顺长城', '景顺', '华宝', '申万菱信', '万家', '中欧',
        '兴证全球', '浙商', '诺安', '前海开源', '泰康', '泰达宏利', '农银汇理', '交银', '东方红', '财通', '华商',
        '国联', '永赢', '金鹰', '德邦', '创金合信', '西部利得', '圆信永丰', '泓德', '汇安', '诺德', '恒生前海',
        '华润元大', '大成', '海富通', '摩根', '华泰', '中信', '中银', '兴全', '国信', '长城', '中金', '浙商证券',
        '东海', '东吴', '浦银安盛', '信达澳亚', '中加', '中航', '中融', '中邮', '中庚', '中信保诚', '中信建投',
        '中银国际', '中银证券', '九泰', '交银施罗德', '光大保德信', '兴银', '农银', '国投瑞银', '国海富兰克林',
        '国联安', '国金', '太平', '方正富邦', '民生加银', '汇丰晋信', '银河', '长信', '长安', '长盛', '长江证券', '鹏扬'
    ])), key=len, reverse=True)
    
    NOISE_WORDS = sorted(list(set([
        '6666', '8888', '9999', 'A类', 'AH', 'B', 'BS', 'C', 'C类', 'CS', 'DB', 'E', 'E类',
        'ETF', 'ETF基金', 'ETF联接', 'FG', 'G60', 'GF', 'GT', 'HGS', 'LOF', 'LOF基金', 'LOF联接',
        'SG', 'SZ', 'TF', 'TK', 'WJ', 'YH', 'ZS', 'ZZ', '板块', '策略', '产业', '场内', '场外', '低波',
        '基本面', '基金', '精选', '联接', '联接基金', '量化', '龙头', '民企', '民营', '国企', '央企', '智能',
        '全指', '上市开放式', '指基', '指增', '指数', '指数A', '指数C', '指数ETF', '指数基金', '主题', '增强',
        '上海', '黄', '30', '50', '100', '300', '500', '1000', '2000', '大', '新', '四川', '浙江', '湖北',
    ])), key=len, reverse=True)
    
    SPECIAL_GROUPS = sorted([
        {'name': '香港组', 'keywords': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS科技'], key=len, reverse=True),
         'remove_words': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS'], key=len, reverse=True)},
        {'name': '科创组', 'keywords': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创'], key=len, reverse=True),
         'remove_words': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创', '债券', '债汇', '债指', '债沪', '债易', '债基', '债兴', '债摩', '债', 'AAA'], key=len, reverse=True)},
        {'name': '创业组', 'keywords': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True),
         'remove_words': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True)},
        {'name': '美指组', 'keywords': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True),
         'remove_words': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True)}
    ], key=lambda x: max(len(kw) for kw in x['keywords']), reverse=True)
    
    exclude_keywords = sorted(list(set([
        '300', '500', '1000', '2000', '800', '30', '50', '100', '180', '200',
        '沪深', '中证', '上证', '深证', '深成', 'A50', 'A100', 'A500', '深100',
        '短融', '可转债', '转债', '双债', '利率债', '国债', '地债', '政金债', '国开债', '基准国债', '新综债',
        '信用债', '企业债', '公司债', '城投债', '城投', '美元债', '沪公司债', '科创债', '科债', '科创AAA',
        '自由现金流', '现金流', '现金流E', '现金流基', '现金流TF', '现金流全', '300现金流', '800现金流',
        '货币', '现金', '快线', '快钱', '中银现金', '500现金', '800现金', '现金800', '现金自由', '现金指数',
        '全指现金', '现金全指', 'ESG', 'MSCI', 'MS', '债',
    ])), key=len, reverse=True)
    
    try:
        df_etf = get_all_securities(['etf'], date=context.previous_date)
        etf_list = df_etf.index.tolist()
        g.s4_etf_names_dict = df_etf['display_name'].to_dict()
    except Exception as e:
        log.warning(f"获取全市场ETF列表失败: {e}")
        return
    
    log.info(f"【策略4】 【动态池更新】全市场ETF总数: {len(etf_list)}只")
    normal_etfs = []
    special_etfs = []
    special_group_map = {}
    excluded_count = 0
    
    for code in etf_list:
        try:
            name = g.s4_etf_names_dict.get(code, str(code))
            is_special = False
            matched_group = None
            for group in SPECIAL_GROUPS:
                for kw in group['keywords']:
                    if kw in name:
                        is_special = True
                        matched_group = group['name']
                        break
                if is_special:
                    break
            is_excluded = False
            for k in exclude_keywords:
                if k in name:
                    is_excluded = True
                    excluded_count += 1
                    break
            if not is_excluded:
                if is_special:
                    special_etfs.append(code)
                    special_group_map[code] = matched_group
                else:
                    normal_etfs.append(code)
        except Exception:
            continue
    
    group_counts = {}
    for code in special_etfs:
        group_name = special_group_map.get(code, '未知')
        group_counts[group_name] = group_counts.get(group_name, 0) + 1
    log.info(f"【策略4】 【动态池更新】特别组分布: {group_counts}")
    log.info(f"【策略4】 【动态池更新】进入特别组: {len(special_etfs)}只")
    log.info(f"【策略4】 【动态池更新】进入普通组: {len(normal_etfs)}只")
    log.info(f"【策略4】 【动态池更新】排除ETF: {excluded_count}只")
    
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    dynamic_threshold = g.s4_avg_etf_money_threshold
    
    def filter_by_liquidity(etf_codes, group_name):
        if not etf_codes:
            return pd.Series(dtype=float), 0
        try:
            price_data = get_price(etf_codes, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
            if price_data is None or price_data.empty:
                return pd.Series(dtype=float), len(etf_codes)
            total_money = price_data.groupby('code')['money'].sum()
            avg_daily_money = total_money / TRADE_DAYS_COUNT
            qualified_series = avg_daily_money[avg_daily_money > dynamic_threshold].sort_values(ascending=False)
            filtered_out = len(etf_codes) - len(qualified_series)
            return qualified_series, filtered_out
        except Exception:
            return pd.Series(dtype=float), len(etf_codes)
    
    normal_qualified, normal_filtered_out = filter_by_liquidity(normal_etfs, "普通组")
    special_qualified, special_filtered_out = filter_by_liquidity(special_etfs, "特别组")
    normal_sorted = normal_qualified.index.tolist()
    special_sorted = special_qualified.index.tolist()
    log.info(f"【策略4】 【动态池更新】特别组流动性过滤: {len(special_etfs)}→{len(special_sorted)}只")    
    log.info(f"【策略4】 【动态池更新】普通组流动性过滤: {len(normal_etfs)}→{len(normal_sorted)}只")
    
    if not normal_sorted and not special_sorted:
        log.warning("【动态池更新】无ETF通过流动性过滤")
        g.s4_dynamic_etf_pool = []
        return
    
    def get_remove_words_for_etf(_, is_special, matched_group_name):
        if not is_special:
            return []
        for group in SPECIAL_GROUPS:
            if group['name'] == matched_group_name:
                return group['remove_words']
        return []
    
    def clean_name(original_name, is_special=False, matched_group_name=None):
        cleaned = original_name
        for company in FUND_COMPANIES:
            cleaned = cleaned.replace(company, '')
        if is_special and matched_group_name:
            for word in get_remove_words_for_etf(original_name, is_special, matched_group_name):
                cleaned = cleaned.replace(word, '')
        for noise in NOISE_WORDS:
            cleaned = cleaned.replace(noise, '')
        return cleaned.strip()
    
    normal_industry_groups = {}
    for code in normal_sorted:
        try:
            original_name = g.s4_etf_names_dict.get(code, str(code))
            money = normal_qualified[code]
            cleaned = clean_name(original_name, is_special=False)
            if cleaned == '':
                continue
            industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
            if industry_key not in normal_industry_groups:
                normal_industry_groups[industry_key] = []
            normal_industry_groups[industry_key].append({
                'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                'money': money, 'group_type': '普通'
            })
        except Exception:
            continue
    
    special_industry_groups = {}
    for code in special_sorted:
        try:
            original_name = g.s4_etf_names_dict.get(code, str(code))
            matched_group = special_group_map.get(code, '未知')
            money = special_qualified[code]
            cleaned = clean_name(original_name, is_special=True, matched_group_name=matched_group)
            if cleaned == '':
                continue
            industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
            group_key = f"{matched_group}_{industry_key}"
            if group_key not in special_industry_groups:
                special_industry_groups[group_key] = []
            special_industry_groups[group_key].append({
                'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                'money': money, 'group_type': matched_group, 'display_group': matched_group
            })
        except Exception:
            continue
    
    final_pool_info = []
    for industry_key, items in normal_industry_groups.items():
        sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
        final_pool_info.append(sorted_items[0])
    for group_key, items in special_industry_groups.items():
        sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
        final_pool_info.append(sorted_items[0])
    
    final_pool_info_sorted = sorted(final_pool_info, key=lambda x: x['money'], reverse=True)
    top_300 = final_pool_info_sorted[:300]
    g.s4_dynamic_etf_pool = [item['code'] for item in top_300]
    log.info(f"【策略4】 【动态池更新完成】动态池共{len(g.s4_dynamic_etf_pool)}只ETF")
    if len(g.s4_dynamic_etf_pool) <= 10:
        for item in top_300[:10]:
            log.info(f"【策略4】   {item['code']} {item['original_name']} 日均成交额: {item['money']/1e8:.2f}亿")


def s4_filter_fixed_pool_by_volume(context):
    log.info("【策略4】 【固定池过滤】开始执行")
    if getattr(g, 's4_avg_etf_money_threshold', None) is None:
        log.info("【策略4】 【固定池过滤】阈值未初始化，立即计算")
        s4_calculate_global_etf_threshold(context)
    if not g.s4_fixed_etf_pool:
        log.info("【策略4】 【固定池过滤】固定池为空，跳过过滤")
        return
    dynamic_threshold = g.s4_avg_etf_money_threshold
    log.info(f"【策略4】 【固定池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    try:
        price_data = get_price(g.s4_fixed_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
        if price_data is None or price_data.empty:
            log.warning("【固定池过滤】无法获取成交额数据，跳过过滤")
            g.s4_filtered_fixed_pool = g.s4_fixed_etf_pool[:]
            return
        total_money = price_data.groupby('code')['money'].sum()
        avg_daily_money = total_money / TRADE_DAYS_COUNT
        qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
        new_fixed_pool = qualified.index.tolist()
        removed = set(g.s4_fixed_etf_pool) - set(new_fixed_pool)
        if removed:
            removed_info = []
            for code in removed:
                try:
                    name = getattr(g, 's4_etf_names_dict', {}).get(code, str(code))
                    money = avg_daily_money.get(code, 0)
                    removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                except:
                    removed_info.append(code)
            log.info(f"【策略4】 【固定池过滤】剔除低流动性ETF({len(removed)}只)")
        g.s4_filtered_fixed_pool = new_fixed_pool
        sorted_qualified = qualified.sort_values(ascending=False)
        log.info(f"【策略4】 【固定池过滤】保留高流动性ETF({len(new_fixed_pool)}只)")
    except Exception as e:
        log.warning(f"【固定池过滤】异常: {e}")
        g.s4_filtered_fixed_pool = g.s4_fixed_etf_pool[:]


def s4_daily_merge_etf_pools(context):
    if not hasattr(g, 's4_filtered_fixed_pool'):
        g.s4_filtered_fixed_pool = g.s4_fixed_etf_pool[:]
    merged = list(set(g.s4_filtered_fixed_pool + g.s4_dynamic_etf_pool))
    merged.sort()
    log.info("【策略4】 【合并ETF池】开始执行")
    log.info(f"【策略4】 【合并池统计】固定池: {len(g.s4_filtered_fixed_pool)}只, 动态池: {len(g.s4_dynamic_etf_pool)}只, 合并后: {len(merged)}只")
    g.s4_merged_etf_pool = merged


def s4_calculate_and_log_ranked_etfs(context):
    if not hasattr(g, 's4_merged_etf_pool') or not g.s4_merged_etf_pool:
        log.warning("【动量计算】合并池为空，无法计算")
        g.s4_ranked_etfs_result = []
        return
    final_list = s4_get_final_ranked_etfs(context)
    g.s4_ranked_etfs_result = final_list


def s4_calculate_momentum_score(price_series, lookback_days):
    if len(price_series) < lookback_days + 1:
        return None, None, None
    recent_price_series = price_series[-(lookback_days + 1):]
    y = np.log(recent_price_series)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    W = weights ** 2
    W_sum = np.sum(W)
    x_bar = np.sum(W * x) / W_sum
    y_bar = np.sum(W * y) / W_sum
    dx = x - x_bar
    dy = y - y_bar
    variance_x = np.sum(W * dx**2)
    if variance_x == 0:
        return 0, 0, 0
    slope = np.sum(W * dx * dy) / variance_x
    intercept = y_bar - slope * x_bar
    annualized_returns = math.exp(slope * 250) - 1
    y_pred = slope * x + intercept
    ss_res = np.sum(weights * (y - y_pred) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2) 
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0
    momentum_score = annualized_returns * r_squared
    return momentum_score, annualized_returns, r_squared


def s4_calculate_all_metrics_for_etf(etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context):
    try:
        price_series = np.append(hist_closes, current_price)
        if len(price_series) < g.s4_lookback_days * 0.8:
            return None
        momentum_score, annualized_returns, r_squared = s4_calculate_momentum_score(price_series, g.s4_lookback_days)
        if momentum_score is None:
            return None
        passed_momentum = (g.s4_min_score_threshold <= momentum_score <= g.s4_max_score_threshold)
        volume_ratio = s4_get_volume_ratio(hist_volumes, today_vol, context, g.s4_volume_lookback)
        
        passed_loss_filter = True
        day_ratios = []
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            day_ratios = [day1, day2, day3]
            if min(day_ratios) < g.s4_loss:
                passed_loss_filter = False
        
        passed_r2 = r_squared > g.s4_r2_threshold
        
        passed_ma = True
        ma_value = None
        if len(price_series) >= g.s4_ma_lookback:
            ma_value = np.mean(price_series[-g.s4_ma_lookback:])
            passed_ma = current_price > ma_value * g.s4_ma_threshold
        else:
            passed_ma = False
        
        return {
            'etf': etf,
            'etf_name': etf_name,
            'momentum_score': momentum_score,
            'annualized_returns': annualized_returns,
            'r_squared': r_squared,
            'current_price': current_price,
            'volume_ratio': volume_ratio,
            'day_ratios': day_ratios,
            'passed_momentum': passed_momentum,
            'passed_r2': passed_r2,
            'passed_ma': passed_ma,
            'passed_volume': volume_ratio is not None and volume_ratio < g.s4_volume_threshold,
            'passed_loss': passed_loss_filter,
            'ma_value': ma_value,
        }
    except Exception as e:
        log.debug(f"【指标计算】{etf} {etf_name} 计算失败: {e}")
        return None


def s4_get_volume_ratio(hist_volumes, today_vol, context, lookback_days=None):
    if lookback_days is None:
        lookback_days = g.s4_volume_lookback
    try:
        if hist_volumes is None or len(hist_volumes) < lookback_days:
            return None
        past_n_days_vol = hist_volumes[-lookback_days:]
        if np.any(np.isnan(past_n_days_vol)) or np.any(past_n_days_vol == 0):
            return None
        avg_volume = np.mean(past_n_days_vol)
        if avg_volume == 0:
            return None
        now = context.current_dt
        elapsed_minutes = (now.hour - 9) * 60 + now.minute - 30
        if now.hour >= 13:
            elapsed_minutes -= 90
        elapsed_minutes = max(1, min(elapsed_minutes, 240))
        projected_today_vol = today_vol * (240.0 / elapsed_minutes)
        return projected_today_vol / avg_volume if avg_volume > 0 else 0
    except Exception:
        return None


def s4_check_a_share_weak_period(context):
    today = context.current_dt.date()
    indexes = {
        '大盘': '000300.XSHG',
        '小盘': '399101.XSHE',
        '创业板': '399006.XSHE',
        '中证A500': '000510.XSHG'
    }
    
    above_count = 0
    below_count = 0
    for name, code in indexes.items():
        df = attribute_history(code, g.s4_weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
        if df is None or len(df) < g.s4_weak_period_ma_lookback:
            log.warning(f"📊 【走弱期判断】{name}({code})数据不足，跳过该指数")
            continue
        current_price = df['close'][-1]
        ma_val = df['close'][-g.s4_weak_period_ma_lookback:].mean()
        is_above = current_price > ma_val
        is_below = current_price < ma_val
        if is_above:
            above_count += 1
        if is_below:
            below_count += 1
        status_emoji = "⬆️站上" if is_above else ("⬇️低于" if is_below else "➡️持平")
        log.info(f"【策略4】 📊 【走弱期判断】{name}({code}): 收盘{current_price:.2f} / MA{g.s4_weak_period_ma_lookback} {ma_val:.2f} → {status_emoji}")
    
    weak_condition_met = (below_count >= 3)
    exit_condition_met = (above_count >= 3)
    log.info(f"【策略4】 📊 【走弱期判断】低于MA{g.s4_weak_period_ma_lookback}: {below_count}/4, 站上MA{g.s4_weak_period_ma_lookback}: {above_count}/4")
    
    if g.s4_is_a_share_weak and g.s4_weak_start_date is not None:
        g.s4_weak_days_count = len(get_trade_days(start_date=g.s4_weak_start_date, end_date=today))
    else:
        g.s4_weak_days_count = 0
    max_days_exceeded = (g.s4_weak_days_count >= g.s4_max_weak_days)
    
    if g.s4_is_a_share_weak:
        if max_days_exceeded:
            log.info(f"【策略4】 🔔 【走弱期退出】已达到最大持续天数{g.s4_max_weak_days}个交易日，强制退出")
            g.s4_is_a_share_weak = False
            g.s4_weak_start_date = None
            g.s4_weak_days_count = 0
        elif exit_condition_met:
            log.info(f"【策略4】 🟢 【走弱期退出】满足退出条件，退出走弱期")
            g.s4_is_a_share_weak = False
            g.s4_weak_start_date = None
            g.s4_weak_days_count = 0
        elif weak_condition_met:
            old_start = g.s4_weak_start_date
            g.s4_weak_start_date = today
            g.s4_weak_days_count = 0
            log.info(f"【策略4】 🟡 【走弱期延续】再次触发进入条件，重置计数器")
        else:
            log.info(f"【策略4】 🔴 【走弱期中】已持续{g.s4_weak_days_count}/{g.s4_max_weak_days}个交易日")
    else:
        if weak_condition_met:
            log.info(f"【策略4】 🔴 【走弱期进入】触发进入条件，进入大A走弱期")
            g.s4_is_a_share_weak = True
            g.s4_weak_start_date = today
            g.s4_weak_days_count = 0
        else:
            log.info(f"【策略4】 🟢 【正常期中】未满足进入条件")
    
    status_emoji = "🔴" if g.s4_is_a_share_weak else "🟢"
    status_str = f"{status_emoji} 最终状态: 走弱期={g.s4_is_a_share_weak}"
    if g.s4_is_a_share_weak:
        status_str += f" (已持续{g.s4_weak_days_count}/{g.s4_max_weak_days}个交易日)"
    
    log.info(f"【策略4】 📊 【走弱期判断】{status_str}")
    return g.s4_is_a_share_weak
    
    
def s4_apply_filters(metrics_list):
    steps = [
        ('动量得分', lambda m: m['passed_momentum'], True),
        ('R²', lambda m: m['passed_r2'], g.s4_enable_r2_filter and not g.s4_is_a_share_weak),
        ('均线', lambda m: m['passed_ma'], g.s4_enable_ma_filter and g.s4_is_a_share_weak),
        ('成交量', lambda m: m['passed_volume'], g.s4_enable_volume_check),
        ('短期风控', lambda m: m['passed_loss'], g.s4_enable_loss_filter),
    ]
    filtered = metrics_list[:]
    for name, condition, is_enabled in steps:
        if is_enabled:
            filtered = [m for m in filtered if condition(m)]
    return filtered


def s4_get_final_ranked_etfs(context):
    all_metrics = []
    etf_set = list(g.s4_merged_etf_pool)
    end_date = context.previous_date
    log.info(f"【策略4】 【动量得分计算】使用合并池，合计{len(etf_set)}只ETF")
    log.info(f"【策略4】 【当前状态】{'🔴 大A走弱期' if g.s4_is_a_share_weak else '🟢 大A正常期'}")
    lookback = max(g.s4_lookback_days, g.s4_volume_lookback, g.s4_ma_lookback) + 20
    today = context.current_dt.date()
    current_data = get_current_data()
    safe_lookback = lookback + 20
    hist_df = get_price(etf_set, count=safe_lookback, end_date=end_date, frequency='1d', fields=['close', 'volume'], panel=False)
    today_vol_df = get_price(etf_set, start_date=today, end_date=context.current_dt, frequency='1m', fields=['volume'], panel=False, fill_paused=False)
    if hist_df is None or hist_df.empty:
        log.warning("【动量计算】无法获取历史价格数据")
        return []
    today_vols = today_vol_df.groupby('code')['volume'].sum() if (today_vol_df is not None and not today_vol_df.empty) else pd.Series(dtype=float)
    close_pivot = hist_df.pivot(index='time', columns='code', values='close')
    volume_pivot = hist_df.pivot(index='time', columns='code', values='volume')
    # ========== 遍历ETF计算动量得分 ==========
    for etf in etf_set:
        if current_data[etf].paused:
            continue
        if s4_is_temporarily_suspended(etf, context):
            log.debug(f"{etf} {s4_get_security_name(etf)} 盘中临时停牌，跳过计算")
            continue
        if etf not in close_pivot.columns:
            continue
        if not is_red_line(context,etf):
            continue
        raw_closes = close_pivot[etf].values
        raw_volumes = volume_pivot[etf].values
        valid_mask = (~np.isnan(raw_volumes)) & (raw_volumes > 0)
        hist_closes = raw_closes[valid_mask]
        hist_volumes = raw_volumes[valid_mask]
        hist_closes = hist_closes[-lookback:]
        hist_volumes = hist_volumes[-lookback:]
        if len(hist_closes) < g.s4_lookback_days:
            continue
        etf_name = s4_get_security_name(etf)
        current_price = current_data[etf].last_price
        today_vol = today_vols.get(etf, 0)
        metrics = s4_calculate_all_metrics_for_etf(etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context)
        if metrics:
            if metrics['etf'] in {m['etf'] for m in all_metrics}:
                continue
            all_metrics.append(metrics)
    for item in all_metrics:
        score = item.get('momentum_score')
        if pd.isna(score) or (isinstance(score, float) and np.isnan(score)):
            item['momentum_score'] = float('-inf')
    # 按动量得分排序
    all_metrics.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
    # ========== 第一步：输出所有ETF排序表格 ==========
    log_buffer = []
    log_buffer.append("")
    log_buffer.append(">>> 第一步：所有ETF按动量得分从大到小排序 <<<")
    for m in all_metrics[:100]:
        def fmt_status(value_str, passed):
            return f"{value_str} {'✅' if passed else '❌'}"
        score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
        r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
        vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
        min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
        loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
        ma_str = f"MA{g.s4_ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
        line = (
            f"{m['etf']} {m['etf_name']}: "
            f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
            f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
            f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
            f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
            f"短期风控: {fmt_status(loss_val, m['passed_loss'])}"
        )
        log_buffer.append(line)
    # ========== 第二步：应用过滤条件 ==========
    filtered_list = s4_apply_filters(all_metrics)
    filtered_list.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
    top_10 = filtered_list[:10]
    log_buffer.append("")
    log_buffer.append(">>> 第二步：符合全部过滤条件的ETF按动量得分从大到小排序(前10名) <<<")
    if top_10:
        for m in top_10:
            def fmt_status(value_str, passed):
                return f"{value_str} {'✅' if passed else '❌'}"
            score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
            r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
            vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
            min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
            loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
            ma_str = f"MA{g.s4_ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
            line = (
                f"{m['etf']} {m['etf_name']}: "
                f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
                f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
                f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
                f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
                f"短期风控: {fmt_status(loss_val, m['passed_loss'])}"
            )
            log_buffer.append(line)
    else:
        log_buffer.append("（无符合条件的ETF）")
        full_log = "\n".join(log_buffer)
        log.info(full_log)
        return []
    # ========== 第三步：确定候选池 ==========
    score_key = 'momentum_score'
    if len(top_10) >= g.s4_holdings_num:
        reference_score = top_10[g.s4_holdings_num - 1].get(score_key, float('-inf'))
        ratio = g.s4_score_threshold_ratio if not g.s4_is_a_share_weak else 1.0
        score_threshold = reference_score * ratio
        log_buffer.append("")
        log_buffer.append(f">>> 第三步：选取动量得分≥第{g.s4_holdings_num}名({top_10[g.s4_holdings_num - 1]['etf_name']})得分{reference_score:.4f}×{g.s4_score_threshold_ratio}={score_threshold:.4f}的ETF <<<")
        candidate_pool = [item for item in top_10 if item.get(score_key, float('-inf')) >= score_threshold]
    else:
        log_buffer.append("")
        log_buffer.append(f">>> 第三步：前10名不足{g.s4_holdings_num}只，全部作为候选池 <<<")
        candidate_pool = top_10[:]
    log_buffer.append(f"【候选池】共{len(candidate_pool)}只ETF（按动量得分排序）：")
    for i, item in enumerate(candidate_pool):
        log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}")
    # ========== 第四步：结合当前持仓进行调整 ==========
    log_buffer.append("")
    log_buffer.append(">>> 第四步：结合当前持仓进行调整 <<<")
    positions = get_portfolio_positions(context,pindex=3)
    current_holdings = [sec for sec, pos in positions.items() if pos.total_amount > 0]
    log_buffer.append(f"当前持仓ETF：{current_holdings}")
    candidate_dict = {item['etf']: item for item in candidate_pool}
    retained = [candidate_dict[etf] for etf in current_holdings if etf in candidate_dict]
    log_buffer.append(f"其中存在于候选池中的持仓ETF：{[item['etf'] for item in retained]}")
    if len(retained) >= g.s4_holdings_num:
        retained_sorted = sorted(retained, key=lambda x: x.get(score_key, float('-inf')), reverse=True)
        final_result = retained_sorted[:g.s4_holdings_num]
        log_buffer.append(f"保留的持仓ETF数量({len(retained)})超过目标持仓数({g.s4_holdings_num})，将从保留的ETF中按动量得分取前{g.s4_holdings_num}只作为最终目标。")
    else:
        need = g.s4_holdings_num - len(retained)
        remaining_pool = [item for item in candidate_pool if item['etf'] not in {r['etf'] for r in retained}]
        additional = remaining_pool[:need]
        final_result = retained + additional
        log_buffer.append(f"保留持仓ETF {len(retained)}只，还需补充{need}只。")
        if retained:
            log_buffer.append("保留的ETF（按原有顺序）：")
            for item in retained:
                log_buffer.append(f"  {item['etf_name']}({item['etf']})")
        if additional:
            log_buffer.append("补充的ETF（按动量得分排序）：")
            for i, item in enumerate(additional):
                log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}")
    log_buffer.append(f"【最终目标】共{len(final_result)}只ETF：")
    for i, item in enumerate(final_result):
        log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']})")
    log_buffer.append("==================================================")
    full_log = "\n".join(log_buffer)
    log.info(full_log)
    return final_result


def s4_execute_sell_trades(context):
    log.info("【策略4】 ========== 卖出操作开始 ==========")
    ranked_etfs = getattr(g, 's4_ranked_etfs_result', [])
    target_etfs = []
    
    if ranked_etfs:
        for metrics in ranked_etfs[:g.s4_holdings_num]:
            target_etfs.append(metrics['etf'])
            log.info(f"【策略4】 确定最终目标: {metrics['etf']} {metrics['etf_name']}")
    else:
        if s4_check_defensive_etf_available(context):
            target_etfs = [g.s4_defensive_etf]
            etf_name = s4_get_security_name(g.s4_defensive_etf)
            log.info(f"【策略4】 🛡️ 确定最终目标(防御模式): {g.s4_defensive_etf} {etf_name}")
        else:
            log.info("【策略4】 💤 无最终目标(空仓模式)")
            target_etfs = []
    
    g.s4_target_etfs_list = target_etfs
    positions = get_portfolio_positions(context,pindex=3)
    current_positions = list(positions.keys())
    target_set = set(target_etfs)
    sell_count = 0
    
    for security in current_positions:
        position = positions[security]
        if position.closeable_amount > 0 and security not in target_set:
            security_name = s4_get_security_name(security)
            success = s4_smart_order_target_value(security, 0, context)
            if success:
                sell_count += 1
                log.info(f"【策略4】 ✅ 已成功卖出: {security} {security_name}")
    
    log.info(f"【策略4】 本次共计划卖出{sell_count}只ETF。")
    log.info("【策略4】 ========== 卖出操作完成 ==========")


def s4_execute_buy_trades(context):
    log.info("【策略4】 ========== 买入操作开始 ==========")
    target_etfs = g.s4_target_etfs_list
    
    if not target_etfs:
        log.info("【策略4】 根据计算的结果，今日无目标ETF，保持空仓")
        log.info("【策略4】 ========== 买入操作完成 ==========")
        return

    positions = get_portfolio_positions(context,pindex=3)
    current_positions = set(positions.keys())
    etfs_to_buy = [etf for etf in target_etfs if etf not in current_positions]
    actual_holding_count = len(current_positions)
    max_buy_count = max(0, g.s4_holdings_num - actual_holding_count)
    num_etfs_to_buy = min(len(etfs_to_buy), max_buy_count)
    
    if num_etfs_to_buy <= 0:
        log.info(f"【策略4】 当前实际持仓数量({actual_holding_count})已达到或超过目标({g.s4_holdings_num})，无需买入")
        log.info("【策略4】 ========== 买入操作完成 ==========")
        return
    
    etfs_to_buy = etfs_to_buy[:num_etfs_to_buy]
    log.info(f"【策略4】 当前实际持仓: {actual_holding_count}只, 目标持仓: {g.s4_holdings_num}只, 本次计划买入: {num_etfs_to_buy}只")
    
    # 修复：动态分配资金，避免可用现金为负
    for i, etf in enumerate(etfs_to_buy):
        portfolio = get_portfolio(context,pindex=3)
        remaining_cash = portfolio.available_cash
        if remaining_cash < g.s4_min_money:
            log.info(f"【策略4】 可用现金 {remaining_cash:.2f} 不足最小交易额 {g.s4_min_money:.2f}，停止买入")
            break
        
        remaining_to_buy = len(etfs_to_buy) - i
        target_value_for_this_etf = remaining_cash // remaining_to_buy
        
        # 最后一笔可使用剩余全部现金，但确保不小于最小交易额
        if target_value_for_this_etf < g.s4_min_money and remaining_cash >= g.s4_min_money:
            target_value_for_this_etf = remaining_cash
        
        log.info(f"【策略4】 为 {etf} 分配目标金额: {target_value_for_this_etf:.2f} 元 (剩余现金 {remaining_cash:.2f}, 待买数量 {remaining_to_buy})")
        success = s4_smart_order_target_value(etf, target_value_for_this_etf, context)
        if success:
            log.info(f"【策略4】 ✅ ETF {etf} 下单成功")
        else:
            log.info(f"【策略4】 ❌ ETF {etf} 下单失败")
    
    log.info("【策略4】 ========== 买入操作完成 ==========")


def s4_is_temporarily_suspended(security, context, minute_count=10):
    return is_temporarily_suspended(security,context)


def s4_smart_order_target_value(security, target_value, context):
    """
    智能下单：根据目标市值调整持仓，处理停牌、涨跌停、最小交易金额、T+1
    """
    data = get_current_data()
    name = s4_get_security_name(security)
    # ========== 1. 全天停牌检测 ==========
    if data[security].paused:
        log.info(f"【策略4】 {security} {name} 全天停牌，跳过交易")
        return False
    # ========== 2. 盘中临时停牌检测 ==========
    if s4_is_temporarily_suspended(security, context):
        log.info(f"【策略4】 {security} {name} 盘中临时停牌，跳过交易")
        return False
    price = data[security].last_price
    if price == 0:
        log.info(f"【策略4】 {security} {name} 当前价格为0，跳过交易")
        return False
    # ========== 3. 买入时使用预估成交价（包含佣金+滑点）计算股数 ==========
    if target_value > 0:
        buy_commission_rate = 0.0001   # 买入佣金
        slippage_rate = BUY_SLIP         # 滑点
        estimated_price = price * (1 + buy_commission_rate + slippage_rate)
        target_amount = int(target_value / estimated_price)
        target_amount = (target_amount // 100) * 100
        if target_amount <= 0:
            target_amount = 100
        # 二次校验：用实时可用现金和当前价格严格限制（兜底）
        portfolio = get_portfolio(context,pindex=3)
        max_shares = int(portfolio.available_cash / price)
        max_shares = (max_shares // 100) * 100
        if max_shares < target_amount:
            target_amount = max_shares
        if target_amount <= 0:
            log.info(f"【策略4】 {security} {name}: 现金不足买100股，跳过")
            return False
    else:
        target_amount = 0
    positions = get_portfolio_positions(context,pindex=3)
    cur_pos = positions.get(security, None)
    cur_amount = cur_pos.total_amount if cur_pos else 0
    diff = target_amount - cur_amount
    slip = BUY_SLIP
    limit_price = price*(1+slip) if diff > 0 else price*(1-slip)
    style = MarketOrderStyle(limit_price)
    # ========== 4. 涨跌停检测（统一：涨停跌停都不交易） ==========
    if data[security].last_price >= data[security].high_limit:
        log.info(f"【策略4】 {security} {name} 当前涨停，跳过交易")
        return False
    if data[security].last_price <= data[security].low_limit:
        log.info(f"【策略4】 {security} {name} 当前跌停，跳过交易")
        return False
    trade_val = abs(diff) * price
    if 0 < trade_val < g.s4_min_money:
        log.info(f"【策略4】 {security} {name} 交易金额{trade_val:.2f} < {g.s4_min_money}，跳过")
        return False
    # ========== 5. T+1检查（仅卖出时） ==========
    if diff < 0:
        closeable = cur_pos.closeable_amount if cur_pos else 0
        if closeable == 0:
            log.info(f"【策略4】 {security} {name} 当天买入不可卖出(T+1)")
            return False
        diff = -min(abs(diff), closeable)
    # ========== 6. 执行下单 ==========
    if diff != 0:
        pindex = 0
        if has_subportfolio(context,3):
            pindex=3
        order_result = order(security, diff, style,pindex=pindex)
        if order_result:
            if diff > 0:
                log.info(f"【策略4】 📥 买入 {security} {name} 数量{abs(diff)} 价格{price:.3f} (预估含成本价: {estimated_price:.3f})")
            else:
                log.info(f"【策略4】 📤 卖出 {security} {name} 数量{abs(diff)} 价格{price:.3f}")
            return True
        else:
            log.warning(f"【策略4】下单失败: {security} {name}，数量{diff}")
            return False
    return False

def s4_take_fix_profit(context):
    take_fix_profit_check(context,FIX_RATE_LIMITS[3],pindex=3)

def s4_minute_level_stop_loss(context):
    if not g.s4_use_fixed_stop_loss:
        return
    current_time = context.current_dt.strftime('%H:%M')
    if not (('09:40' < current_time < '10:29') or ('10:40' < current_time < '11:30') or ('13:00' < current_time < '14:57')):
        return
    current_data = get_current_data()
    positions = get_portfolio_positions(context,pindex=3)
    for security in list(positions.keys()):
        position = positions[security]
        if position.total_amount <= 0 or position.closeable_amount <= 0:
            continue
        current_price = current_data[security].last_price
        if current_price <= 0:
            continue
        cost_price = position.avg_cost
        if cost_price <= 0:
            continue
        if current_price <= cost_price * g.s4_fixedStopLossThreshold:
            security_name = s4_get_security_name(security)
            loss_percent = (current_price / cost_price - 1) * 100
            log.info(f"【策略4】 🚨 【分钟级固定止损】{security} {security_name} 触发止损，亏损: {loss_percent:.2f}%")
            s4_smart_order_target_value(security, 0, context)


def s4_get_security_name(security):
    try:
        if hasattr(g, 's4_etf_names_dict') and security in g.s4_etf_names_dict:
            return g.s4_etf_names_dict[security]
        return get_security_info(security).display_name
    except Exception:
        return "未知名称"


def s4_check_defensive_etf_available(context):
    current_data = get_current_data()
    defensive_etf = g.s4_defensive_etf
    if current_data[defensive_etf].paused:
        log.info(f"【策略4】 防御性ETF {defensive_etf} 今日停牌")
        return False
    if current_data[defensive_etf].last_price >= current_data[defensive_etf].high_limit:
        log.info(f"【策略4】 防御性ETF {defensive_etf} 当前涨停")
        return False
    if current_data[defensive_etf].last_price <= current_data[defensive_etf].low_limit:
        log.info(f"【策略4】 防御性ETF {defensive_etf} 当前跌停")
        return False
    return True

#=========策略4 end=======

#=========策略5 弱转强 start=======

def s5_initialize(context):
    common_initialize(context)
    s5_set_params(context)
    s5_init_industry(context)
    s5_scheduler_task(context)

def s5_set_params(context):
    # 全局参数
    # 初始持仓数，随着可用金额增加
    g.s5_init_pos_num = 2
    # 单个标的最大金额
    g.s5_max_stock_cash = 10 * 10000
    g.s5_stop_loss = -0.03
    g.s5_max_hold_days = 3
    g.s5_max_cap_yi = 300.0
    
    # 状态变量
    g.s5_candidates = []
    g.s5_allow_trade = True
    g.s5_caps = {}
    g.s5_industry_map = {}
    g.s5_industry_ret = {}
    g.s5_industry_med = -999
    # 每日目标标的
    g.s5_targets = []
    # 大的候选池
    g.s5_stock_pool = []
    

def s5_scheduler_task(context):
    run_daily(s5_before_market_open, time='09:05')
    run_daily(s5_after_market_call_auction, time='09:28:10')
    run_daily(s5_market_open_buy, time='09:31')
    run_daily(s5_morning_sell, time='10:29')
    run_daily(s5_intraday_check, time='10:30')
    run_daily(s5_intraday_check, time='13:30')
    run_daily(s5_intraday_check, time='14:30')
    run_daily(s5_eod_sell, time='14:50')
    # run_daily(s5_analyze_daily, time='15:00')

def s5_is_limit_up(close, pre_close, stock):
    if pre_close == 0:
        return False
    if stock.startswith('30') or stock.startswith('688'):
        limit = 0.20
    else:
        limit = 0.10
    return close / pre_close - 1 >= limit - 0.005

def s5_is_red_line_limit_up(open, close, pre_close, stock):
    # 实体涨停，非T涨停，非一字涨停
    limit_up = s5_is_limit_up(close, pre_close, stock)
    if limit_up:
        is_red_line = close > open*1.01
        return is_red_line
    return limit_up

def s5_init_stock_list(context):
    # 中证2000
    filtered = []
    try:
        # 399303.XSHE	国证2000，932000.CSI；399311.XSHE	国证1000
        index_stocks = set(get_index_stocks('932000.CSI'))
        filtered = common_filter_stocks(context,index_stocks)
        g.s5_stock_pool = filtered
    except Exception as e:
        g.csi2000 = set()
        log.info(f"[初始化] 中证2000加载失败：{e}")

def s5_init_industry(context):
    # 行业映射
    try:
        industry_df = get_industries(name='sw_l1')
        for idx in industry_df.index:
            stocks = get_industry_stocks(idx)
            for s in stocks:
                # g.s5_industry_map[s] = idx
                g.s5_industry_map[s] = str(idx) + '.XSHG'
        log.debug(f"【策略5】[初始化] 行业映射数量：{len(g.s5_industry_map)}")
    except Exception as e:
        log.info(f"【策略5】[初始化] 行业映射失败：{e}")

def s5_before_market_open(context):
    log.info("=" * 70)
    log.info(f"【策略5】【盘前选股】当前时间：{context.current_dt}，上一交易日：{context.previous_date}")
    s5_init_stock_list(context)
    # 清空标的池
    g.s5_targets = []

    # ---------- 市场情绪门控 ----------
    g.s5_allow_trade = True
    try:
        idx_df = attribute_history('000001.XSHG', count=3, unit='1d', fields=['close'],
                                   skip_paused=True, df=True, fq='pre')
        log.info(f"【策略5】[门控] 上证指数最近3日收盘：{idx_df['close'].values if idx_df is not None else 'None'}")
        if idx_df is not None and len(idx_df) >= 3:
            idx_close = idx_df['close'].values
            prev_ret = idx_close[-1] / idx_close[-2] - 1
            log.info(f"【策略5】[门控] 昨日上证涨跌幅：{prev_ret:.4f}")
            if prev_ret <= -0.04:
                g.s5_allow_trade = False
        else:
            log.info("【策略5】[门控] 上证指数数据不足3条")
    except Exception as e:
        log.info(f"【策略5】[门控] 获取上证指数异常：{e}")
    log.info(f"【策略5】[门控] allow_trade = {g.s5_allow_trade}")
    
   # ---------- 行业动量（通过 SW1_DAILY_PRICE 表获取） ----------
    g.s5_industry_ret = {}
    try:
        industry_df = get_industries(name='sw_l1')
        end_date = context.previous_date.strftime('%Y-%m-%d')
        start_date = (context.previous_date - timedelta(days=15)).strftime('%Y-%m-%d')
        
        for code in industry_df.index:
            code_str = str(code)   # 如 '801010'
            try:
                q = query(finance.SW1_DAILY_PRICE).filter(
                    finance.SW1_DAILY_PRICE.code == code_str,
                    finance.SW1_DAILY_PRICE.date >= start_date,
                    finance.SW1_DAILY_PRICE.date <= end_date
                ).order_by(finance.SW1_DAILY_PRICE.date.desc()).limit(6)
                
                df = finance.run_query(q)
                if df is not None and len(df) >= 6:
                    closes = df['close'].values[::-1]   # 反转为时间正序
                    ret = closes[-1] / closes[0] - 1
                    g.s5_industry_ret[code_str + '.XSHG'] = ret
            except Exception as e:
                log.info(f"【策略5】[行业] {code_str} 取数失败：{e}")
                continue
    except Exception as e:
        log.info(f"【策略5】[行业] get_industries 失败：{e}")

    if g.s5_industry_ret:
        g.s5_industry_med = np.median(list(g.s5_industry_ret.values()))
    log.info(f"【策略5】[行业] 有效行业数={len(g.s5_industry_ret)}，中位数={g.s5_industry_med:.4f}")
    
    # ---------- 市值数据 ----------
    g.s5_caps = {}
    try:
        q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(g.s5_stock_pool))
        df = get_fundamentals(q, date=context.previous_date)
        for _, row in df.iterrows():
            g.s5_caps[row['code']] = row['market_cap']
    except Exception as e:
        log.info(f"【策略5】[市值] 获取异常：{e}")
    log.info(f"【策略5】[市值] 获取到市值数据的股票数={len(g.s5_caps)}")
    
    # ---------- 选股漏斗 ----------
    candidates = []
    try:
        # history 一次只能取一个字段，分 4 次调用
        df_open = history(5, '1d', 'open', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_close = history(5, '1d', 'close', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_volume = history(5, '1d', 'volume', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_money = history(5, '1d', 'money', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        log.info(f"【策略5】[数据] df_close 形状={None if df_close is None else df_close.shape}")
    except Exception as e:
        log.info(f"【策略5】[数据] history 获取异常：{e}")
        g.s5_candidates = []
        return
    
    if df_close is None or df_close.empty:
        log.info("【策略5】[数据] df_close 为空，选股终止")
        g.s5_candidates = []
        return
    
    # 统计漏斗
    stat = {
        'has_data': 0, 'cond1_red_line_limit_up_t2': 0, 'cond2_not_limit_t1': 0,
        'cond3_drop_ok': 0, 'cond4_money_ok': 0, 'cond5_vol_ok': 0,
        'h1_strong_t2': 0, 'h2_cap_ok': 0, 'cond6_industry_ok': 0,
        'csi2000_ok': 0
    }
    
    for stock in df_close.columns:
        try:
            c_series = df_close[stock].dropna()
            o_series = df_open[stock].dropna()
            v_series = df_volume[stock].dropna()
            m_series = df_money[stock].dropna()
            if len(c_series) < 5 or len(o_series) < 5 or len(v_series) < 5 or len(m_series) < 5:
                continue
            stat['has_data'] += 1
            c = c_series.values[-5:]
            o = o_series.values[-5:]
            v = v_series.values[-5:]
            m = m_series.values[-5:]
            
            c_t1, c_t2, c_t3 ,c_t5= c[-1], c[-2], c[-3], c[-5]
            o_t2 = o[-2]
            m_t1 = m[-1]
            v_t1, v_t2 = v[-1], v[-2]
            
            # 条件1：T-2 实体涨停
            if not s5_is_limit_up(c_t2, c_t3, stock):
                continue
            stat['cond1_red_line_limit_up_t2'] += 1
            
            # 条件2：T-1 未涨停
            if s5_is_limit_up(c_t1, c_t2, stock):
                continue
            stat['cond2_not_limit_t1'] += 1
            
            # 条件3：T-1 跌幅 >= -4%
            if c_t1 / c_t2 - 1 < -0.04:
                continue
            stat['cond3_drop_ok'] += 1

            # 五日涨跌幅小于35%，过滤猛涨的
            # if c_t1 / c_t5 - 1 > 0.35:
            #     continue
            
            # 条件4：T-1 成交额 >= 3亿
            if m_t1 < 300000000:
                continue
            stat['cond4_money_ok'] += 1
            
            # 条件5：T-1 量 / T-2 量 <= 2.5
            if v_t2 == 0 or v_t1 / v_t2 > 2.5:
                continue
            stat['cond5_vol_ok'] += 1
            
            # H1：T-2 开盘涨幅 >= 5%
            open_chg = o_t2 / c_t3 - 1 if c_t3 > 0 else 0
            if open_chg < 0.05:
                continue
            stat['h1_strong_t2'] += 1
            
            # H2：市值 <= 300亿
            cap = g.s5_caps.get(stock, 0)
            if cap == 0 or cap > g.s5_max_cap_yi:
                continue
            stat['h2_cap_ok'] += 1
            
            # 条件6：行业动量
            ind = g.s5_industry_map.get(stock)
            if ind and ind in g.s5_industry_ret:
                if g.s5_industry_ret[ind] < g.s5_industry_med:
                    continue
            stat['cond6_industry_ok'] += 1
            
            # 中证2000
            # if g.csi2000 and stock not in g.csi2000:
            #     continue
            # stat['csi2000_ok'] += 1
            
            candidates.append(stock)
        except Exception as e:
            continue
    
    log.info(f"【策略5】[漏斗统计] {stat}")
    log.info(f"【策略5】[选股] 最终候选数={len(candidates)}，候选={candidates}")
    
    g.s5_candidates = candidates

def s5_after_market_call_auction(context):
    # 集合竞价结束，28分之后可以取数据，仅计算信号
    log.info(f"【策略5】【集合竞价】时间={context.current_dt}，allow_trade={g.s5_allow_trade}，候选数={len(g.s5_candidates)}")
    if not g.s5_allow_trade:
        log.info("【策略5】[买入判断] 市场门控关闭，跳过")
        return
    if not g.s5_candidates:
        log.info("【策略5】[买入判断] 候选为空，跳过")
        return
    
    current_data = get_current_data()
    targets = []
    for stock in g.s5_candidates:
        # ---------- 昨日数据 ----------
        try:
            hist = attribute_history(stock, count=1, unit='1d', fields=['close', 'volume'],
                                        skip_paused=True, df=True, fq='pre')
            if hist is None or hist.empty:
                log.info(f"【策略5】[买入判断] {stock} 昨日数据为空，跳过")
                continue
            prev_close = hist['close'].iloc[-1]
            prev_vol = hist['volume'].iloc[-1]
        except Exception as e:
            log.info(f"【策略5】[买入判断] {stock} 获取昨日数据异常：{e}")
            continue
        
        # ---------- 集合竞价数据（修复字段名） ----------
        a_open = None
        a_vol = 0
        try:
            auction = get_call_auction(
                stock,
                start_date=context.current_dt.strftime('%Y-%m-%d 09:15:00'),
                end_date=context.current_dt.strftime('%Y-%m-%d 09:25:00')
            )
            if auction is not None and not auction.empty:
                # 聚宽该接口价格字段为 current，成交量字段为 volume
                if 'current' in auction.columns:
                    a_open = auction['current'].iloc[-1]
                elif 'price' in auction.columns:
                    a_open = auction['price'].iloc[-1]
                if 'volume' in auction.columns:
                    # volume 为累计成交量，取最后一条即可
                    a_vol = auction['volume'].iloc[-1]
                log.info(f"【策略5】[竞价] {stock} 竞价返回列={list(auction.columns)}，条数={len(auction)}，"
                            f"取到价={a_open}，量={a_vol}")
        except Exception as e:
            log.info(f"【策略5】[买入判断] {stock} 竞价数据异常：{e}")
        
        # 竞价数据缺失时退化
        if a_open is None or a_open == 0 or (isinstance(a_open, float) and np.isnan(a_open)):
            a_open = current_data[stock].day_open
            a_vol = 0
            log.info(f"【策略5】[买入判断] {stock} 竞价数据缺失，退化使用 day_open={a_open}")
        
        if a_open is None or a_open == 0:
            log.info(f"【策略5】[买入判断] {stock} 无法获取开盘价，跳过")
            continue
        
        a_chg = a_open / prev_close - 1
        log.info(f"【策略5】[买入判断] {stock} 竞价价={a_open:.4f} 昨收={prev_close:.4f} 涨幅={a_chg:.4f} "
                    f"竞价量={a_vol} 昨量={prev_vol}")
        
        # ---------- 过滤条件 ----------
        if a_chg < -0.01 or a_chg > 0.06:
            log.info(f"【策略5】[买入判断] {stock} 竞价涨幅 {a_chg:.4f} 不在 [-1%, 6%]，跳过")
            continue
        vol_limit = prev_vol * 0.005
        if a_vol > 0 and a_vol < vol_limit:
            log.info(f"【策略5】[买入判断] {stock} 竞价量不足（{a_vol} < {vol_limit:.0f}），跳过")
            continue

        targets.append(stock)
    g.s5_targets = targets
    log.info(f"【策略5】[集合竞价结束]待买入标的个数{len(targets)},列表:{targets}")
    target_names = {code:get_security_name(code) for code in targets}
    if targets:
        send_message(f"【策略5】待买入弱转强标的：{target_names}")

    
def s5_market_open_buy(context):
    if not g.s5_targets:
        return
    cash = get_portfolio(context,pindex=4).available_cash
    positions = get_portfolio_positions(context,pindex=4)
    n_pos = len([s for s in positions if positions[s].total_amount > 0])
    targets_len = len(g.s5_targets)
    # ---------- 仓位与下单 ----------
    can_buy_pos_num = max(cash // g.s5_max_stock_cash + n_pos,g.s5_init_pos_num)
    remaining_pos = int(min(max(can_buy_pos_num - n_pos,0),targets_len))
    target_value = cash / (remaining_pos) if remaining_pos > 0 else 0
    target_value = min(target_value, g.s5_max_stock_cash)
    log.info(f"[买入] 当前持仓数={n_pos}，可用现金={cash}，总共可买数={can_buy_pos_num}, 剩余可买数={remaining_pos}, 单标的金额={target_value:.2f} {g.s5_targets}")
    buy_targets = g.s5_targets[:remaining_pos] if remaining_pos > 0 else []
    ignore_buy_targets = g.s5_targets[remaining_pos:] if remaining_pos < len(g.s5_targets) else []
    for stock in buy_targets:
        safe_order_target_value(context,'buy',stock,target_value,pindex=4)
        

def s5_morning_sell(context):
    log.info("-" * 70)
    log.info(f"【10:00 未涨停冲高出】时间={context.current_dt}")
    positions = get_portfolio_positions(context,pindex=4)
    log.info(f"[10:00] 当前持仓：{list(positions.keys())}")
    for stock in list(positions.keys()):
        if can_not_deal(stock,''):
            continue
        safe_order_target_value(context,'sell',stock,0,pindex=4)

def s5_intraday_check(context):
    log.info("-" * 70)
    log.info(f"【盘中检查】时间={context.current_dt}")
    positions = get_portfolio_positions(context,pindex=4)
    current_data = get_current_data()
    for stock in list(positions.keys()):
        pos = positions[stock]
        if pos.closeable_amount == 0:
            continue
        cur_price = current_data[stock].last_price
        high_limit = current_data[stock].high_limit
        if cur_price >= high_limit * 0.999:
            log.info(f"[盘中] {stock} 涨停封死，继续持有")
            continue
        if pos.price > 0 and (cur_price / pos.price - 1) <= g.s5_stop_loss:
            safe_order_target_value(context,'sell',stock,0,pindex=4)
        else:
            log.info(f"[盘中] {stock} 现价={cur_price} 成本={pos.price} 收益率={(cur_price/pos.price-1):.4f}")

def s5_eod_sell(context):
    log.info("-" * 70)
    log.info(f"【14:50 收盘前兜底】时间={context.current_dt}")
    positions = get_portfolio_positions(context,pindex=4)
    current_data = get_current_data()
    for stock in list(positions.keys()):
        cur_price = current_data[stock].last_price
        high_limit = current_data[stock].high_limit
        is_in_gaps_day = is_buy_in_gaps_day(context,stock,g.s5_max_hold_days,pindex=4)
        if cur_price >= high_limit * 0.999 and is_in_gaps_day:
            log.info(f"[14:50] {stock} 涨停且未超期，继续持有")
            continue
        if can_not_deal(stock,'sell'):
            continue
        safe_order_target_value(context,'sell',stock,0,pindex=4)
# ==========策略5 弱转强 end==========

# ==========策略6 红利增强 start======

def s6_set_params(context):
    # ---------- 全局参数 ----------
    g.s6_trade_symbol = '512040.XSHG'   # 目标ETF（价值国富ETF）
    g.s6_money_symbol = '511260.XSHG'   # 空仓替代ETF（国债ETF，对应掘金511260）
    g.s6_cci_period = 14
    g.s6_rsi_period = 14
    g.s6_bb_period = 20
    g.s6_bb_std = 2
    g.s6_cci_buy_threshold = -180
    g.s6_rsi_sell_threshold = 74
    g.s6_data_count = 120

    # ---------- 当日信号缓存 ----------
    g.s6_signal = None          # 'SELL_TRADE_BUY_MONEY' / 'SELL_MONEY_BUY_TRADE'
                                # 'BUY_TRADE' / 'BUY_MONEY' / 'HOLD_TRADE' / 'HOLD_MONEY'
    g.s6_today_str = None
    g.s6_prev_date = None

def s6_scheduler_tasks(context):
    # ---------- 调度：计算信号 → 卖 → 买，间隔 1 分钟 ----------
    run_daily(s6_calc_signal, time='09:30')
    run_daily(s6_do_sell,     time='09:31')
    run_daily(s6_do_buy,      time='09:32')

def s6_initialize(context):
    # ---------- 系统设置 ----------
    common_initialize(context)
    s6_set_params(context)
    s6_scheduler_tasks(context)

# ================================================================
# 第一步：09:35 计算信号（只计算，不下单）
# ================================================================
def s6_calc_signal(context):
    g.s6_today_str = context.current_dt.strftime('%Y-%m-%d')
    g.s6_prev_date = context.previous_date.strftime('%Y-%m-%d')
    g.s6_signal = None

    # 拉取到前一个交易日为止的完整日线数据（前复权）
    data = attribute_history(g.s6_trade_symbol, g.s6_data_count, '1d',
                             ['high', 'low', 'close'],
                             skip_paused=True, df=True, fq='pre')
    if len(data) < max(g.s6_cci_period, g.s6_rsi_period, g.s6_bb_period) + 10:
        log.info('>>> [策略6] [%s] 数据不足（仅%d条），跳过' % (g.s6_today_str, len(data)))
        return
    data = data.ffill().bfill().dropna()

    closes = data['close'].values.astype(float)
    highs = data['high'].values.astype(float)
    lows = data['low'].values.astype(float)

    # ========== 1. 计算 CCI ==========
    tp = (highs + lows + closes) / 3.0
    ma_tp = pd.Series(tp).rolling(window=g.s6_cci_period).mean().values
    md = pd.Series(np.abs(tp - ma_tp)).rolling(window=g.s6_cci_period).mean().values
    cci = np.where(md != 0, (tp - ma_tp) / (0.015 * md), 0.0)
    cci = np.where(np.isnan(cci), 0.0, cci)

    # ========== 2. 计算 RSI ==========
    def calc_rsi(c, period):
        c = pd.Series(c).ffill().bfill().values.astype(float)
        deltas = np.diff(c)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = pd.Series(gains).rolling(period).mean().values
        avg_loss = pd.Series(losses).rolling(period).mean().values
        with np.errstate(divide='ignore', invalid='ignore'):
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        # 兼容旧版 NumPy：手动填充 NaN 为 50
        rsi = np.where(np.isnan(rsi), 50.0, rsi)
        return rsi

    rsi = calc_rsi(closes, g.s6_rsi_period)

    # ========== 3. 计算布林带 ==========
    ma = pd.Series(closes).rolling(window=g.s6_bb_period).mean().values
    std = pd.Series(closes).rolling(window=g.s6_bb_period).std().values
    upper_band = ma + g.s6_bb_std * std

    # ========== 信号计算（基于前一日） ==========
    prev_close = closes[-1]
    prev_cci = cci[-1]
    prev_rsi = rsi[-1]
    prev_upper = upper_band[-1]

    if len(closes) >= 2:
        prev2_close = closes[-2]
        prev2_upper = upper_band[-2]
        break_upper = (prev2_close >= prev2_upper) and (prev_close < prev_upper)
    else:
        break_upper = False

    buy_signal = prev_cci < g.s6_cci_buy_threshold
    sell_signal = (prev_rsi > g.s6_rsi_sell_threshold) and break_upper

    # ---------- 持仓查询 ----------
    pos_trade = 0
    pos_money = 0
    positions = get_portfolio_positions(context,pindex=5)
    if g.s6_trade_symbol in positions:
        pos_trade = positions[g.s6_trade_symbol].total_amount
    if g.s6_money_symbol in positions:
        pos_money = positions[g.s6_money_symbol].total_amount

    log.info('>>> [策略6][%s] 基于%s数据：收盘:%.4f CCI:%.2f RSI:%.2f 上轨:%.4f 持仓(%s):%d 货币:%d'
             % (g.s6_today_str, g.s6_prev_date, prev_close, prev_cci, prev_rsi, prev_upper,
                g.s6_trade_symbol, pos_trade, pos_money))
    log.info('>>> [策略6]  买入信号:%s | 卖出信号:%s (RSI>%d:%s 跌破上轨:%s)'
             % (buy_signal, sell_signal, g.s6_rsi_sell_threshold,
                prev_rsi > g.s6_rsi_sell_threshold, break_upper))

    # ---------- 生成操作指令（不执行） ----------
    if pos_trade > 0:
        if sell_signal:
            g.s6_signal = 'SELL_TRADE_BUY_MONEY'   # 卖目标ETF → 买货币ETF
        else:
            g.s6_signal = 'HOLD_TRADE'
    else:
        if buy_signal:
            if pos_money > 0:
                g.s6_signal = 'SELL_MONEY_BUY_TRADE'  # 卖货币ETF → 买目标ETF
            else:
                g.s6_signal = 'BUY_TRADE'             # 直接买目标ETF
        else:
            if pos_money == 0:
                g.s6_signal = 'BUY_MONEY'             # 空仓 → 买货币ETF
            else:
                g.s6_signal = 'HOLD_MONEY'

    log.info('>>> [策略6]  [09:35] 信号计算完成，当日指令：%s' % g.s6_signal)


# ================================================================
# 第二步：09:36 执行卖出
# ================================================================
def s6_do_sell(context):
    if g.s6_signal is None:
        log.info('>>> [策略6] [%s] 无有效信号，跳过卖出步骤' % g.s6_today_str)
        return

    if g.s6_signal == 'SELL_TRADE_BUY_MONEY':
        log.info('>>> [策略6] [09:36] 卖出目标ETF <<<')
        safe_order_target_value(context,'sell',g.s6_trade_symbol,0,pindex=5)
    elif g.s6_signal == 'SELL_MONEY_BUY_TRADE':
        log.info('>>> [策略6] [09:36] 卖出货币ETF <<<')
        safe_order_target_value(context,'sell',g.s6_money_symbol,0,pindex=5)
    else:
        log.info('>>> [策略6]  [09:36] 无需卖出操作（信号：%s）' % g.s6_signal)


# ================================================================
# 第三步：09:37 执行买入
# ================================================================
def s6_do_buy(context):
    if g.s6_signal is None:
        log.info('>>> [策略6] [%s] 无有效信号，跳过买入步骤' % g.s6_today_str)
        return
    portfolio = get_portfolio(context,pindex=5)
    total_value = portfolio.total_value

    if g.s6_signal == 'SELL_TRADE_BUY_MONEY':
        log.info('>>> [策略6] [09:37] 买入货币ETF <<<')
        safe_order_target_value(context,'buy',g.s6_money_symbol,total_value,pindex=5)

    elif g.s6_signal in ('SELL_MONEY_BUY_TRADE', 'BUY_TRADE'):
        log.info('>>> [策略6] [09:37] 买入目标ETF <<<')
        safe_order_target_value(context,'buy',g.s6_trade_symbol,total_value,pindex=5)

    elif g.s6_signal == 'BUY_MONEY':
        log.info('>>> [策略6] [09:37] 空仓，买入货币ETF <<<')
        safe_order_target_value(context,'buy',g.s6_money_symbol,total_value,pindex=5)

    else:
        log.info('>>> [策略6]  [09:37] 无需买入操作（信号：%s）' % g.s6_signal)

# ==========策略6 红利增强 end========

# ==========策略7 均线粘合-个股 start=======
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
    run_daily(s7_etf_pool_and_filters, time='13:01')   # 更新池
    run_daily(s7_trade_sell, time='14:00')     # 卖出交易判断
    run_daily(s7_trade_buy, time='14:01')     # 买入交易判断
    run_daily(s7_take_fix_profit, time='every_bar')     # 止盈
    # run_daily(s7_take_fix_profit, time='09:40')     # 止盈

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

def s7_get_index_stocks_list(context):
    zz1000stocks = []
    hs300stocks = get_index_stocks('000300.XSHG',date=context.current_dt)
    zz500stocks = get_index_stocks('000905.XSHG',date=context.current_dt)
    # zz1000stocks = get_index_stocks('399852.XSHE',date=context.current_dt)
    all_stocks = list(set(hs300stocks + zz500stocks + zz1000stocks))
    all_stocks = common_filter_stocks(context,all_stocks)
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
            if can_not_deal(stock,''):
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
        is_in_gaps_day = is_buy_in_gaps_day(context,etf,g.s7_max_hold_days,pindex=6)
        if is_in_gaps_day:
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
    current_holdings = [s for s in positions if positions[s].closeable_amount > 0]
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
    ascending=False：市值降序，True=市值升序
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
# ==========策略7 均线粘合-个股 end========

# ==========策略8 小市值 start ===========

#初始化函数 
def s8_initialize(context):
    # 用真实价格交易
    # set_option('order_volume_ratio', 0.01)
    # set_option('match_with_order_book', True)
    common_initialize(context)
    s8_set_params(context)
    s8_scheduler_tasks(context)

def s8_set_params(context):
    #初始化全局变量 bool
    g.s8_no_trading_today_signal = False  # 是否为可交易日
    g.s8_pass_april = True  # 是否四月空仓
    g.s8_run_stoploss = True  # 是否进行止损
    #全局变量list
    g.s8_hold_list = [] #当前持仓的全部股票    
    g.s8_yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.s8_target_list = []
    g.s8_not_buy_again = []
    #全局变量float/str
    g.s8_stock_num = 5
    g.s8_m_days = 5 #取值参考天数
    g.s8_up_price = 100  # 设置股票单价 
    g.s8_reason_to_sell = ''
    g.s8_stoploss_strategy = 3  # 1为止损线止损，2为市场趋势止损, 3为联合1、2策略
    g.s8_stoploss_limit = 0.1  # 止损线
    g.s8_stoploss_market = 0.05  # 市场趋势止损参数
    
def s8_scheduler_tasks(context):
    # 设置交易运行时间
    run_daily(s8_prepare_stock_list, '9:05')
    run_weekly(s8_weekly_sell, 2, '10:00')
    run_weekly(s8_weekly_buy, 2, '10:01')
    run_daily(s8_trade_afternoon_sell, time='14:00') #检查持仓中的涨停股是否需要卖出
    run_daily(s8_trade_afternoon_buy, time='14:01') #检查是否有余额买入

    # 399401.XSHE, 000300.XSHG
    run_daily(s8_sell_stocks, time='10:00') # 止损函数
    run_daily(s8_close_account, '14:50')

#1-1 准备股票池
def s8_prepare_stock_list(context):
    #获取已持有列表
    g.s8_hold_list= []
    positions = get_portfolio_positions(context,pindex=7)
    for position in list(positions.values()):
        stock = position.security
        g.s8_hold_list.append(stock)
    #获取昨日涨停列表
    if g.s8_hold_list != []:
        df = get_price(g.s8_hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.s8_yesterday_HL_list = list(df.code)
    else:
        g.s8_yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    g.s8_no_trading_today_signal = s8_today_is_between(context)

#1-2 选股模块
def s8_get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = get_index_stocks(MKT_index)
    initial_list = common_filter_stocks(context,initial_list,days=375)
    
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),valuation.market_cap.between(5,30)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:100]
    
    initial_list = list(df_fun.code)
    initial_list = s8_filter_limitup_stock(context, initial_list)
    initial_list = s8_filter_limitdown_stock(context, initial_list)
    #print('initial_list中含有{}个元素'.format(len(initial_list)))
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:50]
    final_list  = list(df_fun.code)
    return final_list

#1-3 整体调整持仓

def s8_choose_stocks(stock_list, n):
    """从列表中取中间的 n 个；不足 n 个则全部返回"""
    if len(stock_list) <= n:
        return stock_list
    start = (len(stock_list) - n) // 2
    start = 0
    return stock_list[start:start + n]

#1-3 整体调整持仓：先卖
def s8_weekly_sell(context):
    if g.s8_no_trading_today_signal:
        return

    # 新一周重置“不再买入”记录
    g.s8_not_buy_again = []

    # 获取原始候选池，供卖出和后续补仓使用
    g.s8_target_list = s8_get_stock_list(context)

    # 生成本次调仓的最终目标列表
    target_list = s8_filter_not_buy_again(g.s8_target_list)
    target_list = s8_filter_paused_stock(target_list)
    target_list = s8_filter_limitup_stock(context, target_list)
    target_list = s8_filter_limitdown_stock(context, target_list)
    target_list = s8_filter_highprice_stock(context, target_list)
    target_list = s8_choose_stocks(target_list,g.s8_stock_num)

    # 调仓卖出：不在目标列表且昨日未涨停的持仓卖出
    positions = get_portfolio_positions(context,pindex=7)
    for stock in g.s8_hold_list:
        if stock not in positions:
            continue
        if can_not_deal(stock,'sell'):
            continue
        if (stock not in target_list) and (stock not in g.s8_yesterday_HL_list):
            log.info("卖出[%s]" % stock)
            position = positions[stock]
            s8_close_position(context,position)
        else:
            log.info("已持有[%s]" % stock)


#1-3 整体调整持仓：后买
def s8_weekly_buy(context):
    if g.s8_no_trading_today_signal:
        return

    # 1分钟后再次基于原始候选池过滤，防止状态变化
    target_list = s8_filter_not_buy_again(g.s8_target_list)
    target_list = s8_filter_paused_stock(target_list)
    target_list = s8_filter_limitup_stock(context, target_list)
    target_list = s8_filter_limitdown_stock(context, target_list)
    target_list = s8_filter_highprice_stock(context, target_list)
    target_list = target_list[:g.s8_stock_num]

    log.info("调仓买入，目标列表：%s" % str(target_list))

    # 调仓买入
    s8_buy_security(context, target_list)

    # 记录本周已买入股票，供后续 check_remain_amount 使用
    g.s8_not_buy_again = []
    positions = get_portfolio_positions(context,pindex=7)
    for position in list(positions.values()):
        g.s8_not_buy_again.append(position.security)

#1-4 调整昨日涨停股票
def s8_check_limit_up(context):
    now_time = context.current_dt
    if g.s8_yesterday_HL_list != []:
        positions = get_portfolio_positions(context,pindex=7)
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.s8_yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = positions[stock]
                s8_close_position(context,position)
                g.s8_reason_to_sell = 'limitup'
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-5 如果昨天有股票卖出或者买入失败，剩余的金额今天早上买入
def s8_check_remain_amount(context):
    if g.s8_reason_to_sell is 'limitup': #判断提前售出原因，如果是涨停售出则次日再次交易，如果是止损售出则不交易
        g.s8_hold_list= []
        portfolio = get_portfolio(context,pindex=7)
        positions = get_portfolio_positions(context,pindex=7)
        for position in list(positions.values()):
            stock = position.security
            g.s8_hold_list.append(stock)
        if len(g.s8_hold_list) < g.s8_stock_num:
            target_list = g.s8_target_list
            #剔除本周一曾买入的股票，不再买入
            target_list = s8_filter_not_buy_again(target_list)
            target_list = target_list[:min(g.s8_stock_num, len(target_list))]
            log.info('有余额可用'+str(round((portfolio.cash),2))+'元。'+ str(target_list))
            s8_buy_security(context,target_list)
        g.s8_reason_to_sell = ''
    else:
        log.info('虽然有余额可用，但是为止损后余额，下周再交易')
        g.s8_reason_to_sell = ''

#1-6 下午检查交易
def s8_trade_afternoon_sell(context):
    if g.s8_no_trading_today_signal == False:
        s8_check_limit_up(context)

#1-6 下午检查交易
def s8_trade_afternoon_buy(context):
    if g.s8_no_trading_today_signal == False:
        s8_check_remain_amount(context)   

#1-7 止盈止损
def s8_sell_stocks(context):
    positions = get_portfolio_positions(context,pindex=7)
    if g.s8_run_stoploss == True:
        if g.s8_stoploss_strategy == 1:
            for stock in positions.keys():
                # 股票盈利大于等于100%则卖出
                if positions[stock].price >= positions[stock].avg_cost * 2:
                    s8_close_position(context,positions[stock])
                    log.debug("收益100%止盈,卖出{}".format(stock))
                # 止损
                elif positions[stock].price < positions[stock].avg_cost * (1-g.s8_stoploss_limit):
                    s8_close_position(context,positions[stock])
                    log.debug("收益止损,卖出{}".format(stock))
                    g.s8_reason_to_sell = 'stoploss'
        elif g.s8_stoploss_strategy == 2:
            stock_df = get_price(security=get_index_stocks('399101.XSHE'), end_date=context.previous_date, frequency='daily', fields=['close', 'open'], count=1,panel=False)
            down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
            if down_ratio >= g.s8_stoploss_market:
                g.s8_reason_to_sell = 'stoploss'
                log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
                for stock in positions.keys():
                    s8_close_position(context,positions[stock])
        elif g.s8_stoploss_strategy == 3:
            stock_df = get_price(security=get_index_stocks('399101.XSHE'), end_date=context.previous_date, frequency='daily', fields=['close', 'open'], count=1,panel=False)
            down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
            if down_ratio >= g.s8_stoploss_market:
                g.s8_reason_to_sell = 'stoploss'
                log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
                for stock in positions.keys():
                    s8_close_position(context,positions[stock])
            else:
                for stock in positions.keys():
                    if positions[stock].price < positions[stock].avg_cost * (1-g.s8_stoploss_limit):
                        s8_close_position(context,positions[stock])
                        log.debug("收益止损,卖出{}".format(stock))
                        g.s8_reason_to_sell = 'stoploss'


#2-1 过滤停牌股票
def s8_filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-4 过滤涨停的股票
def s8_filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    positions = get_portfolio_positions(context,pindex=7)
    return [stock for stock in stock_list if stock in positions.keys() or last_prices[stock][-1] <    current_data[stock].high_limit]

#2-5 过滤跌停的股票
def s8_filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    positions = get_portfolio_positions(context,pindex=7)
    return [stock for stock in stock_list if stock in positions.keys() or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6.5 过滤股价
def s8_filter_highprice_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    positions = get_portfolio_positions(context,pindex=7)
    return [stock for stock in stock_list if stock in positions.keys()
			or last_prices[stock][-1] <= g.s8_up_price]

#2-7 删除本周一买入的股票
def s8_filter_not_buy_again(stock_list):
    return [stock for stock in stock_list if stock not in g.s8_not_buy_again]
 
#3-1 交易模块-自定义下单

#3-2 交易模块-开仓
def s8_open_position(context,security, value):
    if can_not_deal(security,'buy'):
        return False
    ret = safe_order_target_value(context,'buy',security,value,pindex=7)
    if ret > 0:
        return True
    return False

#3-3 交易模块-平仓
def s8_close_position(context,position):
    security = position.security
    if can_not_deal(security,'sell'):
        return False
    ret = safe_order_target_value(context,'sell',security,0,pindex=7)
    if ret == -1:
        return True
    return False

#3-4 买入模块
def s8_buy_security(context,target_list):
    #调仓买入
    portfolio = get_portfolio(context,pindex=7)
    positions = get_portfolio_positions(context,pindex=7)
    position_count = len(positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if positions[stock].total_amount == 0:
                if s8_open_position(context,stock, value):
                    log.info("买入[%s]（%s元）" % (stock,value))
                    g.s8_not_buy_again.append(stock) #持仓清单，后续不希望再买入
                    if len(positions) == target_num:
                        break


#4-1 判断今天是否为四月
def s8_today_is_between(context):
    today = context.current_dt.strftime('%m-%d')
    if g.s8_pass_april is True:
        if (('04-05' <= today) and (today <= '04-30')):
            return True
        else:
           return False
    else:
        return False


#4-2 清仓后次日资金可转
def s8_close_account(context):
    if g.s8_no_trading_today_signal == True:
        positions = get_portfolio_positions(context,pindex=7)
        if len(g.s8_hold_list) != 0:
            for stock in g.s8_hold_list:
                position = positions[stock]
                s8_close_position(context,position)
                log.info("卖出[%s]" % (stock))

# ==========策略8 小市值 end =============
