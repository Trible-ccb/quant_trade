# 克隆自聚宽文章：https://www.joinquant.com/post/47346
# 标题：14-24【年化86%|胜率66%|回撤33%】无未来函数
# 作者：zycash

#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
from datetime import time
#import datetime

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
# 不同策略固定止损阈值,均线粘合、N宽基、全球宽基、自适应宽基,弱转强，红利增强，均线粘合个股，小市值
FIX_RATE_LIMITS = [0.05,0.03,0.03,0.03,0.03,0.03,0.05,0.03]

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
        if i == 4:
            record(弱转强=returns)
        if i == 5:
            record(红利增强=returns)
        if i == 6:
            record(均线粘合个股版=returns)
        if i == 7:
            record(小市值=returns)
    
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


def initialize(context):
    s8_initialize(context)
    N = 10
    g.buy_date_history = {}
    g.sell_date_history = {}
    for i in range(0,N):
        g.buy_date_history[i] = {}
        g.sell_date_history[i] = {}

#初始化函数 
def s8_initialize(context):
    # 用真实价格交易
    set_option('order_volume_ratio', 0.01)
    set_option('match_with_order_book', True)
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
    initial_list = s8_filter_new_stock(context, initial_list)
    initial_list = s8_filter_kcbj_stock(initial_list)
    initial_list = s8_filter_st_stock(initial_list)
    
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),valuation.market_cap.between(5,30)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:100]
    
    initial_list = list(df_fun.code)
    initial_list = s8_filter_paused_stock(initial_list)
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

#2-2 过滤ST及其他具有退市标签的股票
def s8_filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票
def s8_filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

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

#2-6 过滤次新股
def s8_filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date <  datetime.timedelta(days=375)]

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
