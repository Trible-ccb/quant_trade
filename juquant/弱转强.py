# 聚宽策略：弱转强_开盘买入_v11_D3T（不使用 get_price，带详细日志）
from jqdata import *
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from jqdata import finance

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
FIX_RATE_LIMITS = [0.05,0.03,0.03,0.03]
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
                log.warn(f"safe_order_target_value ignore {action} {code} {pindex}, closeable_amount=0")
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
def initialize(context):
    s5_initialize(context)

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
    g.s5_max_stock_cash = 5 * 10000
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

def after_code_changed(context):
    unschedule_all()
    s5_scheduler_task(context)

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
        for s in index_stocks:
            if s.startswith('688') or s.startswith('30'):
                continue
            if s.startswith('8') or s.startswith('4') or s.startswith('920'):
                continue
            info = get_security_info(s)
            name = info.display_name
            if 'ST' in name or '退' in name:
                continue
            start_date = info.start_date
            if (context.current_dt.date() - start_date).days < 60:
                continue
            filtered.append(s)
            g.s5_stock_pool = filtered
    except Exception as e:
        g.csi2000 = set()
        log.info(f"[初始化] 中证2000加载失败：{e}")
    log.info(f"[初始化] 中证2000成分股数量：{len(index_stocks)}，满足粗筛条件：{len(filtered)}")

def s5_init_industry(context):
    # 行业映射
    try:
        industry_df = get_industries(name='sw_l1')
        for idx in industry_df.index:
            stocks = get_industry_stocks(idx)
            for s in stocks:
                # g.s5_industry_map[s] = idx
                g.s5_industry_map[s] = str(idx) + '.XSHG'
        log.info(f"[初始化] 行业映射数量：{len(g.s5_industry_map)}")
    except Exception as e:
        log.info(f"[初始化] 行业映射失败：{e}")

