# 克隆自聚宽文章：https://www.joinquant.com/post/47346
# 标题：14-24【年化86%|胜率66%|回撤33%】无未来函数
# 作者：zycash

#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
from datetime import time
import talib

#import datetime
#初始化函数 
def initialize(context):
    # 开启防未来函数
    set_option('avoid_future_data', True)
    # 设定基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('order_volume_ratio', 0.01)
    set_option('match_with_order_book', True)
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(PriceRelatedSlippage(3/1000))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=1/10000, close_commission=1/10000, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    #初始化全局变量 bool
    g.no_trading_today_signal = False  # 是否为可交易日
    g.pass_april = True  # 是否四月空仓
    g.run_stoploss = True  # 是否进行止损
    #全局变量list
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.target_list = []
    g.not_buy_again = []
    #全局变量float/str
    g.stock_num = 5
    g.m_days = 5 #取值参考天数
    g.up_price = 100  # 设置股票单价 
    g.reason_to_sell = ''
    g.stoploss_strategy = 3  # 1为止损线止损，2为市场趋势止损, 3为联合1、2策略
    g.stoploss_limit = 0.1  # 止损线
    g.stoploss_market = 0.05  # 市场趋势止损参数
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    # run_weekly(weekly_adjustment,2,'10:00')
    run_weekly(weekly_sell, 2, '10:00')
    run_weekly(weekly_buy, 2, '10:01')
    run_daily(trade_afternoon_sell, time='14:00') #检查持仓中的涨停股是否需要卖出
    run_daily(trade_afternoon_buy, time='14:01') #检查是否有余额买入

    # 399401.XSHE, 000300.XSHG
    run_daily(sell_stocks, time='10:00') # 止损函数
    run_daily(close_account, '14:50')
    run_weekly(print_position_info, 5, time='15:10')

#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    g.no_trading_today_signal = today_is_between(context)

#1-2 选股模块
def get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = get_index_stocks(MKT_index)
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)

    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),valuation.market_cap.between(10,100)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:200]
    
    initial_list = list(df_fun.code)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_limitup_stock(context, initial_list)
    initial_list = filter_limitdown_stock(context, initial_list)
    #print('initial_list中含有{}个元素'.format(len(initial_list)))
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:200]
    final_list  = list(df_fun.code)
    final_list = filter_macd_bottom_divergence(context,final_list)

    return final_list

#1-3 整体调整持仓

def choose_stocks(stock_list, n):
    """从列表中取中间的 n 个；不足 n 个则全部返回"""
    if len(stock_list) <= n:
        return stock_list
    start = (len(stock_list) - n) // 2
    start = 0
    return stock_list[start:start + n]

#1-3 整体调整持仓：先卖
def weekly_sell(context):
    if g.no_trading_today_signal:
        return

    # 新一周重置“不再买入”记录
    g.not_buy_again = []

    # 获取原始候选池，供卖出和后续补仓使用
    g.target_list = get_stock_list(context)

    # 生成本次调仓的最终目标列表
    target_list = filter_not_buy_again(g.target_list)
    target_list = filter_paused_stock(target_list)
    target_list = filter_limitup_stock(context, target_list)
    target_list = filter_limitdown_stock(context, target_list)
    target_list = filter_highprice_stock(context, target_list)
    target_list = choose_stocks(target_list,g.stock_num)

    log.info("调仓卖出，目标列表：%s" % str(target_list))

    # 调仓卖出：不在目标列表且昨日未涨停的持仓卖出
    for stock in g.hold_list:
        if stock not in context.portfolio.positions:
            continue

        if target_list and (stock not in target_list) and (stock not in g.yesterday_HL_list):
            log.info("卖出[%s]" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % stock)


