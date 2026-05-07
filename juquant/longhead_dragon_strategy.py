# 聚宽龙头战法策略
# 策略逻辑：昨日涨停（非连板）→ 今日开盘跌1%-4% → 相对低位top10 → 9:28满仓买入
# → T+1日11:28盈利卖出（无盈利拿到14:50） → 14:50全部卖出

from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
import datetime

def initialize(context):
    """策略初始化"""
    # 设定基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, 
                             close_today_commission=0, min_commission=5), type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    
    # ========== 策略参数 ==========
    g.yesterday_limit_up_list = []  # 昨日涨停股列表
    g.target_list = []              # 今日候选股票列表
    g.hold_list = []                # 当前持仓列表
    g.buy_prices = {}               # 持仓买入价 {stock: price}
    g.buy_dates = {}                # 持仓买入日期 {stock: date}
    
    # 策略参数（可调）
    g.use_cach_rate = 0.5   # 使用金额占总仓位比例
    g.open_price_drop_low = -0.04   # 开盘价下跌下限 -4%
    g.open_price_drop_high = -0.01   # 开盘价下跌上限 -1%
    g.relative_low_threshold = 0.5  # 相对低位阈值（可调，0.5表示距离年低位50%以内）
    g.top_stock_count = 10          # 取Top10股票
    
    # 记录当日是否已执行买入
    g.buy_executed_today = False
    g.last_buy_date = None
    
    # 设置交易运行时间
    # 9:28 执行选股和买入逻辑
    run_daily(execute_buy_order, '9:28')
    # 11:28 T+1日检查盈利情况
    run_daily(check_profit_at_11_28, '11:28')
    # 14:50 尾盘卖出
    run_daily(close_all_positions, '14:50')
    run_daily(print_position_info, '15:10')

    log.info("龙头战法策略启动：昨涨停→开盘跌1%-4%→相对低位→9:28满仓→T+1日11:28/14:50卖出")


# ========== 核心选股逻辑 ==========

def get_yesterday_limit_up_stocks(context):
    """获取昨日涨停的股票"""
    yesterday = context.previous_date
    # 获取全市场股票
    all_stocks = get_all_securities('stock', yesterday).index.tolist()
    log.debug(f"  [get_yesterday_limit_up_stocks] 全市场股票总数: {len(all_stocks)} 只")
    
    # 过滤：获取昨日涨停的股票
    limit_up_list = []
    try:
        df = get_price(all_stocks, end_date=yesterday, frequency='daily', 
                       fields=['close', 'high_limit'], count=1, panel=False, fill_paused=False)
        df_limit = df[df['close'] == df['high_limit']]
        limit_up_list = list(df_limit['code'].unique())
        log.debug(f"  [get_yesterday_limit_up_stocks] 获取到涨停股: {len(limit_up_list)} 只")
    except Exception as e:
        log.error(f"  [get_yesterday_limit_up_stocks] 获取涨停股失败: {e}")
    
    if not limit_up_list:
        log.warning("  [get_yesterday_limit_up_stocks] 昨日无涨停股票")
    
    return limit_up_list


def is_continuous_limit_up(context, stock):
    """检查是否为连板涨停（近两日都涨停）"""
    yesterday = context.previous_date
    try:
        df = get_price(stock, end_date=yesterday, frequency='daily', 
                       fields=['close', 'high_limit'], count=2, panel=False, fill_paused=False)
        
        if len(df) < 2:
            return False
        
        # 检查近两个交易日是否都涨停
        for idx, row in df.iterrows():
            if row['close'] != row['high_limit']:
                return False
        
        return True  # 两日都涨停，是连板
    except Exception as e:
        log.error(f"  [is_continuous_limit_up] {stock} 判断连板异常: {e}")
        return False


def filter_st_stock(stock_list):
    """过滤ST及其他具有退市标签的股票"""
    before_count = len(stock_list)
    current_data = get_current_data()
    filtered = [stock for stock in stock_list
                if not current_data[stock].is_st
                and 'ST' not in current_data[stock].name
                and '*' not in current_data[stock].name
                and '退' not in current_data[stock].name]
    st_filtered = before_count - len(filtered)
    if st_filtered > 0:
        log.debug(f"  ST过滤: {before_count} → {len(filtered)} (-{st_filtered}只ST股)")
    return filtered


