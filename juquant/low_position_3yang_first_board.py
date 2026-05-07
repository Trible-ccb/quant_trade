# =============================================================================
# 聚宽平台 · 低位3连阳首板接力策略
# =============================================================================
# 【策略来源】
#   参考自聚宽社区用户"顶级理解"分享的帖子：
#   https://www.joinquant.com/view/community/detail/80b2a638c6ca291fb60cc80a8ef50747
#
# 【核心逻辑】
#   选股（5层过滤）：
#     1. 量价过滤（核心条件）：
#        a. 大前天(T-3)+前天(T-2)+昨天(T-1)连续3阳线
#        b. 昨日成交量 ≥ 前日2倍（明显放量）
#        c. 前两日(T-3和T-2)涨幅均 < 5%（防止追高）
#        d. 排除异常爆量（涨停日成交量>8倍均量或>12倍最小量且股价创新高）
#        e. 成交额5-30亿（流动性要求）
#     2. 集合竞价过滤：
#        a. 竞价成交量 ≥ 昨日总成交量的3%（有承接）
#        b. 竞价涨幅0%-6%（不追高）
#     3. 首板筛选：昨日涨停但前日未涨停（首次涨停，非连板）
#     4. 波动过滤：剔除近5日波动超过20%的股票
#     5. 市值过滤：30-300亿
#   买入：
#     时机：每日09:30（开盘价买入）
#     仓位：最多持有10只，等资金分配
#   卖出（三层风控）：
#     1. 涨停保护：接近涨停(99%)时不触发卖出
#     2. 线性止盈（分钟级 9:30-11:25）：昨日收阴的股票，冲高超3%后动态回撤控制
#     3. 多条件止损止盈：盈利>50%止盈/当日跌幅<-2%/现价<开盘价-4%/亏损<-7%/跌破5日线-3%
#
# 【回测表现】（2025-01-01 ~ 2026-04-27）
#   收益1602.00%，年化834.95%，回撤13.13%，胜率0.544
#   2026年收益141.25%，年化1859.47%，回撤5.98%，胜率0.818
#
# 【作者】顶级理解（聚宽社区）
# 【整理日期】2026-05-07
# =============================================================================

from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
import datetime


# =============================================================================
# 策略初始化
# =============================================================================

def initialize(context):
    """策略初始化"""
    # -------- 系统设置 --------
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_slippage(FixedSlippage(0))
    set_order_cost(
        OrderCost(open_tax=0, close_tax=0.001,
                  open_commission=0.0003, close_commission=0.0003,
                  close_today_commission=0, min_commission=5),
        type='stock'
    )
    log.set_level('order', 'error')

    # ===== 策略参数 =====
    # 持仓控制
    g.max_hold_count = 10            # 最大同时持仓数
    g.target_list = []               # 当日目标买入列表

    # 持仓记录
    # {stock: {'buy_price': price, 'buy_date': date, 'peak_price': peak}}
    g.hold_stocks = {}

    # -------- 选股参数 --------
    # 量价过滤
    g.volume_ratio_min = 2.0         # 昨日成交量 / 前日成交量 >= 2倍
    g.max_prev_gain = 0.05           # 前两日(T-3,T-2)涨幅均 < 5%
    g.volume_abnormal_ratio = 8.0    # 涨停日成交量 > 8倍均量 → 异常爆量
    g.volume_abnormal_min_ratio = 12.0  # 涨停日成交量 > 12倍最小量 → 异常爆量
    g.amount_min = 5e8               # 成交额下限 5亿
    g.amount_max = 30e8              # 成交额上限 30亿
    g.volume_lookback_days = 20      # 均量计算回看天数

    # 集合竞价过滤
    g.auction_volume_ratio = 0.03    # 竞价成交量 ≥ 昨日总成交量 × 3%
    g.auction_gain_min = 0.00        # 竞价涨幅下限 0%
    g.auction_gain_max = 0.06        # 竞价涨幅上限 6%

    # 波动过滤
    g.max_volatility_5d = 0.20       # 近5日最大波动 ≤ 20%

    # 市值过滤
    g.market_cap_min = 30e8          # 流通市值下限 30亿
    g.market_cap_max = 300e8         # 流通市值上限 300亿

    # -------- 卖出参数 --------
    g.profit_take_profit = 0.50      # 盈利 > 50% → 止盈
    g.day_loss_threshold = -0.02     # 当日跌幅 < -2% → 卖出
    g.price_vs_open_loss = -0.04     # 现价 < 开盘价 - 4% → 卖出
    g.max_loss = -0.07               # 亏损 < -7% → 止损
    g.ma5_loss = -0.03              # 跌破5日均线 -3% → 止损
    g.near_limit_up = 0.99          # 接近涨停(99%)不触发卖出

    # 线性止盈参数
    g.surge_threshold = 0.03         # 冲高超过3%才开始跟踪
    g.use_linear_stop_profit = True  # 是否启用线性止盈

    # -------- 时间调度 --------
    # 9:27 选股（集合竞价结束后，开盘价已确定）
    run_daily(select_stocks, '9:27')
    # 9:30 执行买入
    run_daily(buy_stocks, '09:30')
    # 9:30-11:25 每分钟线性止盈检查（昨日收阴的股票）
    run_minutely(minute_linear_stop_profit, '9:30')
    # 14:50 尾盘统一止损止盈
    run_daily(close_positions_14_50, '14:50')
    # 15:10 打印持仓信息
    run_daily(print_position_info, '15:10')

    log.info('=== 低位3连阳首板接力策略启动 ===')
    log.info(f'最大持仓: {g.max_hold_count}只 | '
             f'量比≥{g.volume_ratio_min}倍 | '
             f'成交额{g.amount_min/1e8:.0f}-{g.amount_max/1e8:.0f}亿 | '
             f'市值{g.market_cap_min/1e8:.0f}-{g.market_cap_max/1e8:.0f}亿')


