"""
CTA趋势跟随ETF策略
基于均线突破+ADX趋势确认的趋势跟踪策略
交易标的：沪深场内ETF（宽基指数ETF、行业ETF、商品ETF等）
预期收益：年化20%

策略逻辑：
1. 使用20/60日均线判断趋势方向
2. 使用ADX指标确认趋势强度（ADX>25为强趋势）
3. 使用ATR动态计算止损止盈位
4. 跟踪止损保护利润
5. 独立账户管理+风险控制
"""

import pickle
from collections import defaultdict
import math
import traceback
import datetime

# 持久化文件
cta_hold_info_file = "cta_etf_hold_info.pkl"
cta_daily_loss_file = "cta_etf_daily_loss.pkl"
cta_account_file = "cta_etf_account_info.pkl"


def initialize(context):
    """
    策略初始化
    设置策略参数、初始化账户、加载持久化数据
    """
    # ========== 策略参数 ==========
    # 均线系统
    g.ma_short = 20  # 短期均线
    g.ma_long = 60  # 长期均线

    # ADX趋势强度指标
    g.adx_period = 14  # ADX计算周期
    g.adx_threshold = 25  # ADX趋势强度阈值（>25认为趋势较强）
    g.adx_low_threshold = 20  # ADX趋势转弱阈值

    # ATR波动率指标
    g.atr_period = 10  # ATR计算周期
    g.atr_stop_loss = 1.5  # ATR止损倍数（1.5倍ATR）
    g.atr_take_profit = 3.0  # ATR止盈倍数（3倍ATR，盈亏比2:1）
    g.track_stop_loss = 1.5  # 跟踪止损ATR倍数

    # 资金管理参数
    g.total_capital = 1000000  # 初始资金100万
    g.single_position_ratio = 0.15  # 单只ETF仓位上限15%（ETF波动较小，可适当提高）
    g.max_total_position = 0.9  # 总仓位上限90%
    g.max_hold_count = 5  # 最大持仓数量
    g.daily_loss_limit = 0.015  # 单日最大亏损限制1.5%

    # 交易费用
    g.commission_rate = 0.00015  # 佣金万1.5
    g.tax_rate = 0.001  # 印花税千1（卖出，ETF免印花税但代码保留兼容）

    # 持仓管理
    g.max_hold_days = 30  # 最大持仓天数（ETF趋势持续性可能更长）

    # 辅助变量
    g.hold_info = defaultdict(list)  # 持仓信息
    g.daily_loss = 0.0  # 当日亏损
    g.order_flag = defaultdict(bool)  # 订单标记
    g.daily_trade_count = 0  # 当日交易次数

    # ========== 独立账户系统 ==========
    g.acc = {
        "initial_capital": 1000000.0,  # 初始资金
        "cash": 1000000.0,  # 可用现金
        "positions_value": 0.0,  # 持仓市值
        "total_value": 1000000.0,  # 总资产
        "daily_pnl": 0.0,  # 当日盈亏
        "closed_pnl": 0.0,  # 当日已平仓盈亏
        "cumulative_pnl": 0.0,  # 累计收益
        "cumulative_return": 0.0,  # 累计收益率
        "annualized_return": 0.0,  # 年化收益率
        "prev_total_value": 1000000.0,  # 昨日总资产
        "max_drawdown": 0.0,  # 最大回撤
        "high_water_mark": 1000000.0,  # 最高净值
    }
    g.acc_pos = defaultdict(dict)  # 持仓明细
    g.start_date = None
    g.notebook_path = get_research_path()

    # 目标ETF列表（主要宽基指数ETF）
    g.target_etfs = [
        # 宽基指数ETF（A股）
        "510300.SS",  # 华泰柏瑞沪深300ETF
        "510500.SS",  # 南方中证500ETF
        "510050.SS",  # 华夏上证50ETF
        "159915.SZ",  # 易方达创业板ETF
        "588000.SS",  # 华夏上证科创板50ETF
        "159949.SZ",  # 华安创业板50ETF
        # 境外ETF（QDII）
        "513100.SS",  # 国泰纳指ETF（跟踪纳斯达克100）
        "513500.SS",  # 博时标普500ETF
        "513050.SS",  # 易方达中证海外互联ETF（跟踪中概互联）
        "513520.SS",  # 华夏日经225ETF
        "159866.SZ",  # 南方日经225ETF
        "520830.SS",  # 南方沙特ETF
        "159329.SZ",  # 华泰柏瑞沙特ETF
        "513350.SS",  # 华安标普油气ETF
        "159941.SZ",  # 广发纳指100ETF
        "513300.SS",  # 华夏纳斯达克100ETF
        # 港股ETF
        "159920.SZ",  # 华夏恒生ETF
        "510900.SS",  # 易方达恒生国企ETF
        "513130.SS",  # 华泰柏瑞恒生科技ETF
        "513180.SS",  # 华夏恒生科技ETF
        "513060.SS",  # 博时恒生医疗ETF
        # 商品ETF
        "518880.SS",  # 华安黄金ETF
        "159934.SZ",  # 易方达黄金ETF
        "159985.SZ",  # 华夏饲料豆粕期货ETF
        "159981.SZ",  # 建信易盛能源化工期货ETF
        "159980.SZ",  # 华夏易盛郑商所能源化工期货ETF
        "513680.SS",  # 建信恒生红利ETF
        # 行业ETF（A股）
        "512000.SS",  # 华宝中证全指证券ETF
        "512480.SS",  # 国联安中证全指半导体ETF
        "515030.SS",  # 华夏中证新能源汽车ETF
        "515700.SS",  # 平安中证新能源汽车ETF
        "512170.SS",  # 华宝中证医疗ETF
        "512010.SS",  # 易方达沪深300医药ETF
        "159928.SZ",  # 汇添富中证主要消费ETF
        "159819.SZ",  # 易方达中证人工智能ETF
        "515880.SS",  # 国泰中证全指通信设备ETF
        "512760.SS",  # 国泰CES半导体芯片ETF
        "512690.SS",  # 鹏华中证酒ETF
        "515050.SS",  # 华夏中证5G通信主题ETF
        "515210.SS",  # 国泰中证煤炭ETF
        "516160.SS",  # 南方中证新能源ETF
        "510880.SS",  # 华泰柏瑞红利ETF
        "512800.SS",  # 华宝中证银行ETF
        "512200.SS",  # 南方中证全指房地产ETF
        "512660.SS",  # 国泰中证军工ETF
        "515180.SS",  # 红利低波100ETF
    ]

    # 持久化加载
    load_persist()

    # 回测设置
    if get_frequency() == "1d":
        set_benchmark("510300.SS")  # 以沪深300ETF为基准
        set_commission(commission_rate=g.commission_rate)
        set_fixed_slippage(0.0001)  # 固定滑点万1

    log.info("CTA ETF策略启动：20/60均线，ADX14，ATR10，目标年化20%")
    log.info(f"目标ETF池：{len(g.target_etfs)}只")