def filter_paused_stock(stock_list):
    """过滤停牌股票"""
    before_count = len(stock_list)
    current_data = get_current_data()
    filtered = [stock for stock in stock_list if not current_data[stock].paused]
    paused_filtered = before_count - len(filtered)
    if paused_filtered > 0:
        log.debug(f"  停牌过滤: {before_count} → {len(filtered)} (-{paused_filtered}只停牌股)")
    return filtered


def filter_kcb_stock(stock_list):
    """过滤科创板股票"""
    before_count = len(stock_list)
    filtered = [stock for stock in stock_list if stock[0:3] != '688']
    kcb_filtered = before_count - len(filtered)
    if kcb_filtered > 0:
        log.debug(f"  科创板过滤: {before_count} → {len(filtered)} (-{kcb_filtered}只科创股)")
    return filtered


def filter_new_stock(context, stock_list):
    """过滤上市不足1年的新股"""
    before_count = len(stock_list)
    yesterday = context.previous_date
    filtered = [stock for stock in stock_list 
                if (yesterday - get_security_info(stock).start_date).days >= 365]
    new_filtered = before_count - len(filtered)
    if new_filtered > 0:
        log.debug(f"  新股过滤: {before_count} → {len(filtered)} (-{new_filtered}只新股)")
    return filtered


def get_open_price_change(stock, yesterday):
    """计算今日开盘价相对昨日收盘的涨跌幅"""
    try:
        # 获取昨日收盘和今日开盘
        data = get_price(stock, end_date=yesterday, frequency='daily', 
                        fields=['close'], count=1, panel=False, fill_paused=False)
        yesterday_close = data.iloc[0]['close']
        
        current_data = get_current_data()
        today_open = current_data[stock].day_open
        
        change_ratio = (today_open - yesterday_close) / yesterday_close
        return change_ratio
    except Exception as e:
        log.error(f"  [get_open_price_change] {stock} 获取开盘涨跌幅失败: {e}")
        return None


def calculate_relative_position(context, stock, days=60):
    """计算股票在近N日内的相对位置
    公式：(当前价 - 最低价) / (最高价 - 最低价)
    返回值越小说明越接近底部
    """
    yesterday = context.previous_date
    try:
        df = get_price(stock, end_date=yesterday, frequency='daily', fields=['close', 'high', 'low'], 
                      count=days, panel=False, fill_paused=False)
        
        if len(df) < days:
            log.debug(f"  [calculate_relative_position] {stock} 数据不足({len(df)}<{days})，跳过")
            return None
        
        current_data = get_current_data()
        current_price = current_data[stock].day_open
        min_price = df['low'].min()
        max_price = df['high'].max()
        
        if max_price == min_price:
            log.debug(f"  [calculate_relative_position] {stock} 最高=最低={min_price:.2f}，返回中位值0.5")
            return 0.5
        
        relative_pos = (current_price - min_price) / (max_price - min_price)
        log.debug(f"  [calculate_relative_position] {stock} 当前:{current_price:.2f} 最低:{min_price:.2f} 最高:{max_price:.2f} 相对位:{relative_pos:.4f}")
        return relative_pos
    except Exception as e:
        log.error(f"  [calculate_relative_position] {stock} 异常: {e}")
        return None