# =============================================================================
# 1. 选股逻辑（5层过滤）
# =============================================================================

def select_stocks(context):
    """
    9:27 集合竞价后选股
    执行5层过滤，筛选出当日目标股票
    """
    yesterday = context.previous_date
    log.info('=' * 70)
    log.info(f'【选股】日期: {context.current_dt} 上一交易日: {yesterday}')
    log.info('=' * 70)

    # Step 1: 量价过滤（核心条件）
    log.info('[Step1] 量价过滤...')
    candidates = volume_price_filter(context, yesterday)
    log.info(f'  → 量价过滤后: {len(candidates)} 只')

    if not candidates:
        log.info('  ✗ 量价过滤后无候选股票，退出选股')
        g.target_list = []
        return

    # Step 2: 集合竞价过滤
    log.info('[Step2] 集合竞价过滤...')
    candidates = auction_filter(context, candidates)
    log.info(f'  → 竞价过滤后: {len(candidates)} 只')

    if not candidates:
        log.info('  ✗ 竞价过滤后无候选股票，退出选股')
        g.target_list = []
        return

    # Step 3: 首板筛选（昨日涨停但前日未涨停）
    log.info('[Step3] 首板筛选...')
    candidates = first_board_filter(context, yesterday, candidates)
    log.info(f'  → 首板筛选后: {len(candidates)} 只')

    if not candidates:
        log.info('  ✗ 无首板股票，退出选股')
        g.target_list = []
        return

    # Step 4: 波动过滤
    log.info('[Step4] 波动过滤...')
    candidates = volatility_filter(context, yesterday, candidates)
    log.info(f'  → 波动过滤后: {len(candidates)} 只')

    if not candidates:
        log.info('  ✗ 波动过滤后无候选股票，退出选股')
        g.target_list = []
        return

    # Step 5: 市值过滤
    log.info('[Step5] 市值过滤...')
    candidates = market_cap_filter(context, yesterday, candidates)
    log.info(f'  → 市值过滤后: {len(candidates)} 只')

    if not candidates:
        log.info('  ✗ 市值过滤后无候选股票，退出选股')
        g.target_list = []
        return

    # 最终结果
    g.target_list = candidates
    log.info(f'【选股结果】共 {len(candidates)} 只目标股票:')
    for i, s in enumerate(candidates, 1):
        name = get_security_info(s).display_name
        log.info(f'  {i}. {s} ({name})')
    log.info('=' * 70)


