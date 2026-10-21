# 克隆自聚宽文章：https://www.joinquant.com/post/75962
# 标题：市场行情不好，不炒股票了，ETF基金主升浪收益比股票强~
# 作者：爱国者量化研究

# 克隆自聚宽文章：https://www.joinquant.com/post/75867
# 标题：年化169%的缝合实验：五福+七星+择时，发生了什么
# 作者：Sam2008

# -*- coding: utf-8 -*-
"""
五福+七星 综合策略（方案3专用版）+择时 （合并版v6）
==================================
v6改动：走弱期比较五福与七星评分，选高分者
  - 原v6：走弱期无条件切换到七星标的
  - 现v6改：走弱期比较WF#1与QX#1的momentum_score，谁高选谁
v5改动：当切换到七星标的时不做择时（直接买入），仅对五福标的做日内趋势择时
核心思路：五福为基+七星极端覆盖（方案3）
- 默认全仓五福（即五福5.2本身）
- 仅当七星#1分数 > 阈值且#1连续N天同一标的
- 才分配 DYN3_MAX_QIXING_WEIGHT 给七星

合并版：将 wufu_5_2_jq_class_v1.py + qixing_1_7_2_jq_class_v1.py + wufu_qixing_combine-v3.py
合并为单一文件，消除实盘子模块JQ内置函数不可见问题。

运行环境：聚宽（JoinQuant）回测/实盘环境
"""
from jqdata import *
import numpy as np
import math
import pandas as pd
import datetime
from datetime import datetime, date, timedelta

try:
    from etf_name_map import get_name as _get_std_name
except ImportError:
    _get_std_name = None


# ==================== 全局参数 ====================
CMP_MODE = True
VERBOSE_LOG = False

# ---- 方案3：五福为基+七星极端覆盖 ----
DYN3_QIXING_SCORE_THRESHOLD = 20
DYN3_STABILITY_DAYS = 1
DYN3_MAX_QIXING_WEIGHT = 0.8
SLIPPAGE = 0.0005

# ---- 日内趋势择时 ----
TREND_LOOKBACK_MINUTES = 30
TREND_SLOPE_THRESHOLD = 0.001
TREND_MIN_BARS = 5

# ---- 七星策略模块级参数 ----
ENABLE_PREMIUM_FILTER = True
USE_SHORT_MOMENTUM_FILTER = True


# ==================== 日志控制 ====================
_LOG_AVAILABLE = False
_orig_log_info = None
_orig_log_warning = None
_orig_log_error = None

try:
    _orig_log_info = log.info
    _orig_log_warning = log.warning
    _orig_log_error = log.error
    _LOG_AVAILABLE = True
except NameError:
    pass


def _log_filtered(msg):
    if VERBOSE_LOG and _orig_log_info:
        _orig_log_info(msg)


def _log_warn_filtered(msg):
    if VERBOSE_LOG and _orig_log_warning:
        _orig_log_warning(msg)


def _log_err_filtered(msg):
    if VERBOSE_LOG and _orig_log_error:
        _orig_log_error(msg)


if _LOG_AVAILABLE:
    log.info = _log_filtered
    log.warning = _log_warn_filtered
    log.error = _log_err_filtered


def _cmp(tag, msg):
    """模块级对比日志（综合策略使用）"""
    if CMP_MODE and _orig_log_info:
        _orig_log_info(f"[CMP] {tag}|{msg}")


def _get_name(security):
    try:
        return get_current_data()[security].name
    except:
        return "未知"


# ==================== 方案3：五福为基+七星极端覆盖 ====================

def _compute_dynamic_weights_scheme3(context):
    """
    以五福为基，仅在七星出现极端动量时覆盖。
    v6改：五福走弱期时比较五福与七星评分，选高分者

    核心逻辑：
    - 五福正常期：默认全仓五福，仅当七星#1分数>阈值且连续N天同一标的时才分配权重给七星
    - 五福走弱期：比较WF#1与QX#1的评分，谁高选谁（全仓）
    """
    qixing_ranked = getattr(g, '_qixing_ranked', []) or []
    wufu_ranked = getattr(g, '_wufu_ranked', []) or []
    wufu_weak = getattr(g._wufu, 'is_a_share_weak', False) if hasattr(g, '_wufu') else False

    triggered = False
    qx_score = 0
    qx_target = ''
    if qixing_ranked:
        qx_score = qixing_ranked[0].get('score', 0)
        qx_target = qixing_ranked[0].get('etf', '')

        prev_target = getattr(g, '_qixing_prev_target', None)
        stability = getattr(g, '_qixing_stability_count', 0)

        if qx_target and qx_target == prev_target:
            stability += 1
        else:
            stability = 1

        g._qixing_prev_target = qx_target
        g._qixing_stability_count = stability

        if qx_score > DYN3_QIXING_SCORE_THRESHOLD and stability >= DYN3_STABILITY_DAYS:
            triggered = True

    # v6改：五福走弱期 → 比较WF#1与QX#1评分，选高分者
    if wufu_weak:
        qx_defensive = g._qixing.defensive_etf if hasattr(g, '_qixing') else '511880.XSHG'
        qx_has_valid_target = bool(qx_target) and qx_target != qx_defensive

        wf_score = wufu_ranked[0].get('momentum_score', 0) if wufu_ranked else 0
        wf_target = wufu_ranked[0].get('etf', '') if wufu_ranked else ''

        if qx_has_valid_target and qx_score > wf_score:
            wufu_weight = 0.0
            qixing_weight = 1.0
            label = "WEAK_QX_WIN"
            _orig_log_info(f"【走弱期评分比较】QX胜出: WF={wf_target} score={wf_score:.4f} < QX={qx_target} score={qx_score:.4f}，全仓七星")
        elif wf_target and wf_score > 0:
            wufu_weight = 1.0
            qixing_weight = 0.0
            label = "WEAK_WF_WIN"
            _orig_log_info(f"【走弱期评分比较】WF胜出: WF={wf_target} score={wf_score:.4f} > QX={qx_target} score={qx_score:.4f}，全仓五福")
        else:
            # 两者都无有效目标，维持防御
            wufu_weight = 1.0
            qixing_weight = 0.0
            label = "WEAK_NO_TARGET"
            _orig_log_info("【走弱期评分比较】双方均无有效目标，保持防御")
    elif triggered:
        wufu_weight = 1.0 - DYN3_MAX_QIXING_WEIGHT
        qixing_weight = DYN3_MAX_QIXING_WEIGHT
        label = "TRIGGERED"
    else:
        wufu_weight = 1.0
        qixing_weight = 0.0
        label = "WUFU_ONLY"

    _orig_log_info(
        f"[DYN_W3] {label} wufu={wufu_weight:.3f} qixing={qixing_weight:.3f} "
        f"qx_score={qx_score:.4f} stability={getattr(g, '_qixing_stability_count', 0)}"
        f"{' WEAK' if wufu_weak else ''}"
    )
    return wufu_weight, qixing_weight


# ==================== 日内趋势择时 ====================


def _get_current_weights():
    """获取当前策略权重（方案3动态权重）"""
    w = getattr(g, '_wufu_weight', None)
    q = getattr(g, '_qixing_weight', None)
    if w is not None and q is not None:
        return w, q
    return 1.0, 0.0


def check_intraday_trend(security, context):
    """判断ETF盘中短期趋势：基于最近N分钟分钟线收盘价线性回归斜率"""
    try:
        minute_data = get_price(
            security, end_date=context.current_dt,
            count=TREND_LOOKBACK_MINUTES, frequency='1m',
            fields=['close'], skip_paused=False, fq='pre'
        )
        if minute_data is None or minute_data.empty:
            return True
        closes = minute_data['close'].values
        closes = closes[closes > 0]
        if len(closes) < TREND_MIN_BARS:
            return False
        x = np.arange(len(closes))
        slope = np.polyfit(x, closes, 1)[0]
        mean_price = closes.mean()
        slope_pct = slope / mean_price * 100 if mean_price > 0 else 0
        return slope_pct > TREND_SLOPE_THRESHOLD
    except Exception:
        return True


def _execute_buy_with_trend(context, force=False):
    """趋势判断买入：上涨趋势立即买入，下跌趋势保留到后续复检"""
    if not g._pending_buy_targets:
        return
    today_str = context.current_dt.strftime('%Y%m%d')
    etfs_to_buy_now = []
    still_pending = []

    for etf, target_val in g._pending_buy_targets:
        if force or check_intraday_trend(etf, context):
            etfs_to_buy_now.append((etf, target_val))
        else:
            still_pending.append((etf, target_val))

    for etf, target_val in etfs_to_buy_now:
        success = g._wufu.smart_order_target_value(etf, target_val, context)
        if success:
            _cmp('TRADE_BUY', f"{today_str}|{etf}|{target_val:.0f}|reason=趋势买入|etfname={_get_name(etf)}")

    g._pending_buy_targets = still_pending


def _check_pending_trend(context):
    """13:40/14:10/14:40 待买ETF趋势复检"""
    if not g._pending_buy_targets:
        return
    _execute_buy_with_trend(context, force=False)


def _force_buy_pending(context):
    """14:55 强制买入所有剩余待买ETF"""
    if not g._pending_buy_targets:
        return
    _execute_buy_with_trend(context, force=True)
    w = getattr(g, '_wufu_weight', None)
    q = getattr(g, '_qixing_weight', None)
    if w is not None and q is not None:
        return w, q
    return 1.0, 0.0


# ==================== 初始化 ====================

def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(SLIPPAGE), type="fund")
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=0.0001, close_commission=0.0001,
        close_today_commission=0.0001, min_commission=5,
    ), type="fund")
    set_benchmark("510300.XSHG")
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'info')

    log.info("【五福+七星综合策略-方案3 v6】启动！走弱期评分比较选高分，正常期同v5")

    g._wufu = WufuStrategy()
    g._qixing = QixingStrategy()

    g._wufu.verbose_log = False
    g._wufu.daily_detail = False
    g._wufu.attribute_history = attribute_history
    g._qixing.verbose_log = False
    g._qixing.daily_detail = False

    g._qixing.enable_premium_filter = True
    g._qixing.init_range_bound_status(context)

    run_daily(_morning_routine, time='09:30')
    run_daily(_afternoon_routine, time='13:10')
    run_daily(_sell_combined, time='13:10')
    run_daily(_buy_combined, time='13:10')
    run_daily(_check_pending_trend, time='13:40')
    run_daily(_check_pending_trend, time='14:10')
    run_daily(_check_pending_trend, time='14:40')
    run_daily(_force_buy_pending, time='14:55')
    run_daily(_reset_daily_flags, time='15:10')
    run_daily(_stop_loss_routine, time='every_bar')

    log.info("综合策略（方案3）v6初始化完成：走弱期评分比较(WF vs QX)，正常期同v5")


# ==================== 定时任务 ====================

def _morning_routine(context):
    today_str = context.current_dt.strftime('%Y%m%d')
    _cmp(f"{today_str}", "-" * 150)
    g._wufu.check_weak_period_daily(context)


def _afternoon_routine(context):
    """13:10 午盘任务：运行两个子策略的排名，准备目标"""
    today_str = context.current_dt.strftime('%Y%m%d')

    g._wufu_target = None
    g._qixing_target = None

    # ---- 1. 五福策略排名 ----
    if g._wufu.is_a_share_weak:
        g._wufu.merged_etf_pool = list(set(g._wufu.filtered_global_pool)) if g._wufu.filtered_global_pool else list(set(g._wufu.global_etf_pool))
        g._wufu.merged_etf_pool.sort()

    g._wufu.calculate_and_log_ranked_etfs(context)
    wufu_ranked = g._wufu.ranked_etfs_result or []
    g._wufu_ranked = wufu_ranked
    if wufu_ranked:
        g._wufu_target = wufu_ranked[0]['etf']
        wf_top10 = getattr(g._wufu, 'ranked_top_10', wufu_ranked) or wufu_ranked
        for i, m in enumerate(wf_top10[:5]):
            passed_filters = []
            if m.get('passed_momentum'): passed_filters.append('mom')
            if m.get('passed_r2'): passed_filters.append('r2')
            if m.get('passed_ma'): passed_filters.append('ma')
            if m.get('passed_volume'): passed_filters.append('vol')
            if m.get('passed_loss'): passed_filters.append('loss')
            _cmp(f"WF_RANK", f"{today_str}|rank{i+1}={m['etf']} score={m.get('momentum_score', 0):.4f} r2={m.get('r_squared', 0):.4f} filters={','.join(passed_filters)} etfname={_get_name(m['etf'])}")
    else:
        g._wufu_target = g._wufu.defensive_etf
    log.info(f"【五福】目标: {g._wufu_target}")

    # ---- 2. 七星策略排名 ----
    qixing_ranked = g._qixing.get_ranked_etfs(context) or []
    g._qixing_ranked = qixing_ranked
    if qixing_ranked:
        g._qixing_target = qixing_ranked[0]['etf']
        for i, m in enumerate(qixing_ranked[:5]):
            _cmp(f"QX_RANK", f"{today_str}|rank{i+1}={m['etf']} score={m.get('score',0):.4f} r2={m.get('r_squared',0):.4f} ann={m.get('annualized_returns',0)*100:.2f}% etfname={_get_name(m['etf'])}")
    else:
        g._qixing_target = g._qixing.defensive_etf
    log.info(f"【七星】目标: {g._qixing_target}")

    log.info(f"【综合策略】排名完成：五福→{g._wufu_target}，七星→{g._qixing_target}")

    # ---- 3. 计算方案3动态权重 ----
    wf_w, qx_w = _compute_dynamic_weights_scheme3(context)
    g._wufu_weight = wf_w
    g._qixing_weight = qx_w
    _orig_log_info(f"【方案3v6】五福={wf_w:.1%} 七星={qx_w:.1%}"
                   f"{' 走弱期评分比较' if getattr(g._wufu, 'is_a_share_weak', False) else ''}")
    record(七星切换状态=1 if qx_w > 0 else 0)


# ==================== 统一交易 ====================