def s5_before_market_open(context):
    log.info("=" * 70)
    log.info(f"【盘前选股】当前时间：{context.current_dt}，上一交易日：{context.previous_date}")
    s5_init_stock_list(context)
    # 清空标的池
    g.s5_targets = []

    # ---------- 市场情绪门控 ----------
    g.s5_allow_trade = True
    try:
        idx_df = attribute_history('000001.XSHG', count=3, unit='1d', fields=['close'],
                                   skip_paused=True, df=True, fq='pre')
        log.info(f"[门控] 上证指数最近3日收盘：{idx_df['close'].values if idx_df is not None else 'None'}")
        if idx_df is not None and len(idx_df) >= 3:
            idx_close = idx_df['close'].values
            prev_ret = idx_close[-1] / idx_close[-2] - 1
            log.info(f"[门控] 昨日上证涨跌幅：{prev_ret:.4f}")
            if prev_ret <= -0.04:
                g.s5_allow_trade = False
        else:
            log.info("[门控] 上证指数数据不足3条")
    except Exception as e:
        log.info(f"[门控] 获取上证指数异常：{e}")
    log.info(f"[门控] allow_trade = {g.s5_allow_trade}")
    
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
                log.info(f"[行业] {code_str} 取数失败：{e}")
                continue
    except Exception as e:
        log.info(f"[行业] get_industries 失败：{e}")

    if g.s5_industry_ret:
        g.s5_industry_med = np.median(list(g.s5_industry_ret.values()))
    log.info(f"[行业] 有效行业数={len(g.s5_industry_ret)}，中位数={g.s5_industry_med:.4f}")
    
    # ---------- 市值数据 ----------
    g.s5_caps = {}
    try:
        q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(g.s5_stock_pool))
        df = get_fundamentals(q, date=context.previous_date)
        for _, row in df.iterrows():
            g.s5_caps[row['code']] = row['market_cap']
    except Exception as e:
        log.info(f"[市值] 获取异常：{e}")
    log.info(f"[市值] 获取到市值数据的股票数={len(g.s5_caps)}")
    
    # ---------- 选股漏斗 ----------
    candidates = []
    try:
        # history 一次只能取一个字段，分 4 次调用
        df_open = history(5, '1d', 'open', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_close = history(5, '1d', 'close', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_volume = history(5, '1d', 'volume', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        df_money = history(5, '1d', 'money', g.s5_stock_pool, df=True, skip_paused=True, fq='pre')
        log.info(f"[数据] df_close 形状={None if df_close is None else df_close.shape}")
    except Exception as e:
        log.info(f"[数据] history 获取异常：{e}")
        g.s5_candidates = []
        return
    
    if df_close is None or df_close.empty:
        log.info("[数据] df_close 为空，选股终止")
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
    
    log.info(f"[漏斗统计] {stat}")
    log.info(f"[选股] 最终候选数={len(candidates)}，候选={candidates}")
    
    g.s5_candidates = candidates

def s5_after_market_call_auction(context):
    # 集合竞价结束，28分之后可以取数据，仅计算信号
    log.info(f"【集合竞价】时间={context.current_dt}，allow_trade={g.s5_allow_trade}，候选数={len(g.s5_candidates)}")
    if not g.s5_allow_trade:
        log.info("[买入判断] 市场门控关闭，跳过")
        return
    if not g.s5_candidates:
        log.info("[买入判断] 候选为空，跳过")
        return
    
    current_data = get_current_data()
    targets = []
    for stock in g.s5_candidates:
        # ---------- 昨日数据 ----------
        try:
            hist = attribute_history(stock, count=1, unit='1d', fields=['close', 'volume'],
                                        skip_paused=True, df=True, fq='pre')
            if hist is None or hist.empty:
                log.info(f"[买入判断] {stock} 昨日数据为空，跳过")
                continue
            prev_close = hist['close'].iloc[-1]
            prev_vol = hist['volume'].iloc[-1]
        except Exception as e:
            log.info(f"[买入判断] {stock} 获取昨日数据异常：{e}")
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
                log.info(f"[竞价] {stock} 竞价返回列={list(auction.columns)}，条数={len(auction)}，"
                            f"取到价={a_open}，量={a_vol}")
        except Exception as e:
            log.info(f"[买入判断] {stock} 竞价数据异常：{e}")
        
        # 竞价数据缺失时退化
        if a_open is None or a_open == 0 or (isinstance(a_open, float) and np.isnan(a_open)):
            a_open = current_data[stock].day_open
            a_vol = 0
            log.info(f"[买入判断] {stock} 竞价数据缺失，退化使用 day_open={a_open}")
        
        if a_open is None or a_open == 0:
            log.info(f"[买入判断] {stock} 无法获取开盘价，跳过")
            continue
        
        a_chg = a_open / prev_close - 1
        log.info(f"[买入判断] {stock} 竞价价={a_open:.4f} 昨收={prev_close:.4f} 涨幅={a_chg:.4f} "
                    f"竞价量={a_vol} 昨量={prev_vol}")
        
        # ---------- 过滤条件 ----------
        if a_chg < -0.01 or a_chg > 0.06:
            log.info(f"[买入判断] {stock} 竞价涨幅 {a_chg:.4f} 不在 [-1%, 6%]，跳过")
            continue
        vol_limit = prev_vol * 0.005
        if a_vol > 0 and a_vol < vol_limit:
            log.info(f"[买入判断] {stock} 竞价量不足（{a_vol} < {vol_limit:.0f}），跳过")
            continue

        targets.append(stock)
    g.s5_targets = targets
    log.info(f"[集合竞价结束]待买入标的个数{len(targets)},列表:{targets}")
    target_names = {code:get_security_name(code) for code in targets}
    if targets:
        send_message(f"待买入弱转强标的：{target_names}")
        
    
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
        buy_date = get_history(context,'buy',stock,pindex=4)
        if not buy_date:
            buy_date = context.current_dt.date()
        over = (context.current_dt.date() - buy_date).days >= g.s5_max_hold_days
        log.info(f"[14:50] {stock} 现价={cur_price} 涨停价={high_limit} 买入日={buy_date} 超期={over}")
        if cur_price >= high_limit * 0.999 and not over:
            log.info(f"[14:50] {stock} 涨停且未超期，继续持有")
            continue
        if can_not_deal(stock,'sell'):
            continue
        safe_order_target_value(context,'sell',stock,0,pindex=4)
