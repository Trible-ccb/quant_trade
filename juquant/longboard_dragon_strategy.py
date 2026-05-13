# =============================================================================
# 聚宽平台 · 连板龙头策略（Long-board Dragon Strategy）
# =============================================================================
# 【策略来源】
#   参考自聚宽社区用户 wywy1995 分享的连板龙头策略：
#   https://www.joinquant.com/view/community/detail/f0aa792a562e5bdd60682c0e11c7a03e
#
# 【核心逻辑】
#   1. 每日生成初始股票池（过滤ST/停牌/科创板/北交所/次新股）
#   2. 筛选出当日涨停的股票
#   3. 计算每只股票的"连板数"（连续涨停天数）
#   4. 选出连板数最高的股票 == 市场最高板龙头
#   5. 用聚宽因子（如VOL5）对龙头进一步排序筛选，选因子值最优的
#   6. 09:30 买入：若开盘继续涨停则用限价单排板，否则市价单买入
#   7. 14:50 卖出：不涨停 + (持有≥2天 或 已盈利) → 卖出
#   8. （可选增强）热门概念/情绪周期/市场特征分析
#
# 【作者】wywy1995（聚宽社区）
# 【整理日期】2026-05-07
# 【回测条件参考】2005-02-01 ~ 2023-11-12, ￥100,000, 分钟级
# =============================================================================

from jqdata import *
from jqfactor import get_factor_values
from jqlib.technical_analysis import *
import datetime as dt
import pandas as pd
import numpy as np


# =============================================================================
# 策略初始化
# =============================================================================

def initialize(context):
    """
    策略初始化函数
    """
    set_benchmark('000300.XSHG')

    # -------- 系统设置 --------
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    log.set_level('system', 'error')

    # -------- 策略参数 --------
    # 分仓数量：同时持仓的最高板龙头数（一般不超过10个）
    g.ps = 10

    # 聚宽因子设置（用于对龙头股进行二次排序筛选）
    g.jqfactor = 'VOL5'       # 5日平均换手率（示例因子，可按需修改）
    g.sort = True              # True = 选因子值最小的; False = 选因子值最大的

    # -------- 运行时变量 --------
    g.emo_count = []           # 情绪计数列表（用于判断情绪周期）
    g.target_list = []         # 当日目标买入列表

    # -------- 时间调度 --------
    run_daily(get_stock_list, '9:01')     # 9:01 选股
    run_daily(buy, '09:30')               # 09:30 开盘买入
    run_daily(sell, '14:50')              # 14:50 尾盘卖出
    run_daily(print_position_info, '15:02')  # 15:02 打印持仓信息

    log.info('=== 连板龙头策略启动 ===')
    log.info(f'分仓数量: {g.ps} | 排序因子: {g.jqfactor} | 选最小值: {g.sort}')


# =============================================================================
# 选股逻辑 (9:01 运行)
# =============================================================================