def _get_combined_targets():
    """获取两个子策略合并后的唯一目标ETF列表"""
    wufu_target = getattr(g, '_wufu_target', None)
    qixing_target = getattr(g, '_qixing_target', None)
    targets = []
    if wufu_target:
        targets.append(wufu_target)
    if qixing_target and qixing_target != wufu_target:
        targets.append(qixing_target)
    return targets, wufu_target, qixing_target


def _sell_combined(context):
    """13:10 统一卖出：先汇总目标比例，卖出超配部分，释放现金给后续买入"""
    today_str = context.current_dt.strftime('%Y%m%d')

    targets, wufu_target, qixing_target = _get_combined_targets()
    target_set = set(targets)
    total_val = context.portfolio.total_value
    cur_wufu_ratio, cur_qixing_ratio = _get_current_weights()
    total_ratio = cur_wufu_ratio + cur_qixing_ratio

    for sec in list(context.portfolio.positions.keys()):
        pos = context.portfolio.positions[sec]
        if pos.total_amount <= 0:
            continue

        if sec not in target_set:
            target_val = 0
        else:
            if len(targets) == 1 and wufu_target == qixing_target and wufu_target is not None:
                continue
            ratio = cur_wufu_ratio / total_ratio if sec == wufu_target else cur_qixing_ratio / total_ratio
            target_val = total_val * ratio

        current_val = pos.total_amount * pos.price
        if current_val > target_val:

            success = g._wufu.smart_order_target_value(sec, target_val, context)
            if success:
                _cmp('TRADE_SELL', f"{today_str}|{sec}|reason=组合调仓")


def _buy_combined(context):
    """13:10 统一买入（v5：七星直接买入不做择时，五福做日内趋势择时）"""
    today_str = context.current_dt.strftime('%Y%m%d')

    targets, wufu_target, qixing_target = _get_combined_targets()

    if not targets:
        log.info("今日无目标ETF，保持空仓")
        g._pending_buy_targets = []
        _cmp('COMB', f"{today_str}|wufu={wufu_target}|qixing={qixing_target}|"
                     f"value={context.portfolio.total_value:.0f}|"
                     f"cash={context.portfolio.available_cash:.0f}|"
                     f"wufuname={_get_name(wufu_target) if wufu_target else ''}&qixingname={_get_name(qixing_target) if qixing_target else ''}")
        return

    total_val = context.portfolio.total_value
    cur_wufu_ratio, cur_qixing_ratio = _get_current_weights()
    total_ratio = cur_wufu_ratio + cur_qixing_ratio

    # v5：七星标的直接买入（不做择时），五福标的走趋势择时队列
    pending_wufu = []
    for etf in targets:
        if len(targets) == 1 and wufu_target == qixing_target and wufu_target is not None:
            # 五福七星同标的 -> 按五福逻辑，正常择时
            target_val = total_val
            pending_wufu.append((etf, target_val))
        else:
            ratio = cur_wufu_ratio / total_ratio if etf == wufu_target else cur_qixing_ratio / total_ratio
            target_val = total_val * ratio

            if cur_qixing_ratio > 0 and etf == qixing_target:
                # v5：七星标的直接买入，跳过趋势择时
                success = g._wufu.smart_order_target_value(etf, target_val, context)
                if success:
                    _cmp('TRADE_BUY', f"{today_str}|{etf}|{target_val:.0f}|reason=七星直接买入(无择时)|etfname={_get_name(etf)}")
                    log.info(f"【七星直接买入】{etf} {_get_name(etf)} 目标{target_val:.0f}（跳过趋势择时）")
            else:
                # 五福标的 -> 进入趋势择时等待队列
                pending_wufu.append((etf, target_val))

    g._pending_buy_targets = pending_wufu
    if pending_wufu:
        _execute_buy_with_trend(context, force=False)

    _cmp('COMB', f"{today_str}|wufu={wufu_target}|qixing={qixing_target}|"
                 f"value={context.portfolio.total_value:.0f}|"
                 f"cash={context.portfolio.available_cash:.0f}|"
                 f"wufuname={_get_name(wufu_target) if wufu_target else ''}&qixingname={_get_name(qixing_target) if qixing_target else ''}")


def _stop_loss_routine(context):
    """every_bar 分钟级止损"""
    g._wufu.minute_level_stop_loss(context)
    if hasattr(g._qixing, 'minute_level_stop_loss'):
        g._qixing.minute_level_stop_loss(context)


def _reset_daily_flags(context):
    """15:10 收盘缓存重置"""
    g._pending_buy_targets = []
    g._wufu.reset_daily_flags(context)
    if hasattr(g._qixing, 'reset_range_bound_daily'):
        g._qixing.reset_range_bound_daily(context)


# ==================== WufuStrategy ====================

