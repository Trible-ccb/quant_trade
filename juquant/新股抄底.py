# 聚宽研究环境 / 回测策略代码
# 新股抄底策略（回调触发 + 移动止盈 + 冷却期 + MACD过滤（柱>0 且 DIF上升）+ 分时买卖）

import pandas as pd
import numpy as np
from datetime import timedelta

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
# 不同策略固定止损阈值,均线粘合、N宽基、全球宽基、自适应宽基,弱转强，红利增强，均线粘合个股，新股抄底
FIX_RATE_LIMITS = [0.05,0.03,0.03,0.03,0.03,0.03,0.05,0.03]

def initialize(context):
    total_init_cash = context.portfolio.available_cash
    # 均线粘合策略资金
    g.s1_cash = total_init_cash // 10 * 2
    # N大宽基策略资金
    g.s2_cash = total_init_cash // 10
    # 全球ETF策略资金
    g.s3_cash = total_init_cash // 10
    # 自适应ETF轮动
    g.s4_cash = total_init_cash // 10 * 2
    # 弱转强
    g.s5_cash = total_init_cash // 10 * 2
    # 红利增强
    g.s6_cash = total_init_cash // 10
    # 均线粘合-个股版
    g.s7_cash = total_init_cash // 10

    set_subportfolios([SubPortfolioConfig(cash=g.s1_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s2_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s3_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s4_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s5_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s6_cash, type='stock'),\
                       SubPortfolioConfig(cash=g.s7_cash, type='stock')])
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

    N = 10
    g.buy_date_history = {}
    g.sell_date_history = {}
    for i in range(0,N):
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
        ]

def after_trading_end(context):
    log_portfolio(context)

def after_code_changed(context):
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

# 初始化函数
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=1/1000,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))

    # 策略参数
    g.buy_amount = 200000          # 每只股票买入金额（元），若资金不足则按比例分配
    g.hold_days = 200               # 最大持有天数
    g.stop_loss = -0.1            # 固定止损线
    g.take_profit = 0.4           # 固定止盈线
    g.trailing_stop = -0.06        # 移动止盈回撤幅度（-6%）
    g.cooldown_days = 15           # 卖出后冷却天数（自然日）
    g.max_positions = 5            # 最大同时持仓数量
    g.max_buy_count = 3            # 单日最多买入股票数（资金充足时）

    # 板块回撤阈值（根据统计数据设定）
    g.drawdown_threshold = {
        '主板': -0.95,
        '创业板': -0.95,
        '科创板': -0.4
    }

    # 记录持仓信息：{股票代码: {'buy_date': date, 'buy_price': float, 'high_price': float}}
    g.positions = {}

    # 记录冷却期：{股票代码: 最早可买入日期}
    g.cooldown = {}

    # 分时执行：先卖后买，间隔1分钟
    run_daily(check_sell, '09:31')   # 先卖出
    run_daily(check_buy, '09:32')    # 后买入

# ========== 卖出函数 ==========
def check_sell(context):
    current_date = context.current_dt.date()
    current_holdings = list(context.portfolio.positions.keys())

    for stock in current_holdings:
        if stock not in g.positions:
            continue
        info = g.positions[stock]
        buy_date = info['buy_date']
        buy_price = info['buy_price']
        high_price = info['high_price']

        hold_days = (current_date - buy_date).days
        current_price = get_current_data()[stock].last_price
        ret = current_price / buy_price - 1
        drawdown_from_high = current_price / high_price - 1

        # 更新最高价
        if current_price > high_price:
            info['high_price'] = current_price
            high_price = current_price

        style = MarketOrderStyle(current_price * 0.999)

        sell_flag = False
        reason = ''

        if ret >= g.take_profit:
            sell_flag = True
            reason = '固定止盈'
        elif ret <= g.stop_loss:
            sell_flag = True
            reason = '固定止损'
        elif drawdown_from_high <= g.trailing_stop:
            sell_flag = True
            reason = f'移动止盈（回撤{drawdown_from_high:.2%}）'
        elif hold_days >= g.hold_days:
            sell_flag = True
            reason = '持有到期'

        if sell_flag:
            order_target_value(stock, 0, style)
            log.info(f'{current_date} 卖出 {stock}，{reason}，收益率 {ret:.2%}，持仓天数 {hold_days}')
            # 记录冷却期
            g.cooldown[stock] = current_date + timedelta(days=g.cooldown_days)
            del g.positions[stock]