def get_stock_list(context):
    """
    每日9:01运行的选股函数
    核心步骤：
      1. 准备初始股票池（过滤）
      2. 获取当日涨停股票
      3. 计算连板数，选出最高连板股票（龙头）
      4. 用因子对龙头排序，按仓位截取最终列表
    """
    # 当前日期（字符串格式）
    date = context.previous_date
    date = transform_date(date, 'str')

    # Step 1: 准备初始股票池（过滤ST/停牌/科创板/北交所/次新股）
    initial_list = prepare_stock_list(date)

    if len(initial_list) == 0:
        log.warning('[选股] 初始股票池为空，跳过今日选股')
        g.target_list = []
        return

    log.info(f'[选股] 初始股票池: {len(initial_list)} 只')

    # Step 2: 获取当日涨停股票
    hl_list = get_hl_stock(initial_list, date)
    log.info(f'[选股] 当日涨停: {len(hl_list)} 只')

    if len(hl_list) == 0:
        log.info('[选股] 无涨停股票，跳过今日选股')
        g.target_list = []
        return

    # Step 3: 计算连板数，获取全部连板股票及其连板天数
    ccd = get_continue_count_df(hl_list, date, watch_days=20)
    log.info(f'[选股] 连板股票: {len(ccd)} 只')

    if len(ccd) == 0:
        log.info('[选股] 无连板股票，跳过今日选股')
        g.target_list = []
        return

    # Step 4: 找出最高连板数 → 即市场龙头
    M = ccd['count'].max()
    CCD = ccd[ccd['count'] == M]
    lt = list(CCD.index)
    log.info(f'[选股] 最高板数: {M} 板 | 龙头候选: {len(lt)} 只')

    # ---------------------------------------------------------------
    # 【可选增强】在这里可以用市场特征（热门概念/情绪周期等）
    # 对 lt 中的龙头进行进一步筛选，见下方 _market_analysis() 函数
    # ---------------------------------------------------------------

    # Step 5: 利用聚宽因子对龙头进行排序筛选
    df = get_factor_filter_df(context, lt, g.jqfactor, g.sort)

    if len(df) == 0:
        log.info('[选股] 因子筛选后无合格股票')
        g.target_list = []
        return

    stock_list = list(df.index)

    # Step 6: 根据剩余仓位截取最终买入列表
    remaining_slots = g.ps - len(context.portfolio.positions)
    g.target_list = stock_list[:remaining_slots]

    log.info(f'[选股] 最终目标: {len(g.target_list)} 只 (剩余仓位: {remaining_slots})')
    for i, s in enumerate(g.target_list, 1):
        stock_name = get_security_info(s).display_name
        log.info(f'  {i}. {s} ({stock_name})')


# =============================================================================
# 买卖逻辑
# =============================================================================

def buy(context):
    """
    09:30 开盘买入逻辑
    - 如果开盘涨停 → 用限价单排板（可能买到）
    - 如果未涨停   → 用市价单即刻买入
    - 每只股票分配等额资金
    """
    current_data = get_current_data()
    value = context.portfolio.total_value / g.ps

    for s in g.target_list:
        try:
            # 检查可用资金是否足够买入至少100股
            if context.portfolio.available_cash / current_data[s].last_price <= 100:
                log.debug(f'[买入] {s} 资金不足买入100股，跳过')
                continue

            # 如果开盘涨停 → 用限价单排板
            if current_data[s].last_price == current_data[s].high_limit:
                order_value(s, value, LimitOrderStyle(current_data[s].day_open))
                log.info(f'[买入] {s} ⬆ 涨停排板 | 资金: {value:.0f}元')

            # 如果开盘未涨停 → 用市价单即刻买入
            else:
                order_value(s, value, MarketOrderStyle(current_data[s].day_open))
                log.info(f'[买入] {s} ✅ 市价买入 | 资金: {value:.0f}元')

        except Exception as e:
            log.error(f'[买入] {s} 异常: {e}')


def sell(context):
    """
    14:50 尾盘卖出逻辑
    卖出条件（需同时满足）：
      条件1: 当前不涨停
      条件2（满足其一即可）:
        a. 持有时间 ≥ 2个交易日
        b. 已盈利（浮盈 > 0）
      条件3: 当前价 > 跌停价（防止跌停卖不出）
    """
    hold_list = list(context.portfolio.positions)
    current_data = get_current_data()

    for s in hold_list:
        try:
            position = context.portfolio.positions[s]

            # 条件1：不涨停才考虑卖出
            if current_data[s].last_price == current_data[s].high_limit:
                log.debug(f'[卖出] {s} 仍涨停，保留')
                continue

            # 检查可卖数量
            if position.closeable_amount == 0:
                continue

            # 条件2.1：持有时间 ≥ 2个交易日
            start_date = transform_date(position.init_time, 'str')
            target_date = get_shifted_date(start_date, 2, 'T')
            current_date = transform_date(context.current_dt, 'str')
            hold_enough = current_date >= target_date

            # 条件2.2：已盈利
            cost = position.avg_cost
            price = position.price
            ret = 100 * (price / cost - 1)
            is_profitable = ret > 0

            # 条件3：当前价 > 跌停价（避免跌停卖不出）
            can_sell = current_data[s].last_price > current_data[s].low_limit

            # 在满足条件1的前提下，条件2中只要满足一个即卖出
            if (hold_enough or is_profitable) and can_sell:
                order_target_value(s, 0)
                reason = '持仓≥2天' if hold_enough else ''
                reason += ' + ' if hold_enough and is_profitable else ''
                reason += '已盈利' if is_profitable else ''
                log.info(f'[卖出] {s} ✅ {reason} | 收益: {ret:+.2f}% | 持有: {position.total_amount}股')

        except Exception as e:
            log.error(f'[卖出] {s} 异常: {e}')


