import pickle
from collections import defaultdict
import math
import traceback
import datetime

cta_hold_info_file = 'cta_hold_info427.pkl'
cta_daily_loss_file = 'cta_daily_loss427.pkl'
cta_account_file = 'cta_account_info427.pkl'

def initialize(context):
    # ========== 原有策略参数 完全不变 ==========
    g.ma_short = 20
    g.ma_long = 60
    g.adx_period = 14
    g.adx_threshold = 25
    g.adx_low_threshold = 20
    g.atr_period = 10
    g.atr_stop_loss = 1.5
    g.atr_take_profit = 3
    g.track_stop_loss = 1.5

    # 资金参数
    g.total_capital = 1000000
    g.single_position_ratio = 0.1
    g.max_total_position = 1
    g.daily_loss_limit = 0.01
    g.commission_rate = 0.00015    # 佣金万1.5
    g.tax_rate = 0.001             # 印花税千1（卖出）

    # 辅助变量
    g.hold_info = defaultdict(list)
    g.daily_loss = 0.0
    g.order_flag = defaultdict(bool)
    g.daily_trade_count = 0

    # ========== 独立账户（修复版：完全对齐实盘） ==========
    g.acc = {
        "initial_capital": 1000000.0,
        "cash": 1000000.0,                # 真实可用资金
        "positions_value": 0.0,           # 持仓市值（市价）
        "total_value": 1000000.0,         # 现金+持仓
        "daily_pnl": 0.0,                 # 当日真实盈亏（含浮动）
        "closed_pnl": 0.0,                # 当日已平仓盈亏
        "cumulative_pnl": 0.0,            # 累计收益
        "cumulative_return": 0.0,         # 累计收益率
        "annualized_return": 0.0,
        "prev_total_value": 1000000.0     # 昨日总资产（算当日盈亏用）
    }
    g.acc_pos = defaultdict(dict)  # 持仓：{代码: {amount, cost_price}}
    g.start_date = None
    g.notebook_path = get_research_path()

    # 持久化加载
    try:
        with open(g.notebook_path + cta_hold_info_file, 'rb') as f:
            g.hold_info = pickle.load(f)
        with open(g.notebook_path + cta_daily_loss_file, 'rb') as f:
            g.daily_loss = pickle.load(f)
        with open(g.notebook_path + cta_account_file, 'rb') as f:
            g.acc = pickle.load(f)
            g.acc_pos = pickle.load(f)
            g.start_date = pickle.load(f)
        log.info("独立账户加载成功")
    except:
        log.info("初始化全新独立账户（100万）")
        g.acc = {
            "initial_capital": 1000000.0, "cash": 1000000.0,
            "positions_value": 0.0, "total_value": 1000000.0,
            "daily_pnl": 0.0, "closed_pnl": 0.0,
            "cumulative_pnl": 0.0, "cumulative_return": 0.0,
            "annualized_return": 0.0, "prev_total_value": 1000000.0
        }
        g.acc_pos = defaultdict(dict)
        g.start_date = datetime.datetime.now().date()

    # 回测设置
    if get_frequency() == '1d':
        set_benchmark('000905.SS')
        set_commission(commission_rate=g.commission_rate)
        set_fixed_slippage(0.0001)

    log.info("CTA策略启动：20/60均线，ADX14，ATR10")

def before_trading_start(context, data):
    # 每日重置
    g.daily_loss = 0.0
    g.daily_trade_count = 0
    g.acc["daily_pnl"] = 0.0
    g.acc["closed_pnl"] = 0.0
    g.acc["prev_total_value"] = g.acc["total_value"]  # 昨日总资产

    # 标的池（完全原版）
    g.cs500_candidates = get_index_stocks('000905.SS')
    valid_pool = []
    st_status = get_stock_status(g.cs500_candidates, 'ST')
    for security in g.cs500_candidates:
        try:
            hist = get_history(20, '1d', 'volume', security, fq='qfq')
            if not st_status[security] and hist['volume'].mean() >= 50000000:
                valid_pool.append(security)
        except:
            continue
    g.security_pool = valid_pool[:500]
    set_universe(g.security_pool)

    # 强制平仓（不在池标的）
    for sec in list(g.hold_info.keys()):
        if sec not in g.security_pool:
            order_target(sec, 0)
            if sec in g.acc_pos:
                del g.acc_pos[sec]
            del g.hold_info[sec]
            g.daily_trade_count +=1

    acc_refresh()
    save_persist()