def load_persist():
    """加载持久化数据"""
    try:
        with open(g.notebook_path + cta_hold_info_file, "rb") as f:
            g.hold_info = pickle.load(f)
        with open(g.notebook_path + cta_daily_loss_file, "rb") as f:
            g.daily_loss = pickle.load(f)
        with open(g.notebook_path + cta_account_file, "rb") as f:
            g.acc = pickle.load(f)
            g.acc_pos = pickle.load(f)
            g.start_date = pickle.load(f)
        log.info("独立账户加载成功")
    except:
        log.info("初始化全新独立账户（100万）")
        g.acc = {
            "initial_capital": 1000000.0,
            "cash": 1000000.0,
            "positions_value": 0.0,
            "total_value": 1000000.0,
            "daily_pnl": 0.0,
            "closed_pnl": 0.0,
            "cumulative_pnl": 0.0,
            "cumulative_return": 0.0,
            "annualized_return": 0.0,
            "prev_total_value": 1000000.0,
            "max_drawdown": 0.0,
            "high_water_mark": 1000000.0,
        }
        g.acc_pos = defaultdict(dict)
        g.start_date = datetime.datetime.now().date()


def before_trading_start(context, data):
    """
    盘前准备
    1. 重置每日变量
    2. 筛选交易标的
    3. 清理不在池中的持仓
    """
    # 每日重置
    g.daily_loss = 0.0
    g.daily_trade_count = 0
    g.acc["daily_pnl"] = 0.0
    g.acc["closed_pnl"] = 0.0
    g.acc["prev_total_value"] = g.acc["total_value"]

    # 筛选ETF池（检查流动性和数据完整性）
    valid_pool = []
    for etf in g.target_etfs:
        try:
            # 获取历史数据检查流动性
            hist = get_history(20, "1d", ["volume", "amount"], etf, fq="pre")
            avg_volume = hist["volume"].mean()
            avg_amount = hist["amount"].mean()

            # ETF筛选条件：日均成交额>5000万，数据完整
            if avg_amount >= 50000000 and len(hist) >= 20:
                valid_pool.append(etf)
        except:
            continue

    g.security_pool = valid_pool
    set_universe(g.security_pool)
    log.info(f"今日ETF池：{len(g.security_pool)}只")

    # 强制平仓不在池中的ETF
    for sec in list(g.hold_info.keys()):
        if sec not in g.security_pool:
            order_target(sec, 0)
            if sec in g.acc_pos:
                del g.acc_pos[sec]
            del g.hold_info[sec]
            g.daily_trade_count += 1
            log.info(f"{sec} 不在ETF池中，强制平仓")

    acc_refresh()
    save_persist()


