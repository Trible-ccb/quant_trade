# 量价共振行业轮动策略（改进版） - 聚宽完整代码
# 改进点：
# 1. 多周期动量 + 价格路径平滑度 + 量价质量评分
# 2. 移动止损 + 排名阈值放宽 + 成交量异常减仓不立即清仓
# 3. 动态市场状态：高波高相关时启用超跌反转子策略
# 4. 持仓4只：2进攻 + 2防御，板块分散
# 5. 买入时避免追涨：跳空低开或长上影限制买入比例

import numpy as np
import pandas as pd
from jqdata import *

# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper

# 默认下单函数
TRADE_TYPE = 'no_live'  # 'live':实盘模式,其他值：用聚宽平台默认下单函数
(order,order_target_value,order_value,order_target)  = bt_wrapper.wrap_orders(order, order_target_value, order_value, order_target,TRADE_TYPE)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured(globals(), context)
    
# =======================实盘配置End=======================================

# ================== 基础设置 ==================
def create_etf_pool():
    """构建行业主题ETF池，含板块分类（用于分散）"""
    etf_list = {
        '512480.XSHG': ('半导体', '科技'),
        '159995.XSHE': ('芯片', '科技'),
        '515030.XSHG': ('新能源车', '新能源'),
        '515790.XSHG': ('光伏', '新能源'),
        '512010.XSHG': ('医药', '医药'),
        '159928.XSHE': ('消费', '消费'),
        '512690.XSHG': ('酒', '消费'),
        '512660.XSHG': ('军工', '国防'),
        '512880.XSHG': ('证券', '金融'),
        '512800.XSHG': ('银行', '金融'),
        '159869.XSHE': ('动漫游戏', '科技'),
        '516160.XSHG': ('新能源', '新能源'),
        '159766.XSHE': ('旅游', '消费'),
        '515050.XSHG': ('人工智能', '科技'),
        '510230.XSHG': ('金融地产', '金融'),
        '159611.XSHE': ('电力', '公用事业'),
        '512890.XSHG': ('红利低波', '红利'),   # 防御型代表
        '510880.XSHG': ('红利ETF', '红利'),
    }
    return etf_list

def set_targets(context):
    g.etf_dict = create_etf_pool()          # {code: (name, sector)}
    g.assets = list(g.etf_dict.keys())
    g.cash_etf = '511880.XSHG'