def volume_price_filter(context, date):
    """
    Step 1: 量价过滤（核心条件）
    条件：
      a. T-3, T-2, T-1连续3阳线
      b. T-1成交量 >= T-2 × 2倍
      c. T-3和T-2涨幅均 < 5%
      d. 排除异常爆量（涨停日成交量 > 8倍均量 或 > 12倍最小量 且 创新高）
      e. 成交额5-30亿
    """
    # 获取全市场股票
    all_stocks = get_all_securities('stock', date).index.tolist()
    log.debug(f'  全市场: {len(all_stocks)} 只')

    # 基础过滤：ST/停牌/科创板/新股
    all_stocks = filter_basic(all_stocks)
    log.debug(f'  基础过滤后: {len(all_stocks)} 只')

    # 获取T-3, T-2, T-1交易日数据
    # 需要3根日线: T-3, T-2, T-1
    try:
        df = get_price(
            all_stocks,
            end_date=date,
            frequency='daily',
            fields=['open', 'close', 'high', 'low', 'volume', 'money',
                    'high_limit', 'low_limit'],
            count=4,       # 取4天，确保至少有3个交易日数据
            panel=False,
            fill_paused=False,
            skip_paused=True
        )
    except Exception as e:
        log.error(f'获取行情数据失败: {e}')
        return []

    if df.empty:
        return []

    df.index = df.code

    candidates = []
    for stock in all_stocks:
        try:
            if stock not in df.index:
                continue
            sub = df.loc[stock]

            # 确保至少有3根有效数据
            valid_data = sub.dropna(subset=['close', 'open', 'high', 'low', 'volume'])
            if len(valid_data) < 3:
                continue

            # 取最近3天（T-3, T-2, T-1）
            recent = valid_data.iloc[-3:]

            # 条件a: 3连阳（收盘价 > 开盘价 或 收盘价 > 前日收盘价）
            # 这里使用收盘价 > 开盘价作为阳线定义
            for _, row in recent.iterrows():
                if row['close'] <= row['open']:
                    raise ValueError('非阳线')

            # 条件a补充: 昨日(T-1)必须是涨停
            yesterday_row = recent.iloc[-1]
            if yesterday_row['close'] != yesterday_row['high_limit']:
                raise ValueError('昨日未涨停')

            # 条件c: T-3和T-2涨幅均 < 5%
            # T-2涨幅
            gain_t2 = (recent.iloc[-2]['close'] - recent.iloc[-2]['open']) / recent.iloc[-2]['open']
            # T-3涨幅
            gain_t3 = (recent.iloc[-3]['close'] - recent.iloc[-3]['open']) / recent.iloc[-3]['open']

            if abs(gain_t2) >= g.max_prev_gain or abs(gain_t3) >= g.max_prev_gain:
                raise ValueError(f'前两日涨幅超过5%: T-2={gain_t2:.2%}, T-3={gain_t3:.2%}')

            # 条件b: 昨日成交量 >= 前日 × 2倍
            vol_yesterday = recent.iloc[-1]['volume']
            vol_t2 = recent.iloc[-2]['volume']
            if vol_t2 > 0 and vol_yesterday / vol_t2 < g.volume_ratio_min:
                raise ValueError(f'放量不足: {vol_yesterday/vol_t2:.2f}倍 < {g.volume_ratio_min}倍')

            # 条件d: 排除异常爆量
            # 计算过去20日均量
            lookback = min(g.volume_lookback_days, len(valid_data))
            if lookback >= 5 and stock in df.index:
                sub_long = df.loc[stock].dropna(subset=['volume'])
                if len(sub_long) >= 5:
                    avg_volume = sub_long['volume'].iloc[-lookback:-1].mean()
                    min_volume = sub_long['volume'].iloc[-lookback:-1].min()

                    if avg_volume > 0 and min_volume > 0:
                        # 涨停日成交额
                        limit_up_vol = recent.iloc[-1]['volume']

                        # 如果成交量 > 8倍均量 或 > 12倍最小量
                        abnormal = False
                        if limit_up_vol > g.volume_abnormal_ratio * avg_volume:
                            abnormal = True
                        elif limit_up_vol > g.volume_abnormal_min_ratio * min_volume:
                            abnormal = True

                        if abnormal:
                            # 同时检查股价是否创新高
                            price_high = recent.iloc[-1]['high']
                            prev_high = sub_long['high'].iloc[-lookback:-1].max()
                            if prev_high > 0 and price_high > prev_high:
                                raise ValueError(f'异常爆量+创新高，排除')

            # 条件e: 成交额5-30亿
            money_yesterday = recent.iloc[-1]['money']
            if money_yesterday < g.amount_min or money_yesterday > g.amount_max:
                raise ValueError(f'成交额不符合: {money_yesterday/1e8:.2f}亿')

            candidates.append(stock)

        except ValueError as e:
            # 正常过滤，跳过
            continue
        except Exception as e:
            log.debug(f'  [量价过滤] {stock} 异常: {e}')
            continue

    return candidates