def handle_data(context, data):
    """
    主交易逻辑
    1. 风控检查
    2. 遍历ETF池计算指标
    3. 持仓管理（止损/止盈/跟踪止损/趋势反转）
    4. 开新仓
    """
    # 单日风控
    if g.daily_loss >= g.daily_loss_limit * g.total_capital:
        log.warning("单日亏损达标，暂停交易")
        return

    # 检查持仓数量上限
    current_hold_count = len(g.hold_info)

    for sec in g.security_pool:
        try:
            # ========== 指标计算 ==========
            # 均线数据
            ma_data = get_history(g.ma_long, "1d", "close", sec, fq="pre")
            ma_short = ma_data["close"].tail(g.ma_short).mean()
            ma_long = ma_data["close"].mean()

            # ATR数据
            atr_data = get_history(
                g.adx_period + g.atr_period,
                "1d",
                ["high", "low", "close"],
                sec,
                fq="pre",
            )
            atr_data["tr"] = atr_data.apply(
                lambda x: max(
                    x["high"] - x["low"],
                    abs(x["high"] - x["close"]),
                    abs(x["low"] - x["close"]),
                ),
                axis=1,
            )
            atr = atr_data["tr"].tail(g.atr_period).mean()

            # ADX数据
            adx_data = get_history(
                g.adx_period * 3, "1d", ["high", "low", "close"], sec, fq="pre"
            )
            adx_data["prev_close"] = adx_data["close"].shift(1)
            adx_data["tr"] = adx_data.apply(
                lambda r: max(
                    r["high"] - r["low"],
                    abs(r["high"] - r["prev_close"]),
                    abs(r["low"] - r["prev_close"]),
                ),
                axis=1,
            )
            adx_data["up_move"] = adx_data["high"] - adx_data["high"].shift(1)
            adx_data["down_move"] = adx_data["low"].shift(1) - adx_data["low"]
            adx_data["plus_dm"] = adx_data.apply(
                lambda r: (
                    r["up_move"]
                    if r["up_move"] > 0 and r["up_move"] > r["down_move"]
                    else 0
                ),
                axis=1,
            )
            adx_data["minus_dm"] = adx_data.apply(
                lambda r: (
                    r["down_move"]
                    if r["down_move"] > 0 and r["down_move"] > r["up_move"]
                    else 0
                ),
                axis=1,
            )

            tr_sum = adx_data["tr"].rolling(g.adx_period, min_periods=1).sum()
            plus_di = (
                100
                * adx_data["plus_dm"].rolling(g.adx_period, min_periods=1).sum()
                / tr_sum
            )
            minus_di = (
                100
                * adx_data["minus_dm"].rolling(g.adx_period, min_periods=1).sum()
                / tr_sum
            )
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)
            current_adx = (
                dx.rolling(g.adx_period, min_periods=1).mean().iloc[-1]
                if len(dx.dropna()) > 0
                else 0
            )

            # 成交量趋势
            vol_data = get_history(5, "1d", "volume", sec)
            vol_trend = vol_data["volume"].diff().mean()

            # 当前价格和持仓
            current_price = data[sec]["close"]
            amt = (
                context.portfolio.positions[sec].amount
                if sec in context.portfolio.positions
                else 0
            )

            # ========== 持仓管理（平仓逻辑） ==========
            if sec in g.hold_info:
                open_p, sl, tp, ts, days = g.hold_info[sec]
                days += 1

                # 更新跟踪止损位（取最高）
                ts = max(current_price - g.track_stop_loss * atr, open_p, ts)

                # 1. 止损
                if current_price <= sl:
                    close_position(sec, current_price, "止损")
                    continue

                # 2. 止盈或跟踪止损
                if current_price >= tp or current_price <= ts:
                    close_position(
                        sec,
                        current_price,
                        "止盈" if current_price >= tp else "跟踪止损",
                    )
                    continue

                # 3. 趋势反转（ADX转弱+均线死叉）
                if current_adx < g.adx_low_threshold and ma_short < ma_long:
                    close_position(sec, current_price, "趋势反转")
                    continue

                # 4. 持仓超时
                if days > g.max_hold_days:
                    close_position(sec, current_price, "持仓超时")
                    continue

                # 更新持仓信息
                g.hold_info[sec] = [open_p, sl, tp, ts, days]

            # ========== 开仓逻辑 ==========
            else:
                # 检查持仓数量上限
                if current_hold_count >= g.max_hold_count:
                    continue

                # 检查总仓位上限
                pos_ratio = (
                    context.portfolio.positions_value / context.portfolio.total_value
                )
                if pos_ratio >= g.max_total_position:
                    continue

                # 做多信号：均线多头排列 + 价格站上短期均线 + 放量 + ADX确认趋势
                long_signal = (
                    ma_short > ma_long  # 短期均线上穿长期均线
                    and current_price > ma_short  # 价格站上短期均线
                    and vol_trend > 0  # 成交量增加
                    and current_adx > g.adx_threshold  # ADX确认强趋势
                )

                if long_signal:
                    # 计算买入金额
                    max_single = g.total_capital * g.single_position_ratio
                    available_cash = min(max_single, context.portfolio.cash)

                    # 最小交易金额检查（100股起）
                    if available_cash < 100 * current_price:
                        continue

                    # 计算买入数量（100股整数倍）
                    qty = math.floor(available_cash / current_price / 100) * 100
                    if qty < 100:
                        continue

                    # 计算止损止盈位
                    sl_p = current_price - g.atr_stop_loss * atr
                    tp_p = current_price + g.atr_take_profit * atr

                    # 执行买入
                    order(sec, qty, limit_price=round(current_price, 3))

                    # 独立账户记账
                    cost = qty * current_price
                    commission = cost * g.commission_rate
                    g.acc["cash"] -= cost + commission
                    g.acc_pos[sec] = {"amount": qty, "cost_price": current_price}

                    # 记录持仓信息
                    g.hold_info[sec] = [current_price, sl_p, tp_p, current_price, 1]
                    current_hold_count += 1
                    g.daily_trade_count += 1

                    log.info(
                        f"【开仓】{sec} {qty}股 @ {current_price:.3f}, "
                        f"止损{sl_p:.3f} 止盈{tp_p:.3f} ADX:{current_adx:.1f}"
                    )

        except Exception as e:
            log.error(f"{sec} 处理异常：{e}")
            continue

    acc_refresh()
    save_persist()