def select_target_stocks(context):
    """选择目标股票的核心逻辑"""
    yesterday = context.previous_date
    log.info("-" * 60)
    log.info(f"【选股过程详细日志】上一个交易日：{yesterday}")
    log.info("-" * 60)
    
    # Step 1: 获取昨日涨停股
    limit_up_stocks = get_yesterday_limit_up_stocks(context)
    log.info(f"[Step1] 昨日涨停股: {len(limit_up_stocks)} 只")
    
    if not limit_up_stocks:
        log.info("  ✗ 未找到昨日涨停股，退出选股")
        return []
    
    # Step 2: 过滤连板涨停
    non_continuous_limit_up = []
    continuous_count = 0
    for stock in limit_up_stocks:
        if not is_continuous_limit_up(context, stock):
            non_continuous_limit_up.append(stock)
        else:
            continuous_count += 1
    log.info(f"[Step2] 非连板过滤: {len(limit_up_stocks)} → {len(non_continuous_limit_up)} (-{continuous_count}只连板)")
    
    if not non_continuous_limit_up:
        log.info("  ✗ 全部为连板涨停，退出选股")
        return []
    
    # Step 3: 过滤ST、停牌、科创板
    log.info(f"[Step3] 基础过滤(ST/停牌/科创板)...")
    filtered_list = filter_st_stock(non_continuous_limit_up)
    filtered_list = filter_paused_stock(filtered_list)
    filtered_list = filter_kcb_stock(filtered_list)
    log.info(f"        后: {len(filtered_list)} 只")
    
    if not filtered_list:
        log.info("  ✗ 无合格的基础股票，退出选股")
        return []
    
    # Step 4: 过滤新股
    log.info(f"[Step4] 新股过滤(上市<1年)...")
    filtered_list = filter_new_stock(context, filtered_list)
    log.info(f"        后: {len(filtered_list)} 只")
    
    if not filtered_list:
        log.info("  ✗ 无上市满1年的股票，退出选股")
        return []
    
    # Step 5: 过滤开盘价涨跌幅
    log.info(f"[Step5] 开盘价涨跌幅过滤 [{g.open_price_drop_low*100:.1f}% ~ {g.open_price_drop_high*100:.1f}%]")
    valid_list = []
    drop_ratio_details = {}
    for stock in filtered_list:
        open_change = get_open_price_change(stock, yesterday)
        if open_change is not None:
            drop_ratio_details[stock] = open_change
            if g.open_price_drop_low <= open_change <= g.open_price_drop_high:
                valid_list.append(stock)
    
    log.info(f"        后: {len(filtered_list)} → {len(valid_list)} (-{len(filtered_list)-len(valid_list)}只超出范围)")
    if valid_list:
        for stock in valid_list[:5]:  # 只显示前5只
            log.debug(f"        ✓ {stock} 开盘涨跌: {drop_ratio_details[stock]*100:.2f}%")
    
    if not valid_list:
        log.info("  ✗ 无开盘价在目标范围内的股票，退出选股")
        return []
    
    # Step 6: 计算相对位置，排序
    log.info(f"[Step6] 相对位置过滤 (≤ {g.relative_low_threshold*100:.0f}%)...")
    stock_pos_list = []
    for stock in valid_list:
        rel_pos = calculate_relative_position(context, stock, days=60)
        if rel_pos is not None:
            if rel_pos <= g.relative_low_threshold:
                stock_pos_list.append((stock, rel_pos))
    
    log.info(f"        后: {len(valid_list)} → {len(stock_pos_list)} (-{len(valid_list)-len(stock_pos_list)}只过高)")
    
    if not stock_pos_list:
        log.info("  ✗ 无相对低位的股票，退出选股")
        return []
    
    # 按相对位置从小到大排序，取Top10
    stock_pos_list.sort(key=lambda x: x[1])
    target_stocks = [stock for stock, pos in stock_pos_list[:g.top_stock_count]]
    
    log.info(f"[Step7] 最终选股: 取 Top{g.top_stock_count} → {len(target_stocks)} 只")
    for i, (stock, pos) in enumerate(stock_pos_list[:g.top_stock_count], 1):
        log.info(f"        {i}. {stock} 相对位置: {pos:.4f}")
    
    log.info("-" * 60)
    return target_stocks


# ========== 交易执行逻辑 ==========

