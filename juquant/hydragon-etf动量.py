# =====================================================================
# 策略名称: ETF动量轮动策略 V2.6-D (截面收益率离散度判别)
# 来源: V2.2 基础上新增截面得分离散度 → TOP2均分切换机制
# 版本: V2.6-D — 2026-08-02
# =====================================================================
#
# ─── V2.6-D 新增: 截面收益率离散度判别 ─────────────────────────────────
#   机制: 计算近5日, 评分在阈值区间内ETF的评分标准差均值
#   触发: 5日平均std < 0.25 → 资产间收益差距小 → TOP2均分仓位
#         黄金ETF(518880)/纳指100(513100)/红利ETF(510880)/创业板50(159949)
#         /科创50(588000)/原油LOF(160723)/豆粕ETF(159985)/沪深300(510300)
#         /煤炭ETF(515220) 中的得分TOP2, 各50%仓位
#   恢复: 5日平均std > 0.45 → 收益差距恢复 → 单支满仓动量
#   阈值来源: 得分区间[0.085,5.0], std<0.25表示9支ETF得分聚类在~0.5以内,
#           std接近0则无差异(随机选股), std>0.45表示有明确分层;
#           文献CFRN(2025): 高离散度利好动量, 低离散度动量衰减
#   ───────── 以下V2.2逻辑完全未改动 ─────────
# =====================================================================

from jqdata import *
import numpy as np
import pandas as pd
import math
import time

import bullet_trade_jq_wrapper as bt_wrapper
Live_Type = False
(order,order_target_value,order_value,order_target) = bt_wrapper.get_orders_func(order,order_target_value,order_value,order_target)

def process_initialize(context):
    bt_wrapper.configured(context,Live_Type)

def before_trading_start(context):
    try:
        if Live_Type:
            ok = bt_wrapper.qmt_is_ok()
            if not ok:
                send_message("QMT服务端异常，检查云服务器是否正常登录qmt")
    except Exception as e:
        print(f"before_trading_start检查qmt异常")

def after_trading_end(context):
    if 'sim_trade' == context.run_params.type and Live_Type:
        bt_wrapper.sync_check_jq_sim_vs_real(get_portfolio_positions(context))

def initialize(context):
    set_benchmark('000985.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5), type='stock')
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=0.0001, close_commission=0.0001,
        close_today_commission=0, min_commission=5), type='fund')
    log.set_level('order', 'warning')

    g.etf_names = {
        '518880.XSHG': '黄金ETF', '513100.XSHG': '纳指100ETF',
        '159949.XSHE': '创业板50ETF', '510880.XSHG': '红利ETF',
        '588000.XSHG': '科创50ETF', '159985.XSHE': '豆粕ETF',
        '510300.XSHG': '沪深300ETF', '515220.XSHG': '煤炭ETF','513350.XSHG': '标普油气ETF',
    }
    g.etf_pool = list(g.etf_names.keys())
    # 十年期国债ETF
    g.bond_etf = '511090.XSHG'
    g.etf_score_threshold_min = 0.085
    g.etf_score_threshold_max = 5.0
    g.next_etf_target = None
    g.next_etf_targets = []
    

    g.etf_momentum_lookback = 15
    g.etf_min_hold_days = 2
    g.etf_stop_loss = -0.03
    g.etf_drawdown_stop = -0.04
    g.etf_cooldown_days = 3
    g.etf_cooldown = {}
    g.etf_hold_state = {}
    g.consecutive_stop_losses = 0
    g.stop_loss_penalty_bump = 1.0
    g.etf_score_threshold_min_base = 0.085
    g.vix_thresholds = {
        '513100.XSHG':22,'588000.XSHG':22,'159949.XSHE':24,'159985.XSHE':30,'510300.XSHG':22,'515220.XSHG':26,'513350.XSHG':26
    }
    g.etf_position_ratio = 0.5
    g.float_tolerance = 0.10

    # ── ★ V2.6-D: 截面离散度判别参数 ──
    g.dispersion_mode = 'single'            # single | top2
    g.dispersion_lookback = 5               # 5日滚动
    g.dispersion_history = []               # [(date, std_val), ...]
    g.dispersion_top2_threshold = 0.25      # <0.25→TOP2均分
    g.dispersion_single_threshold = 0.45    # >0.45→恢复单支满仓(迟滞0.20)
    # 阈值来源: 得分范围[0.085,5.0]; std<0.25表示9支ETF聚类于~0.5以内
    #          CFRN(2025): 收益离散度低→动量衰减, 高→动量增强
    # 止盈线
    g.take_profit_pct = 0.01

    # run_weekly(etf_sell, 1, '14:45')
    # run_weekly(etf_buy, 1, '14:45:30')

    run_daily(check_profits_and_losses, '14:45')
    run_daily(etf_sell,  '14:45')
    run_daily(etf_buy,  '14:45:30')
    run_daily(log_daily_summary, '15:10')