def close_position(sec, current_price, reason):
    """
    平仓处理
    """
    if sec not in g.hold_info or sec not in g.acc_pos:
        return

    pos = g.acc_pos[sec]
    qty = pos["amount"]
    cost_price = pos["cost_price"]

    # 执行卖出
    order_target(sec, 0)

    # 计算盈亏
    turnover = qty * current_price
    commission = turnover * g.commission_rate
    tax = turnover * g.tax_rate
    pnl = (current_price - cost_price) * qty - commission - tax

    # 更新独立账户
    g.acc["cash"] += turnover - commission - tax
    g.acc["closed_pnl"] += pnl

    if pnl < 0:
        g.daily_loss += abs(pnl)

    # 清理持仓记录
    del g.acc_pos[sec]
    del g.hold_info[sec]
    g.daily_trade_count += 1

    log.info(f"【平仓】{sec} {reason}, 盈亏{pnl:.2f} @ {current_price:.3f}")


def after_trading_end(context, data):
    """
    盘后处理
    计算收益、输出日志、保存持久化数据
    """
    acc_refresh()
    calc_returns()

    # 平台账户信息
    plat_pnl = context.portfolio.total_value - g.total_capital
    plat_pos = (
        context.portfolio.positions_value / context.portfolio.total_value
        if context.portfolio.total_value > 0
        else 0
    )

    # 独立账户信息
    log.info("=" * 60)
    log.info("【CTA ETF策略 - 盘后报告】")
    log.info("-" * 60)
    log.info(f"平台实盘 | 总盈亏: {plat_pnl:,.2f} | 仓位: {plat_pos * 100:.1f}%")
    log.info("-" * 60)
    log.info(f"独立账户 | 初始: {g.acc['initial_capital']:,.2f}")
    log.info(f"         | 当前: {g.acc['total_value']:,.2f}")
    log.info(
        f"         | 当日盈亏: {g.acc['daily_pnl']:,.2f} ({g.acc['daily_pnl'] / g.acc['initial_capital'] * 100:.2f}%)"
    )
    log.info(
        f"         | 累计盈亏: {g.acc['cumulative_pnl']:,.2f} ({g.acc['cumulative_return'] * 100:.2f}%)"
    )
    log.info(f"         | 年化收益: {g.acc['annualized_return'] * 100:.2f}%")
    log.info(f"         | 最大回撤: {g.acc['max_drawdown'] * 100:.2f}%")
    log.info(
        f"         | 现金: {g.acc['cash']:,.2f} | 持仓: {g.acc['positions_value']:,.2f}"
    )
    log.info("-" * 60)

    # 持仓详情
    if g.hold_info:
        log.info(f"当前持仓 ({len(g.hold_info)}只):")
        for sec, info in g.hold_info.items():
            open_p, sl, tp, ts, days = info
            log.info(f"  {sec} 成本{open_p:.3f} 持仓{days}天 SL:{sl:.3f} TP:{tp:.3f}")
    else:
        log.info("当前无持仓")

    log.info("-" * 60)
    log.info(f"当日交易次数: {g.daily_trade_count}")
    log.info("=" * 60)

    if g.daily_trade_count > 15:
        log.warning(f"当日交易{g.daily_trade_count}次，注意合规")

    save_persist()