def execute_buy_order(context):
    """9:28 执行买入逻辑"""
    today = context.current_dt.date()
    log.info(f"【execute_buy_order】当前日期: {today}")
    
    # 避免同一天重复执行
    if g.buy_executed_today and g.last_buy_date == today:
        log.debug(f"  [execute_buy_order] {today} 已执行过买入操作，跳过重复执行")
        return
    
    log.info("=" * 70)
    log.info("【9:28 龙头战法买入执行】")
    log.info("=" * 70)
    
    # 选择目标股票
    target_stocks = select_target_stocks(context)
    
    if not target_stocks:
        log.info("  ✗ 未找到符合条件的目标股票，本日无交易")
        return
    
    g.target_list = target_stocks
    
    # 等权重满仓买入
    portfolio_value = context.portfolio.total_value
    available_cash = context.portfolio.cash
    use_cash = available_cash
    # 限制每次使用金额的上限不超过总仓的比例
    use_cash_limitup = g.use_cach_rate * portfolio_value
    if available_cash>use_cash_limitup:
        use_cash = use_cash_limitup
    cash_per_stock = use_cash / len(target_stocks)
    
    log.info(f"总市值: {portfolio_value:,.2f}元，可用现金: {available_cash:,.2f}元，买入不超过总市值比例：{g.use_cach_rate:.2f}，最终使用现金：{use_cash:.2f}元")
    log.info(f"每只股票分配资金: {cash_per_stock:,.2f}元，目标持仓数: {len(target_stocks)} 只")
    log.info("-" * 70)
    
    current_data = get_current_data()
    total_invested = 0
    bought_count = 0
    buy_details = []
    
    for idx, stock in enumerate(target_stocks, 1):
        try:
            # 获取集合竞价开盘价
            current_price = current_data[stock].day_open
            
            # 计算买入数量（100股整数倍）
            qty = int(cash_per_stock / current_price / 100) * 100
            
            if qty > 0:
                # 执行买入
                order(stock, qty)
                
                # 记录持仓信息
                g.buy_prices[stock] = current_price
                g.buy_dates[stock] = today
                g.hold_list.append(stock)
                
                cost = qty * current_price
                total_invested += cost
                bought_count += 1
                
                buy_details.append({
                    'stock': stock,
                    'qty': qty,
                    'price': current_price,
                    'cost': cost
                })
                
                log.info(f"  {idx}. 【买入】{stock}")
                log.info(f"     开盘价: {current_price:.3f}元  数量: {qty}股  成本: {cost:,.2f}元")
            else:
                log.warning(f"  {idx}. 【买入失败】{stock} 可用资金不足以买入100股")
        except Exception as e:
            log.error(f"  {idx}. 【买入异常】{stock} {e}")
    
    g.buy_executed_today = True
    g.last_buy_date = today
    
    log.info("-" * 70)
    log.info(f"本次买入统计:")
    log.info(f"  成功买入: {bought_count} 只股票")
    log.info(f"  总投入金额: {total_invested:,.2f}元")
    log.info(f"  仓位占比: {total_invested/portfolio_value*100:.2f}%")
    log.info(f"  剩余现金: {context.portfolio.cash:,.2f}元")
    log.info("=" * 70)