# =============================================================================
# 工具函数 · 日期处理
# =============================================================================

def transform_date(date, date_type):
    """
    日期格式转换
    Parameters:
        date: 日期（str / datetime / date）
        date_type: 目标类型 'str' / 'dt' / 'd'
    Returns:
        转换后的日期
    """
    if type(date) == str:
        str_date = date
        dt_date = dt.datetime.strptime(date, '%Y-%m-%d')
        d_date = dt_date.date()
    elif type(date) == dt.datetime:
        str_date = date.strftime('%Y-%m-%d')
        dt_date = date
        d_date = dt_date.date()
    elif type(date) == dt.date:
        str_date = date.strftime('%Y-%m-%d')
        dt_date = dt.datetime.strptime(str_date, '%Y-%m-%d')
        d_date = date
    else:
        raise TypeError(f'不支持的日期类型: {type(date)}')

    dct = {'str': str_date, 'dt': dt_date, 'd': d_date}
    return dct[date_type]


def get_shifted_date(date, days, days_type='T'):
    """
    获取平移后的日期
    Parameters:
        date: 基准日期
        days: 平移天数
        days_type: 'T' = 交易日平移, 'N' = 自然日平移
    Returns:
        平移后的日期（字符串 YYYY-MM-DD）
    """
    d_date = transform_date(date, 'd')
    yesterday = d_date + dt.timedelta(-1)

    # 自然日平移
    if days_type == 'N':
        shifted_date = yesterday + dt.timedelta(days + 1)
        return str(shifted_date)

    # 交易日平移
    if days_type == 'T':
        all_trade_days = [i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]

        # 如果上一个自然日是交易日，直接平移
        if str(yesterday) in all_trade_days:
            idx = all_trade_days.index(str(yesterday))
            shifted_date = all_trade_days[idx + days + 1]
            return str(shifted_date)

        # 否则从上一个自然日向前找最近的交易日
        for i in range(100):
            last_trade_date = yesterday - dt.timedelta(i)
            if str(last_trade_date) in all_trade_days:
                idx = all_trade_days.index(str(last_trade_date))
                shifted_date = all_trade_days[idx + days + 1]
                return str(shifted_date)

    return None


# =============================================================================
# 工具函数 · 股票过滤
# =============================================================================

def filter_new_stock(initial_list, date, days=50):
    """
    过滤上市不足指定天数的次新股
    Parameters:
        initial_list: 股票列表
        date: 当前日期
        days: 上市天数阈值（默认50天）
    Returns:
        过滤后的股票列表
    """
    d_date = transform_date(date, 'd')
    return [
        stock for stock in initial_list
        if d_date - get_security_info(stock).start_date > dt.timedelta(days=days)
    ]


def filter_st_stock(initial_list, date):
    """
    过滤ST/*ST股票
    """
    str_date = transform_date(date, 'str')
    # 如果date不是交易日，取上一个交易日
    if get_shifted_date(str_date, 0, 'N') != get_shifted_date(str_date, 0, 'T'):
        str_date = get_shifted_date(str_date, -1, 'T')

    df = get_extras('is_st', initial_list, start_date=str_date, end_date=str_date, df=True)
    df = df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == False]
    return list(df.index)


def filter_kcbj_stock(initial_list):
    """
    过滤科创板(68开头)、创业板(4开头)、北交所(8开头)的股票
    """
    return [
        stock for stock in initial_list
        if stock[0] != '4'
        and stock[0] != '8'
        and stock[:2] != '68'
    ]