#1-3 整体调整持仓：后买
def weekly_buy(context):
    if g.no_trading_today_signal:
        return

    # 1分钟后再次基于原始候选池过滤，防止状态变化
    target_list = filter_not_buy_again(g.target_list)
    target_list = filter_paused_stock(target_list)
    target_list = filter_limitup_stock(context, target_list)
    target_list = filter_limitdown_stock(context, target_list)
    target_list = filter_highprice_stock(context, target_list)

    target_list = choose_stocks(target_list,g.stock_num)

    log.info("调仓买入，目标列表：%s" % str(target_list))

    # 调仓买入
    buy_security(context, target_list)

    # 记录本周已买入股票，供后续 check_remain_amount 使用
    g.not_buy_again = []
    for position in list(context.portfolio.positions.values()):
        g.not_buy_again.append(position.security)

#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
                g.reason_to_sell = 'limitup'
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-5 如果昨天有股票卖出或者买入失败，剩余的金额今天早上买入
def check_remain_amount(context):
    if g.reason_to_sell is 'limitup': #判断提前售出原因，如果是涨停售出则次日再次交易，如果是止损售出则不交易
        g.hold_list= []
        for position in list(context.portfolio.positions.values()):
            stock = position.security
            g.hold_list.append(stock)
        if len(g.hold_list) < g.stock_num:
            target_list = g.target_list
            #剔除本周一曾买入的股票，不再买入
            target_list = filter_not_buy_again(target_list)
            target_list = target_list[:min(g.stock_num, len(target_list))]
            log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。'+ str(target_list))
            buy_security(context,target_list)
        g.reason_to_sell = ''
    else:
        log.info('虽然有余额可用，但是为止损后余额，下周再交易')
        g.reason_to_sell = ''

#1-6 下午检查交易
def trade_afternoon_sell(context):
    if g.no_trading_today_signal == False:
        check_limit_up(context)

#1-6 下午检查交易
def trade_afternoon_buy(context):
    if g.no_trading_today_signal == False:
        check_remain_amount(context)   

#1-7 止盈止损
def sell_stocks(context):
    if g.run_stoploss == True:
        if g.stoploss_strategy == 1:
            for stock in context.portfolio.positions.keys():
                # 股票盈利大于等于100%则卖出
                if context.portfolio.positions[stock].price >= context.portfolio.positions[stock].avg_cost * 2:
                    order_target_value(stock, 0)
                    log.debug("收益100%止盈,卖出{}".format(stock))
                # 止损
                elif context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * (1-g.stoploss_limit):
                    order_target_value(stock, 0)
                    log.debug("收益止损,卖出{}".format(stock))
                    g.reason_to_sell = 'stoploss'
        elif g.stoploss_strategy == 2:
            stock_df = get_price(security=get_index_stocks('399101.XSHE'), end_date=context.previous_date, frequency='daily', fields=['close', 'open'], count=1,panel=False)
            #down_ratio = (stock_df['close'] / stock_df['open'] < 1).sum() / len(stock_df)
            down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
            if down_ratio >= g.stoploss_market:
                g.reason_to_sell = 'stoploss'
                log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
                for stock in context.portfolio.positions.keys():
                    order_target_value(stock, 0)
        elif g.stoploss_strategy == 3:
            stock_df = get_price(security=get_index_stocks('399101.XSHE'), end_date=context.previous_date, frequency='daily', fields=['close', 'open'], count=1,panel=False)
            down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
            if down_ratio >= g.stoploss_market:
                g.reason_to_sell = 'stoploss'
                log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
                for stock in context.portfolio.positions.keys():
                    order_target_value(stock, 0)
            else:
                for stock in context.portfolio.positions.keys():
                    if context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * (1-g.stoploss_limit):
                        order_target_value(stock, 0)
                        log.debug("收益止损,卖出{}".format(stock))
                        g.reason_to_sell = 'stoploss'


#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] <    current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date <  datetime.timedelta(days=375)]

#2-6.5 过滤股价
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] <= g.up_price]

#2-7 删除本周一买入的股票
def filter_not_buy_again(stock_list):
    return [stock for stock in stock_list if stock not in g.not_buy_again]