def check_profit_at_11_28(context):
    """T+1日 11:28 检查盈利情况，有利润就卖出"""
    today = context.current_dt.date()
    log.info(f"【check_profit_at_11_28】当前日期: {today} 持仓记录: {len(g.buy_dates)} 只")
    
    # 只在买入后的第二个交易日执行
    if not g.buy_dates:
        log.debug("  [check_profit_at_11_28] 无持仓记录(buy_dates为空)，跳过")
        return
    
    # 检查是否有T+1日的持仓
    holding_on_t1 = []
    for stock in list(g.hold_list):
        buy_date = g.buy_dates.get(stock)
        if buy_date is not None and buy_date < today:
            holding_on_t1.append(stock)
    
    if not holding_on_t1:
        log.info(f"  [check_profit_at_11_28] 所有持仓均已卖出或无需T+1操作(今日无持仓适合卖出的条件)，跳过")
        return
    
    log.info("=" * 70)
    log.info(f"【11:28 盈利检查】{today} T+1日持仓检查")
    log.info("=" * 70)
    log.info(f"检查持仓数: {len(holding_on_t1)} 只")
    log.info("-" * 70)
    
    current_data = get_current_data()
    sell_profit_count = 0
    hold_continue_count = 0
    sell_profit_details = []
    hold_details = []
    
    # 检查是否是T+1日
    for idx, stock in enumerate(holding_on_t1, 1):
        buy_date = g.buy_dates.get(stock)
        
        try:
            current_price = current_data[stock].last_price
            buy_price = g.buy_prices[stock]
            position = context.portfolio.positions.get(stock)
            
            if position is None or position.total_amount == 0:
                log.info(f"  {idx}. {stock} 已平仓，跳过检查")
                continue
            
            # 计算浮动盈利
            position_qty = position.total_amount
            profit_value = (current_price - buy_price) * position_qty
            profit_ratio = (current_price - buy_price) / buy_price
            
            log.info(f"  {idx}. {stock} 【T+1日检查】")
            log.info(f"     买入价: {buy_price:.3f}元  当前价: {current_price:.3f}元  持仓: {position_qty}股")
            log.info(f"     浮动盈亏: {profit_value:,.2f}元  盈利率: {profit_ratio*100:.2f}%")
            
            if profit_ratio > 0:
                # 有盈利，卖出
                order_target_value(stock, 0)
                log.info(f"     ✓ 触发条件: 盈利 > 0")
                log.info(f"     → 【11:28卖出】已发送卖单")
                
                sell_profit_count += 1
                sell_profit_details.append({
                    'stock': stock,
                    'sell_price': current_price,
                    'profit_ratio': profit_ratio,
                    'profit_value': profit_value
                })
                
                # 清除记录
                g.hold_list.remove(stock)
                del g.buy_prices[stock]
                del g.buy_dates[stock]
            else:
                # 无盈利，继续持仓
                log.info(f"     ✗ 触发条件: 盈利 ≤ 0")
                log.info(f"     → 【继续持仓】等待14:50统一清仓")
                
                hold_continue_count += 1
                hold_details.append({
                    'stock': stock,
                    'current_price': current_price,
                    'profit_ratio': profit_ratio
                })
        except Exception as e:
            log.error(f"  {idx}. 【检查异常】{stock} {e}")
    
    log.info("-" * 70)
    log.info(f"检查结果统计:")
    log.info(f"  11:28卖出(有盈利): {sell_profit_count} 只")
    log.info(f"  继续持仓(无盈利): {hold_continue_count} 只")
    if sell_profit_count > 0:
        avg_profit_ratio = sum([x['profit_ratio'] for x in sell_profit_details]) / len(sell_profit_details)
        log.info(f"  平均盈利率: {avg_profit_ratio*100:.2f}%")
    log.info("=" * 70)