# ========== 买入函数 ==========
def check_buy(context):
    current_date = context.current_dt.date()
    pre_date = context.previous_date
    current_holdings = list(context.portfolio.positions.keys())

    # 若持仓已达上限，不再买入
    if len(current_holdings) >= g.max_positions:
        log.info(f'持仓已达上限 {g.max_positions}，暂停买入')
        return

    # 获取所有新股候选
    all_stocks = get_all_securities(['stock'])
    new_stocks = []
    for code in all_stocks.index:
        list_date = all_stocks.loc[code, 'start_date']
        if isinstance(list_date, str):
            list_date = pd.to_datetime(list_date).date()
        days_since = (current_date - list_date).days
        if 60 <= days_since <= 250:
            board = get_board(code)
            if board in g.drawdown_threshold:
                new_stocks.append((code, board, list_date))

    # 过滤：已持仓、冷却期内
    new_stocks = [s for s in new_stocks if s[0] not in current_holdings]
    new_stocks = [s for s in new_stocks if s[0] not in g.cooldown or current_date >= g.cooldown[s[0]]]

    if not new_stocks:
        return

    # 计算每个候选的指标并排序
    candidates = []
    for code, board, list_date in new_stocks:
        # 获取日线数据（用于计算回撤和MACD）
        df = get_price(code, start_date=list_date, end_date=pre_date,
                       frequency='daily', fields=['high', 'close'], skip_paused=True, fq='pre')
        if df is None or len(df) < 2:
            continue

        # 回撤计算
        first_high = df.iloc[0]['high']
        if first_high <= 0:
            continue
        pre_close = get_current_data()[code].last_price
        drawdown = pre_close / first_high - 1

        # 判断是否达到回撤阈值
        if drawdown > g.drawdown_threshold[board]:
            continue

        # ---- MACD过滤（柱>0 且 DIF上升） ----
        # 获取足够长的收盘价（至少60个交易日）
        close_series = df['close']
        if len(close_series) < 60:
            # 若数据不足60天，再往前取一些
            extra_days = 60 - len(close_series)
            start_extra = list_date - timedelta(days=extra_days*2)  # 粗略
            df_extra = get_price(code, start_date=start_extra, end_date=pre_date,
                                 frequency='daily', fields=['close'], skip_paused=True, fq='pre')
            if df_extra is not None and len(df_extra) >= 60:
                close_series = df_extra['close']
            else:
                continue   # 数据不足，跳过

        # 计算MACD（返回DIF, DEA, MACD柱）
        def calc_macd(close, fast=12, slow=26, signal=9):
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            dif = ema_fast - ema_slow
            dea = dif.ewm(span=signal, adjust=False).mean()
            macd_hist = 2 * (dif - dea)
            return dif, dea, macd_hist

        dif, dea, macd_hist = calc_macd(close_series)

        # 确保有至少两个DIF值用于比较
        if len(dif) < 2:
            continue

        # 条件1：MACD柱 > 0
        # 条件2：DIF当天 > 前一天（DIF上升）
        if not (macd_hist.iloc[-1] > 0 and dif.iloc[-1] > dif.iloc[-2]):
            continue

        # 通过所有过滤，加入候选
        # 获取市值（用于辅助排序，可选）
        q = query(valuation.code, valuation.market_cap).filter(valuation.code == code)
        df_val = get_fundamentals(q, date=pre_date)
        market_cap = df_val['market_cap'].iloc[0] if not df_val.empty else np.inf

        # 板块权重
        board_weight = {'科创板': 3, '创业板': 2, '主板': 1}[board]
        candidates.append({
            'code': code,
            'board': board,
            'board_weight': board_weight,
            'drawdown': drawdown,
            'market_cap': market_cap,
            'list_date': list_date
        })

    if not candidates:
        return

    # 排序：先按板块权重降序，再按回撤幅度升序（负值越大越靠前）
    candidates.sort(key=lambda x: (-x['board_weight'], x['drawdown']))

    # 限制单日买入数量
    buy_count = min(g.max_buy_count, len(candidates), g.max_positions - len(current_holdings))
    buy_list = candidates[:buy_count]

    if not buy_list:
        return

    # 计算每只股票可分配金额（剩余可用资金均分）
    cash = context.portfolio.available_cash
    per_stock =  cash / buy_count
    if per_stock < 2000:
        log.warn(f'可用资金不足（{cash}），放弃买入')
        return

    for item in buy_list:
        code = item['code']
        current_price = get_current_data()[code].last_price
        style = MarketOrderStyle(current_price * 1.01)
        order_target_value(code, per_stock, style)
        # 记录买入信息
        g.positions[code] = {
            'buy_date': current_date,
            'buy_price': current_price,
            'high_price': current_price
        }
        # 若有冷却记录则清除
        if code in g.cooldown:
            del g.cooldown[code]
        log.info(f'{current_date} 买入 {code}，板块 {item["board"]}，回撤 {item["drawdown"]:.2%}，买入价 {current_price:.2f}，分配资金 {per_stock:.2f}')

# 辅助函数：判断股票所属板块
def get_board(code):
    if code.startswith('688'):
        return '科创板'
    elif code.startswith('30'):
        return '创业板'
    elif code.startswith('60') or code.startswith('00'):
        return '主板'
    else:
        return '其他'