def is_etf_available(context, etf):
    try:
        info = get_security_info(etf)
        if info is None: return False
        if info.start_date > context.previous_date: return False
        return True
    except: return False


# =====================================================================
# ★ V2.6-D: 截面得分离散度计算 + 模式切换
# =====================================================================
def calc_score_dispersion(context, score_dict):
    """
    计算当前截面得分离散度 + 更新5日历史 → 判定模式.

    步骤:
      1. 取阈值区间内ETF的评分, 计算std
      2. 存入g.dispersion_history(保持5日)
      3. 计算5日std均值
      4. 判定模式: <0.25→top2, >0.45→single, 中间保持

    返回: (mode, top2_list或None)
    """
    today = context.current_dt.date()

    # 1. 截面离散度
    valid_scores = [s for e, s in score_dict.items()
                    if g.etf_score_threshold_min <= s <= g.etf_score_threshold_max]
    if len(valid_scores) < 3:
        log.info('[离散度] 有效ETF不足(%d), 维持单支模式' % len(valid_scores))
        return 'single', None

    current_std = np.std(valid_scores, ddof=1)  # 样本标准差

    # 2. 更新历史
    g.dispersion_history.append((today, current_std))
    # 保持只保留近5个交易日
    cutoff_date = None
    try:
        trade_days = get_trade_days(end_date=today, count=g.dispersion_lookback + 1)
        if len(trade_days) >= 2:
            cutoff_date = trade_days[0]
    except: pass

    if cutoff_date:
        g.dispersion_history = [(d, v) for d, v in g.dispersion_history if d >= cutoff_date]
    if len(g.dispersion_history) > g.dispersion_lookback:
        g.dispersion_history = g.dispersion_history[-g.dispersion_lookback:]

    # 3. 5日均值
    avg_std = np.mean([v for _, v in g.dispersion_history]) if g.dispersion_history else current_std

    # 4. 模式判定
    old_mode = g.dispersion_mode

    if old_mode == 'single':
        if avg_std < g.dispersion_top2_threshold:
            g.dispersion_mode = 'top2'
            log.info('╔══════════════════════════════════════════╗')
            log.info('║ [离散度判别] 5日均std=%.4f < %.2f          ║' % (
                avg_std, g.dispersion_top2_threshold))
            log.info('║ 收益差距缩小 → 切换TOP2均分模式           ║')
            log.info('╚══════════════════════════════════════════╝')
    elif old_mode == 'top2':
        if avg_std > g.dispersion_single_threshold:
            g.dispersion_mode = 'single'
            log.info('╔══════════════════════════════════════════╗')
            log.info('║ [离散度判别] 5日均std=%.4f > %.2f          ║' % (
                avg_std, g.dispersion_single_threshold))
            log.info('║ 收益差距恢复 → 回到单支满仓               ║')
            log.info('╚══════════════════════════════════════════╝')

    # 5. 如果是top2模式, 确定TOP2
    top2_list = None
    if g.dispersion_mode == 'top2':
        ranked = sorted(score_dict.keys(), key=lambda e: score_dict.get(e, -999), reverse=True)
        top2_list = ranked[:2]

    log.info('[离散度] 当日std=%.4f | 5日均=%.4f | 模式=%s | n=%d支' % (
        current_std, avg_std, g.dispersion_mode, len(valid_scores)))

    return g.dispersion_mode, top2_list