def auction_filter(context, candidates):
    """
    Step 2: 集合竞价过滤
    条件：
      a. 竞价成交量（今日开盘第一根分钟线的成交量） >= 昨日总成交量 × 3%
      b. 竞价涨幅（开盘价相对昨日收盘）在 0% ~ 6%
    """
    yesterday = context.previous_date
    current_data = get_current_data()
    filtered = []

    for stock in candidates:
        try:
            # 获取竞价涨幅 = (开盘价 - 昨日收盘) / 昨日收盘
            yesterday_close = current_data[stock].yesterday_close
            today_open = current_data[stock].day_open

            if yesterday_close == 0:
                continue

            auction_gain = (today_open - yesterday_close) / yesterday_close

            # 条件b: 竞价涨幅 0%~6%
            if auction_gain < g.auction_gain_min or auction_gain > g.auction_gain_max:
                continue

            # 条件a: 竞价成交量（使用day_open的对应成交量数据）
            # 在聚宽中，获取9:30前集合竞价的成交量：使用分钟线数据
            # 获取今日的第一根分钟线数据来近似竞价成交量
            today_str = str(context.current_dt.date())
            try:
                minute_data = get_price(
                    stock,
                    start_date=today_str,
                    end_date=today_str,
                    frequency='1m',
                    fields=['volume', 'money'],
                    count=1,
                    panel=False,
                    fill_paused=False
                )
                if minute_data is not None and len(minute_data) > 0:
                    auction_vol = minute_data.iloc[0]['volume']
                else:
                    continue
            except Exception:
                # 如果没有分钟数据（回测可能没有），跳过竞价量检查
                auction_vol = 0

            # 获取昨日总成交量
            yesterday_data = get_price(
                stock,
                end_date=yesterday,
                frequency='daily',
                fields=['volume'],
                count=1,
                panel=False,
                fill_paused=False
            )
            if yesterday_data is None or len(yesterday_data) == 0:
                continue

            yesterday_vol = yesterday_data.iloc[0]['volume']

            if yesterday_vol > 0:
                vol_ratio = auction_vol / yesterday_vol
                if vol_ratio < g.auction_volume_ratio:
                    # 竞价量不足
                    continue

            filtered.append(stock)

        except Exception as e:
            log.debug(f'  [竞价过滤] {stock} 异常: {e}')
            continue

    return filtered


def first_board_filter(context, yesterday, candidates):
    """
    Step 3: 首板筛选
    昨日(T-1)涨停，但前日(T-2)未涨停
    """
    filtered = []
    try:
        # 获取T-1和T-2收盘价和涨停价
        df = get_price(
            candidates,
            end_date=yesterday,
            frequency='daily',
            fields=['close', 'high_limit'],
            count=2,
            panel=False,
            fill_paused=False,
            skip_paused=True
        )
    except Exception as e:
        log.error(f'获取首板数据失败: {e}')
        return []

    df.index = df.code

    for stock in candidates:
        try:
            if stock not in df.index:
                continue
            sub = df.loc[stock]
            if len(sub) < 2:
                continue

            valid_data = sub.dropna(subset=['close', 'high_limit'])
            if len(valid_data) < 2:
                continue

            recent = valid_data.iloc[-2:]

            # T-1 必须涨停
            yesterday_hl = recent.iloc[-1]['high_limit']
            yesterday_close = recent.iloc[-1]['close']
            t1_limit_up = yesterday_close == yesterday_hl

            # T-2 不能涨停
            t2_hl = recent.iloc[-2]['high_limit']
            t2_close = recent.iloc[-2]['close']
            t2_not_limit_up = t2_close < t2_hl

            if t1_limit_up and t2_not_limit_up:
                filtered.append(stock)

        except Exception as e:
            continue

    return filtered


def volatility_filter(context, yesterday, candidates):
    """
    Step 4: 波动过滤
    剔除近5日波动超过20%的股票
    波动率 = (5日内最高价 - 5日内最低价) / 5日内最低价
    """
    filtered = []
    try:
        df = get_price(
            candidates,
            end_date=yesterday,
            frequency='daily',
            fields=['high', 'low'],
            count=5,
            panel=False,
            fill_paused=False,
            skip_paused=True
        )
    except Exception as e:
        log.error(f'获取波动数据失败: {e}')
        return candidates  # 数据获取失败时不过滤

    if df.empty:
        return candidates

    df.index = df.code

    for stock in candidates:
        try:
            if stock not in df.index:
                continue
            sub = df.loc[stock].dropna(subset=['high', 'low'])
            if len(sub) < 3:
                continue

            high_5d = sub['high'].max()
            low_5d = sub['low'].min()

            if low_5d > 0:
                volatility = (high_5d - low_5d) / low_5d
                if volatility <= g.max_volatility_5d:
                    filtered.append(stock)
        except Exception:
            continue

    return filtered