def handle_data(context, data):
    # 单日风控
    if g.daily_loss >= g.daily_loss_limit * g.total_capital:
        log.warning("单日亏损达标，暂停交易")
        return

    for sec in g.security_pool:
        try:
            # ========== 指标计算（完全原版） ==========
            ma_data = get_history(g.ma_long, '1d', 'close', sec, fq='pre')
            atr_data = get_history(g.adx_period+g.atr_period, '1d', ['high','low','close'], sec, fq='pre')
            adx_data = get_history(g.adx_period*3, '1d', ['high','low','close'], sec, fq='pre')
            ma_short = ma_data['close'].tail(g.ma_short).mean()
            ma_long = ma_data['close'].mean()
            current_price = data[sec]['close']

            # ATR
            atr_data['tr'] = atr_data.apply(lambda x: max(x['high']-x['low'],abs(x['high']-x['close']),abs(x['low']-x['close'])),1)
            atr = atr_data['tr'].tail(g.atr_period).mean()

            # ADX
            adx_data['prev_close'] = adx_data['close'].shift(1)
            adx_data['tr'] = adx_data.apply(lambda r: max(r['high']-r['low'],abs(r['high']-r['prev_close']),abs(r['low']-r['prev_close'])),1)
            adx_data['up_move'] = adx_data['high'] - adx_data['high'].shift(1)
            adx_data['down_move'] = adx_data['low'].shift(1) - adx_data['low']
            adx_data['plus_dm'] = adx_data.apply(lambda r: r['up_move'] if r['up_move']>0 and r['up_move']>r['down_move'] else 0, 1)
            adx_data['minus_dm'] = adx_data.apply(lambda r: r['down_move'] if r['down_move']>0 and r['down_move']>r['up_move'] else 0, 1)
            tr_sum = adx_data['tr'].rolling(g.adx_period, min_periods=1).sum()
            plus_di = 100 * adx_data['plus_dm'].rolling(g.adx_period, min_periods=1).sum() / tr_sum
            minus_di = 100 * adx_data['minus_dm'].rolling(g.adx_period, min_periods=1).sum() / tr_sum
            dx = 100 * abs(plus_di-minus_di)/(plus_di+minus_di+1e-8)
            current_adx = dx.rolling(g.adx_period, min_periods=1).mean().iloc[-1] if len(dx.dropna())>0 else 0

            vol5 = get_history(5, '1d', 'volume', sec)['volume']
            vol_trend = vol5.diff().mean()
            amt = context.portfolio.positions[sec].amount

            # ========== 平仓（完全原版 + 独立账户精准记账） ==========
            if sec in g.hold_info:
                open_p, sl, tp, ts, days = g.hold_info[sec]
                days +=1
                ts = max(current_price - g.track_stop_loss*atr, open_p, sl)

                # 止损
                if current_price <= sl:
                    order_target(sec, 0)
                    loss = (open_p - current_price)*amt
                    g.daily_loss += loss
                    g.daily_trade_count +=1
                    # 独立账户：卖出+费用+盈亏
                    if sec in g.acc_pos:
                        pos = g.acc_pos[sec]
                        turnover = pos['amount'] * current_price
                        commission = turnover * g.commission_rate
                        tax = turnover * g.tax_rate
                        g.acc["cash"] += turnover - commission - tax
                        g.acc["closed_pnl"] += (current_price - pos['cost_price'])*pos['amount'] - commission - tax
                        del g.acc_pos[sec]
                    del g.hold_info[sec]
                    log.info(f"{sec} 止损，亏损{loss:.2f}")
                    continue

                # 止盈/跟踪止盈
                if current_price >= tp or current_price <= ts:
                    order_target(sec, 0)
                    profit = (current_price-open_p)*amt
                    g.daily_trade_count +=1
                    if sec in g.acc_pos:
                        pos = g.acc_pos[sec]
                        turnover = pos['amount']*current_price
                        commission = turnover*g.commission_rate
                        tax = turnover*g.tax_rate
                        g.acc["cash"] += turnover-commission-tax
                        g.acc["closed_pnl"] += (current_price-pos['cost_price'])*pos['amount']-commission-tax
                        del g.acc_pos[sec]
                    del g.hold_info[sec]
                    log.info(f"{sec} 止盈，盈利{profit:.2f}")
                    continue

                # 趋势反转
                if current_adx < g.adx_low_threshold:
                    if (ma_short<ma_long and open_p<ma_long) or (ma_short>ma_long and open_p>ma_long):
                        order_target(sec,0)
                        profit = (current_price-open_p)*amt
                        g.daily_trade_count +=1
                        if sec in g.acc_pos:
                            pos = g.acc_pos[sec]
                            turnover = pos['amount']*current_price
                            commission = turnover*g.commission_rate
                            tax = turnover*g.tax_rate
                            g.acc["cash"] += turnover-commission-tax
                            g.acc["closed_pnl"] += (current_price-pos['cost_price'])*pos['amount']-commission-tax
                            del g.acc_pos[sec]
                        del g.hold_info[sec]
                        log.info(f"{sec} 趋势反转，盈亏{profit:.2f}")
                        continue

                # 持仓超时
                if days>20:
                    order_target(sec,0)
                    profit = (current_price-open_p)*amt
                    g.daily_trade_count +=1
                    if sec in g.acc_pos:
                        pos = g.acc_pos[sec]
                        turnover = pos['amount']*current_price
                        commission = turnover*g.commission_rate
                        tax = turnover*g.tax_rate
                        g.acc["cash"] += turnover-commission-tax
                        g.acc["closed_pnl"] += (current_price-pos['cost_price'])*pos['amount']-commission-tax
                        del g.acc_pos[sec]
                    del g.hold_info[sec]
                    log.info(f"{sec} 持仓超时，盈亏{profit:.2f}")
                    continue

                g.hold_info[sec] = [open_p, sl, tp, ts, days]

            # ========== 开仓（完全原版 + 独立账户精准记账） ==========
            else:
                long_ok = (ma_short>ma_long) and (current_price>ma_short) and (vol_trend>0) and (current_adx>g.adx_threshold)
                if long_ok:
                    max_single = g.total_capital * g.single_position_ratio
                    pos_ratio = context.portfolio.positions_value/context.portfolio.total_value
                    if pos_ratio >= g.max_total_position:
                        continue
                    buy_money = min(max_single, context.portfolio.cash)
                    if buy_money < 100*current_price:
                        continue
                    qty = math.floor(buy_money/current_price/100)*100
                    sl_p = current_price - g.atr_stop_loss*atr
                    tp_p = current_price + g.atr_take_profit*atr

                    # 真实下单
                    order(sec, qty, limit_price=round(current_price,2))

                    # 独立账户：买入+扣佣金
                    cost = qty * current_price
                    commission = cost * g.commission_rate
                    g.acc["cash"] -= (cost + commission)
                    g.acc_pos[sec] = {"amount": qty, "cost_price": current_price}

                    g.hold_info[sec] = [current_price, sl_p, tp_p, current_price, 1]
                    g.daily_trade_count +=1
                    log.info(f"{sec} 开仓{qty}股，成本{current_price}")

        except Exception as e:
            log.error(f"{sec} 异常：{e}")
            continue

    acc_refresh()
    save_persist()