def common_init(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000, close_commission=1/10000, min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

def set_params(context):
    # ---------- 多周期动量参数 ----------
    g.momentum_short = 20
    g.momentum_long = 60
    g.momentum_smooth_days = 20         # 路径平滑度计算窗口
    # 综合动量权重：20日动量0.4, 60日动量0.3, 路径平滑0.3
    g.w_ret20 = 0.6
    g.w_ret60 = 0.2
    g.w_smooth = 0.2

    # ---------- 量价质量参数 ----------
    g.vol_quality_days = 20
    g.vol_quality_threshold = 1.2       # 上涨日平均量/下跌日平均量 > 1.2 视为健康

    # ---------- 最终得分权重 ----------
    g.w_momentum = 0.5
    g.w_quality = 0.5

    # ---------- 放量滞涨罚分 ----------
    g.churn_penalty_days = 5
    g.churn_vol_quantile = 0.9
    g.churn_ret_threshold = 0.005       # 近5日涨幅低于0.5% 且 量能>90分位 扣分

    # ---------- 均线与市场过滤 ----------
    g.ma_days = 60
    g.market_vol_window = 20
    g.market_corr_window = 60           # 计算行业相关性的窗口

    # ---------- 持仓与风险管理 ----------
    g.top_n = 4                         # 总持仓数
    g.attack_num = 2                    # 进攻型数量
    g.defend_num = 2                    # 防御型数量
    g.rank_sell_threshold = 0.3         # 排名跌出前30%卖出（放宽）
    g.stop_loss = 0.08                  # 移动止损：从持仓最高点回撤8%
    g.volume_warning_ratio = 0.5        # 成交量异常时仓位减至原来的50%
    g.max_sector_exposure = 2           # 同一板块最多持有只数

    # ---------- 超跌反转子策略参数 ----------
    g.reversal_days = 10                # 计算跌幅窗口
    g.reversal_vol_days = 5             # 确认放量窗口
    g.reversal_allocation = 0.2         # 高波高相关时分配给反转策略的仓位比例

    # ---------- 买入防追涨参数 ----------
    g.buy_price_drop_threshold = -0.015  # 较前收盘下跌1.5%以上只买一半
    g.buy_high_open_shadow_ratio = 1.5   # 长上影判断比例



def schedule_tasks(context):
    unschedule_all()
    # 每日尾盘计算信号并执行交易
    run_weekly(calc_signals_and_clear, 1, '14:45')
    run_weekly(buy_signals, 1, '14:46')

def after_code_changed(context):
    common_init(context)
    set_targets(context)
    set_params(context)
    schedule_tasks(context)

def initialize(context):
    common_init(context)
    set_targets(context)
    set_params(context)
    schedule_tasks(context)
    # 动态记录
    g.entry_highest = {}                # 持仓ETF自买入以来最高价 {code: highest_price}
    g.volume_warning_flag = {}          # 标记成交量异常已减仓的ETF
    g.target_etfs = []                  # 本期目标
    g.pending_buy = {}                  # 暂缓买入记录 {code: wanted_value}

# ================== 数据获取与因子计算 ==================
def get_valid_etfs(context):
    """返回当前可交易的ETF"""
    valid = []
    for etf in g.assets:
        try:
            if can_not_deal(etf):
                continue
            info = get_security_info(etf)
            if info.start_date is None or info.start_date > context.current_dt.date():
                continue
            if info.end_date is not None and info.end_date < context.current_dt.date():
                continue
            # 至少需要足够数据
            prices = attribute_history(etf, 1, '1d', ['close'], skip_paused=True, df=False)
            if not prices['close']:
                continue
            valid.append(etf)
        except:
            continue
    return valid
    
def compute_factors(etf_list, context):
    """计算所有候选ETF的综合得分（改进版，使用 attribute_history 循环）"""
    if not etf_list:
        return pd.DataFrame()

    hist_days = max(g.momentum_long, g.ma_days, g.vol_quality_days + g.churn_penalty_days) + 100
    end_date = context.current_dt

    # 沪深300数据
    hs300_data = attribute_history('000300.XSHG', hist_days, '1d', ['close'], skip_paused=True)
    hs300_close = hs300_data['close']

    results = {}
    for etf in etf_list:
        try:
            # 单标的获取多个字段
            data = attribute_history(etf, hist_days, '1d',
                                     ['close', 'volume', 'high', 'low'],
                                     skip_paused=True)
            if data is None or len(data) < max(g.momentum_long, g.ma_days) + 20:
                continue

            close = data['close']
            volume = data['volume']
            high = data['high']
            low = data['low']

            # ----- 1. 综合动量得分 -----
            # 20日超额收益
            etf_ret20 = close.iloc[-1] / close.iloc[-g.momentum_short - 1] - 1
            hs300_ret20 = hs300_close.iloc[-1] / hs300_close.iloc[-g.momentum_short - 1] - 1
            excess_ret20 = etf_ret20 - hs300_ret20

            # 60日超额收益
            etf_ret60 = close.iloc[-1] / close.iloc[-g.momentum_long - 1] - 1
            hs300_ret60 = hs300_close.iloc[-1] / hs300_close.iloc[-g.momentum_long - 1] - 1
            excess_ret60 = etf_ret60 - hs300_ret60

            # 20日价格路径平滑度
            smooth_series = close.iloc[-g.momentum_smooth_days:]
            peak = smooth_series.expanding().max()
            drawdown = (smooth_series - peak) / peak
            max_dd = abs(drawdown.min())
            smooth_score = max(0, 1 - max_dd)

            # ----- 2. 量价质量得分 -----
            vol_window = volume.iloc[-g.vol_quality_days:]
            close_window = close.iloc[-g.vol_quality_days:]
            daily_ret = close_window.pct_change().dropna()
            aligned_vol = vol_window.iloc[1:]
            up_vol = aligned_vol[daily_ret > 0].mean()
            down_vol = aligned_vol[daily_ret < 0].mean()
            if pd.isna(up_vol) or pd.isna(down_vol) or down_vol == 0:
                vol_quality_ratio = 1.0
            else:
                vol_quality_ratio = up_vol / down_vol
            quality_score = min(1.0, max(0, (vol_quality_ratio - 0.8) / 0.8))

            # ----- 3. 放量滞涨罚分 -----
            penalty = 0
            if len(volume) >= g.churn_penalty_days:
                recent_ret = close.iloc[-1] / close.iloc[-g.churn_penalty_days] - 1
                recent_vol_mean = volume.iloc[-g.churn_penalty_days:].mean()
                vol_rank = volume[-250:].rank(pct=True).iloc[-1]
                if vol_rank > g.churn_vol_quantile and abs(recent_ret) < g.churn_ret_threshold:
                    penalty = 0.5

            # 计算均线和波动率
            ma60 = close.iloc[-g.ma_days:].mean()
            volatility_20 = close.pct_change().iloc[-20:].std()

            results[etf] = {
                'excess_ret20': excess_ret20,
                'excess_ret60': excess_ret60,
                'smooth_score': smooth_score,
                'quality_score': quality_score,
                'penalty': penalty,
                'close': close.iloc[-1],
                'ma60': ma60,
                'volatility_20': volatility_20,
                'close_series': close,
                'volume_series': volume,
                'high_series': high,
                'low_series': low
            }
        except Exception as e:
            log.error(f"计算因子出错 {etf}: {e}")
            continue

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results).T
    # 排名
    df['rank_ex20'] = df['excess_ret20'].rank(pct=True)
    df['rank_ex60'] = df['excess_ret60'].rank(pct=True)
    df['rank_smooth'] = df['smooth_score'].rank(pct=True)
    df['rank_quality'] = df['quality_score'].rank(pct=True)

    # 综合动量
    df['momentum_score'] = (g.w_ret20 * df['rank_ex20'] +
                            g.w_ret60 * df['rank_ex60'] +
                            g.w_smooth * df['rank_smooth'])

    # 最终得分
    df['final_score'] = (g.w_momentum * df['momentum_score'] +
                         g.w_quality * df['rank_quality'] - df['penalty'])

    return df.sort_values('final_score', ascending=False)