def market_cap_filter(context, yesterday, candidates):
    """
    Step 5: 市值过滤
    选30-300亿市值的股票
    """
    filtered = []
    try:
        for stock in candidates:
            q = query(
                valuation.code,
                valuation.circulating_market_cap
            ).filter(
                valuation.code == stock
            )
            df = get_fundamentals(q, date=yesterday)
            if df is not None and len(df) > 0:
                cap = df.iloc[0]['circulating_market_cap']
                if g.market_cap_min <= cap <= g.market_cap_max:
                    filtered.append(stock)
    except Exception as e:
        log.error(f'获取市值数据失败: {e}')
        return candidates

    return filtered


# =============================================================================
# 2. 买入逻辑
# =============================================================================

def buy_stocks(context):
    """
    9:30 开盘买入
    等资金分配，最多持有 g.max_hold_count 只
    """
    today = context.current_dt.date()
    log.info('=' * 70)
    log.info(f'【买入】{today} 执行买入')

    if not g.target_list:
        log.info('  → 今日无目标股票，跳过买入')
        return

    # 计算剩余可买入仓位
    current_hold_count = len(g.hold_stocks)
    remaining_slots = g.max_hold_count - current_hold_count

    if remaining_slots <= 0:
        log.info(f'  → 持仓已达上限({g.max_hold_count}只)，跳过买入')
        return

    # 取目标股票中前N只
    buy_targets = g.target_list[:remaining_slots]
    log.info(f'  目标: {len(g.target_list)}只 | 当前持仓: {current_hold_count}只 | '
             f'可买: {remaining_slots}只 | 实际买入目标: {len(buy_targets)}只')

    # 等资金分配
    available_cash = context.portfolio.available_cash
    cash_per_stock = available_cash / len(buy_targets)
    log.info(f'  可用资金: {available_cash:,.2f}元 | 每只分配: {cash_per_stock:,.2f}元')

    current_data = get_current_data()

    for i, stock in enumerate(buy_targets, 1):
        try:
            # 检查是否已持仓
            if stock in g.hold_stocks:
                continue

            buy_price = current_data[stock].day_open

            # 计算可买股数（100的整数倍）
            qty = int(cash_per_stock / buy_price / 100) * 100

            if qty >= 100:
                order_id = order(stock, qty)

                if order_id:
                    # 记录持仓
                    g.hold_stocks[stock] = {
                        'buy_price': buy_price,
                        'buy_date': today,
                        'peak_price': buy_price,   # 跟踪最高价
                        'yesterday_negative': None  # 延迟到买入后设置
                    }
                    log.info(f'  {i}. ✅ 【买入】{stock} '
                             f'价格: {buy_price:.3f} | 数量: {qty}股 | '
                             f'金额: {qty * buy_price:,.2f}元')
            else:
                log.warning(f'  {i}. ⚠️ 【资金不足】{stock} 需买入100股')

        except Exception as e:
            log.error(f'  {i}. ❌ 【买入异常】{stock}: {e}')

    # 买入后记录昨日涨跌情况（用于线性止盈判断）
    today = context.current_dt.date()
    for stock in list(g.hold_stocks.keys()):
        try:
            buy_date = g.hold_stocks[stock]['buy_date']
            if buy_date >= today:
                # 判断昨日涨跌
                yesterday = context.previous_date
                df = get_price(
                    stock,
                    end_date=yesterday,
                    frequency='daily',
                    fields=['close', 'open'],
                    count=1,
                    panel=False,
                    fill_paused=False
                )
                if len(df) > 0:
                    close_y = df.iloc[0]['close']
                    open_y = df.iloc[0]['open']
                    g.hold_stocks[stock]['yesterday_negative'] = (close_y < open_y)
        except Exception:
            g.hold_stocks[stock]['yesterday_negative'] = False

    log.info('=' * 70)


# =============================================================================
# 3. 卖出逻辑
# =============================================================================