#2-7 过滤没有macd底背离的股票
def filter_macd_bottom_divergence(context, stock_list, lookback=60, low_window=20):
    """
    使用 talib 计算 MACD，过滤出同时满足以下条件的股票：
    1. 昨日（previous_date）MACD 金叉：DIF 上穿 DEA；
    2. 近期出现 MACD 底背离：价格创出更低低点，但 DIF 未创新低。
    :param context: 上下文
    :param stock_list: 待过滤股票列表
    :param lookback: 回看天数，用于判断背离
    :param low_window: 判断局部低点的窗口大小
    :return: 符合条件的股票列表
    """
    result = []
    end_date = context.previous_date

    for stock in stock_list:
        try:
            # 多取 60 天用于 MACD 预热，避免 NaN
            df = get_price(
                stock,
                end_date=end_date,
                frequency='daily',
                fields=['close'],
                count=lookback + 60,
                panel=False,
                fq='pre'
            )
            if len(df) < lookback + 35:
                continue

            close = df['close'].values.astype(float)
            # 处理可能的 NaN（停牌等）
            close = pd.Series(close).fillna(method='ffill').values

            # talib.MACD 返回：DIF, DEA, MACD柱
            dif, dea, macd_hist = talib.MACD(
                close,
                fastperiod=12,
                slowperiod=26,
                signalperiod=9
            )

            # ===== 条件1：昨日 MACD 金叉 =====
            # 数据截止到 previous_date，所以 dif[-1] 是昨日，dif[-2] 是前一日
            if (np.isnan(dif[-1]) or np.isnan(dea[-1]) or
                np.isnan(dif[-2]) or np.isnan(dea[-2])):
                continue
            # 前一日 DIF <= DEA，昨日 DIF > DEA，即金叉
            if not (dif[-2] <= dea[-2] and dif[-1] > dea[-1]):
                continue

            # ===== 条件2：MACD 底背离 =====
            close_recent = close[-lookback:]
            dif_recent = dif[-lookback:]

            if np.isnan(dif_recent).any():
                continue

            # 寻找局部低点：价格是过去 low_window 天的最低点
            low_indices = []
            for i in range(low_window, len(close_recent)):
                if close_recent[i] == min(close_recent[i - low_window:i + 1]):
                    low_indices.append(i)

            if len(low_indices) < 2:
                continue

            # 取最近两个低点
            idx1 = low_indices[-2]
            idx2 = low_indices[-1]

            # 底背离：后一个低点价格更低，但 DIF 更高
            if close_recent[idx2] < close_recent[idx1] and dif_recent[idx2] > dif_recent[idx1]:
                result.append(stock)

        except Exception as e:
            log.debug("MACD底背离+金叉计算失败 %s: %s" % (stock, e))
            continue

    return result

#2-8 过滤最近一个月没有涨停的股票
def filter_recent_limit_up(stock_list, context, days=22):
    """
    保留最近 days 个交易日内至少有一次涨停的股票。
    days=30 约等于最近一个月交易日数量。
    """
    if not stock_list:
        return []

    end_date = context.previous_date
    df = get_price(
        stock_list,
        end_date=end_date,
        frequency='daily',
        fields=['close', 'high_limit', 'low_limit'],
        count=days,
        panel=False,
        fill_paused=False
    )

    if df is None or df.empty:
        return []

    # 收盘价等于涨停价，视为当日涨停
    df = df[df['close'] == df['high_limit']]

    # 出现过涨停的股票代码集合
    limit_up_stocks = set(df['code'].unique())

    # 保持原有顺序
    return [stock for stock in stock_list if stock in limit_up_stocks]
 
#3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        pass
        #log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#3-4 买入模块
def buy_security(context,target_list):
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if context.portfolio.positions[stock].total_amount == 0:
            #if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    log.info("买入[%s]（%s元）" % (stock,value))
                    g.not_buy_again.append(stock) #持仓清单，后续不希望再买入
                    if len(context.portfolio.positions) == target_num:
                        break


#4-1 判断今天是否为四月
def today_is_between(context):
    today = context.current_dt.strftime('%m-%d')
    if g.pass_april is True:
        if (('04-05' <= today) and (today <= '04-30')):
            return True
        else:
           return False
    else:
        return False


#4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))


def print_position_info(context):
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')