def close_all_positions(context):
    """14:50 尾盘清空T+1可卖的持仓（排除当日买入的股票，T+1制度限制）"""
    today = context.current_dt.date()
    log.info("=" * 70)
    log.info("【14:50 尾盘清仓执行】")
    log.info("=" * 70)
    
    if not g.hold_list:
        log.info("  → 当前无持仓，跳过清仓")
        return
    
    # 区分T+1可卖（昨天及之前买入）和今日买入（T+1不可卖）
    sellable_stocks = []  # buy_date < today，可以卖出
    today_bought_stocks = []  # buy_date == today，T+1不可卖
    for stock in g.hold_list:
        buy_date = g.buy_dates.get(stock)
        if buy_date is not None and buy_date < today:
            sellable_stocks.append(stock)
        else:
            today_bought_stocks.append(stock)
    
    log.info(f"总持仓: {len(g.hold_list)} 只 | T+1可卖: {len(sellable_stocks)} 只 | 今日买入(T+1不可卖): {len(today_bought_stocks)} 只")
    
    if not sellable_stocks:
        log.info("  → 所有持仓均为今日买入(T+1)，需保留至明日处理，跳过清仓")
        log.info("=" * 70)
        return
    
    log.info(f"待清仓(T+1可卖): {len(sellable_stocks)} 只")
    log.info("-" * 70)
    
    current_data = get_current_data()
    close_details = []
    total_profit = 0
    total_pnl_ratio = 0
    sold_stocks = []  # 成功卖出的股票
    
    # 只卖出T+1可卖的股票（昨天及之前买入的）
    for idx, stock in enumerate(sellable_stocks, 1):
        try:
            position = context.portfolio.positions.get(stock)
            if position is None or position.total_amount == 0:
                log.info(f"  {idx}. {stock} 已无持仓，跳过清仓")
                sold_stocks.append(stock)  # 清理记录
                continue
            
            current_price = current_data[stock].last_price
            buy_price = g.buy_prices.get(stock, current_price)
            position_qty = position.total_amount
            
            # 计算盈亏
            profit_value = (current_price - buy_price) * position_qty
            profit_ratio = (current_price - buy_price) / buy_price if buy_price != 0 else 0
            
            order_target_value(stock, 0)
            
            log.info(f"  {idx}. 【14:50清仓】{stock}")
            log.info(f"     成本: {buy_price:.3f}元  卖价: {current_price:.3f}元  数量: {position_qty}股")
            log.info(f"     盈亏: {profit_value:,.2f}元  盈利率: {profit_ratio*100:+.2f}%")
            
            close_details.append({
                'stock': stock,
                'buy_price': buy_price,
                'sell_price': current_price,
                'qty': position_qty,
                'profit_value': profit_value,
                'profit_ratio': profit_ratio
            })
            
            total_profit += profit_value
            total_pnl_ratio += profit_ratio
            sold_stocks.append(stock)
        except Exception as e:
            log.error(f"  {idx}. 【清仓异常】{stock} {e}")
    
    # 仅清除已卖出股票的记录，今日买入的保留到明天
    for stock in sold_stocks:
        if stock in g.hold_list:
            g.hold_list.remove(stock)
        if stock in g.buy_prices:
            del g.buy_prices[stock]
        if stock in g.buy_dates:
            del g.buy_dates[stock]
    
    # 重置当日买入标记（若所有今日买入股票都保留到明天）
    if not g.hold_list:
        # 如果已无可持有的股票（今天买入的也都卖了，但理论上不会发生）
        g.buy_executed_today = False
    
    # 清仓统计
    log.info("-" * 70)
    log.info(f"当日清仓统计:")
    log.info(f"  清仓笔数: {len(close_details)} 只")
    log.info(f"  剩余持仓(今日买入T+1持有到明天): {len(g.hold_list)} 只")
    if today_bought_stocks:
        for s in today_bought_stocks:
            log.info(f"    → {s} 今日买入(保留)")
    if close_details:
        log.info(f"  清仓总盈亏: {total_profit:,.2f}元")
        log.info(f"  平均盈利率: {total_pnl_ratio/len(close_details)*100:+.2f}%")
        
        # 统计盈利/亏损数量
        profit_count = sum(1 for x in close_details if x['profit_value'] > 0)
        loss_count = len(close_details) - profit_count
        win_rate = profit_count / len(close_details) * 100 if close_details else 0
        log.info(f"  盈利: {profit_count}只  亏损: {loss_count}只  胜率: {win_rate:.1f}%")
    
    # 打印当日成交记录
    trades = get_trades()
    if trades:
        log.info("-" * 70)
        log.info(f"当日所有成交记录: {len(trades)} 笔")
        for trade in list(trades.values())[:10]:  # 显示最新的10笔
            log.debug(f"  {trade}")
    
    # 打印账户信息
    log.info("-" * 70)
    log.info(f"账户状态:")
    log.info(f"  总资产: {context.portfolio.total_value:,.2f}元")
    log.info(f"  可用现金: {context.portfolio.cash:,.2f}元")
    log.info(f"  持仓市值: {context.portfolio.positions_value:,.2f}元")
    log.info(f"  当日清仓盈亏: {total_profit:,.2f}元")
    log.info("=" * 70)


# ========== 辅助函数 ==========

def print_position_info(context):
    """打印持仓信息"""
    log.info("=" * 60)
    log.info("【portfolio 持仓信息】")
    log.info("=" * 60)
    
    positions = context.portfolio.positions
    if len(positions) == 0:
        log.info('当前空仓')
        return

    current_data = get_current_data()
    for stock in g.hold_list:
        try:
            position = context.portfolio.positions[stock]
            current_price = current_data[stock].last_price
            buy_price = g.buy_prices[stock]
            real_buy_price=position.avg_cost
            profit_ratio = (current_price - real_buy_price) / real_buy_price
            
            log.info(f"{stock}: 预期成本{buy_price:.3f} 实际成本{position.avg_cost:.3f} 现价{current_price:.3f} "
                   f"盈亏率{profit_ratio*100:.2f}% 持仓{position.total_amount}股 市值{position.value}")
        except Exception as e:
            log.error(f"打印{stock}信息失败: {e}")
    
    log.info("=" * 60)