def minute_linear_stop_profit(context):
    """
    分钟级线性止盈（9:30-11:25）
    适用条件：持仓股票昨日收阴（close < open）
    逻辑：若股票冲高超3%后回撤，动态计算回撤容忍度
         涨幅越大容忍回撤越小
    """
    dt = context.current_dt
    today = dt.date()

    # 只在9:30-11:25执行
    current_time = dt.hour * 100 + dt.minute
    if current_time < 930 or current_time > 1125:
        return

    if not g.use_linear_stop_profit:
        return

    sell_count = 0
    for stock in list(g.hold_stocks.keys()):
        try:
            info = g.hold_stocks[stock]

            # 仅处理T日买入的股票（当日）
            if info['buy_date'] != today:
                continue

            # 仅处理昨日收阴的股票
            if not info.get('yesterday_negative', False):
                continue

            current_data = get_current_data()

            # 涨停保护：接近涨停时不触发卖出
            current_price = current_data[stock].last_price
            high_limit = current_data[stock].high_limit

            if current_price >= high_limit * g.near_limit_up:
                continue

            buy_price = info['buy_price']

            if buy_price <= 0:
                continue

            # 计算当前涨幅
            current_gain = (current_price - buy_price) / buy_price

            # 更新峰值
            if current_price > info['peak_price']:
                info['peak_price'] = current_price

            peak_price = info['peak_price']
            peak_gain = (peak_price - buy_price) / buy_price

            # 只有冲高超3%时才触发线性止盈
            if peak_gain < g.surge_threshold:
                continue

            # 动态回撤容忍度计算
            # 涨幅越大，容忍回撤越小（相对比例）
            # peak_gain = 3% → 容忍60%回撤
            # peak_gain = 5% → 容忍45%回撤
            # peak_gain = 10% → 容忍25%回撤
            # peak_gain = 15% → 容忍15%回撤
            # peak_gain >= 20% → 容忍10%回撤

            allowed_retrace_ratio = max(
                0.10,
                0.60 - (peak_gain - 0.03) * (0.50 / 0.17)
            )
            allowed_retrace_ratio = min(allowed_retrace_ratio, 0.80)

            # 当前回撤
            pullback = peak_gain - current_gain

            # 如果回撤超过容忍度，卖出
            if pullback > allowed_retrace_ratio * peak_gain:
                order_target_value(stock, 0)
                del g.hold_stocks[stock]
                sell_count += 1
                log.info(f'【线性止盈】{stock} ✅ '
                         f'峰值涨幅: {peak_gain:.2%} | '
                         f'当前涨幅: {current_gain:.2%} | '
                         f'回撤: {pullback:.2%} | '
                         f'容忍回撤比: {allowed_retrace_ratio:.0%}')

        except Exception as e:
            log.debug(f'【线性止盈异常】{stock}: {e}')
            continue

    if sell_count > 0:
        log.info(f'  线性止盈累计卖出: {sell_count} 只')