# ================== 市场状态评估 ==================
def assess_market_state(context):
    """判断市场是否处于高波动+高相关状态"""
    # 1. 计算沪深300波动率分位
    hs300 = attribute_history('000300.XSHG', g.market_vol_window + 250, '1d',
                              ['close'], skip_paused=True)['close']
    if len(hs300) < 250:
        return False, False

    rets = hs300.pct_change().dropna()
    current_vol = rets.iloc[-g.market_vol_window:].std()
    vol_hist = rets.rolling(20).std().dropna()
    if len(vol_hist) < 100:
        return False, False
    vol_quantile = (vol_hist.iloc[-250:] < current_vol).mean()

    # 2. 行业间平均相关系数
    valid_etfs = get_valid_etfs(context)
    if len(valid_etfs) < 5:
        return False, False

    # 获取多个标的的收盘价，返回 DataFrame，列是ETF代码，行是日期
    ret_df = history(g.market_corr_window, '1d', 'close', valid_etfs, skip_paused=True, df=True)
    if ret_df.empty or ret_df.shape[1] < 5:
        return False, False

    # 计算日收益率（每列是一个ETF的收盘价）
    ret_df = ret_df.pct_change().dropna()
    if ret_df.empty:
        return False, False

    # 计算相关系数矩阵
    corr_matrix = ret_df.corr()
    # 去除对角线元素后求均值
    mask = np.ones_like(corr_matrix, dtype=bool)
    np.fill_diagonal(mask, False)
    avg_corr = corr_matrix.where(mask).stack().mean()

    # 设定阈值：波动率分位>0.7 且 平均相关系数>0.5 视为高波高相关
    high_vol = vol_quantile > 0.7
    high_corr = avg_corr > 0.5
    return high_vol, high_corr