def acc_refresh():
    """
    刷新账户信息
    计算持仓市值和当日盈亏
    """
    # 计算持仓市值
    pos_val = 0.0
    for code, pos in g.acc_pos.items():
        try:
            close = get_history(1, "1d", "close", code, fq="pre")["close"].iloc[-1]
            pos_val += pos["amount"] * close
        except:
            # 使用成本价作为 fallback
            pos_val += pos["amount"] * pos["cost_price"]

    g.acc["positions_value"] = pos_val
    g.acc["total_value"] = g.acc["cash"] + pos_val

    # 计算当日盈亏
    float_pnl = g.acc["total_value"] - g.acc["prev_total_value"] - g.acc["closed_pnl"]
    g.acc["daily_pnl"] = float_pnl + g.acc["closed_pnl"]

    # 更新最大回撤
    if g.acc["total_value"] > g.acc["high_water_mark"]:
        g.acc["high_water_mark"] = g.acc["total_value"]
    current_dd = (g.acc["high_water_mark"] - g.acc["total_value"]) / g.acc[
        "high_water_mark"
    ]
    if current_dd > g.acc["max_drawdown"]:
        g.acc["max_drawdown"] = current_dd


def calc_returns():
    """
    计算收益率指标
    """
    ini = g.acc["initial_capital"]
    total = g.acc["total_value"]

    g.acc["cumulative_pnl"] = total - ini
    g.acc["cumulative_return"] = g.acc["cumulative_pnl"] / ini if ini != 0 else 0

    # 年化收益
    days = (datetime.datetime.now().date() - g.start_date).days or 1
    years = days / 365.0
    if years > 0:
        g.acc["annualized_return"] = (1 + g.acc["cumulative_return"]) ** (1 / years) - 1
    else:
        g.acc["annualized_return"] = 0


def save_persist():
    """
    保存持久化数据
    """
    try:
        with open(g.notebook_path + cta_hold_info_file, "wb") as f:
            pickle.dump(g.hold_info, f, -1)
        with open(g.notebook_path + cta_daily_loss_file, "wb") as f:
            pickle.dump(g.daily_loss, f, -1)
        with open(g.notebook_path + cta_account_file, "wb") as f:
            pickle.dump(g.acc, f, -1)
            pickle.dump(g.acc_pos, f, -1)
            pickle.dump(g.start_date, f, -1)
    except Exception as e:
        log.error(f"持久化保存失败: {e}")