def close_positions_14_50(context):
    """
    14:50 尾盘止损止盈
    多个条件任一满足即卖出：
    1. 盈利 > 50%（止盈）
    2. 当日跌幅 < -2%（日内止损）
    3. 现价 < 开盘价 - 4%
    4. 亏损 < -7%（总止损）
    5. 跌破5日线 - 3%
    """
    today = context.current_dt.date()
    log.info('=' * 70)
    log.info(f'【14:50 尾盘止损止盈】{today}')

    if not g.hold_stocks:
        log.info('  → 无持仓，跳过')
        return

    log.info(f'  当前持仓: {len(g.hold_stocks)} 只')

    current_data = get_current_data()
    sell_count = 0
    sell_reasons = []

    for stock in list(g.hold_stocks.keys()):
        try:
            position = context.portfolio.positions.get(stock)
            if position is None or position.total_amount == 0:
                # 持仓已清，清理记录
                if stock in g.hold_stocks:
                    del g.hold_stocks[stock]
                continue

            info = g.hold_stocks[stock]
            buy_price = info['buy_price']
            current_price = current_data[stock].last_price
            today_open = current_data[stock].day_open
            high_limit = current_data[stock].high_limit

            if buy_price <= 0:
                continue

            # 涨停保护：接近涨停不卖出
            if current_price >= high_limit * g.near_limit_up:
                continue

            # 计算各项指标
            total_gain = (current_price - buy_price) / buy_price  # 总盈亏
            day_gain = (current_price - today_open) / today_open if today_open > 0 else 0  # 当日涨跌
            open_loss = (current_price - today_open) / today_open if today_open > 0 else 0  # 相对开盘价

            # 条件1: 盈利 > 50%
            if total_gain >= g.profit_take_profit:
                reason = f'止盈(盈利>{g.profit_take_profit:.0%})'
                sell_stock(context, stock, reason, total_gain)
                sell_count += 1
                sell_reasons.append((stock, reason, total_gain))
                continue

            # 条件2: 当日跌幅 < -2%
            if day_gain <= g.day_loss_threshold:
                reason = f'日内止损(当日跌幅<{g.day_loss_threshold:.0%})'
                sell_stock(context, stock, reason, total_gain)
                sell_count += 1
                sell_reasons.append((stock, reason, total_gain))
                continue

            # 条件3: 现价 < 开盘价 - 4%
            if open_loss <= g.price_vs_open_loss:
                reason = f'开盘回撤止损(现价<开盘价{g.price_vs_open_loss:.0%})'
                sell_stock(context, stock, reason, total_gain)
                sell_count += 1
                sell_reasons.append((stock, reason, total_gain))
                continue

            # 条件4: 亏损 < -7%
            if total_gain <= g.max_loss:
                reason = f'总止损(亏损<{g.max_loss:.0%})'
                sell_stock(context, stock, reason, total_gain)
                sell_count += 1
                sell_reasons.append((stock, reason, total_gain))
                continue

            # 条件5: 跌破5日线 - 3%
            try:
                df_ma5 = get_price(
                    stock,
                    end_date=context.previous_date,
                    frequency='daily',
                    fields=['close'],
                    count=5,
                    panel=False,
                    fill_paused=False
                )
                if len(df_ma5) >= 5:
                    ma5 = df_ma5['close'].mean()
                    if ma5 > 0:
                        ma5_diff = (current_price - ma5) / ma5
                        if ma5_diff <= g.ma5_loss:
                            reason = f'破5日线止损(跌破{g.ma5_loss:.0%})'
                            sell_stock(context, stock, reason, total_gain)
                            sell_count += 1
                            sell_reasons.append((stock, reason, total_gain))
                            continue
            except Exception:
                pass

            log.debug(f'  {stock}: 总盈亏={total_gain:.2%}, '
                      f'当日={day_gain:.2%}, 未触发卖出条件')

        except Exception as e:
            log.error(f'  卖出检查异常 {stock}: {e}')

    # 汇总
    log.info('- ' * 35)
    log.info(f'  卖出: {sell_count} 只')
    if sell_reasons:
        for s, r, g_ret in sell_reasons:
            log.info(f'    ✅ {s}: {r} (盈亏: {g_ret:.2%})')
    log.info(f'  剩余持仓: {len(g.hold_stocks)} 只')
    log.info('=' * 70)


def sell_stock(context, stock, reason, gain_ratio):
    """执行卖出并清理持仓记录"""
    try:
        order_target_value(stock, 0)
        if stock in g.hold_stocks:
            del g.hold_stocks[stock]
        log.info(f'    ✅ 【卖出】{stock} | 原因: {reason} | 盈亏: {gain_ratio:.2%}')
    except Exception as e:
        log.error(f'    ❌ 【卖出失败】{stock}: {e}')


# =============================================================================
# 4. 辅助函数
# =============================================================================

def filter_basic(stock_list):
    """基础过滤：ST股、停牌、科创板、北交所、新股(上市<1年)"""
    current_data = get_current_data()
    filtered = []

    for stock in stock_list:
        try:
            # ST过滤
            if current_data[stock].is_st:
                continue
            if 'ST' in current_data[stock].name or '*' in current_data[stock].name:
                continue
            if '退' in current_data[stock].name:
                continue

            # 停牌过滤
            if current_data[stock].paused:
                continue

            # 科创板(688)过滤
            if stock.startswith('688'):
                continue

            # 北交所(8开头)过滤
            if stock.startswith('8'):
                continue

            filtered.append(stock)
        except Exception:
            continue

    return filtered