# =====================================================================
# get_rank(未改动)
# =====================================================================
def get_rank(context):
    bars = g.etf_momentum_lookback*4
    score_list=[]; valid_etfs=[]
    for etf in g.etf_pool:
        if not is_etf_available(context,etf): continue
        try:
            df=attribute_history(etf,bars,'60m',['close'],skip_paused=True,df=True)
            if len(df)<bars: continue
            y=np.log(df['close'].values); x=np.arange(len(y))
            slope,intercept=np.polyfit(x,y,1)
            annualized_ret=math.exp(slope*4*250)-1
            y_pred=slope*x+intercept
            ss_res=np.sum((y-y_pred)**2); ss_tot=np.sum((y-np.mean(y))**2)
            r_squared=1-(ss_res/ss_tot) if ss_tot!=0 else 0
            score=annualized_ret*r_squared
            score_list.append(score); valid_etfs.append(etf)
        except: continue
    if not valid_etfs: return [],-999,{}
    df=pd.DataFrame({'etf':valid_etfs,'score':score_list})
    df=df.sort_values('score',ascending=False)
    score_info=[]
    for etf in g.etf_pool:
        if etf in valid_etfs:
            s=df[df['etf']==etf]['score'].values[0]
            score_info.append('%s=%.4f'%(g.etf_names.get(etf,etf),s))
        else: score_info.append('%s=N/A'%g.etf_names.get(etf,etf))
    log.info('[动量] 排名: '+' | '.join(score_info))
    return df['etf'].tolist(), df.iloc[0]['score'], dict(zip(df['etf'],df['score']))


# ─────────────── V2.2下单体系(未改动) ───────────────
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

def calc_order_shares(context,code,target_value,overshoot_ok=True):
    try: px=get_current_data()[code].last_price
    except: return 0
    if not px or px<=0:
        try:
            df=attribute_history(code,1,'1d',['close'],skip_paused=True,df=True)
            px=df['close'].iloc[-1]
        except: return 0
    if not px or px<=0: return 0
    holdings=context.portfolio.positions
    already_value=0
    if code in holdings: already_value=holdings[code].value
    diff_value=target_value-already_value
    if diff_value<=0: return 0
    a_cash=context.portfolio.available_cash
    if a_cash<diff_value: diff_value=a_cash
    exact=int(diff_value/px/100)*100; ret=exact
    if exact<100: ret=0
    if overshoot_ok and ret>0:
        ceil=int(math.ceil(diff_value/px/100))*100
        if ceil>=100 and ceil*px<=target_value: ret=ceil
    return ret

def get_vix_level():
    try:
        df=attribute_history('510050.XSHG',21,'1d',['close'],skip_paused=True,df=True)
        if len(df)<21: return -1
        returns=df['close'].pct_change().dropna()
        return returns.std()*math.sqrt(250)*100
    except: return -1

def is_vix_elevated(etf):
    if etf not in g.vix_thresholds: return False
    vix=get_vix_level()
    if vix<0: return False
    if vix>g.vix_thresholds[etf]:
        log.info('[VIX风控] VIX=%.1f > %.0f(%s阈值) → %s 降至半仓'%(
            vix,g.vix_thresholds[etf],g.etf_names.get(etf,etf),g.etf_names.get(etf,etf)))
        return True
    return False

def _is_in_cooldown(etf,context):
    if etf in g.etf_cooldown:
        trade_days=get_trade_days(start_date=g.etf_cooldown[etf],end_date=context.current_dt.date())
        if len(trade_days)-1<g.etf_cooldown_days: return True
        else: del g.etf_cooldown[etf]
    return False

def _clean_cooldown(context):
    for etf in list(g.etf_cooldown.keys()): _is_in_cooldown(etf,context)

def _is_above_ma200(etf):
    try:
        df=attribute_history(etf,200,'1d',['close'],skip_paused=True,df=True)
        if len(df)<200: return True
        return df['close'].iloc[-1]>df['close'].mean()
    except: return True

def take_profit_check(context):
    # ===== ★ 新增：止盈检查（仅单支满仓模式） =====
    positions = get_portfolio_positions(context)
    for code, pos in positions.items():
        if pos.closeable_amount <= 0: continue
        entry_price = pos.avg_cost
        cur_price = get_current_data()[code].last_price
        if cur_price and cur_price > 0 and entry_price > 0:
            profit_pct = (cur_price - entry_price) / entry_price
            log.info(f"[止盈检查] {g.etf_names.get(code, code)} | cur_price={cur_price:.4f} | entry_price={entry_price:.4f} profit_pct={profit_pct*100:.2f}%")
            if profit_pct >= g.take_profit_pct:
                log.info('[止盈] %s 涨幅%.2f%% >= %.2f%% 触发止盈' % (
                    g.etf_names.get(code, code),
                    profit_pct * 100,
                    g.take_profit_pct * 100))
                close_position(code, context)
                if code in g.etf_hold_state:
                    del g.etf_hold_state[code]
                