def filter_paused_stock(initial_list, date):
    """
    过滤停牌股票
    """
    df = get_price(
        initial_list,
        end_date=date,
        frequency='daily',
        fields=['paused'],
        count=1,
        panel=False,
        fill_paused=True
    )
    df = df[df['paused'] == 0]
    return list(df.code)


def filter_extreme_limit_stock(context, stock_list, date):
    """
    过滤一字涨停（极端涨停）的股票
    一字涨停定义为：最低价 == 涨停价
    """
    tmp = []
    for stock in stock_list:
        df = get_price(
            stock,
            end_date=date,
            frequency='daily',
            fields=['low', 'high_limit'],
            count=1,
            panel=False
        )
        if df.iloc[0, 0] < df.iloc[0, 1]:  # 最低价 < 涨停价，不是一字板
            tmp.append(stock)
    return tmp


def prepare_stock_list(date):
    """
    每日初始股票池
    按顺序执行多个过滤，生成可交易的初始股票列表
    """
    initial_list = get_all_securities('stock', date).index.tolist()

    # 依次过滤
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_new_stock(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)

    return initial_list


# =============================================================================
# 工具函数 · 涨停 & 连板计算
# =============================================================================

def get_hl_stock(initial_list, date):
    """
    筛选出某一日涨停的股票
    涨停定义：收盘价 == 涨停价
    Parameter:
        initial_list: 候选股票列表
        date: 日期
    Returns:
        涨停股票列表
    """
    df = get_price(
        initial_list,
        end_date=date,
        frequency='daily',
        fields=['close', 'high_limit'],
        count=1,
        panel=False,
        fill_paused=False,
        skip_paused=False
    )
    df = df.dropna()  # 去除停牌
    df = df[df['close'] == df['high_limit']]
    return list(df.code)


def get_hl_count_df(hl_list, date, watch_days):
    """
    计算每只股票在 watch_days 内的涨停天数
    （同时计算"一字涨停"天数：最低价 == 涨停价）
    Parameters:
        hl_list: 涨停股票列表
        date: 当前日期
        watch_days: 回看天数
    Returns:
        DataFrame(index=股票, columns=['count', 'extreme_count'])
            - count: 涨停天数
            - extreme_count: 一字涨停天数
    """
    df = get_price(
        hl_list,
        end_date=date,
        frequency='daily',
        fields=['close', 'high_limit', 'low'],
        count=watch_days,
        panel=False,
        fill_paused=False,
        skip_paused=False
    )
    df.index = df.code

    hl_count_list = []
    extreme_hl_count_list = []

    for stock in hl_list:
        df_sub = df.loc[stock]
        # 涨停天数
        hl_days = df_sub[df_sub.close == df_sub.high_limit].high_limit.count()
        # 一字涨停天数（最低价==涨停价）
        extreme_hl_days = df_sub[df_sub.low == df_sub.high_limit].high_limit.count()
        hl_count_list.append(hl_days)
        extreme_hl_count_list.append(extreme_hl_days)

    result_df = pd.DataFrame(
        index=hl_list,
        data={
            'count': hl_count_list,
            'extreme_count': extreme_hl_count_list
        }
    )
    return result_df


def get_continue_count_df(hl_list, date, watch_days):
    """
    计算每只股票的"连板数"（连续涨停天数）
    通过累加不同天数的涨停统计，找出连续涨停的天数
    Parameters:
        hl_list: 涨停股票列表
        date: 当前日期
        watch_days: 最大回看天数
    Returns:
        DataFrame(index=股票, columns=['count', 'extreme_count'])
            已按 count 降序排列
    """
    df = pd.DataFrame()
    for d in range(2, watch_days + 1):
        HLC = get_hl_count_df(hl_list, date, d)
        CHLC = HLC[HLC['count'] == d]
        df = pd.concat([df, CHLC])

    if df.empty:
        return pd.DataFrame(index=[], data={'count': [], 'extreme_count': []})

    stock_list = list(set(df.index))
    ccd = pd.DataFrame()

    for s in stock_list:
        tmp = df.loc[[s]]
        if len(tmp) > 1:
            M = tmp['count'].max()
            tmp = tmp[tmp['count'] == M]
        ccd = pd.concat([ccd, tmp])

    if not ccd.empty:
        ccd = ccd.sort_values(by='count', ascending=False)

    return ccd