def after_trading_end(context, data):
    acc_refresh()
    calc_returns()

    # 平台账户
    plat_pnl = context.portfolio.total_value - g.total_capital
    plat_pos = context.portfolio.positions_value / context.portfolio.total_value
    log.info(f"【平台实盘】总盈亏{plat_pnl:.2f}，仓位{plat_pos*100:.1f}%")

    # 独立账户（完全对齐）
    log.info("【独立统计账户】")
    log.info(f"  初始：{g.acc['initial_capital']:.2f} | 总资产：{g.acc['total_value']:.2f}")
    log.info(f"  当日盈亏：{g.acc['daily_pnl']:.2f}({g.acc['daily_pnl']/g.acc['initial_capital']*100:.2f}%)")
    log.info(f"  累计：{g.acc['cumulative_pnl']:.2f}({g.acc['cumulative_return']*100:.2f}%) | 年化：{g.acc['annualized_return']*100:.2f}%")
    log.info(f"  现金：{g.acc['cash']:.2f} | 持仓市值：{g.acc['positions_value']:.2f}")

    log.info(f"持仓：{list(g.hold_info.keys())}" if g.hold_info else "无持仓")
    if g.daily_trade_count>15:
        log.warning(f"当日交易{g.daily_trade_count}次，注意合规")

    save_persist()

# ========== 核心修复：账户刷新（市价+真实盈亏） ==========
def acc_refresh():
    # 1. 持仓市值（当日收盘价）
    pos_val = 0.0
    for code, pos in g.acc_pos.items():
        try:
            # 正确取当日价
            close = get_history(1, '1d', 'close', code, fq='pre')['close'].iloc[-1]
            pos_val += pos['amount'] * close
        except:
            pass
    g.acc["positions_value"] = pos_val
    g.acc["total_value"] = g.acc["cash"] + pos_val

    # 2. 当日真实盈亏 = 浮动盈亏 + 已平仓盈亏
    float_pnl = g.acc["total_value"] - g.acc["prev_total_value"] - g.acc["closed_pnl"]
    g.acc["daily_pnl"] = float_pnl + g.acc["closed_pnl"]

def calc_returns():
    ini = g.acc["initial_capital"]
    total = g.acc["total_value"]
    g.acc["cumulative_pnl"] = total - ini
    g.acc["cumulative_return"] = g.acc["cumulative_pnl"] / ini if ini !=0 else 0

    days = (datetime.datetime.now().date() - g.start_date).days or 1
    years = days / 365.0
    if years>0:
        g.acc["annualized_return"] = (1+g.acc["cumulative_return"])**(1/years)-1
    else:
        g.acc["annualized_return"] = 0

def save_persist():
    try:
        with open(g.notebook_path+cta_hold_info_file,'wb') as f:
            pickle.dump(g.hold_info,f,-1)
        with open(g.notebook_path+cta_daily_loss_file,'wb') as f:
            pickle.dump(g.daily_loss,f,-1)
        with open(g.notebook_path+cta_account_file,'wb') as f:
            pickle.dump(g.acc,f,-1)
            pickle.dump(g.acc_pos,f,-1)
            pickle.dump(g.start_date,f,-1)
    except:
        pass