class WufuStrategy:
    def _cmp(self, tag, msg):
        """输出 [CMP] 对比日志（不受 VERBOSE_LOG 影响）"""
        if tag.startswith('POOL') and not self.daily_detail:
            return
        if CMP_MODE and _orig_log_info:
            _orig_log_info(f"[CMP] {tag}|{msg}")

    def __init__(self):
        # ==================== ETF池定义 ====================
        self.global_etf_pool = [
            '518880.XSHG', 
            #'501018.XSHG',
            #'161226.XSHE', 
            #'159985.XSHE',
            '159980.XSHE', '513310.XSHG', 
            #'159518.XSHE', 
            '159509.XSHE',
            '513100.XSHG', '513520.XSHG', '513500.XSHG', '159502.XSHE',
            '513400.XSHG', '513030.XSHG', '513290.XSHG', '520830.XSHG',
            '159529.XSHE',
        ]
        self.china_etf_pool = [
            '513090.XSHG', '513120.XSHG', '513180.XSHG', '513330.XSHG',
            '513750.XSHG', '159892.XSHE', '513190.XSHG', '159605.XSHE',
            '513630.XSHG', '159323.XSHE', '510900.XSHG', '513920.XSHG',
            '513970.XSHG', '511380.XSHG', '512050.XSHG', '510500.XSHG',
            '159915.XSHE', '510300.XSHG', '512100.XSHG', '159949.XSHE',
            '588080.XSHG', '159967.XSHE', '588220.XSHG', '563300.XSHG',
            '510760.XSHG', '588200.XSHG', '515880.XSHG', '159981.XSHE',
            '512880.XSHG', 
            #'513350.XSHG', 
            '159326.XSHE', '159516.XSHE',
            '159206.XSHE', '512480.XSHG', '159363.XSHE', '159870.XSHE',
            '512400.XSHG', '159755.XSHE', '588170.XSHG', '159992.XSHE',
            '159995.XSHE', '512890.XSHG', '515220.XSHG', '159566.XSHE',
            '159819.XSHE', '512800.XSHG', '512690.XSHG', '515050.XSHG',
            '562500.XSHG', '512170.XSHG', '517520.XSHG', '159869.XSHE',
            '512070.XSHG', '159611.XSHE', '562800.XSHG', '515120.XSHG',
            '512010.XSHG', '510880.XSHG', '515790.XSHG', '515980.XSHG',
            '512660.XSHG', '159928.XSHE', '512710.XSHG', '560860.XSHG',
            '515030.XSHG', '159766.XSHE', '159218.XSHE', '159852.XSHE',
            '516160.XSHG', '516150.XSHG', '159227.XSHE', '159583.XSHE',
            '588790.XSHG', '159865.XSHE', '512980.XSHG', '159851.XSHE',
            #'561360.XSHG', 
            '561980.XSHG', '562590.XSHG', '512200.XSHG',
            '159732.XSHE', '159667.XSHE', '516510.XSHG', '159840.XSHE',
            '159998.XSHE', '159825.XSHE', '512670.XSHG', '159883.XSHE',
            '515210.XSHG', '515400.XSHG', '159256.XSHE', '561330.XSHG',
            '515170.XSHG', '159638.XSHE', '516520.XSHG', '513360.XSHG',
            '516190.XSHG',
        ]
        self.qixing_etf_pool = [
            '513080.XSHG', '513730.XSHG', '159792.XSHE', '513130.XSHG',
            '513050.XSHG', '159920.XSHE', '513690.XSHG', '510050.XSHG',
            '510210.XSHG', '563360.XSHG', '512040.XSHG', '159201.XSHE',
            '511010.XSHG', '511220.XSHG',
        ]

        self.fixed_etf_pool = self.global_etf_pool + self.china_etf_pool #+ self.qixing_etf_pool
        self.avg_etf_money_threshold = None
        self.filtered_fixed_pool = []
        self.dynamic_etf_pool = []
        self.merged_etf_pool = []
        self.ranked_etfs_result = []
        self.filtered_global_pool = []
        self.global_threshold_divisor = 20000
        self.is_a_share_weak = False
        self.weak_period_ma_lookback = 10
        self.weak_start_date = None
        self.weak_days_count = 0
        self.max_weak_days = 20
        self.holdings_num = 1
        self.defensive_etf = "511880.XSHG"
        self.min_money = 10
        self.target_etfs_list = []
        self.etf_names_dict = {}
        self.cache_date = None
        self.yesterday_close_cache = {}
        self.lookback_days = 25
        self.min_score_threshold = 0
        self.max_score_threshold = 5.0
        self.score_threshold_ratio = 0.9
        self.enable_r2_filter = True
        self.r2_threshold = 0.4
        self.enable_ma_filter = True
        self.ma_lookback = 10
        self.ma_threshold = 1.0
        self.enable_volume_check = True
        self.volume_lookback = 5
        self.volume_threshold = 1.8
        self.enable_loss_filter = True
        self.loss = 0.97
        self.max_portfolio_value = 0
        self.drawdown_threshold = 0.03
        self.drawdown_records = []
        self.use_fixed_stop_loss = True
        self.fixedStopLossThreshold = 0.95
        self.verbose_log = False
        self.daily_detail = False

    def setup_jq(self, context):
        set_option("avoid_future_data", True)
        set_option("use_real_price", True)
        set_slippage(PriceRelatedSlippage(0.0001), type="fund")
        set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0001,
                      close_commission=0.0001, close_today_commission=0.0001, min_commission=5), type="fund")
        set_benchmark("510300.XSHG")
        log.set_level('order', 'error')
        log.set_level('system', 'error')
        log.set_level('strategy', 'info')

    def schedule(self, context):
        run_daily(self.morning_routine, time='09:00')
        run_daily(self.check_weak_period_daily, time='09:40')
        run_daily(self.afternoon_routine, time='13:10')
        run_daily(self.sell_routine, time='13:10')
        run_daily(self.buy_routine, time='13:15')
        run_daily(self.reset_daily_flags, time='15:10')
        run_daily(self.minute_level_stop_loss, time='every_bar')

    def initialize(self, context):
        self.setup_jq(context)
        self.schedule(context)
        log.info("【五福闹新春】v5.2！")
        log.info(f"策略初始化完成：ETF池{len(self.china_etf_pool)}只，动量周期{self.lookback_days}天")
        log.info(f"止损: {'启用' if self.use_fixed_stop_loss else '禁用'} ({self.fixedStopLossThreshold:.0%})")

    def check_weak_period_daily(self, context):
        self.check_a_share_weak_period(context)
        self.midday_routine(context)

    def morning_routine(self, context):
        log.info("★" * 80)
        log.info("▶️ 【晨间流水线】启动...")
        log.info("【持仓检查】检查当前持仓状态...")
        self.check_positions(context)
        log.info("【回撤监控】监控策略回撤...")
        self.monitor_drawdown(context)
        log.info("【流动性阈值】计算全市场ETF流动性阈值...")
        self.calculate_global_etf_threshold(context)
        log.info("⏸️ 【晨间流水线】执行完毕！")

    def midday_routine(self, context):
        if self.daily_detail:
            log.info("★" * 80)
            log.info("▶️ 【早盘流水线】启动...")
        if self.is_a_share_weak:
            if self.daily_detail:
                log.info(f"🔴 【走弱期池更新】仅对全球/海外ETF池进行流动性过滤...")
            self.filter_global_pool_by_volume(context)
            if self.daily_detail:
                log.info(f"【走弱期池更新完成】过滤后全球池: {len(self.filtered_global_pool)}只")
        else:
            if self.daily_detail:
                log.info(f"🟢 【正常期池更新】执行动态池更新、固定池过滤、合并池...")
                log.info("【动态池更新】更新行业ETF动态池（各行业流动性最佳ETF）...")
            self.update_sector_pool(context)
            if self.daily_detail:
                log.info("【固定池过滤】过滤固定ETF池流动性...")
            self.filter_fixed_pool_by_volume(context)
            if self.daily_detail:
                log.info("【合并池】合并固定池与动态池...")
            self.daily_merge_etf_pools(context)
            if self.daily_detail:
                log.info(f"【正常期池更新完成】合并池: {len(self.merged_etf_pool)}只")
        if self.daily_detail:
            log.info("⏸️ 【早盘流水线】执行完毕！")

    def afternoon_routine(self, context):
        log.info("★" * 80)
        log.info("▶️ 【午盘流水线】启动...")
        if self.is_a_share_weak:
            if hasattr(self, 'filtered_global_pool') and self.filtered_global_pool:
                self.merged_etf_pool = list(set(self.filtered_global_pool))
            else:
                self.merged_etf_pool = list(set(self.global_etf_pool))
            self.merged_etf_pool.sort()
            log.info(f"🔴 【大A走弱期】使用过滤后全球/海外ETF池，共{len(self.merged_etf_pool)}只")
        else:
            log.info(f"🟢 【大A正常期】使用合并池，共{len(self.merged_etf_pool)}只")
        log.info("【动量计算】计算ETF动量得分与排序...")
        self.calculate_and_log_ranked_etfs(context)
        log.info("⏸️ 【午盘流水线】执行完毕！")

    def sell_routine(self, context):
        log.info("★" * 80)
        log.info("▶️ 【卖出流水线】启动...")
        self.execute_sell_trades(context)
        log.info("⏸️ 【卖出流水线】执行完毕！")

    def buy_routine(self, context):
        log.info("★" * 80)
        log.info("▶️ 【买入流水线】启动...")
        self.execute_buy_trades(context)
        log.info("⏸️ 【买入流水线】执行完毕！")
        today_str = context.current_dt.strftime('%Y%m%d')
        self._cmp('PORTFOLIO', f"{today_str}|value={context.portfolio.total_value:.0f}|cash={context.portfolio.available_cash:.0f}|positions={len(getattr(self, 'target_etfs_list', []))}")

    def reset_daily_flags(self, context):
        self.cache_date = None
        self.yesterday_close_cache = {}
        log.info("🔄 收盘缓存重置完成")

    def check_positions(self, context):
        current_data = get_current_data()
        for security in context.portfolio.positions:
            position = context.portfolio.positions[security]
            if position.total_amount > 0:
                security_name = self.get_security_name(security)
                log.info(f"📊 【持仓检查】{security} {security_name}, 数量: {position.total_amount}, 成本: {position.avg_cost:.3f}, 当前价: {position.price:.3f}")
                if current_data[security].paused:
                    log.info(f"⚠️ {security} {security_name} 今日停牌")

    def monitor_drawdown(self, context):
        try:
            current_value = context.portfolio.total_value
            if current_value > self.max_portfolio_value:
                self.max_portfolio_value = current_value
            if self.max_portfolio_value > 0:
                current_drawdown = (self.max_portfolio_value - current_value) / self.max_portfolio_value
                if current_drawdown >= self.drawdown_threshold:
                    record = {
                        'date': context.current_dt.strftime('%Y-%m-%d'),
                        'drawdown': current_drawdown,
                        'portfolio_value': current_value,
                        'max_value': self.max_portfolio_value,
                        'is_weak': self.is_a_share_weak
                    }
                    positions_info = []
                    for security in context.portfolio.positions:
                        position = context.portfolio.positions[security]
                        if position.total_amount > 0:
                            security_name = self.get_security_name(security)
                            positions_info.append(f"{security_name}:{position.total_amount}股")
                    record['positions'] = positions_info
                    self.drawdown_records.append(record)
                    log.info(f"【回撤预警】回撤达到 {current_drawdown:.2%} (阈值: {self.drawdown_threshold:.0%})")
                    log.info(f"  当前净值: {current_value:,.0f}  |  最高净值: {self.max_portfolio_value:,.0f}")
                    log.info(f"  大A状态: {'走弱期' if self.is_a_share_weak else '正常期'}")
                    log.info(f"  持仓: {', '.join(positions_info) if positions_info else '空仓'}")
        except Exception as e:
            log.error(f"【回撤监控】计算异常: {e}")

    def calculate_global_etf_threshold(self, context):
        log.info("【全局阈值更新】开始计算全市场ETF流动性门槛")
        try:
            df_etf = get_all_securities(['etf'], date=context.current_dt)
            etf_list = df_etf.index.tolist()
            if not etf_list:
                log.warning("未找到任何场内ETF，使用保守阈值1000万")
                self.avg_etf_money_threshold = 10000000
                return
            log.info(f"全市场ETF总数: {len(etf_list)}只")
            trade_days = get_trade_days(end_date=context.previous_date, count=3)
            start_day = trade_days[0]
            df = get_price(security=etf_list, start_date=start_day, end_date=context.previous_date, frequency='daily', fields=['money'], panel=False, skip_paused=True)
            if df is None or df.empty:
                log.warning("无法获取历史成交额数据，使用保守阈值1000万")
                self.avg_etf_money_threshold = 10000000
                return
            daily_totals = df.groupby('time')['money'].sum()
            daily_counts = df[df['money'] > 0].groupby('time')['code'].nunique()
            for day, money in daily_totals.items():
                count = daily_counts.get(day, 0)
                log.info(f"  {day.date()} 全市场ETF总成交额: {money/1e8:.2f}亿元 ({count}只ETF有成交)")
            if len(daily_totals) < 3:
                log.warning(f"仅有{len(daily_totals)}个有效交易日，使用保守阈值1000万")
                self.avg_etf_money_threshold = 10000000
                return
            avg_total_money = daily_totals.mean()
            threshold = avg_total_money / self.global_threshold_divisor
            self.avg_etf_money_threshold = threshold
            log.info(f"【全局阈值更新完成】近{len(daily_totals)}日全市场ETF日均总成交额={avg_total_money/1e8:.2f}亿元，阈值={threshold/1e4:.0f}万元({threshold:,.0f}元)")
        except Exception as e:
            log.warning(f"计算全局阈值异常: {e}，使用保守阈值1000万")
            self.avg_etf_money_threshold = 10000000

    def filter_global_pool_by_volume(self, context):
        log.info("【全球池过滤】开始执行")
        if getattr(self, 'avg_etf_money_threshold', None) is None:
            log.info("【全球池过滤】阈值未初始化，立即计算")
            self.calculate_global_etf_threshold(context)
        if not self.global_etf_pool:
            log.info("【全球池过滤】全球池为空，跳过过滤")
            self.filtered_global_pool = []
            return
        dynamic_threshold = self.avg_etf_money_threshold
        log.info(f"【全球池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
        end_date = context.previous_date
        TRADE_DAYS_COUNT = 3
        try:
            price_data = get_price(self.global_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
            if price_data is None or price_data.empty:
                log.warning("【全球池过滤】无法获取成交额数据，使用原始全球池")
                self.filtered_global_pool = self.global_etf_pool[:]
                return
            total_money = price_data.groupby('code')['money'].sum()
            avg_daily_money = total_money / TRADE_DAYS_COUNT
            qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
            new_global_pool = qualified.index.tolist()
            removed = set(self.global_etf_pool) - set(new_global_pool)
            if removed:
                removed_info = []
                for code in removed:
                    try:
                        name = getattr(self, 'etf_names_dict', {}).get(code, str(code))
                        money = avg_daily_money.get(code, 0)
                        removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                    except:
                        removed_info.append(code)
                log.info(f"【全球池过滤】剔除低流动性ETF({len(removed)}只)")
            self.filtered_global_pool = new_global_pool
            sorted_qualified = qualified.sort_values(ascending=False)
            log.info(f"【全球池过滤】保留高流动性ETF({len(new_global_pool)}只)")
        except Exception as e:
            log.warning(f"【全球池过滤】异常: {e}")
            self.filtered_global_pool = self.global_etf_pool[:]

    def update_sector_pool(self, context):
        log.info("【动态池更新】开始执行")
        log.info("【动态池更新】计算流动性阈值")
        self.calculate_global_etf_threshold(context)

        FUND_COMPANIES = sorted(list(set([
            '易方达', '广发', '华夏', '华安', '嘉实', '富国', '招商', '鹏华', '南方', '汇添富', '国泰', '平安',
            '银华', '天弘', '建信', '工银', '华泰柏瑞', '博时', '景顺长城', '景顺', '华宝', '申万菱信', '万家', '中欧',
            '兴证全球', '浙商', '诺安', '前海开源', '泰康', '泰达宏利', '农银汇理', '交银', '东方红', '财通', '华商',
            '国联', '永赢', '金鹰', '德邦', '创金合信', '西部利得', '圆信永丰', '泓德', '汇安', '诺德', '恒生前海',
            '华润元大', '大成', '海富通', '摩根', '华泰', '中信', '中银', '兴全', '国信', '长城', '中金', '浙商证券',
            '东海', '东吴', '浦银安盛', '信达澳亚', '中加', '中航', '中融', '中邮', '中庚', '中信保诚', '中信建投',
            '中银国际', '中银证券', '九泰', '交银施罗德', '光大保德信', '兴银', '农银', '国投瑞银', '国海富兰克林',
            '国联安', '国金', '太平', '方正富邦', '民生加银', '汇丰晋信', '银河', '长信', '长安', '长盛', '长江证券', '鹏扬'
        ])), key=len, reverse=True)

        NOISE_WORDS = sorted(list(set([
            '6666', '8888', '9999', 'A类', 'AH', 'B', 'BS', 'C', 'C类', 'CS', 'DB', 'E', 'E类',
            'ETF', 'ETF基金', 'ETF联接', 'FG', 'G60', 'GF', 'GT', 'HGS', 'LOF', 'LOF基金', 'LOF联接',
            'SG', 'SZ', 'TF', 'TK', 'WJ', 'YH', 'ZS', 'ZZ', '板块', '策略', '产业', '场内', '场外', '低波',
            '基本面', '基金', '精选', '联接', '联接基金', '量化', '龙头', '民企', '民营', '国企', '央企', '智能',
            '全指', '上市开放式', '指基', '指增', '指数', '指数A', '指数C', '指数ETF', '指数基金', '主题', '增强',
            '上海', '黄', '30', '50', '100', '300', '500', '1000', '2000', '大', '新', '四川', '浙江', '湖北',
        ])), key=len, reverse=True)

        SPECIAL_GROUPS = sorted([
            {'name': '香港组', 'keywords': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS科技'], key=len, reverse=True),
             'remove_words': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS'], key=len, reverse=True)},
            {'name': '科创组', 'keywords': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创'], key=len, reverse=True),
             'remove_words': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创', '债券', '债汇', '债指', '债沪', '债易', '债基', '债兴', '债摩', '债', 'AAA'], key=len, reverse=True)},
            {'name': '创业组', 'keywords': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True),
             'remove_words': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True)},
            {'name': '美指组', 'keywords': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True),
             'remove_words': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True)}
        ], key=lambda x: max(len(kw) for kw in x['keywords']), reverse=True)

        exclude_keywords = sorted(list(set([
            '300', '500', '1000', '2000', '800', '30', '50', '100', '180', '200',
            '沪深', '中证', '上证', '深证', '深成', 'A50', 'A100', 'A500', '深100',
            '短融', '可转债', '转债', '双债', '利率债', '国债', '地债', '政金债', '国开债', '基准国债', '新综债',
            '信用债', '企业债', '公司债', '城投债', '城投', '美元债', '沪公司债', '科创债', '科债', '科创AAA',
            '自由现金流', '现金流', '现金流E', '现金流基', '现金流TF', '现金流全', '300现金流', '800现金流',
            '货币', '现金', '快线', '快钱', '中银现金', '500现金', '800现金', '现金800', '现金自由', '现金指数',
            '全指现金', '现金全指', 'ESG', 'MSCI', 'MS', '债',
        ])), key=len, reverse=True)

        try:
            df_etf = get_all_securities(['etf'])
            etf_list = df_etf.index.tolist()
            self.etf_names_dict = df_etf['display_name'].to_dict()
            if _get_std_name is not None:
                for _code in list(self.etf_names_dict.keys()):
                    _std = _get_std_name(_code)
                    if _std is not None:
                        self.etf_names_dict[_code] = _std
        except Exception as e:
            log.warning(f"获取全市场ETF列表失败: {e}")
            return

        if self.daily_detail:
            self._cmp('POOL_DETAIL', f"{context.current_dt.strftime('%Y%m%d')}|total_mkt={len(etf_list)}|threshold={self.avg_etf_money_threshold:.0f}")
        log.info(f"【动态池更新】全市场ETF总数: {len(etf_list)}只")
        normal_etfs = []
        special_etfs = []
        special_group_map = {}
        excluded_count = 0

        for code in etf_list:
            try:
                name = self.etf_names_dict.get(code, str(code))
                is_special = False
                matched_group = None
                for group in SPECIAL_GROUPS:
                    for kw in group['keywords']:
                        if kw in name:
                            is_special = True
                            matched_group = group['name']
                            break
                    if is_special:
                        break
                is_excluded = False
                for k in exclude_keywords:
                    if k in name:
                        is_excluded = True
                        excluded_count += 1
                        break
                if not is_excluded:
                    if is_special:
                        special_etfs.append(code)
                        special_group_map[code] = matched_group
                    else:
                        normal_etfs.append(code)
            except Exception:
                continue

        group_counts = {}
        for code in special_etfs:
            group_name = special_group_map.get(code, '未知')
            group_counts[group_name] = group_counts.get(group_name, 0) + 1
        self._cmp('POOL_DETAIL', f"{context.current_dt.strftime('%Y%m%d')}|special={{{','.join(f'{k}={v}' for k,v in group_counts.items())}}}|normal_cnt={len(normal_etfs)}|special_cnt={len(special_etfs)}|excluded={excluded_count}")
        log.info(f"【动态池更新】特别组分布: {group_counts}")
        log.info(f"【动态池更新】进入特别组: {len(special_etfs)}只")
        log.info(f"【动态池更新】进入普通组: {len(normal_etfs)}只")
        log.info(f"【动态池更新】排除ETF: {excluded_count}只")

        end_date = context.previous_date
        TRADE_DAYS_COUNT = 3
        dynamic_threshold = self.avg_etf_money_threshold

        def filter_by_liquidity(etf_codes, group_name):
            if not etf_codes:
                return pd.Series(dtype=float), 0
            try:
                price_data = get_price(etf_codes, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
                if price_data is None or price_data.empty:
                    return pd.Series(dtype=float), len(etf_codes)
                total_money = price_data.groupby('code')['money'].sum()
                avg_daily_money = total_money / TRADE_DAYS_COUNT
                qualified_series = avg_daily_money[avg_daily_money > dynamic_threshold].sort_values(ascending=False)
                filtered_out = len(etf_codes) - len(qualified_series)
                return qualified_series, filtered_out
            except Exception:
                return pd.Series(dtype=float), len(etf_codes)

        normal_qualified, normal_filtered_out = filter_by_liquidity(normal_etfs, "普通组")
        special_qualified, special_filtered_out = filter_by_liquidity(special_etfs, "特别组")
        normal_sorted = normal_qualified.index.tolist()
        special_sorted = special_qualified.index.tolist()
        self._cmp('POOL_DETAIL', f"{context.current_dt.strftime('%Y%m%d')}|after_liq|normal={len(normal_sorted)}|special={len(special_sorted)}")
        log.info(f"【动态池更新】特别组流动性过滤: {len(special_etfs)}→{len(special_sorted)}只")
        log.info(f"【动态池更新】普通组流动性过滤: {len(normal_etfs)}→{len(normal_sorted)}只")

        if not normal_sorted and not special_sorted:
            log.warning("【动态池更新】无ETF通过流动性过滤")
            self.dynamic_etf_pool = []
            return

        def get_remove_words_for_etf(_, is_special, matched_group_name):
            if not is_special:
                return []
            for group in SPECIAL_GROUPS:
                if group['name'] == matched_group_name:
                    return group['remove_words']
            return []

        def clean_name(original_name, is_special=False, matched_group_name=None):
            cleaned = original_name
            for company in FUND_COMPANIES:
                cleaned = cleaned.replace(company, '')
            if is_special and matched_group_name:
                for word in get_remove_words_for_etf(original_name, is_special, matched_group_name):
                    cleaned = cleaned.replace(word, '')
            for noise in NOISE_WORDS:
                cleaned = cleaned.replace(noise, '')
            return cleaned.strip()

        normal_industry_groups = {}
        for code in normal_sorted:
            try:
                original_name = self.etf_names_dict.get(code, str(code))
                money = normal_qualified[code]
                cleaned = clean_name(original_name, is_special=False)
                if cleaned == '':
                    continue
                industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
                if industry_key not in normal_industry_groups:
                    normal_industry_groups[industry_key] = []
                normal_industry_groups[industry_key].append({
                    'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                    'money': money, 'group_type': '普通'
                })
            except Exception:
                continue

        special_industry_groups = {}
        for code in special_sorted:
            try:
                original_name = self.etf_names_dict.get(code, str(code))
                matched_group = special_group_map.get(code, '未知')
                money = special_qualified[code]
                cleaned = clean_name(original_name, is_special=True, matched_group_name=matched_group)
                if cleaned == '':
                    continue
                industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
                group_key = f"{matched_group}_{industry_key}"
                if group_key not in special_industry_groups:
                    special_industry_groups[group_key] = []
                special_industry_groups[group_key].append({
                    'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                    'money': money, 'group_type': matched_group, 'display_group': matched_group
                })
            except Exception:
                continue

        final_pool_info = []
        for industry_key, items in normal_industry_groups.items():
            sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
            final_pool_info.append(sorted_items[0])
        for group_key, items in special_industry_groups.items():
            sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
            final_pool_info.append(sorted_items[0])

        final_pool_info_sorted = sorted(final_pool_info, key=lambda x: x['money'], reverse=True)
        top_300 = final_pool_info_sorted[:300]
        self.dynamic_etf_pool = [item['code'] for item in top_300]
        log.info(f"【动态池更新完成】动态池共{len(self.dynamic_etf_pool)}只ETF")
        if len(self.dynamic_etf_pool) <= 10:
            for item in top_300[:10]:
                log.info(f"  {item['code']} {item['original_name']} 日均成交额: {item['money']/1e8:.2f}亿")

    def filter_fixed_pool_by_volume(self, context):
        log.info("【固定池过滤】开始执行")
        if getattr(self, 'avg_etf_money_threshold', None) is None:
            log.info("【固定池过滤】阈值未初始化，立即计算")
            self.calculate_global_etf_threshold(context)
        if not self.fixed_etf_pool:
            log.info("【固定池过滤】固定池为空，跳过过滤")
            return
        dynamic_threshold = self.avg_etf_money_threshold
        log.info(f"【固定池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
        end_date = context.previous_date
        TRADE_DAYS_COUNT = 3
        try:
            price_data = get_price(self.fixed_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
            if price_data is None or price_data.empty:
                log.warning("【固定池过滤】无法获取成交额数据，跳过过滤")
                self.filtered_fixed_pool = self.fixed_etf_pool[:]
                return
            total_money = price_data.groupby('code')['money'].sum()
            avg_daily_money = total_money / TRADE_DAYS_COUNT
            qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
            new_fixed_pool = qualified.index.tolist()
            removed = set(self.fixed_etf_pool) - set(new_fixed_pool)
            if removed:
                removed_info = []
                for code in removed:
                    try:
                        name = getattr(self, 'etf_names_dict', {}).get(code, str(code))
                        money = avg_daily_money.get(code, 0)
                        removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                    except:
                        removed_info.append(code)
                log.info(f"【固定池过滤】剔除低流动性ETF({len(removed)}只)")
            self.filtered_fixed_pool = new_fixed_pool
            sorted_qualified = qualified.sort_values(ascending=False)
            log.info(f"【固定池过滤】保留高流动性ETF({len(new_fixed_pool)}只)")

            today_str = context.current_dt.strftime('%Y%m%d')
            for _code in ['512400.XSHG', '517520.XSHG', '515880.XSHG', '159218.XSHE', '512930.XSHG', '515000.XSHG']:
                _amt = avg_daily_money.get(_code, 0)
                _in = _code in qualified.index if hasattr(qualified, 'index') else _code in qualified
                print(f"【DEBUG_{_code.replace('.XSHG','').replace('.XSHE','')}】volume_check|{today_str}|avg_amount={_amt:.0f}|threshold={dynamic_threshold:.0f}|ratio={_amt/dynamic_threshold:.4f}|in_filtered_fix={1 if _in else 0}")
        except Exception as e:
            log.warning(f"【固定池过滤】异常: {e}")
            self.filtered_fixed_pool = self.fixed_etf_pool[:]

# ========== 修改点：新增黑名单过滤 ==========
    def daily_merge_etf_pools(self, context):
        if not hasattr(self, 'filtered_fixed_pool'):
            self.filtered_fixed_pool = self.fixed_etf_pool[:]
        merged = list(set(self.filtered_fixed_pool + self.dynamic_etf_pool))

        # 强制黑名单：永久排除指定ETF
        BLACKLIST = {
            '501018.XSHG',   # 南方原油
            '561360.XSHG',
            '513350.XSHG',
            '161226.XSHE'    # 白银LOF
        }
        merged = [code for code in merged if code not in BLACKLIST]

        merged.sort()
        log.info("【合并ETF池】开始执行")
        log.info(f"【合并池统计】固定池: {len(self.filtered_fixed_pool)}只, 动态池: {len(self.dynamic_etf_pool)}只, 合并后: {len(merged)}只")
        self.merged_etf_pool = merged
        today_str = context.current_dt.strftime('%Y%m%d')
        self._cmp('POOL', f"{today_str}|dyn={len(getattr(self, 'dynamic_etf_pool', []))}|fix={len(self.filtered_fixed_pool)}|mrg={len(merged)}")
        for _code in ['512400.XSHG', '517520.XSHG', '515880.XSHG', '159218.XSHE', '512930.XSHG', '515000.XSHG']:
            _tag = _code.replace('.XSHG','').replace('.XSHE','')
            
    def calculate_and_log_ranked_etfs(self, context):
        if not hasattr(self, 'merged_etf_pool') or not self.merged_etf_pool:
            log.warning("【动量计算】合并池为空，无法计算")
            self.ranked_etfs_result = []
            return
        final_list = self.get_final_ranked_etfs(context)
        self.ranked_etfs_result = final_list

    def calculate_momentum_score(self, price_series, lookback_days):
        if len(price_series) < lookback_days + 1:
            return None, None, None
        recent_price_series = price_series[-(lookback_days + 1):]
        y = np.log(recent_price_series)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        W = weights ** 2
        W_sum = np.sum(W)
        x_bar = np.sum(W * x) / W_sum
        y_bar = np.sum(W * y) / W_sum
        dx = x - x_bar
        dy = y - y_bar
        variance_x = np.sum(W * dx**2)
        if variance_x == 0:
            return 0, 0, 0
        slope = np.sum(W * dx * dy) / variance_x
        intercept = y_bar - slope * x_bar
        annualized_returns = math.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum(weights * (y - y_pred) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot else 0
        momentum_score = annualized_returns * r_squared
        return momentum_score, annualized_returns, r_squared

    def calculate_all_metrics_for_etf(self, etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context, cur_date=''):
        try:
            price_series = np.append(hist_closes, current_price)
            if len(price_series) < self.lookback_days * 0.8:
                return None
            momentum_score, annualized_returns, r_squared = self.calculate_momentum_score(price_series, self.lookback_days)
            if momentum_score is None:
                return None
            passed_momentum = (self.min_score_threshold <= momentum_score <= self.max_score_threshold)
            volume_ratio = self.get_volume_ratio(hist_volumes, today_vol, context, self.volume_lookback, etf=etf, cur_date=cur_date)

            passed_loss_filter = True
            day_ratios = []
            if len(price_series) >= 4:
                day1 = price_series[-1] / price_series[-2]
                day2 = price_series[-2] / price_series[-3]
                day3 = price_series[-3] / price_series[-4]
                day_ratios = [day1, day2, day3]
                if min(day_ratios) < self.loss:
                    passed_loss_filter = False

            passed_r2 = r_squared > self.r2_threshold

            passed_ma = True
            ma_value = None
            if len(price_series) >= self.ma_lookback:
                ma_value = np.mean(price_series[-self.ma_lookback:])
                passed_ma = current_price > ma_value * self.ma_threshold
            else:
                passed_ma = False

            return {
                'etf': etf,
                'etf_name': etf_name,
                'momentum_score': momentum_score,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'current_price': current_price,
                'volume_ratio': volume_ratio,
                'day_ratios': day_ratios,
                'passed_momentum': passed_momentum,
                'passed_r2': passed_r2,
                'passed_ma': passed_ma,
                'passed_volume': volume_ratio is not None and volume_ratio < self.volume_threshold,
                'passed_loss': passed_loss_filter,
                'ma_value': ma_value,
            }
        except Exception as e:
            log.debug(f"【指标计算】{etf} {etf_name} 计算失败: {e}")
            return None

    def get_volume_ratio(self, hist_volumes, today_vol, context, lookback_days=None, etf='', cur_date=''):
        if lookback_days is None:
            lookback_days = self.volume_lookback
        try:
            if hist_volumes is None or len(hist_volumes) < lookback_days:
                return None
            past_n_days_vol = hist_volumes[-lookback_days:]
            if np.any(np.isnan(past_n_days_vol)) or np.any(past_n_days_vol == 0):
                return None
            avg_volume = np.mean(past_n_days_vol)
            if avg_volume == 0:
                return None
            now = context.current_dt
            elapsed_minutes = (now.hour - 9) * 60 + now.minute - 30
            if now.hour >= 13:
                elapsed_minutes -= 90
            elapsed_minutes = max(1, min(elapsed_minutes, 240))
            projected_today_vol = today_vol * (240.0 / elapsed_minutes)
            vr = projected_today_vol / avg_volume if avg_volume > 0 else 0
            return vr
        except Exception:
            return None

    def check_a_share_weak_period(self, context):
        today = context.current_dt.date()
        indexes = {
            '大盘': '000300.XSHG',
            '小盘': '399101.XSHE',
            '创业板': '399006.XSHE',
            '中证A500': '000510.XSHG'
        }

        above_count = 0
        below_count = 0
        for name, code in indexes.items():
            df = attribute_history(code, self.weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
            if df is None or len(df) < self.weak_period_ma_lookback:
                log.warning(f"📊 【走弱期判断】{name}({code})数据不足，跳过该指数")
                continue
            current_price = df['close'][-1]
            ma_val = df['close'][-self.weak_period_ma_lookback:].mean()
            is_above = current_price > ma_val
            is_below = current_price < ma_val
            if is_above:
                above_count += 1
            if is_below:
                below_count += 1
            status_emoji = "⬆️站上" if is_above else ("⬇️低于" if is_below else "➡️持平")
            if self.verbose_log:
                log.info(f"📊 【走弱期判断】{name}({code}): 收盘{current_price:.2f} / MA{self.weak_period_ma_lookback} {ma_val:.2f} → {status_emoji}")

        weak_condition_met = (below_count >= 3)
        exit_condition_met = (above_count >= 3)
        if self.verbose_log:
            log.info(f"📊 【走弱期判断】低于MA{self.weak_period_ma_lookback}: {below_count}/4, 站上MA{self.weak_period_ma_lookback}: {above_count}/4")

        if self.is_a_share_weak and self.weak_start_date is not None:
            self.weak_days_count = len(get_trade_days(start_date=self.weak_start_date, end_date=today))
        else:
            self.weak_days_count = 0
        max_days_exceeded = (self.weak_days_count >= self.max_weak_days)

        if self.is_a_share_weak:
            if max_days_exceeded:
                log.info(f"🔔 【走弱期退出】已达到最大持续天数{self.max_weak_days}个交易日，强制退出")
                self.is_a_share_weak = False
                self.weak_start_date = None
                self.weak_days_count = 0
            elif exit_condition_met:
                log.info(f"🟢 【走弱期退出】满足退出条件，退出走弱期")
                self.is_a_share_weak = False
                self.weak_start_date = None
                self.weak_days_count = 0
            elif weak_condition_met:
                old_start = self.weak_start_date
                self.weak_start_date = today
                self.weak_days_count = 0
                log.info(f"🟡 【走弱期延续】再次触发进入条件，重置计数器")
            else:
                log.info(f"🔴 【走弱期中】已持续{self.weak_days_count}/{self.max_weak_days}个交易日")
        else:
            if weak_condition_met:
                log.info(f"🔴 【走弱期进入】触发进入条件，进入大A走弱期")
                self.is_a_share_weak = True
                self.weak_start_date = today
                self.weak_days_count = 0
            else:
                log.info(f"🟢 【正常期中】未满足进入条件")

        status_emoji = "🔴" if self.is_a_share_weak else "🟢"
        status_str = f"{status_emoji} 最终状态: 走弱期={self.is_a_share_weak}"
        if self.is_a_share_weak:
            status_str += f" (已持续{self.weak_days_count}/{self.max_weak_days}个交易日)"
            record(走弱期状态=1)
        else:
            record(走弱期状态=0)
        log.info(f"📊 【走弱期判断】{status_str}")
        self._cmp('REGIME', f"{today}|regime={'走弱期' if self.is_a_share_weak else '正常期'}|below_ma10={below_count}|above_ma10={above_count}")
        return self.is_a_share_weak

    def apply_filters(self, metrics_list):
        steps = [
            ('动量得分', lambda m: m['passed_momentum'], True),
            ('R²', lambda m: m['passed_r2'], self.enable_r2_filter and not self.is_a_share_weak),
            ('均线', lambda m: m['passed_ma'], self.enable_ma_filter and self.is_a_share_weak),
            ('成交量', lambda m: m['passed_volume'], self.enable_volume_check),
            ('短期风控', lambda m: m['passed_loss'], self.enable_loss_filter),
        ]
        _debug_etfs = ['512400.XSHG', '517520.XSHG', '515880.XSHG', '159218.XSHE', '588080.XSHG', '512930.XSHG', '515000.XSHG']
        filtered = metrics_list[:]
        for name, condition, is_enabled in steps:
            if is_enabled:
                before_count = len(filtered)
                _before = {code: any(m.get('etf') == code for m in filtered) for code in _debug_etfs}
                filtered = [m for m in filtered if condition(m)]
                after_count = len(filtered)
                _after = {code: any(m.get('etf') == code for m in filtered) for code in _debug_etfs}
                if before_count > after_count:
                    print(f"【过滤条件】{name}: 通过 {after_count}/{before_count}")
                for code in _debug_etfs:
                    if _before[code] and not _after[code]:
                        _m = next((m for m in metrics_list if m.get('etf') == code), None)
                        if _m:
                            pass
        return filtered

    def get_final_ranked_etfs(self, context):
        all_metrics = []
        etf_set = list(self.merged_etf_pool)
        end_date = context.previous_date
        log.info(f"【动量得分计算】使用合并池，合计{len(etf_set)}只ETF")
        log.info(f"【当前状态】{'🔴 大A走弱期' if self.is_a_share_weak else '🟢 大A正常期'}")
        lookback = max(self.lookback_days, self.volume_lookback, self.ma_lookback) + 20
        today = context.current_dt.date()
        current_data = get_current_data()
        safe_lookback = lookback + 20
        hist_df = get_price(etf_set, count=safe_lookback, end_date=end_date, frequency='1d', fields=['close', 'volume'], panel=False)
        today_vol_df = get_price(etf_set, start_date=today, end_date=context.current_dt, frequency='1m', fields=['volume'], panel=False, fill_paused=False)
        if hist_df is None or hist_df.empty:
            log.warning("【动量计算】无法获取历史价格数据")
            return []
        today_vols = today_vol_df.groupby('code')['volume'].sum() if (today_vol_df is not None and not today_vol_df.empty) else pd.Series(dtype=float)
        close_pivot = hist_df.pivot(index='time', columns='code', values='close')
        volume_pivot = hist_df.pivot(index='time', columns='code', values='volume')
        for etf in etf_set:
            if current_data[etf].paused:
                continue
            if self.is_temporarily_suspended(etf, context):
                log.debug(f"{etf} {self.get_security_name(etf)} 盘中临时停牌，跳过计算")
                continue
            if etf not in close_pivot.columns:
                continue
            raw_closes = close_pivot[etf].values
            raw_volumes = volume_pivot[etf].values
            valid_mask = (~np.isnan(raw_volumes)) & (raw_volumes > 0)
            hist_closes = raw_closes[valid_mask]
            hist_volumes = raw_volumes[valid_mask]
            hist_closes = hist_closes[-lookback:]
            hist_volumes = hist_volumes[-lookback:]
            if len(hist_closes) < self.lookback_days:
                continue
            etf_name = self.get_security_name(etf)
            current_price = current_data[etf].last_price
            today_vol = today_vols.get(etf, 0)
            metrics = self.calculate_all_metrics_for_etf(etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context, cur_date=context.current_dt.strftime('%Y%m%d'))
            if metrics:
                if metrics['etf'] in {m['etf'] for m in all_metrics}:
                    continue
                all_metrics.append(metrics)
        for item in all_metrics:
            score = item.get('momentum_score')
            if pd.isna(score) or (isinstance(score, float) and np.isnan(score)):
                item['momentum_score'] = float('-inf')
        all_metrics.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
        self.unfiltered_ranked_list = all_metrics
        log_buffer = []
        log_buffer.append("")
        log_buffer.append(">>> 第一步：所有ETF按动量得分从大到小排序 <<<")
        for m in all_metrics[:100]:
            def fmt_status(value_str, passed):
                return f"{value_str} {'✅' if passed else '❌'}"
            score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
            r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
            vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
            min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
            loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
            ma_str = f"MA{self.ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
            line = (
                f"{m['etf']} {m['etf_name']}: "
                f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
                f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
                f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
                f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
                f"短期风控: {fmt_status(loss_val, m['passed_loss'])}"
            )
            log_buffer.append(line)
        filtered_list = self.apply_filters(all_metrics)
        filtered_list.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
        top_10 = filtered_list[:10]
        self.ranked_top_10 = top_10
        log_buffer.append("")
        log_buffer.append(">>> 第二步：符合全部过滤条件的ETF按动量得分从大到小排序(前10名) <<<")
        if top_10:
            for m in top_10:
                def fmt_status(value_str, passed):
                    return f"{value_str} {'✅' if passed else '❌'}"
                score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
                r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
                vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
                min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
                loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
                ma_str = f"MA{self.ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
                line = (
                    f"{m['etf']} {m['etf_name']}: "
                    f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
                    f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
                    f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
                    f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
                    f"短期风控: {fmt_status(loss_val, m['passed_loss'])}"
                )
                log_buffer.append(line)
        else:
            log_buffer.append("（无符合条件的ETF）")
            full_log = "\n".join(log_buffer)
            if self.verbose_log:
                log.info(full_log)
            return []
        score_key = 'momentum_score'
        if len(top_10) >= self.holdings_num:
            reference_score = top_10[self.holdings_num - 1].get(score_key, float('-inf'))
            ratio = self.score_threshold_ratio if not self.is_a_share_weak else 1.0
            score_threshold = reference_score * ratio
            log_buffer.append("")
            log_buffer.append(f">>> 第三步：选取动量得分≥第{self.holdings_num}名({top_10[self.holdings_num - 1]['etf_name']})得分{reference_score:.4f}×{self.score_threshold_ratio}={score_threshold:.4f}的ETF <<<")
            candidate_pool = [item for item in top_10 if item.get(score_key, float('-inf')) >= score_threshold]
        else:
            log_buffer.append("")
            log_buffer.append(f">>> 第三步：前10名不足{self.holdings_num}只，全部作为候选池 <<<")
            candidate_pool = top_10[:]
        log_buffer.append(f"【候选池】共{len(candidate_pool)}只ETF（按动量得分排序）：")
        for i, item in enumerate(candidate_pool):
            log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}")
        log_buffer.append("")
        log_buffer.append(">>> 第四步：结合当前持仓进行调整 <<<")
        current_holdings = [sec for sec, pos in context.portfolio.positions.items() if pos.total_amount > 0]
        log_buffer.append(f"当前持仓ETF：{current_holdings}")
        candidate_dict = {item['etf']: item for item in candidate_pool}
        retained = [candidate_dict[etf] for etf in current_holdings if etf in candidate_dict]
        log_buffer.append(f"其中存在于候选池中的持仓ETF：{[item['etf'] for item in retained]}")
        if len(retained) >= self.holdings_num:
            retained_sorted = sorted(retained, key=lambda x: x.get(score_key, float('-inf')), reverse=True)
            final_result = retained_sorted[:self.holdings_num]
            log_buffer.append(f"保留的持仓ETF数量({len(retained)})超过目标持仓数({self.holdings_num})，将从保留的ETF中按动量得分取前{self.holdings_num}只作为最终目标。")
        else:
            need = self.holdings_num - len(retained)
            remaining_pool = [item for item in candidate_pool if item['etf'] not in {r['etf'] for r in retained}]
            additional = remaining_pool[:need]
            final_result = retained + additional
            log_buffer.append(f"保留持仓ETF {len(retained)}只，还需补充{need}只。")
            if retained:
                log_buffer.append("保留的ETF（按原有顺序）：")
                for item in retained:
                    log_buffer.append(f"  {item['etf_name']}({item['etf']})")
            if additional:
                log_buffer.append("补充的ETF（按动量得分排序）：")
                for i, item in enumerate(additional):
                    log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}")
        log_buffer.append(f"【最终目标】共{len(final_result)}只ETF：")
        for i, item in enumerate(final_result):
            log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']})")
        log_buffer.append("==================================================")
        full_log = "\n".join(log_buffer)
        if self.verbose_log:
            log.info(full_log)

        today_str = context.current_dt.strftime('%Y%m%d')
        for m in top_10[:5]:
            passed_filters = []
            if m.get('passed_momentum'): passed_filters.append('mom')
            if m.get('passed_r2'): passed_filters.append('r2')
            if m.get('passed_ma'): passed_filters.append('ma')
            if m.get('passed_volume'): passed_filters.append('vol')
            if m.get('passed_loss'): passed_filters.append('loss')

        _threshold = score_threshold if 'score_threshold' in dir() else 0
        if not candidate_pool:
            self._cmp('CANDIDATE', f"{today_str}|threshold={_threshold:.4f}|count=0|top1=NONE")
            log.info(f"【候选池为空】跳过本日交易")
            return []
        self._cmp('CANDIDATE', f"{today_str}|threshold={_threshold:.4f}|count={len(candidate_pool)}|top1={candidate_pool[0]['etf']}")
        return final_result

    def execute_sell_trades(self, context):
        log.info("========== 卖出操作开始 ==========")
        ranked_etfs = getattr(self, 'ranked_etfs_result', [])
        target_etfs = []

        if ranked_etfs:
            for metrics in ranked_etfs[:self.holdings_num]:
                target_etfs.append(metrics['etf'])
                log.info(f"确定最终目标: {metrics['etf']} {metrics['etf_name']}")
        else:
            if self.check_defensive_etf_available(context):
                target_etfs = [self.defensive_etf]
                etf_name = self.get_security_name(self.defensive_etf)
                log.info(f"🛡️ 确定最终目标(防御模式): {self.defensive_etf} {etf_name}")
            else:
                log.info("💤 无最终目标(空仓模式)")
                target_etfs = []

        self.target_etfs_list = target_etfs
        current_positions = list(context.portfolio.positions.keys())
        target_set = set(target_etfs)
        sell_count = 0

        for security in current_positions:
            position = context.portfolio.positions[security]
            if position.total_amount > 0 and security not in target_set:
                security_name = self.get_security_name(security)
                success = self.smart_order_target_value(security, 0, context)
                if success:
                    sell_count += 1
                    log.info(f"✅ 已成功卖出: {security} {security_name}")
                    self._cmp('TRADE_SELL', f"{context.current_dt.strftime('%Y%m%d')}|{security}|reason=动量调仓")

        log.info(f"本次共计划卖出{sell_count}只ETF。")
        log.info("========== 卖出操作完成 ==========")

    def execute_buy_trades(self, context):
        log.info("========== 买入操作开始 ==========")
        target_etfs = self.target_etfs_list

        if not target_etfs:
            log.info("根据计算的结果，今日无目标ETF，保持空仓")
            log.info("========== 买入操作完成 ==========")
            return

        current_positions = set(context.portfolio.positions.keys())
        etfs_to_buy = [etf for etf in target_etfs if etf not in current_positions]
        actual_holding_count = len(current_positions)
        max_buy_count = max(0, self.holdings_num - actual_holding_count)
        num_etfs_to_buy = min(len(etfs_to_buy), max_buy_count)

        if num_etfs_to_buy <= 0:
            log.info(f"当前实际持仓数量({actual_holding_count})已达到或超过目标({self.holdings_num})，无需买入")
            log.info("========== 买入操作完成 ==========")
            return

        etfs_to_buy = etfs_to_buy[:num_etfs_to_buy]
        log.info(f"当前实际持仓: {actual_holding_count}只, 目标持仓: {self.holdings_num}只, 本次计划买入: {num_etfs_to_buy}只")

        for i, etf in enumerate(etfs_to_buy):
            remaining_cash = context.portfolio.available_cash
            if remaining_cash < self.min_money:
                log.info(f"可用现金 {remaining_cash:.2f} 不足最小交易额 {self.min_money:.2f}，停止买入")
                break

            remaining_to_buy = len(etfs_to_buy) - i
            target_value_for_this_etf = remaining_cash // remaining_to_buy

            if target_value_for_this_etf < self.min_money and remaining_cash >= self.min_money:
                target_value_for_this_etf = remaining_cash

            log.info(f"为 {etf} 分配目标金额: {target_value_for_this_etf:.2f} 元 (剩余现金 {remaining_cash:.2f}, 待买数量 {remaining_to_buy})")

            success = self.smart_order_target_value(etf, target_value_for_this_etf, context)
            if success:
                log.info(f"✅ ETF {etf} 下单成功")
                self._cmp('TRADE_BUY', f"{context.current_dt.strftime('%Y%m%d')}|{etf}|{target_value_for_this_etf:.0f}|reason=动量调仓")
            else:
                log.info(f"❌ ETF {etf} 下单失败")

        log.info("========== 买入操作完成 ==========")

    def is_temporarily_suspended(self, security, context, minute_count=10):
        try:
            minute_data = get_price(
                security,
                end_date=context.current_dt,
                count=minute_count,
                frequency='1m',
                fields=['volume'],
                skip_paused=False,
                fq='pre'
            )
            if minute_data is None or minute_data.empty:
                return True
            if (minute_data['volume'] == 0).all():
                return True
            return False
        except Exception as e:
            log.debug(f"临时停牌检测异常 {security}: {e}")
            return False

    def smart_order_target_value(self, security, target_value, context):
        data = get_current_data()
        name = self.get_security_name(security)
        if data[security].paused:
            log.info(f"{security} {name} 全天停牌，跳过交易")
            return False
        if self.is_temporarily_suspended(security, context):
            log.info(f"{security} {name} 盘中临时停牌，跳过交易")
            return False
        price = data[security].last_price
        if price == 0:
            log.info(f"{security} {name} 当前价格为0，跳过交易")
            return False
        if target_value > 0:
            buy_commission_rate = 0.0001
            slippage_rate = 0.0001
            estimated_price = price * (1 + buy_commission_rate + slippage_rate)
            target_amount = int(target_value / estimated_price)
            target_amount = (target_amount // 100) * 100
            if target_amount <= 0:
                target_amount = 100
        else:
            target_amount = 0
        cur_pos = context.portfolio.positions.get(security, None)
        cur_amount = cur_pos.total_amount if cur_pos else 0
        diff = target_amount - cur_amount
        if target_value > 0 and diff > 0:
            max_shares = int(context.portfolio.available_cash / price)
            max_shares = (max_shares // 100) * 100
            if max_shares < diff:
                diff = max_shares
            if diff <= 0:
                log.info(f"{security} {name}: 现金不足买100股，跳过")
                return False
        if data[security].last_price >= data[security].high_limit:
            log.info(f"{security} {name} 当前涨停，跳过交易")
            return False
        if data[security].last_price <= data[security].low_limit:
            log.info(f"{security} {name} 当前跌停，跳过交易")
            return False
        trade_val = abs(diff) * price
        if 0 < trade_val < self.min_money:
            log.info(f"{security} {name} 交易金额{trade_val:.2f} < {self.min_money}，跳过")
            return False
        if diff < 0:
            closeable = cur_pos.closeable_amount if cur_pos else 0
            if closeable == 0:
                log.info(f"{security} {name} 当天买入不可卖出(T+1)")
                return False
            diff = -min(abs(diff), closeable)
        if diff != 0:
            order_result = order(security, diff)
            if order_result:
                if diff > 0:
                    log.info(f"📥 买入 {security} {name} 数量{abs(diff)} 价格{price:.3f} (预估含成本价: {estimated_price:.3f})")
                else:
                    log.info(f"📤 卖出 {security} {name} 数量{abs(diff)} 价格{price:.3f}")
                return True
            else:
                log.warning(f"下单失败: {security} {name}，数量{diff}")
                return False
        return False

    def minute_level_stop_loss(self, context):
        if not self.use_fixed_stop_loss:
            return
        current_time = context.current_dt.strftime('%H:%M')
        if not (('09:40' < current_time < '10:29') or ('10:40' < current_time < '11:30') or ('13:00' < current_time < '14:57')):
            return
        current_data = get_current_data()
        for security in list(context.portfolio.positions.keys()):
            position = context.portfolio.positions[security]
            if position.total_amount <= 0 or position.closeable_amount <= 0:
                continue
            current_price = current_data[security].last_price
            if current_price <= 0:
                continue
            cost_price = position.avg_cost
            if cost_price <= 0:
                continue
            if current_price <= cost_price * self.fixedStopLossThreshold:
                security_name = self.get_security_name(security)
                loss_percent = (current_price / cost_price - 1) * 100
                log.info(f"🚨 【分钟级固定止损】{security} {security_name} 触发止损，亏损: {loss_percent:.2f}%")
                self.smart_order_target_value(security, 0, context)

    def get_security_name(self, security):
        try:
            if hasattr(self, 'etf_names_dict') and security in self.etf_names_dict:
                return self.etf_names_dict[security]
            return get_security_info(security).display_name
        except Exception:
            return "未知名称"

    def check_defensive_etf_available(self, context):
        current_data = get_current_data()
        defensive_etf = self.defensive_etf
        if current_data[defensive_etf].paused:
            log.info(f"防御性ETF {defensive_etf} 今日停牌")
            return False
        if current_data[defensive_etf].last_price >= current_data[defensive_etf].high_limit:
            log.info(f"防御性ETF {defensive_etf} 当前涨停")
            return False
        if current_data[defensive_etf].last_price <= current_data[defensive_etf].low_limit:
            log.info(f"防御性ETF {defensive_etf} 当前跌停")
            return False
        return True

    def trade(self, context):
        pass


# ==================== QixingStrategy ====================

class QixingStrategy:
    def cmp_log(self, msg):
        """对比日志输出，仅在 CMP_MODE=True 时输出带[CMP]标记的行"""
        if CMP_MODE and _orig_log_info:
            _orig_log_info("[CMP] " + str(msg))

    # ==================== 初始化模块 ====================
    def __init__(self):
        # ---------- ETF池 ----------
        self.etf_pool_bak = [
            "518880.XSHG",   # 黄金ETF
            #"159985.XSHE",   # 豆粕ETF
            #"501018.XSHG",   # 南方原油
            #"161226.XSHE",   # 白银LOF
            "513100.XSHG",   # 纳指ETF
            "159915.XSHE",   # 创业板ETF
            "511220.XSHG",   # 城投债ETF
        ]
        self.etf_pool  = [
            "518880.XSHG",  "159980.XSHE", 
            "159985.XSHE",  
            #"501018.XSHG",
            #"161226.XSHE", 
            "159981.XSHE",  "513100.XSHG",  "159509.XSHE",
            "513290.XSHG",  "513500.XSHG",  "159529.XSHE",  "513400.XSHG",
            "513520.XSHG",  "513030.XSHG",  "513080.XSHG",  "513310.XSHG",
            "513730.XSHG",  "159792.XSHE",  "513130.XSHG",  "513050.XSHG",
            "159920.XSHE",  "513690.XSHG",  "510300.XSHG",  "510500.XSHG",
            "510050.XSHG",  "510210.XSHG",  "159915.XSHE",  "588080.XSHG",
            "512100.XSHG",  "563360.XSHG",  "563300.XSHG",  "512890.XSHG",
            "159967.XSHE",  "512040.XSHG",  "159201.XSHE",  "511380.XSHG",
            "511010.XSHG",  "511220.XSHG",
        ]
        # ---------- 核心参数 ----------
        self.lookback_days = 25
        self.holdings_num = 1
        self.defensive_etf = "511880.XSHG"
        self.min_money = 5000
        # 盈利保护
        self.enable_profit_protection = False
        self.profit_protection_lookback = 1
        self.profit_protection_threshold = 0.05
        self.profit_protection_check_times = ['11:00']
        self.loss = 0.97
        self.min_score_threshold = 0
        self.max_score_threshold = 100.0
        # 成交量过滤
        self.enable_volume_check = True
        self.volume_lookback = 5
        self.volume_threshold = 2
        self.volume_return_limit = 1
        # 短期动量
        self.use_short_momentum_filter = USE_SHORT_MOMENTUM_FILTER
        self.short_lookback_days = 10
        self.short_momentum_threshold = 0.0
        # 溢价率
        self.enable_premium_filter = ENABLE_PREMIUM_FILTER
        self.premium_threshold = 0.20
        # 运行时
        self.verbose_log = False
        self.daily_detail = False
        self.rankings_cache = {'date': None, 'data': None}
        # 震荡期参数
        self.enable_range_bound_mode = True
        self.current_filter = '正常期'
        self.risk_state = '正常期'
        self.lookback_high_low_days = 20
        self.risk_benchmark = '510300.XSHG'
        self.laplace_s_param = 0.05
        self.laplace_min_slope = 0.001
        self.gaussian_sigma = 1.2
        self.gaussian_min_slope = 0.002
        self.enable_bias_trigger = True
        self.bias_threshold = 0.10
        self.ma_period = 20
        self.enable_rsi_trigger = True
        self.rsi_overbought = 75
        self.rsi_pullback = 60
        self.previous_rsi = None
        self.enable_stop_loss_trigger = False
        self.stop_loss_triggered_today = False
        self.stop_loss_triggered_date = None
        self.enable_low_point_rise_trigger = True
        self.low_point_rise_threshold = 0.03
        self.enable_stable_signal_trigger = True
        self.drawdown_recovery = 0.03
        self.max_range_bound_days = 15
        self.stable_days = 0
        self.filter_switch_cooldown = 2
        self.last_switch_date = None
        self.range_bound_start_date = None
        self.range_bound_days_count = 0
        self.previous_drawdown = None

    def setup_jq(self, context):
        set_option("avoid_future_data", True)
        set_option("use_real_price", True)
        set_slippage(PriceRelatedSlippage(0.0001), type="fund")
        set_order_cost(
            OrderCost(open_tax=0, close_tax=0, open_commission=0.0001,
                      close_commission=0.0001, close_today_commission=0, min_commission=5),
            type="fund",
        )
        set_benchmark("161226.XSHE")
        log.set_level('order', 'error')
        log.set_level('system', 'error')
        log.set_level('strategy', 'info')

    def schedule(self, context):
        run_daily(self.check_positions, time='09:10')
        run_daily(self.etf_sell_trade, time='13:10')
        run_daily(self.etf_buy_trade, time='13:11')
        for check_time in self.profit_protection_check_times:
            run_daily(self.profit_protection_check, time=check_time)
        run_daily(self.check_range_bound, time='13:55')
        run_daily(self.reset_range_bound_daily, time='15:10')

    def initialize(self, context):
        self.setup_jq(context)
        self.schedule(context)
        log.info("========== 策略初始化开始 ==========")
        log.info(f"策略初始化完成：ETF池{len(self.etf_pool)}只，动量周期{self.lookback_days}天，持仓{self.holdings_num}只")
        log.info(f"盈利保护开关：{'开启' if self.enable_profit_protection else '关闭'}")
        if self.enable_premium_filter:
            log.info(f"溢价率过滤已启用，阈值：{self.premium_threshold*100:.0f}%")
        else:
            log.info("溢价率过滤未启用")
        log.info(f"震荡期模式：{'开启' if self.enable_range_bound_mode else '关闭'}")
        self.init_range_bound_status(context)
        log.info("========== 策略初始化完成 ==========")


    # ==================== 盈利保护独立检查函数 ====================
    def profit_protection_check(self, context):
        if not self.enable_profit_protection:
            log.debug("盈利保护模块已关闭，跳过检查")
            return

        log.info("========== 盈利保护独立检查开始 ==========")
        for sec in list(context.portfolio.positions.keys()):
            if sec not in self.etf_pool and sec != self.defensive_etf:
                continue
            pos = context.portfolio.positions[sec]
            if pos.total_amount > 0:
                if self.check_profit_protection(sec, context):
                    if self.smart_order_target_value(sec, 0, context):
                        log.info(f"🛡️ 盈利保护卖出（独立检查）：{sec} {self.get_name(sec)}")
                        if getattr(self, 'enable_stop_loss_trigger', False):
                            self.stop_loss_triggered_today = True
                            self.stop_loss_triggered_date = context.current_dt.date()
                            log.info("【盈利保护触发】记录止损信号，将在震荡期检查时使用")
        log.info("========== 盈利保护独立检查完成 ==========")


    # ==================== 盈利保护检查函数（核心逻辑） ====================
    def check_profit_protection(self, security, context, lookback=None, threshold=None):
        if not self.enable_profit_protection:
            return False

        lookback = lookback or self.profit_protection_lookback
        threshold = threshold or self.profit_protection_threshold

        hist = attribute_history(security, lookback, '1d', ['high'])
        if hist.empty or len(hist) < lookback:
            log.debug(f"{security} {self.get_name(security)} 历史数据不足{lookback}天，无法检查盈利保护")
            return False

        max_high = hist['high'].max()
        current_price = get_current_data()[security].last_price

        if current_price <= max_high * (1 - threshold):
            log.info(f"🔻 {security} {self.get_name(security)} 触发盈利保护：当前价{current_price:.3f}，最近{lookback}日最高{max_high:.3f}，回撤{(1 - current_price/max_high)*100:.2f}% > {threshold*100:.0f}%")
            return True
        else:
            return False


    # ==================== 溢价率获取函数 ====================
    def get_premium_rate(self, code, date, max_back_days=5):
        price_data = get_price(
            code,
            start_date=date,
            end_date=date,
            frequency='daily',
            fields=['close']
        )
        if price_data.empty:
            log.debug(f"{date} {code} 无交易价格数据")
            return None, None, None
        price = price_data['close'].iloc[0]

        net_value = None
        used_date = date
        start_date = date - timedelta(days=max_back_days*2)
        trade_days = get_trade_days(start_date=start_date, end_date=date)
        trade_days = [pd.to_datetime(d).date() for d in trade_days]
        for dt in reversed(trade_days):
            if dt > date:
                continue
            net_data = get_extras('unit_net_value', code, start_date=dt, end_date=dt, df=True)
            if not net_data.empty and not pd.isna(net_data[code].iloc[0]):
                net_value = net_data[code].iloc[0]
                used_date = dt
                break
            try:
                q = query(finance.FUND_NET_VALUE).filter(
                    finance.FUND_NET_VALUE.code == code,
                    finance.FUND_NET_VALUE.day == dt
                )
                net_df = finance.run_query(q)
                if not net_df.empty:
                    net_value = net_df['net_value'].iloc[0]
                    used_date = dt
                    break
            except:
                continue

        if net_value is None:
            log.debug(f"{code} 在{date}及前{max_back_days}个交易日均无净值数据")
            return None, None, None

        premium_rate = (price - net_value) / net_value
        if used_date != date:
            log.debug(f"{code} 使用{used_date}的净值{net_value:.4f}代替{date}的净值计算溢价率")
        return premium_rate, price, net_value


    # ==================== 震荡期机制 ====================
    def calculate_rsi(self, close, period=14):
        try:
            if len(close) < period + 1:
                return None
            deltas = np.diff(close)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except:
            return None

    def laplace_filter(self, price, s=0.05):
        """拉普拉斯滤波器（正常期使用）"""
        alpha = 1 - np.exp(-s)
        L = np.zeros(len(price))
        L[0] = price[0]
        for t in range(1, len(price)):
            L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
        return L

    def gaussian_filter_last_two(self, price, sigma=1.2):
        """仅计算高斯滤波最后两个点（震荡期使用，效率优化）"""
        n = len(price)
        if n < 2:
            return 0, 0
        idx_1 = np.arange(n)
        weights_1 = np.exp(-((idx_1+1)**2) / (2 * sigma**2))[::-1]
        weights_1 /= np.sum(weights_1)
        g1 = np.sum(price * weights_1)
        price_2 = price[:-1]
        idx_2 = np.arange(n-1)
        weights_2 = np.exp(-((idx_2+1)**2) / (2 * sigma**2))[::-1]
        weights_2 /= np.sum(weights_2)
        g2 = np.sum(price_2 * weights_2)
        return g1, g2

    def get_risk_benchmark_state(self, context):
        required_days = max(self.ma_period, self.lookback_high_low_days)
        lookback = required_days + 30
        end_date = getattr(context, 'previous_date', None)
        if end_date is None:
            return None
        df = get_price(self.risk_benchmark, end_date=end_date, count=lookback,
                       frequency='daily', fields=['close', 'high', 'low'], panel=False)
        if df is None or len(df) < required_days:
            return None
        daily_close = df['close'].values.astype(float)
        daily_high = df['high'].values.astype(float)
        daily_low = df['low'].values.astype(float)
        current_price = float(daily_close[-1])
        intraday_high = current_price
        intraday_low = current_price
        data_source = '昨日日线'
        try:
            today = context.current_dt.date()
            minute_df = get_price(
                self.risk_benchmark, start_date=today, end_date=context.current_dt,
                frequency='1m', fields=['close', 'high', 'low'],
                panel=False, fill_paused=False
            )
            if minute_df is not None and not minute_df.empty:
                minute_close = minute_df['close'].dropna()
                minute_high = minute_df['high'].dropna()
                minute_low = minute_df['low'].dropna()
                if not minute_close.empty:
                    current_price = float(minute_close.iloc[-1])
                    intraday_high = float(minute_high.max()) if not minute_high.empty else current_price
                    intraday_low = float(minute_low.min()) if not minute_low.empty else current_price
                    data_source = '当日盘中'
        except Exception:
            pass
        if current_price <= 0:
            try:
                current_data = get_current_data()
                live_price = current_data[self.risk_benchmark].last_price
                if live_price is not None and live_price > 0:
                    current_price = float(live_price)
                    intraday_high = max(intraday_high, current_price)
                    intraday_low = min(intraday_low, current_price)
                    data_source = '实时快照'
            except Exception:
                current_price = float(daily_close[-1])
        close_series = np.append(daily_close, current_price)
        high_series = np.append(daily_high, max(intraday_high, current_price))
        low_series = np.append(daily_low, min(intraday_low, current_price))
        recent_high = np.max(high_series[-self.lookback_high_low_days:])
        recent_low = np.min(low_series[-self.lookback_high_low_days:])
        ma = np.mean(close_series[-self.ma_period:])
        current_rsi = self.calculate_rsi(close_series, period=14)
        previous_rsi = self.calculate_rsi(daily_close, period=14)
        return {
            'close_series': close_series,
            'high_series': high_series,
            'low_series': low_series,
            'current_price': current_price,
            'recent_high': recent_high,
            'recent_low': recent_low,
            'ma': ma,
            'current_rsi': current_rsi,
            'previous_rsi': previous_rsi,
            'data_source': data_source,
        }

    def is_fresh_stop_loss_signal(self, context):
        signal_date = getattr(self, 'stop_loss_triggered_date', None)
        if signal_date is None:
            return False
        today = context.current_dt.date()
        previous_date = getattr(context, 'previous_date', None)
        if signal_date == today:
            return True
        if previous_date is not None and signal_date == previous_date:
            return True
        self.stop_loss_triggered_today = False
        self.stop_loss_triggered_date = None
        return False

    def init_range_bound_status(self, context):
        if not self.enable_range_bound_mode:
            return
        log.info("【首次运行】初始化震荡期状态...")
        try:
            if context.previous_date is None:
                log.warning("【首次运行】无法获取前一个交易日，保持正常期")
                return
            end_date = context.previous_date
            lookback = max(self.ma_period, self.lookback_high_low_days) + 30
            df = get_price(self.risk_benchmark, end_date=end_date, count=lookback,
                           frequency='daily', fields=['close', 'high', 'low'], panel=False)
            if df is None or len(df) < max(self.ma_period, self.lookback_high_low_days):
                log.warning("【首次运行】数据不足，保持正常期")
                return
            close = df['close'].values
            high = df['high'].values
            low = df['low'].values
            current_price = close[-1]
            if len(close) >= self.lookback_high_low_days:
                recent_high = np.max(high[-self.lookback_high_low_days:])
                recent_low = np.min(low[-self.lookback_high_low_days:])
            else:
                recent_high = np.max(high)
                recent_low = np.min(low)
            ma = np.mean(close[-self.ma_period:])
            bias = (current_price - ma) / ma if ma > 0 else 0
            rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
            current_rsi = self.calculate_rsi(close, period=14)
            should_enter = False
            signals = []
            if self.enable_bias_trigger and bias > self.bias_threshold:
                should_enter = True
                signals.append(f"乖离率{bias:.2%}>{self.bias_threshold:.0%}")
            if self.enable_rsi_trigger and current_rsi is not None and len(close) >= 15:
                prev_rsi = self.calculate_rsi(close[:-1], period=14)
                if prev_rsi is not None and prev_rsi > self.rsi_overbought and current_rsi < self.rsi_pullback:
                    should_enter = True
                    signals.append(f"RSI超买回落{prev_rsi:.1f}->{current_rsi:.1f}")
            if should_enter:
                self.current_filter = '震荡期'
                self.risk_state = '震荡期'
                self.range_bound_start_date = end_date
                self.range_bound_days_count = 0
                log.info(f"【首次运行】初始化进入震荡期: {'; '.join(signals)}")
            else:
                self.current_filter = '正常期'
                self.risk_state = '正常期'
                if len(close) >= self.lookback_high_low_days:
                    self.previous_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
                else:
                    self.previous_drawdown = 0
                self.previous_rsi = current_rsi
                rsi_str = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
                log.info(f"【首次运行】初始状态: 正常期, 乖离率: {bias:.2%}, RSI: {rsi_str}, 从低点涨幅: {rise_from_low:.2%}")
                if self.verbose_log:
                    self.cmp_log(f"初始状态: 正常期, 乖离率: {bias:.2%}, RSI: {rsi_str}, 从低点涨幅: {rise_from_low:.2%}")
        except Exception as e:
            log.warning(f"【首次运行】初始化震荡期状态异常: {e}，保持正常期")

    def check_and_exit_range_bound_mode(self, context):
        if not self.enable_range_bound_mode:
            return
        if self.current_filter != '震荡期':
            return
        log.info("【震荡期退出检查】开始检测退出条件...")
        try:
            benchmark_state = self.get_risk_benchmark_state(context)
            if benchmark_state is None:
                log.warning("【震荡期退出检查】数据不足，跳过")
                return
            close = benchmark_state['close_series']
            current_price = benchmark_state['current_price']
            recent_high = benchmark_state['recent_high']
            recent_low = benchmark_state['recent_low']
            current_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
            rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
            recovery_signals = []
            ma = benchmark_state['ma']
            current_rsi = benchmark_state['current_rsi']
            log.info(f"【震荡期数据】当前价: {current_price:.3f}, 近{self.lookback_high_low_days}日高点: {recent_high:.3f}, 低点: {recent_low:.3f}")
            log.info(f"【震荡期数据】回撤: {current_drawdown:.2%}, 从低点涨幅: {rise_from_low:.2%}")
            if self.enable_low_point_rise_trigger:
                if rise_from_low >= self.low_point_rise_threshold:
                    recovery_signals.append(f"从低点上涨{rise_from_low:.2%}>={self.low_point_rise_threshold:.0%}")
                    log.info(f"【退出条件触发】从低点上涨: {rise_from_low:.2%}")
            if self.enable_stable_signal_trigger:
                if current_price > ma:
                    recovery_signals.append("价格站上均线")
                if len(close) >= 2 and close[-1] > close[-2]:
                    recovery_signals.append("价格回升")
                if self.previous_drawdown is not None and current_drawdown < self.previous_drawdown:
                    recovery_signals.append(f"回撤收窄({current_drawdown:.2%}<{self.previous_drawdown:.2%})")
                if current_rsi is not None and self.previous_rsi is not None and current_rsi > self.previous_rsi:
                    recovery_signals.append(f"RSI回升({current_rsi:.1f})")
                drawdown_safe = current_drawdown < self.drawdown_recovery
                if drawdown_safe:
                    self.stable_days += 1
                    log.info(f"【企稳计数】连续企稳天数: {self.stable_days}")
                else:
                    self.stable_days = 0
            self.previous_drawdown = current_drawdown
            self.previous_rsi = current_rsi
            range_bound_days = 0
            if self.range_bound_start_date is not None:
                trade_days = get_trade_days(start_date=self.range_bound_start_date, end_date=context.current_dt.date())
                range_bound_days = len(trade_days) - 1
                if range_bound_days >= self.max_range_bound_days:
                    recovery_signals.append(f"震荡期满({range_bound_days}天)")
                    log.info(f"【退出条件触发】震荡期已满{range_bound_days}天")
            low_point_condition = self.enable_low_point_rise_trigger and rise_from_low >= self.low_point_rise_threshold
            stable_condition = False
            if self.enable_stable_signal_trigger:
                drawdown_safe = current_drawdown < self.drawdown_recovery
                stable_condition = drawdown_safe and len(recovery_signals) >= 2 and self.stable_days >= 2
            force_condition = range_bound_days >= self.max_range_bound_days
            should_recover = low_point_condition or stable_condition or force_condition
            if should_recover:
                can_switch = True
                if self.last_switch_date is not None:
                    trade_days = get_trade_days(start_date=self.last_switch_date, end_date=context.current_dt.date())
                    days_since = len(trade_days) - 1
                    if days_since < self.filter_switch_cooldown:
                        can_switch = False
                        log.info(f"【震荡期退出】冷却期中，距上次切换{days_since}天")
                if can_switch:
                    self.current_filter = '正常期'
                    self.risk_state = '正常期'
                    self.last_switch_date = context.current_dt.date()
                    self.range_bound_start_date = None
                    self.range_bound_days_count = 0
                    self.stable_days = 0
                    log.info(f"【退出震荡期】切换回拉普拉斯滤波器: {'; '.join(recovery_signals)}")
            else:
                log.info("【震荡期退出检查】未满足退出条件，保持震荡期(高斯滤波器)")
        except Exception as e:
            log.warning(f"【震荡期退出检查】判断出错: {e}")

    def check_and_enter_range_bound_mode(self, context):
        if not self.enable_range_bound_mode:
            return
        log.info("【震荡期进入检查】开始检测...")
        stop_loss_signal_active = self.is_fresh_stop_loss_signal(context)
        can_switch = True
        if self.last_switch_date is not None:
            trade_days = get_trade_days(start_date=self.last_switch_date, end_date=context.current_dt.date())
            days_since = len(trade_days) - 1
            if days_since < self.filter_switch_cooldown:
                can_switch = False
                log.info(f"【震荡期检查】冷却期中，距上次切换{days_since}天")
        if self.current_filter == '震荡期':
            log.info("【震荡期检查】当前已在震荡期")
            return
        if not can_switch:
            return
        risk_signals = []
        try:
            benchmark_state = self.get_risk_benchmark_state(context)
            if benchmark_state is not None:
                close = benchmark_state['close_series']
                current_price = benchmark_state['current_price']
                if self.enable_bias_trigger:
                    ma = benchmark_state['ma']
                    bias = (current_price - ma) / ma if ma > 0 else 0
                    if bias > self.bias_threshold:
                        risk_signals.append(f"乖离率过大({bias:.2%}>{self.bias_threshold:.0%})")
                        log.info(f"【条件触发】乖离率: {bias:.2%} (数据源:{benchmark_state['data_source']})")
                if self.enable_rsi_trigger:
                    current_rsi = benchmark_state['current_rsi']
                    if len(close) >= 15 and current_rsi is not None:
                        prev_rsi = benchmark_state['previous_rsi']
                        if prev_rsi is not None:
                            if prev_rsi > self.rsi_overbought and current_rsi < self.rsi_pullback and current_rsi < prev_rsi:
                                risk_signals.append(f"RSI超买回落({prev_rsi:.1f}->{current_rsi:.1f})")
                                log.info(f"【条件触发】RSI超买回落: {prev_rsi:.1f}->{current_rsi:.1f}")
        except Exception as e:
            log.warning(f"【震荡期检查】获取基准数据异常: {e}")
        if self.enable_stop_loss_trigger and stop_loss_signal_active:
            risk_signals.append("盈利保护触发止损")
            log.info("【条件触发】盈利保护触发止损信号")
        if len(risk_signals) > 0:
            self.current_filter = '震荡期'
            self.risk_state = '震荡期'
            self.last_switch_date = context.current_dt.date()
            self.range_bound_start_date = context.current_dt.date()
            self.range_bound_days_count = 0
            self.stable_days = 0
            self.stop_loss_triggered_today = False
            self.stop_loss_triggered_date = None
            log.info(f"【进入震荡期】切换到高斯滤波器: {'; '.join(risk_signals)}")
        else:
            log.info("【震荡期检查】未满足进入条件，保持正常期(拉普拉斯滤波器)")

    def check_range_bound(self, context):
        if not self.enable_range_bound_mode:
            return
        log.info("========== 震荡期检查开始 ==========")
        log.info(f"当前状态: {self.current_filter}")
        self.check_and_exit_range_bound_mode(context)
        self.check_and_enter_range_bound_mode(context)
        log.info(f"检查后状态: {self.current_filter}")
        self.rankings_cache = {'date': None, 'data': None}
        log.info("========== 震荡期检查完成 ==========")

    def reset_range_bound_daily(self, context):
        if self.current_filter == '震荡期' and self.range_bound_start_date is not None:
            trade_days = get_trade_days(start_date=self.range_bound_start_date, end_date=context.current_dt.date())
            self.range_bound_days_count = len(trade_days) - 1
            log.info(f"震荡期已持续 {self.range_bound_days_count} 个交易日")
        log.debug("收盘震荡期标志重置完成")


    # ==================== 核心计算模块 ====================
    def get_cached_rankings(self, context):
        today = context.current_dt.date()
        if self.rankings_cache['date'] != today:
            log.info("重新计算ETF排名...")
            ranked = self.get_ranked_etfs(context)
            self.rankings_cache = {'date': today, 'data': ranked}
        else:
            log.debug("使用缓存的ETF排名")
        return self.rankings_cache['data']

    def get_ranked_etfs(self, context):
        etf_metrics = []
        for etf in self.etf_pool:
            if etf == "159980.XSHE" and context.current_dt.strftime("%Y-%m-%d") in ("2025-12-19", "2026-01-05"):
                self.cmp_log(f"DBG_159980_IN_GET_RANKED etf={etf} paused={get_current_data()[etf].paused}")
            if get_current_data()[etf].paused:
                log.debug(f"{etf} {self.get_name(etf)} 停牌，跳过")
                continue

            metrics = self.calculate_momentum_metrics(context, etf)
            if metrics is not None:
                if self.min_score_threshold < metrics['score'] < self.max_score_threshold:
                    etf_metrics.append(metrics)
                else:
                    log.debug(f"{etf} {metrics['etf_name']} 得分{metrics['score']:.2f}超出阈值，过滤")

        etf_metrics.sort(key=lambda x: x['score'], reverse=True)
        return etf_metrics

    def calculate_momentum_metrics(self, context, etf):
        try:
            name = self.get_name(etf)
            lookback = max(self.lookback_days, self.short_lookback_days) + 20
            prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
            if len(prices) < self.lookback_days:
                log.info(f"{etf} {name} 历史数据{len(prices)}天<{self.lookback_days}天")
                return None

            current_price = get_current_data()[etf].last_price
            price_series = np.append(prices["close"].values, current_price)

            if self.check_profit_protection(etf, context):
                log.info(f"{etf} {name} 触发盈利保护")
                return None

            if self.enable_premium_filter:
                prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
                premium, _, _ = self.get_premium_rate(etf, prev_date)
                if premium is not None:
                    if premium > self.premium_threshold:
                        log.info(f"{etf} {name} 溢价率{premium*100:.1f}%")
                        return None
                else:
                    log.debug(f"{etf} {name} 无法获取溢价率，跳过溢价率过滤")

            if self.enable_volume_check:
                vol_ratio = self.get_volume_ratio(context, etf)
                if vol_ratio is not None:
                    annualized = self.get_annualized_returns(price_series, self.lookback_days)
                    if annualized > self.volume_return_limit:
                        log.info(f"{etf} {name} 成交量放量{vol_ratio:.1f}倍")
                        return None

            if len(price_series) >= self.short_lookback_days + 1:
                short_lookback_price = price_series[-(self.short_lookback_days + 1)]
                short_return = price_series[-1] / short_lookback_price - 1
                short_annualized = (1 + short_return) ** (250 / self.short_lookback_days) - 1
            else:
                short_annualized = 0

            if self.use_short_momentum_filter and short_annualized < self.short_momentum_threshold:
                log.info(f"{etf} {name} 短期动量{short_annualized*100:.2f}%")
                return None

            if self.verbose_log and etf in ("159980.XSHE", "159980.SZ", "159980") and context.current_dt.strftime("%Y-%m-%d") in ("2025-12-19", "2026-01-05"):
                self.cmp_log(f"DBG_{etf} date={context.current_dt.strftime('%Y-%m-%d')} prev_date={context.previous_date} current_dt={context.current_dt}")
                self.cmp_log(f"DBG_{etf} short_ann={short_annualized*100:.4f}% short_lookback={self.short_lookback_days} price_series_len={len(price_series)} current_price={current_price:.4f}")
                raw_close = list(prices["close"].values)
                self.cmp_log(f"DBG_{etf} hist_date_range={prices.index[0].strftime('%Y-%m-%d')}~{prices.index[-1].strftime('%Y-%m-%d')} hist_len={len(raw_close)}")
                recent_prices = price_series[-(self.lookback_days + 1):]
                y_vals = np.log(recent_prices)
                x_vals = np.arange(len(y_vals))
                w_vals = np.linspace(1, 2, len(y_vals))
                slope_i, intercept_i = np.polyfit(x_vals, y_vals, 1, w=w_vals)
                ann_ret_i = math.exp(slope_i * 250) - 1
                ss_res_i = np.sum(w_vals * (y_vals - (slope_i * x_vals + intercept_i)) ** 2)
                ss_tot_i = np.sum(w_vals * (y_vals - np.mean(y_vals)) ** 2)
                r2_i = 1 - ss_res_i / ss_tot_i if ss_tot_i != 0 else 0
                score_i = ann_ret_i * r2_i
                self.cmp_log(f"DBG_{etf} score={score_i:.4f} ann_ret={ann_ret_i*100:.4f}% r2={r2_i:.4f} slope={slope_i:.6f}")
                if len(price_series) >= 4:
                    d1 = price_series[-1] / price_series[-2]
                    d2 = price_series[-2] / price_series[-3]
                    d3 = price_series[-3] / price_series[-4]
                    min_d = min(d1, d2, d3)
                    self.cmp_log(f"DBG_{etf} loss_check:  day1={d1:.4f} day2={d2:.4f} day3={d3:.4f} min={min_d:.4f} threshold={self.loss:.4f} passed={min_d >= self.loss}")
                if self.enable_range_bound_mode and len(price_series) >= 10:
                    try:
                        lp = self.laplace_filter(price_series, s=self.laplace_s_param)
                        lp_slope = lp[-1] - lp[-2] if len(lp) >= 2 else 0
                        passed_lp = (current_price > lp[-1] and lp_slope > self.laplace_min_slope)
                        self.cmp_log(f"DBG_{etf} laplace: last={lp[-1]:.4f} slope={lp_slope:.6f} passed={passed_lp}")
                    except Exception as e:
                        self.cmp_log(f"DBG_{etf} laplace_error: {e}")

            recent = price_series[-(self.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1

            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

            score = annualized_returns * r_squared

            if len(price_series) >= 4:
                day1 = price_series[-1] / price_series[-2]
                day2 = price_series[-2] / price_series[-3]
                day3 = price_series[-3] / price_series[-4]
                if min(day1, day2, day3) < self.loss:
                    log.info(f"{etf} {name} 单日跌幅>3%")
                    return None

            if self.enable_range_bound_mode and len(price_series) >= 10:
                try:
                    laplace_values = self.laplace_filter(price_series, s=self.laplace_s_param)
                    laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                    passed_laplace = (current_price > laplace_values[-1] and laplace_slope > self.laplace_min_slope)
                    g1_val, g2_val = self.gaussian_filter_last_two(price_series, sigma=self.gaussian_sigma)
                    gaussian_slope = g1_val - g2_val
                    passed_gaussian = (current_price > g1_val and gaussian_slope > self.gaussian_min_slope)
                    if self.current_filter == '正常期':
                        passed_filter = passed_laplace
                        filter_name = '拉普拉斯'
                    else:
                        passed_filter = passed_gaussian
                        filter_name = '高斯'
                    if not passed_filter:
                        log.info(f"{etf} {name} 未通过{filter_name}({self.current_filter})")
                        return None
                except Exception as e:
                    log.debug(f"{etf} {name} 滤波器计算异常: {e}")

            return {
                'etf': etf,
                'etf_name': name,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
                'short_annualized': short_annualized,
            }

        except Exception as e:
            log.warning(f"{etf} {name} 计算动量指标时出错: {e}")
            return None

    def get_annualized_returns(self, price_series, lookback_days):
        recent = price_series[-(lookback_days + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, _ = np.polyfit(x, y, 1, w=weights)
        return math.exp(slope * 250) - 1

    def get_volume_ratio(self, context, security, lookback=None, threshold=None):
        lookback = lookback or self.volume_lookback
        threshold = threshold or self.volume_threshold
        try:
            name = self.get_name(security)
            hist = attribute_history(security, lookback, '1d', ['volume'])
            if hist.empty or len(hist) < lookback:
                return None
            avg_vol = hist['volume'].mean()

            today = context.current_dt.date()
            df_vol = get_price(security, start_date=today, end_date=context.current_dt,
                               frequency='1m', fields=['volume'], skip_paused=False, fq='pre')
            if df_vol is None or df_vol.empty:
                return None
            current_vol = df_vol['volume'].sum()
            ratio = current_vol / avg_vol if avg_vol > 0 else 0
            if ratio > threshold:
                log.debug(f"{security} {name} 成交量比{ratio:.2f} > {threshold}")
                return ratio
            return None
        except Exception as e:
            log.warning(f"成交量计算失败 {security}: {e}")
            return None


    # ==================== 卖出模块 ====================
    def check_positions(self, context):
        for sec in context.portfolio.positions:
            pos = context.portfolio.positions[sec]
            if pos.total_amount > 0:
                log.info(f"📊 持仓：{sec} {self.get_name(sec)} 数量{pos.total_amount} 成本{pos.avg_cost:.3f} 现价{pos.price:.3f}")

    def etf_sell_trade(self, context):
        log.info("========== 卖出操作开始 ==========")

        ranked = self.get_cached_rankings(context)
        target_etfs = []
        for m in ranked[:self.holdings_num]:
            if m['score'] >= self.min_score_threshold:
                target_etfs.append(m['etf'])
        defensive_available = self.check_defensive_etf_available(context)
        if not target_etfs and defensive_available:
            target_etfs = [self.defensive_etf]

        target_set = set(target_etfs)

        for sec in list(context.portfolio.positions.keys()):
            if sec not in self.etf_pool and sec != self.defensive_etf:
                continue
            if sec not in target_set:
                pos = context.portfolio.positions[sec]
                if pos.total_amount > 0:
                    if self.smart_order_target_value(sec, 0, context):
                        log.info(f"📤 卖出不在目标的持仓：{sec} {self.get_name(sec)}")

        log.info("========== 卖出操作完成 ==========")


    # ==================== 买入模块 ====================
    def etf_buy_trade(self, context):
        log.info("========== 买入操作开始 ==========")

        ranked = self.get_cached_rankings(context)
        if self.daily_detail:
            log.info("=== ETF排名前5 ===")
            for i, m in enumerate(ranked[:5]):
                log.info(f"排名{i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f} 年化{m['annualized_returns']*100:.2f}% R²={m['r_squared']:.4f}")
                self.cmp_log(f"排名{i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f} 年化{m['annualized_returns']*100:.2f}% R²={m['r_squared']:.4f}")

        target_etfs = []
        prev_date = None
        if self.enable_premium_filter:
            prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]

        for m in ranked:
            if len(target_etfs) >= self.holdings_num:
                break
            etf = m['etf']
            target_etfs.append(etf)
            log.info(f"🎯 目标ETF {len(target_etfs)}: {etf} {m['etf_name']} 得分{m['score']:.4f}")

        if not target_etfs:
            if self.check_defensive_etf_available(context):
                target_etfs = [self.defensive_etf]
                log.info(f"🛡️ 进入防御模式，选择防御ETF：{self.defensive_etf} {self.get_name(self.defensive_etf)}")
            else:
                log.info("💤 无目标ETF且防御不可用，保持空仓")
                return

        current_etf_pos = [s for s in context.portfolio.positions if s in self.etf_pool or s == self.defensive_etf]
        to_sell = [s for s in current_etf_pos if s not in target_etfs]
        if to_sell:
            to_sell_names = [self.get_name(s) for s in to_sell]
            log.info(f"尚有持仓需要卖出：{list(zip(to_sell, to_sell_names))}，等待卖出完成再买入")
            return

        total_val = context.portfolio.total_value
        target_per_etf = total_val / len(target_etfs)

        for etf in target_etfs:
            current_val = 0
            if etf in context.portfolio.positions:
                pos = context.portfolio.positions[etf]
                if pos.total_amount > 0:
                    current_val = pos.total_amount * pos.price
            if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
                if self.smart_order_target_value(etf, target_per_etf, context):
                    action = "买入" if current_val < target_per_etf else "调仓"
                    log.info(f"📦 {action}：{etf} {self.get_name(etf)} 目标金额{target_per_etf:.2f}")

        log.info("========== 买入操作完成 ==========")


    # ==================== 辅助函数 ====================
    def get_name(self, security):
        try:
            return get_current_data()[security].name
        except:
            return "未知"

    def check_defensive_etf_available(self, context):
        data = get_current_data()
        etf = self.defensive_etf
        if data[etf].paused:
            log.debug(f"防御ETF {etf} {self.get_name(etf)} 停牌")
            return False
        if data[etf].last_price >= data[etf].high_limit:
            log.debug(f"防御ETF {etf} {self.get_name(etf)} 涨停")
            return False
        if data[etf].last_price <= data[etf].low_limit:
            log.debug(f"防御ETF {etf} {self.get_name(etf)} 跌停")
            return False
        return True

    def smart_order_target_value(self, security, target_value, context):
        data = get_current_data()
        name = self.get_name(security)

        if data[security].paused:
            log.info(f"{security} {name} 停牌，跳过")
            return False

        price = data[security].last_price
        if price == 0:
            log.info(f"{security} {name} 当前价格0，跳过")
            return False

        target_amount = int(target_value / price)
        target_amount = (target_amount // 100) * 100
        if target_amount <= 0 and target_value > 0:
            target_amount = 100

        cur_pos = context.portfolio.positions.get(security, None)
        cur_amount = cur_pos.total_amount if cur_pos else 0
        diff = target_amount - cur_amount

        if diff > 0:
            if data[security].last_price >= data[security].high_limit:
                log.info(f"{security} {name} 涨停，跳过买入")
                return False
        elif diff < 0:
            if data[security].last_price <= data[security].low_limit:
                log.info(f"{security} {name} 跌停，跳过卖出")
                return False

        trade_val = abs(diff) * price
        if 0 < trade_val < self.min_money:
            log.info(f"{security} {name} 交易金额{trade_val:.2f} < {self.min_money}，跳过")
            return False

        if diff < 0:
            closeable = cur_pos.closeable_amount if cur_pos else 0
            if closeable == 0:
                log.info(f"{security} {name} 当天买入不可卖出")
                return False
            diff = -min(abs(diff), closeable)

        if diff != 0:
            order_result = order(security, diff)
            if order_result:
                log.info(f"{'📥 买入' if diff>0 else '📤 卖出'} {security} {name} 数量{abs(diff)} 价格{price:.3f}")
                action = "买入" if diff>0 else "卖出"
                self.cmp_log(f"{action} {security} {name} 数量{abs(diff)} 价格{price:.3f}")
                return True
            else:
                log.warning(f"下单失败: {security} {name} 数量{diff}")
                return False
        return False