# =============================================================================
# 工具函数 · 因子排序 & 筛选
# =============================================================================

def get_factor_filter_df(context, stock_list, jqfactor, sort):
    """
    按聚宽因子值对股票排序
    Parameters:
        context: 策略上下文
        stock_list: 候选股票列表
        jqfactor: 聚宽因子名称（如 'VOL5', 'PE' 等）
        sort: True=升序(选最小), False=降序(选最大)
    Returns:
        DataFrame(index=股票, columns=['score']) 已排序
    """
    if len(stock_list) == 0:
        return pd.DataFrame(index=[], data={'score': []})

    yesterday = context.previous_date
    try:
        score_list = get_factor_values(
            stock_list, jqfactor,
            end_date=yesterday, count=1
        )[jqfactor].iloc[0].tolist()

        df = pd.DataFrame(
            index=stock_list,
            data={'score': score_list}
        ).dropna()

        df = df.sort_values(by='score', ascending=sort)
        return df

    except Exception as e:
        log.error(f'[因子筛选] 获取因子 {jqfactor} 失败: {e}')
        return pd.DataFrame(index=[], data={'score': []})


# =============================================================================
# 工具函数 · 热门概念分析（可选增强）
# =============================================================================

def get_hot_concept(dct, date):
    """
    计算出现涨停最多的热门概念（用于龙头题材分析）
    Parameters:
        dct: get_concept() 返回的概念字典
        date: 当前日期
    Returns:
        出现最频繁的概念名称
    """
    concept_count = {}
    exclude_concepts = ['转融券标的', '融资融券', '深股通', '沪股通']

    for key in dct:
        for i in dct[key]['jq_concept']:
            concept_name = i['concept_name']
            if concept_name in concept_count:
                concept_count[concept_name] += 1
            else:
                if concept_name not in exclude_concepts:
                    concept_count[concept_name] = 1

    if not concept_count:
        return None

    df = pd.DataFrame(
        list(concept_count.items()),
        columns=['concept_name', 'concept_count']
    )
    df = df.set_index('concept_name')
    df = df.sort_values(by='concept_count', ascending=False)

    max_num = df.iloc[0, 0]
    df = df[df['concept_count'] == max_num]
    return list(df.index)[0]


def filter_concept_stock(dct, concept):
    """
    根据概念名称筛选股票
    Parameters:
        dct: get_concept() 返回的概念字典
        concept: 目标概念名称
    Returns:
        属于该概念的所有股票列表
    """
    tmp_set = set()
    for k, v in dct.items():
        for d in v['jq_concept']:
            if d['concept_name'] == concept:
                tmp_set.add(k)
    return list(tmp_set)


# =============================================================================
# 工具函数 · 情绪周期分析（可选增强）
# =============================================================================

def get_init_emo_count(context, date):
    """
    初始化情绪计数列表
    计算最近3个交易日的最高连板数，用于判断情绪周期
    Parameters:
        context: 策略上下文
        date: 当前日期
    Returns:
        包含最近3个交易日最高连板数的列表
    """
    d1 = get_shifted_date(date, -3)
    d2 = get_shifted_date(date, -2)
    date_list = [d1, d2]

    emo_count = []
    for date in date_list:
        initial_list = prepare_stock_list(date)
        hl_list = get_hl_stock(initial_list, date)

        if len(hl_list) != 0:
            CCD = get_continue_count_df(hl_list, date, 20)
            M = CCD['count'].max() if len(CCD) != 0 else 0
        else:
            M = 0

        emo_count.append(M)

    return emo_count


# =============================================================================
# 市场特征分析（增强版选股，代码末尾注释部分）
# =============================================================================