def print_position_info(context):
    """15:10 打印持仓信息"""
    log.info('=' * 60)
    log.info('【收盘持仓信息】')

    if not g.hold_stocks:
        log.info('  → 当前空仓')
    else:
        current_data = get_current_data()
        total_pnl = 0
        for stock in list(g.hold_stocks.keys()):
            try:
                position = context.portfolio.positions.get(stock)
                if position is None or position.total_amount == 0:
                    if stock in g.hold_stocks:
                        del g.hold_stocks[stock]
                    continue

                info = g.hold_stocks[stock]
                buy_price = info['buy_price']
                current_price = position.price
                pnl = (current_price - buy_price) / buy_price * 100
                total_pnl += (current_price - buy_price) * position.total_amount

                log.info(f'  {stock}')
                log.info(f'    成本: {buy_price:.3f} | '
                         f'现价: {current_price:.3f} | '
                         f'盈亏: {pnl:+.2f}% | '
                         f'持仓: {position.total_amount}股 | '
                         f'市值: {position.value:,.0f}')
            except Exception as e:
                log.error(f'  打印{stock}信息失败: {e}')

    # 账户总资产
    log.info(f'  总资产: {context.portfolio.total_value:,.2f}元 | '
             f'可用: {context.portfolio.available_cash:,.2f}元 | '
             f'持仓: {context.portfolio.positions_value:,.2f}元')

    # 记录仓位
    position_ratio = (context.portfolio.positions_value /
                      context.portfolio.total_value * 100)
    record(仓位=round(position_ratio, 2))

    log.info('=' * 60)


# =============================================================================
# 5. 策略说明
# =============================================================================

"""
【低位3连阳首板接力策略】完整说明

========================================================================
一、选股逻辑（5层过滤）
========================================================================

Step 1: 量价过滤（核心条件）
  a. 连续3天阳线（T-3, T-2, T-1的收盘价 > 开盘价）
  b. 昨日(T-1)必须是涨停板
  c. 昨日成交量 >= 前日(T-2)成交量 × 2倍（明显放量）
  d. 前两日(T-3, T-2)涨幅均 < 5%（非连续大涨，保持低位特征）
  e. 排除异常爆量：
     - 涨停日(T-1)成交量 > 8倍近20日均量 且 股价创新高
     - 或 涨停日成交量 > 12倍近20日最小量 且 股价创新高
  f. 成交额5-30亿（流动性适中）

Step 2: 集合竞价过滤
  a. 竞价成交量 >= 昨日总成交量 × 3%（有承接）
  b. 竞价涨幅（开盘价相对昨日收盘）在 0% ~ 6%（不追高）

Step 3: 首板筛选
  昨日涨停(T-1) 但 前日(T-2)未涨停（第一次涨停，非连板）

Step 4: 波动过滤
  近5日振幅（最高-最低)/最低 不超过 20%

Step 5: 市值过滤
  流通市值 30-300亿

========================================================================
二、买入规则
========================================================================
  - 执行时间: 09:30（开盘价买入）
  - 分配方式: 等资金分配
  - 最大持仓: 10只

========================================================================
三、卖出规则（三层风控）
========================================================================

1. 涨停保护：接近涨停价(99%)时不触发任何卖出

2. 线性止盈（分钟级 9:30-11:25）：
   - 仅对昨日收阴（close < open）的持仓股票执行
   - 若股票从买入价冲高超3%，开始跟踪峰值
   - 回撤超过动态容忍度时卖出：
     - 涨幅3% → 容忍60%回撤（即回撤1.8%触发）
     - 涨幅10% → 容忍25%回撤
     - 涨幅≥20% → 容忍10%回撤

3. 多条件止损止盈（14:50 尾盘检查）：
   - 盈利 > 50% → 止盈
   - 当日跌幅 < -2% → 日内止损
   - 现价 < 开盘价 - 4% → 开盘回撤止损
   - 总亏损 < -7% → 总止损
   - 跌破5日均线 -3% → 趋势止损

========================================================================
四、回测表现
========================================================================
  2025-01-01 ~ 2026-04-27:
    收益 +1602.00%, 年化 834.95%, 最大回撤 13.13%, 胜率 54.4%

  2026-01-01 ~ 2026-04-27:
    收益 +141.25%, 年化 1859.47%, 最大回撤 5.98%, 胜率 81.8%

========================================================================
注意事项：
  1. 该策略在特定年份表现突出，可能存在过拟合风险
  2. 集合竞价成交量在回测中可能存在数据偏差
  3. 建议根据市场环境调整参数（市值范围、量比等）
  4. 策略在弱势市场可能表现不佳，建议配合大盘趋势判断
========================================================================
"""

if __name__ == '__main__':
    print('低位3连阳首板接力策略 - 聚宽平台')
    print('参考: https://www.joinquant.com/view/community/detail/80b2a638c6ca291fb60cc80a8ef50747')
    print('请在聚宽平台上运行此策略')