# ================== 卖出信号检查 ==================
def check_sell_signals(etf, context):
    """返回卖出决策：'sell' 全部卖出, 'reduce' 减仓一半, None 不操作"""
    # 获取历史数据
    hist = attribute_history(etf, 250, '1d',
                             ['close', 'high', 'low', 'volume'], skip_paused=True)
    if hist['close'].shape[0] < 60:
        return None

    close = hist['close']
    high = hist['high']
    low = hist['low']
    volume = hist['volume']

    # 移动止损检查
    if etf in g.entry_highest:
        highest = g.entry_highest[etf]
        current = close[-1]
        if (highest - current) / highest > g.stop_loss:
            log.info(f'移动止损触发: {etf}, 最高 {highest:.3f}, 现价 {current:.3f}')
            return 'sell'

    # 成交量异常警告（长上影/放量阴线），但不立即清仓
    for i in range(1, 6):
        idx = -i
        if -idx > len(volume):
            break
        vol_60_high = np.max(volume[-60:])
        if volume[idx] >= vol_60_high:
            # 用前一日收盘近似开盘
            open_approx = close[idx-1] if idx-1 >= -len(close) else close[idx]
            # 长上影或收阴
            if close[idx] < open_approx:  # 阴线
                log.info(f'成交量异常阴线: {etf}')
                return 'reduce'
            if high[idx] > max(open_approx, close[idx]):
                body = abs(close[idx] - open_approx)
                upper_shadow = high[idx] - max(open_approx, close[idx])
                if body > 0 and upper_shadow > body * 1.5:
                    log.info(f'成交量异常长上影: {etf}')
                    return 'reduce'

    return None

def can_not_deal(code):
    cur_data = get_current_data()
    cur_price = cur_data[code].last_price
    no_price = cur_price is None or cur_price <=0
    is_paused = cur_data[code].paused
    is_st = cur_data[code].is_st
    is_limit = cur_price>=cur_data[code].high_limit or cur_price<=cur_data[code].low_limit 
    can_not_deal = (no_price or is_paused or is_st or is_limit)
    
    # 检查接近涨跌停
    prev_close = cur_data[code].day_open
    if prev_close and prev_close > 0:
        if cur_price >= prev_close * 1.098:   # 接近涨停
            log.info(f'{code} 当前接近涨停，暂停买入')
            can_not_deal = True
        if cur_price <= prev_close * 0.902:   # 接近跌停
            log.info(f'{code} 当前接近跌停，暂停买入')
            can_not_deal = True
    if can_not_deal:
        log.info(f"{code} can_not_deal={can_not_deal},no_price={no_price} is_paused={is_paused} is_st={is_st} is_limit={is_limit}")
    return can_not_deal
    