def _check_stop_loss(context):
    stop_count=0; current_data=get_current_data()
    for etf,state in list(g.etf_hold_state.items()):
        if etf not in context.portfolio.positions: del g.etf_hold_state[etf]; continue
        pos=context.portfolio.positions[etf]
        if pos.total_amount==0: del g.etf_hold_state[etf]; continue
        try: cur_price=current_data[etf].last_price
        except: continue
        if cur_price<=0: continue
        if cur_price>state['high_water']: state['high_water']=cur_price
        if (context.current_dt.date()-state['entry_date']).days<g.etf_min_hold_days: continue
        drop_pct=(cur_price-state['entry_price'])/state['entry_price']
        dd_pct=(cur_price-state['high_water'])/state['high_water']
        triggered=False; reason=''
        if drop_pct<=g.etf_stop_loss: triggered=True; reason='跌幅%.2f%%触发-3%%止损'%(drop_pct*100)
        elif dd_pct<=g.etf_drawdown_stop: triggered=True; reason='回撤%.2f%%触发-4%%止损'%(dd_pct*100)
        if triggered:
            stop_count+=1; pre_amount=pos.total_amount
            log.info('[止损] %s %s | 冷却%d个交易日'%(g.etf_names.get(etf,etf),reason,g.etf_cooldown_days))
            close_position(etf,context); time.sleep(1)
            post_pos=context.portfolio.positions.get(etf)
            post_amount=post_pos.total_amount if post_pos else 0
            if post_amount==0:
                g.etf_cooldown[etf]=context.current_dt.date(); del g.etf_hold_state[etf]
                log.info('[止损] %s 卖出成功 | 原持仓%d股'%(g.etf_names.get(etf,etf),pre_amount))
            else: log.error('[止损] %s 卖出未完成: 剩余%d股'%(g.etf_names.get(etf,etf),post_amount))
    return stop_count

def _update_etf_hold_state(etf,context):
    current_data=get_current_data()
    try: price=current_data[etf].last_price
    except: price=None
    if price is None or price<=0:
        try:
            df=attribute_history(etf,1,'1d',['close'],skip_paused=True,df=True)
            price=df['close'].iloc[-1]
        except: return
    g.etf_hold_state[etf]={'entry_price':price,'entry_date':context.current_dt.date(),'high_water':price}


# =====================================================================
# ★ V2.6-D: etf_sell — 增加离散度判别
# =====================================================================
def check_profits_and_losses(context):
    take_profit_check(context)
    _clean_cooldown(context)
    stop_count=_check_stop_loss(context)
    if stop_count>0:
        g.consecutive_stop_losses+=1
        log.info('[止损惩罚] 连续止损 %d 次'%g.consecutive_stop_losses)
    else:
        if g.consecutive_stop_losses>0:
            log.info('[止损惩罚] 未触发止损, 重置计数(原=%d)'%g.consecutive_stop_losses)
        g.consecutive_stop_losses=0