"""
【市场特征增强分析】

此部分提供了更精细的龙头股筛选逻辑，可在 get_stock_list() 中
找到 lt 之后、因子筛选之前插入使用。

----------------------------------------------------------------------
# === 市场特征计算 ===

# 1. 龙头（从最高板中再精选一字板最少的）
ccd0 = pd.DataFrame(index=[], data={'count':[], 'extreme_count':[]})
CCD = ccd[ccd['count'] == M] if M != 0 else ccd0
m = CCD['extreme_count'].min()
CCD1 = CCD[CCD['extreme_count'] == m] if str(m) != 'nan' else ccd0
lt = list(CCD1.index)

# 2. 龙头数量
l = len(CCD)

# 3. 晋级率（昨日涨停中今日继续涨停的比例）
r = 100 * len(CCD) / len(hl_list) if len(hl_list) != 0 else 0

# 4. 情绪值（最高连板数）
emo = M
g.emo_count.append(emo)

# 5. 情绪周期判断
cyc = g.emo_count[-1] if (g.emo_count[-1] == max(g.emo_count[-3:])
       and g.emo_count[-1] != 0) else 0
cyc = 1 if cyc == emo else 0

# === 热门概念分析 ===
try:
    dct = get_concept(hl_list, date)
    hot_concept = get_hot_concept(dct, date)
    hot_stocks = filter_concept_stock(dct, hot_concept)
except:
    pass

# === 龙头特征筛选 ===
condition_dct = {}
for s in lt:
    try:
        # 6. 独食程度（一字涨停天数）
        ds = ccd.loc[s]['extreme_count']
        # 7. 流通市值
        sz = get_fundamentals(
            query(valuation.code, valuation.circulating_market_cap)
            .filter(valuation.code == s), date
        ).iloc[0, 1]
        # 8. 换手率
        hs = HSL([s], date)[0][s]
        # 9. 是否属于热门概念
        try:
            c = 1 if s in hot_stocks else 0
        except:
            c = 0

        # 逻辑判断（可自定义条件组合）
        condition = ''
        if hs and ds and emo:
            # 上升周期 + 合适市值
            if cyc and sz:
                condition += '上升周期 '
            # 资金接力（换手充分）
            if ds and hs:
                condition += '资金接力 '
            # 题材初期
            if c and emo:
                condition += f'题材初期({hot_concept}) '
            # 热点集中
            if l and r:
                condition += '热点集中 '
            # 情绪突破
            if emo:
                condition += '情绪突破 '

        if len(condition) != 0:
            display_name = get_security_info(s, date).display_name
            condition_dct[s] = f'{display_name} —— {condition}'

    except:
        pass

# 使用筛选后的龙头列表
stock_list = list(condition_dct.keys())

----------------------------------------------------------------------
使用说明：
  将上述代码插入 get_stock_list() 函数中，替换原 lt 到因子筛选之间的逻辑。
  注意：使用前需确保 g.emo_count 已初始化（调用 get_init_emo_count()）。
"""


# =============================================================================
# 工具函数 · 打印持仓信息
# =============================================================================

def print_position_info(context):
    """
    15:02 打印当日持仓信息和账户状态
    """
    position_percent = 100 * context.portfolio.positions_value / context.portfolio.total_value
    record(仓位=round(position_percent, 2))

    log.info('=' * 55)
    log.info('【持仓信息】')

    positions = list(context.portfolio.positions.values())
    if len(positions) == 0:
        log.info('  → 当前空仓')
    else:
        for position in positions:
            securities = position.security
            cost = position.avg_cost
            price = position.price
            ret = 100 * (price / cost - 1)
            value = position.value
            amount = position.total_amount

            log.info(f'  {securities}')
            log.info(f'    成本: {cost:.2f}  现价: {price:.2f}  '
                     f'收益: {ret:+.2f}%  持仓: {amount}股  '
                     f'市值: {value:.2f}')
            log.info(f'  {"—" * 40}')

    log.info(f'【账户】总资产: {context.portfolio.total_value:.2f}  '
             f'可用: {context.portfolio.available_cash:.2f}  '
             f'仓位: {position_percent:.2f}%')
    log.info('=' * 55)