# ================== 主逻辑：计算信号与卖出 ==================
def calc_signals_and_clear(context):
    # 获取有效ETF
    valid_etfs = get_valid_etfs(context)
    if len(valid_etfs) < g.top_n:
        log.info('有效ETF数量不足')
        return

    # 计算综合得分
    df_scores = compute_factors(valid_etfs, context)
    if df_scores.empty:
        return

    # 市场状态
    high_vol, high_corr = assess_market_state(context)
    log.info(f'市场状态：高波动={high_vol}，高相关={high_corr}')
    g.market_high_risk = high_vol and high_corr

    # ---------- 生成目标持仓列表 ----------
    target_list = []
    used_sectors = {}

    # 尝试不同严格层级的过滤条件
    filter_levels = [
        {'name': '严格', 'require_ma': True, 'use_defend': True},
        {'name': '宽松', 'require_ma': False, 'use_defend': True},
        {'name': '底线', 'require_ma': False, 'use_defend': False}
    ]

    for level in filter_levels:
        target_list = []
        used_sectors = {}
        # 进攻型选择
        attack_count = 0
        for etf in df_scores.index:
            if attack_count >= g.attack_num:
                break
            close = df_scores.loc[etf, 'close']
            ma60 = df_scores.loc[etf, 'ma60']
            if level['require_ma'] and close <= ma60:
                continue
            sector = g.etf_dict.get(etf, ('', ''))[1]
            if sector in used_sectors and used_sectors[sector] >= g.max_sector_exposure:
                continue
            target_list.append((etf, 'attack'))
            used_sectors[sector] = used_sectors.get(sector, 0) + 1
            attack_count += 1

        # 防御型选择（如果该级别允许）
        if level['use_defend']:
            defend_candidates = df_scores[~df_scores.index.isin([t[0] for t in target_list])]
            if level['require_ma']:
                defend_candidates = defend_candidates[defend_candidates['close'] > defend_candidates['ma60']]
            if not defend_candidates.empty:
                defend_candidates = defend_candidates.sort_values('volatility_20')
                defend_count = 0
                for etf in defend_candidates.index:
                    if defend_count >= g.defend_num:
                        break
                    sector = g.etf_dict.get(etf, ('', ''))[1]
                    if sector in used_sectors and used_sectors[sector] >= g.max_sector_exposure:
                        continue
                    target_list.append((etf, 'defend'))
                    used_sectors[sector] = used_sectors.get(sector, 0) + 1
                    defend_count += 1

        if len(target_list) >= 1:  # 只要选出一只，就退出循环
            log.info(f'目标生成级别: {level["name"]}, 选出 {len(target_list)} 只')
            break

    # 超跌反转子策略（若仍有机会）
    if g.market_high_risk and len(target_list) < g.top_n:
        reversal_candidates = df_scores[~df_scores.index.isin([t[0] for t in target_list])]
        if not reversal_candidates.empty:
            ret_10 = {}
            for etf in reversal_candidates.index:
                close_series = reversal_candidates.loc[etf, 'close_series']
                if len(close_series) > g.reversal_days:
                    ret_10[etf] = close_series.iloc[-1] / close_series.iloc[-g.reversal_days] - 1
            if ret_10:
                ret_10 = pd.Series(ret_10).sort_values()
                for etf in ret_10.index[:1]:
                    vol_series = reversal_candidates.loc[etf, 'volume_series']
                    if len(vol_series) > g.reversal_vol_days:
                        recent_vol = vol_series.iloc[-g.reversal_vol_days:].mean()
                        prev_vol = vol_series.iloc[-2*g.reversal_vol_days:-g.reversal_vol_days].mean()
                        if prev_vol > 0 and recent_vol / prev_vol > 1.2:
                            target_list.append((etf, 'reversal'))

    g.target_etfs = target_list

    # 如果最终仍无目标，输出警告
    if not g.target_etfs:
        log.warning('当前无任何行业ETF满足买入条件，策略空仓')
    else:
        log.info(f'最终目标持仓: {[t[0] for t in g.target_etfs]}')

    # ---------- 处理现有持仓的卖出/减仓 ----------
    holdings = context.portfolio.positions
    current_codes = list(holdings.keys())
    target_codes = [t[0] for t in target_list]

    # 更新持仓最高价
    for etf in current_codes:
        if etf in holdings and holdings[etf].total_amount > 0:
            current_price = get_current_data()[etf].last_price
            if etf not in g.entry_highest:
                g.entry_highest[etf] = current_price
            else:
                g.entry_highest[etf] = max(g.entry_highest[etf], current_price)

    for etf in current_codes:
        if etf not in target_codes:
            # 排名跌出前30%或触发卖出信号
            rank_threshold_num = int(len(df_scores) * g.rank_sell_threshold)
            top_rank_etfs = df_scores.head(rank_threshold_num).index.tolist()
            sell_action = None
            if etf not in top_rank_etfs:
                sell_action = 'sell'
                log.info(f'卖出 {etf}: 排名跌出前30%')
            else:
                signal = check_sell_signals(etf, context)
                if signal == 'sell':
                    sell_action = 'sell'
                elif signal == 'reduce':
                    # 成交量异常减仓，并标记
                    if etf not in g.volume_warning_flag:
                        g.volume_warning_flag[etf] = True
                        log.info(f'成交量异常减仓: {etf}')
                        # 减仓至一半
                        current_value = holdings[etf].value
                        safe_order_target_value(context, etf, current_value * g.volume_warning_ratio, 'sell')
                    # 不立即清仓，等下一周期再判断
                    continue

            if sell_action == 'sell':
                safe_order_target_value(context, etf, 0, 'sell')
                g.entry_highest.pop(etf, None)
                g.volume_warning_flag.pop(etf, None)
        else:
            # 如果之前被标记警告，但本周没有继续恶化，可恢复仓位（由后续buy_signals调整）
            pass