def etf_sell(context):
    tv=context.portfolio.total_value
    # if tv<1000: 
    #     _clear_all_etf(context)
    #     g.next_etf_targets=[]
    #     return
    # check_profits_and_losses(context)
    dynamic_threshold_min=g.etf_score_threshold_min_base
    if g.consecutive_stop_losses>=2:
        dynamic_threshold_min=g.etf_score_threshold_min_base+g.stop_loss_penalty_bump
        log.info('[止损惩罚] 连续止损≥2次 → 阈值上调: %.3f→%.3f'%(
            g.etf_score_threshold_min_base,dynamic_threshold_min))
    else: dynamic_threshold_min=g.etf_score_threshold_min_base

    rank_list,top_score,score_dict=get_rank(context)

    if rank_list:
        rank_list=[e for e in rank_list if not _is_in_cooldown(e,context)]

    for etf in list(rank_list):
        if etf not in score_dict: continue
        s=score_dict[etf]
        if s<dynamic_threshold_min:
            log.info('[过滤] %s 得分%.4f < %.3f, 剔除'%(g.etf_names.get(etf,etf),s,dynamic_threshold_min))
            rank_list.remove(etf)
        elif s>g.etf_score_threshold_max:
            log.info('[过滤] %s 得分%.4f > %.1f, 剔除'%(g.etf_names.get(etf,etf),s,g.etf_score_threshold_max))
            rank_list.remove(etf)

    for etf in list(rank_list):
        if not _is_above_ma200(etf):
            log.info('[过滤] %s 价格低于200日均线, 剔除'%g.etf_names.get(etf,etf))
            rank_list.remove(etf)

    # ── ★ Step 3.6: 截面离散度判别 ──
    disp_mode, top2_list = calc_score_dispersion(context, score_dict)

    if disp_mode == 'top2' and top2_list and len(top2_list) >= 2:
        # TOP2均分(各50%)
        valid_top2 = [e for e in top2_list if e in rank_list]
        if len(valid_top2) >= 2:
            g.next_etf_targets = [(valid_top2[0], 0.50), (valid_top2[1], 0.50)]
            log.info('[14:45] 模式=TOP2均分 | %s(50%%) + %s(50%%)' % (
                g.etf_names.get(valid_top2[0], valid_top2[0]),
                g.etf_names.get(valid_top2[1], valid_top2[1])))
        elif len(valid_top2) == 1:
            g.next_etf_targets = [(valid_top2[0], 1.0)]
            log.info('[14:45] TOP2仅1支通过过滤 → 单支 %s' % g.etf_names.get(valid_top2[0], valid_top2[0]))
        else:
            g.next_etf_targets = [(g.bond_etf, 1.0)]
            log.info('[14:45] TOP2均无通过过滤 → 国债')
    else:
        # 单支满仓
        if not rank_list:
            g.next_etf_targets = [(g.bond_etf, 1.0)]
            log.info('[14:45] 无ETF可选 → 目标:国债')
        else:
            g.next_etf_targets = [(rank_list[0], 1.0)]
            s=score_dict.get(rank_list[0],0)
            log.info('[14:45] 选定目标 %s(%.4f) → 准备买入'%(
                g.etf_names.get(rank_list[0],rank_list[0]),s))

    target_codes=set(e for e,_ in g.next_etf_targets)
    for etf in list(context.portfolio.positions.keys()):
        if not (etf.startswith('5') or etf.startswith('1')): continue
        if etf in target_codes: continue
        pos=context.portfolio.positions[etf]
        pre_amount=pos.total_amount
        if pre_amount==0: continue
        pre_value=pos.value
        close_position(etf,context); time.sleep(1)
        post_pos=context.portfolio.positions.get(etf)
        post_amount=post_pos.total_amount if post_pos else 0
        if post_amount==0:
            if etf in g.etf_hold_state: del g.etf_hold_state[etf]
            log.info('[14:45] 卖出 %s | 释放约%.0f元(%d股)'%(g.etf_names.get(etf,etf),pre_value,pre_amount))
        else: log.error('[14:45] %s 卖出未完成: 剩余%d股'%(g.etf_names.get(etf,etf),post_amount))


def etf_buy(context):
    targets=g.next_etf_targets
    if not targets: log.warn('[14:45:30] 无目标ETF, 跳过买入'); return
    tv=context.portfolio.total_value
    available=context.portfolio.available_cash
    for target,weight in targets:
        if can_not_deal(target):
            log.error('[14:45:30] %s 不可交易, 跳过'%g.etf_names.get(target,target)); continue
        target_value=tv*weight
        if g.dispersion_mode=='single' and is_vix_elevated(target):
            target_value=target_value*g.etf_position_ratio
            log.info('[14:45:30] VIX超标 → %s 仓位: %.0f→%.0f'%(
                g.etf_names.get(target,target),tv*weight,target_value))
        current_pos=context.portfolio.positions.get(target,None)
        already_value=current_pos.value if current_pos and current_pos.total_amount>0 else 0
        if already_value>0:
            deviation=abs(already_value-target_value)/max(target_value,1)
            if deviation<g.float_tolerance:
                log.info('[14:45:30] %s 仓位到位 | 偏离:%.1f%% → 跳过'%(
                    g.etf_names.get(target,target),deviation*100))
                continue
        shares=calc_order_shares(context,target,target_value,overshoot_ok=True)
        if shares<100:
            log.info('[14:45:30] %s 股数=%d<100 → 跳过'%(g.etf_names.get(target,target),shares))
            continue
        pre_amount=current_pos.total_amount if current_pos else 0
        order_value_amount=shares*(current_pos.price if current_pos and current_pos.price>0
                        else get_current_data()[target].last_price)
        order_error=None
        try: safe_order_target_value(context,'buy',target,order_value_amount+already_value)
        except Exception as e: order_error=str(e)
        log.info('[14:45:30] 买入 %s(%d%%) | 股:%d | 金额:%.0f%s，%s'%(
            g.etf_names.get(target,target),int(weight*100),shares,order_value_amount,
            ' (假阴性?)' if order_error else '', order_error or ''))
        time.sleep(2)
        post_pos=context.portfolio.positions.get(target)
        post_amount=post_pos.total_amount if post_pos else 0; delta=post_amount-pre_amount
        if delta>0:
            if order_error: log.info('[14:45:30] ★ 假阴性确认: %s +%d股'%(g.etf_names.get(target,target),delta))
            if pre_amount==0: _update_etf_hold_state(target,context)
        elif delta==0 and pre_amount>0:
            log.info('[14:45:30] %s 仓位未变(%d股)'%(g.etf_names.get(target,target),post_amount))
        else: log.error('[14:45:30] ★ %s 未成交!'%g.etf_names.get(target,target))
        available=context.portfolio.available_cash
    g.next_etf_targets=[]

def _clear_all_etf(context):
    log.info('[清仓] 总资产%.0f < 1000元 → 清空所有ETF持仓'%context.portfolio.total_value)
    for s in list(context.portfolio.positions.keys()):
        if s.startswith('5') or s.startswith('1'): close_position(s,context)

def log_daily_summary(context):
    p=context.portfolio
    log.info('=== 收盘 [%s] | 离散度模式=%s | 持仓=%d支 ==='%(
        context.current_dt.date(),g.dispersion_mode,
        sum(1 for s in p.positions if (s.startswith('5') or s.startswith('1'))
            and p.positions[s].total_amount>0)))
    log.info('  总资产: %.2f | 现金: %.2f | 收益率: %.2f%%'%(p.total_value,p.available_cash,p.returns*100))
    for s,pos in p.positions.items():
        if s.startswith('5') or s.startswith('1'):
            cost=pos.avg_cost; price=pos.price
            pnl=(price-cost)/cost*100 if cost>0 else 0
            log.info('  [ETF] %s | %d股 | 成本:%.3f | 收盘:%.3f | 盈亏:%.2f%%'%(
                g.etf_names.get(s,s),pos.total_amount,cost,price,pnl))

def close_position(code,context):
    pos=context.portfolio.positions.get(code)
    if not pos or pos.total_amount<=0: return True
    if can_not_deal(code):
        log.warn('[平仓] %s 不可交易, 跳过'%g.etf_names.get(code,code)); return False
    try: safe_order_target_value(context,'sell',code,0)
    except Exception as e: log.warn('[平仓] %s 接口报错(可能假阴性): %s'%(g.etf_names.get(code,code),str(e)))
    return True
    

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

def safe_order_target_value(context,action,code,target_value,pindex=0):
    style = None
    if pindex > 0 and not has_subportfolio(context, pindex):
        pindex = 0
    log.info(f"safe_order_target_value start {action} {code} target_value={target_value}")
    positions = get_portfolio_positions(context,pindex)
    portfolio = get_portfolio(context,pindex)
    available_cash = portfolio.available_cash
    cur_data = get_current_data()
    price = cur_data[code].last_price
    is_kcb = code[:2] == '68'
    limit_price = price*(1+0.005) if action == 'buy' else price*(1-0.005)
    style = MarketOrderStyle(limit_price)

    if code in positions:
        pos = positions[code]
        had_value = pos.value
        diff_value = target_value - had_value
        if action == 'sell' and diff_value < 0:
            if target_value==0:
                order(code, -pos.closeable_amount, style,pindex = pindex)
                return -1
            sell_amount = int(abs(diff_value)  / price // 100) * 100
            a_amount = min(pos.closeable_amount, sell_amount)
            if a_amount >= 100:
                order(code, -a_amount, style,pindex = pindex)
                return -1
        elif diff_value > 0:
            buy_value = min(available_cash, diff_value)
            amount = int(abs(buy_value)  / price // 100) * 100
            if amount >= 200 or (amount>=100 and not is_kcb):
                order(code, amount, style,pindex = pindex)
                return 1
            else:
                log.warn(f"safe_order_target_value ignore,holding {code} {amount} {style} {available_cash} {pindex}")
    elif action == 'buy':
        buy_value = min(available_cash, target_value)
        amount = int(abs(buy_value)  / price // 100) * 100
        if amount >= 200 or (amount>=100 and not is_kcb):
            order(code, amount, style,pindex = pindex)
            return 1
        else:
            log.warn(f"safe_order_target_value ignore, {code} {amount} {style} {available_cash} {pindex}")
    return 0