# ================== 买入执行（含防追涨） ==================
def buy_signals(context):
    targets = g.target_etfs
    if not targets:
        return

    holdings = context.portfolio.positions
    total_value = context.portfolio.total_value

    # 根据市场状态分配资金
    if g.market_high_risk and any(t[1] == 'reversal' for t in targets):
        reversal_value = total_value * g.reversal_allocation
        normal_value = total_value - reversal_value
    else:
        reversal_value = 0
        normal_value = total_value

    attack_etfs = [t[0] for t in targets if t[1] == 'attack']
    defend_etfs = [t[0] for t in targets if t[1] == 'defend']
    reversal_etfs = [t[0] for t in targets if t[1] == 'reversal']

    normal_count = len(attack_etfs) + len(defend_etfs)
    per_normal = normal_value / max(normal_count, 1)
    per_reversal = reversal_value / max(len(reversal_etfs), 1)

    current_data = get_current_data()

    for etf, etype in targets:
        if etf in g.volume_warning_flag:
            continue

        if etype == 'reversal':
            cash_target = per_reversal
        else:
            cash_target = per_normal

        # 获取昨日收盘价（用于判断高开）
        yesterday_close = attribute_history(etf, 1, '1d', ['close'], skip_paused=True)['close']
        if len(yesterday_close) == 0:
            continue
        yesterday_close = yesterday_close.iloc[-1]

        # 获取当日实时价格与开盘价
        current_price = current_data[etf].last_price
        day_open = current_data[etf].day_open
        if day_open == 0:
            continue

        price_change = (current_price - yesterday_close) / yesterday_close
        open_change = (day_open - yesterday_close) / yesterday_close

        buy_ratio = 1.0

        # 防追涨条件1：跳空低开超过1.5%
        if price_change < g.buy_price_drop_threshold:
            buy_ratio = 0.5
            log.info(f'{etf} 低开 {price_change:.2%}，仅买入一半')

        # 防追涨条件2：高开后回落（模拟长上影）
        # 如果开盘高开超过1%，且当前价格已经跌回开盘价下方
        elif open_change > 0.01 and current_price < day_open:
            buy_ratio = 0.5
            log.info(f'{etf} 高开 {open_change:.2%} 后回落，视为追高风险，仅买入一半')

        target_value = cash_target * buy_ratio
        safe_order_target_value(context, etf, target_value, 'buy')
    
def safe_order_target_value(context,code,target_value,action='sell'):
    style = None
    if can_not_deal(code):
        return 0
    holdings = context.portfolio.positions
    available_cash = context.portfolio.available_cash
    cur_data = get_current_data()
    price = cur_data[code].last_price
    is_kcb = code[:2] == '68'
    limit_price = price*(1+0.015) if action == 'buy' else price*(1-0.015)
    style = MarketOrderStyle(limit_price)

    if code in holdings:
        pos = holdings[code]
        had_value = pos.value
        diff_value = target_value - had_value
        if action == 'sell' and diff_value < 0:
            if target_value==0:
                order(code, -pos.closeable_amount, style)
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(pos.closeable_amount, sell_amount)
            if a_amount >= 100:
                order(code, -a_amount, style)
                return -1
        elif diff_value > 0:
            buy_value = min(available_cash, diff_value)
            amount = int(abs(buy_value)  / price // 100) * 100
            if amount >= 200 or (amount>=100 and not is_kcb):
                order(code, amount, style)
                return 1
            else:
                log.warn(f"safe_order_target_value ignore,holding {code} {amount} {style} {available_cash}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {code} {amount} {style} {available_cash}")
    return 0