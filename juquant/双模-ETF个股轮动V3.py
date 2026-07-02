# -*- coding: utf-8 -*-
"""
双模ETF+个股动量轮动策略 V2.2 — 仓位百分比版
牛: ETF 30% + 3支个股各20% = 90%总仓位
熊: 黄金 50% + 现金 50%
基准: 创业板ETF(159915) | 入熊新增单日>-3% / 5日>-8%
"""
import numpy as np
import pandas as pd
import math
from scipy import stats

# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper
import datetime

# 默认下单函数
TRADE_TYPE = 'no_live'  # 'live':实盘模式,其他值：用聚宽平台默认下单函数
(order,order_target_value,order_value,order_target)  = bt_wrapper.wrap_orders(order, order_target_value, order_value, order_target,TRADE_TYPE,log_func=log.info)
# 初始化函数，聚宽重启/代码刷新时调用
def process_initialize(context):
    """
    聚宽重启/代码刷新时调用，此处完成所有初始化与任务注册。
    """
    log.info(f"process_initialize 重建配置 {datetime.datetime.now()}")
    # 初始化链接，同时覆盖默认下单函数
    bt_wrapper.configured()

# =======================实盘配置End=======================================
def after_trading_end(context):
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'backtest' not in context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(context.portfolio.positions)

def set_targets(context):
    g.etf_only = [
        '510300.XSHG','159915.XSHE','510500.XSHG','512880.XSHG',
        '588000.XSHG','588080.XSHG','512100.XSHG','159533.XSHE','159996.XSHE',
        '513100.XSHG','513500.XSHG',
        '518880.XSHG','513010.XSHG','515220.XSHG','159981.XSHE','159985.XSHE',
        '159755.XSHE','561380.XSHG','159129.XSHE','515070.XSHG',
        '516770.XSHG','159565.XSHE','159770.XSHE',
    ]
    g.stock_only = list({
        # 原版
        '002837.XSHE',#英维克
        '603259.XSHG',#药明康德
        '002028.XSHE',#思源电气
        '605117.XSHG',#德业股份
        '002602.XSHE',#世纪华通
        '605499.XSHG',#东鹏饮料
        '002170.XSHE',#芭田股份
        '605020.XSHG',#永和股份
        '600176.XSHG',#中国巨石
        '000426.XSHE',#兴业银锡
        '300037.XSHE',#新宙邦
        '300196.XSHE',#长海股份
        '002709.XSHE',#天赐材料
        '600487.XSHG',#亨通光电
        '002353.XSHE',#杰瑞股份
        '603929.XSHG',#亚翔集成
        '002463.XSHE',#沪电股份
        '300866.XSHE',#安克创新
        '301031.XSHE',#中熔电气
        '605016.XSHG',#百龙创园
        '301536.XSHE',#星宸科技
        '300476.XSHE',#胜宏科技
        '002916.XSHE',#深南电路
        '001389.XSHE',#广合科技
        '301345.XSHE',#涛涛车业
        '605305.XSHG',#中际联合
        '600601.XSHG',#方正科技
        '301606.XSHE',#绿联科技
        '603979.XSHG',#金诚信
        '603530.XSHG',#神马电力
        '603966.XSHG',#法兰泰克
        '603606.XSHG',#东方电缆
        '600549.XSHG',#厦门钨业
        '603699.XSHG',#纽威股份
        '002454.XSHE',#松芝股份
        '300893.XSHE',#松原股份
        '002475.XSHE',#立讯精密
        '603444.XSHG',#吉比特
        '002558.XSHE',#巨人网络
        '300236.XSHE',#上海新阳
        '603129.XSHG',#春风动力
        '301087.XSHE',#可孚医疗
        '300502.XSHE',#新易盛
        '002906.XSHE',#华阳集团
        '002595.XSHE',#豪迈科技
        '300308.XSHE',#中际旭创
        '300394.XSHE',#天孚通信
        '002600.XSHE',#领益智造
        '002050.XSHE',#三花智控
        '603256.XSHG',#宏和科技
        '300201.XSHE',#海伦哲
        '002594.XSHE',#比亚迪
        '300750.XSHE',#宁德时代
        '600660.XSHG',#福耀玻璃
        '600989.XSHG',#宝丰能源
        '002311.XSHE',#海大集团
        '600036.XSHG',#招商银行
        '601688.XSHG',#华泰证券
        '300433.XSHE',#蓝思科技
        '601899.XSHG',#紫金矿业
        '000999.XSHE',#华润三九
        '600938.XSHG',#中国海油
        '601919.XSHG',#中远海控
        '002472.XSHE',#双环传动
        '000733.XSHE',#振华科技
        '000858.XSHE',#五粮液
        '600028.XSHG',#中国石化
        '601857.XSHG',#中国石油
        '600900.XSHG',#长江电力
    })


def after_code_changed(context):
    # 修复模拟盘热更新时，新增参数未初始化的报错
    set_targets(context)
    schedule_tasks(context)
        
def initialize(context):
    set_slippage(FixedSlippage(2/100), type='stock')
    set_slippage(FixedSlippage(2/1000), type='fund')
    set_order_cost(OrderCost(
        open_tax=0.0, close_tax=1/1000,
        open_commission=1/10000, close_commission=1/10000, min_commission=5
    ), type='stock')
    set_order_cost(OrderCost(
        open_tax=0.0, close_tax=0.0,
        open_commission=1/10000, close_commission=1/10000, min_commission=5
    ), type='fund')
    set_benchmark('159915.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('system', 'error')
    log.set_level('order', 'info')
    
    set_targets(context)

    g.m_days = 120; g.momentum_days = 20; g.score_min = 0
    g.multi_momentum_days = [20, 60, 120]
    g.multi_momentum_wight = [0.5,0.3,0.2]
    
    g.etf_num = 1; g.stock_num = 3
    g.etf_pct = 0.3; g.stock_pct = 0.20; g.bear_each_pct = 0.5

    g.stop_loss_rmb = 10000; g.stop_loss_pct = 0.045
    g.atr_mult = 3; g.atr_period = 14

    g.ma_short = 15
    g.ma_long = 65
    g.ma_half_year = 120
    g.benchmark_code = '159915.XSHE'  # 创业板ETF为牛熊判断基准
    g.bear_d1_pct = -0.03             # 单日跌>3%入熊
    g.bear_d5_pct = -0.08             # 5日跌>8%入熊

    g.gold_etf = '518880.XSHG'; g.nasdaq_etf = '513100.XSHG'
    g.hl_etf = '510880.XSHG'
    g.cash_etf = '511880.XSHG'
    g.sp500_etf = '513500.XSHG'; g.safe_etfs = [g.gold_etf, g.cash_etf]

    g.high_prices = {}
    g.bear_mode = False
    g.ma_inited = False
    g.last_rebalance = {}
    g.entry_dates = {}
    g.rebalance_freq_days = 20
    g.vol_filter_min = 50000000
    g.vol_filter_days = 20
    g.min_hold_days = 5

    # 参数设置
    g.short_window = 20      # 短期均线周期
    g.long_window = 60       # 长期均线周期
    g.rsrs_window = 18       # RSRS回归窗口
    g.rsrs_std_window = 600  # RSRS标准化窗口
    
    # 仓位控制参数
    g.bull_threshold = 0.3   # 牛市阈值
    g.bear_threshold = -0.3  # 熊市阈值
    
    schedule_tasks(context)
  
def schedule_tasks(context):
    unschedule_all()
    run_daily(up_strength, "9:00")
    run_daily(compute_signals, '14:45')
    run_daily(execute_sell_stop, '14:45:15')
    run_daily(execute_buy, '14:45:30')
    
def calc_order_shares(context,code, target_value, price, overshoot_ok=True):
    if not price or price <= 0: return 0
    holdings = context.portfolio.positions
    already_value = 0
    total_amount = 0
    if code in holdings:
        already_value = holdings[code].value
        total_amount = holdings[code].total_amount
    a_cash = context.portfolio.available_cash
    diff_value = target_value - already_value
    # log.info(f"calc_order_shares {code} 现价={price} 已有市值={already_value} 目标市值={target_value} 差值={diff_value} 可用={a_cash}")

    if a_cash < (target_value - already_value):
        target_value = already_value + a_cash
    ret = 0
    exact = int(target_value / price / 100) * 100
    ret = exact
    if exact < 100: 
        ret = 0
    if overshoot_ok:
        ceil = int(math.ceil(target_value / price / 100)) * 100
        if ceil >= 100 and ceil * price <= target_value:
            ret = ceil
    return ret


def order_by_pct(context, code, target_pct, total_value,side='buy'):
    if can_not_deal(code):
        return
    px = get_current_data()[code].last_price
    s = calc_order_shares(context,code, total_value * target_pct, px, overshoot_ok=True)
    if s < 100: 
        return
    holdings = context.portfolio.positions
    cv = 0
    if code in holdings:
        cv = holdings[code].total_amount
    if cv > 0 and abs(cv - s) / s < 0.10: 
        return
    diff = s - cv
    value = s * px
    if diff != 0:
        if 'buy' == side and diff > 0: 
            # 只操作买入
            safe_order_target_value(context,side,code, value)
        elif 'sell' == side and diff < 0:
            # 只操作卖出
            safe_order_target_value(context,side,code, value)
    log.info(f"order_by_pct {side} {code}({mingcheng(code)})  目标股数={s} 目标仓位{target_pct} 金额{value} 原有股数={cv} 差{diff}股 现价={px} ")
        

def up_strength(context):
    try:
        r = {}
        r2 = {}
        for idx in range(0,len(g.multi_momentum_days)):
            p = g.multi_momentum_days[idx]
            w = g.multi_momentum_wight[idx]
            df = history(p,'1d','close',g.etf_only,df=True,skip_paused=True,fq='pre').dropna(axis=1)
            if not df.empty:
                m = (df.iloc[-1]-df.iloc[0])/df.iloc[0]
                for c in m.index:
                    value = r.get(c,0)+m[c]  * w
                    r[c] = value
            df = history(p,'1d','close',g.stock_only,df=True,skip_paused=True,fq='pre').dropna(axis=1)
            if not df.empty:
                m = (df.iloc[-1]-df.iloc[0])/df.iloc[0]
                for c in m.index:
                    value = r2.get(c,0)+m[c]  * w
                    r2[c] = value
        g.etf_ranking = sorted(r,key=r.get,reverse=True) if r else []
        g.stock_ranking = sorted(r2,key=r2.get,reverse=True)[:30] if r2 else [] 
        
    except Exception as e:
        log.error(f"[up_strength] {e}")
        g.etf_ranking=[]
        g.stock_ranking=[]


def can_not_deal(code):
    cur_data = get_current_data()
    cur_price = cur_data[code].last_price
    no_price = cur_price is None or cur_price <=0
    is_paused = cur_data[code].paused
    is_st = cur_data[code].is_st
    is_limit = cur_price>=cur_data[code].high_limit or cur_price<=cur_data[code].low_limit 
    can_not_deal = (no_price or is_paused or is_st or is_limit)
    if can_not_deal:
        log.info(f"{code} {mingcheng(code)} can_not_deal={can_not_deal},no_price={no_price} is_paused={is_paused} is_st={is_st} is_limit={is_limit}")
    return can_not_deal
    
def filter_liquidity(pool):
    v = []
    for c in pool:
        try:
            df = attribute_history(c,g.vol_filter_days,'1d',['volume','close'],skip_paused=True)
            if len(df)<g.vol_filter_days:
                continue
            if (df['volume']*df['close']).mean() >= g.vol_filter_min:
                v.append(c)
        except: continue
    return v


def get_rank(pool):
    sv, vv = [], []
    for c in pool:
        try:
            df = attribute_history(c,g.m_days,'1d',['close'],skip_paused=True)
            if len(df) < g.m_days: continue
            y = np.log(df['close']); x = np.arange(len(y))
            sl, ic = np.polyfit(x,y,1)
            ar = math.pow(math.exp(sl),250)-1
            yp = sl*x+ic
            ssr=np.sum((y-yp)**2); sst=np.sum((y-np.mean(y))**2)
            r2 = 1-ssr/sst if sst>1e-12 else 0
            dv = np.std(np.diff(y)) if len(y)>1 else 0.01
            score = ar*r2/dv if dv>0 else ar*r2
            sv.append(score); vv.append(c)
        except: continue
    if not vv: return []
    df = pd.DataFrame(index=vv,data={'score':sv}).sort_values('score',ascending=False)
    return list(df[df['score']>g.score_min].index)

def check_market(context):
    df = attribute_history(g.benchmark_code, 200, '1d', ['close'], skip_paused=True)
    if len(df) < 66: 
        return not g.bear_mode
    close = df['close']
    ma3 = close.rolling(g.ma_short).mean()
    ma13 = close.rolling(g.ma_long).mean()
    ma_half_year = close.rolling(g.ma_half_year).mean()
    v3, v13, v120 = ma3.dropna(), ma13.dropna(),ma_half_year.dropna()
    if len(v3) < 2 or len(v13) < 2: 
        return not g.bear_mode
    p3, p13,p120 = float(v3.iloc[-2]), float(v13.iloc[-2]), float(v120.iloc[-2])
    c3, c13,c120 = float(v3.iloc[-1]), float(v13.iloc[-1]), float(v120.iloc[-1])
    
    cur_data = get_current_data()[g.benchmark_code]
    cur_price = cur_data.last_price
    yesterday_price = close.iloc[-1]
    red_line = cur_price > yesterday_price

    above3_0 = cur_price>=c3
    above3_8 = cur_price>=c3*1.08
    below3_0 = cur_price<c3
    below3_8 = cur_price<c3*(1-0.08)
    
    above13_0 = cur_price>=c13
    above13_02 = cur_price>=c13*1.02
    
    ma15_turn_up = p3<c3
    ma15_turn_dwon = p3>c3
    
    ma65_turn_dwon = p13>c13
    
    below13_0 = cur_price<c13
    below13_02 = cur_price<=c13*0.985
    through_down = cur_data.day_open>=c13
    above120_0 = cur_price>c120
    above120_15 = cur_price>=c120*1.015
    below120_0 = cur_price<c120
    below120_02 = cur_price<=c120*0.98
    
    
    through_up = cur_data.day_open<=c13
    high_too_much = cur_price > c13*1.25
    low_too_much = cur_price < c13*0.8
    if not g.ma_inited: 
        g.bear_mode = (c3 < c13)
        log.info(f"[大盘] 创业板{g.ma_inited} {c3} {c13}")
        g.ma_inited = True

    # 熊市判断
    # 3周MA下穿13周MA
    # 3日跌>5%
    # 跌破120线超2%
    # 涨超65日线20%以上
    
    # 入熊A: 3周MA下穿13周MA
    in_bear_1 = (p3 > p13 and c3 < c13)
    # 3日跌>5%
    d3 = (yesterday_price - close.iloc[-3]) / close.iloc[-3]
    in_bear_2 = d3 < -0.05
    #  5日跌>8%
    d5 = (yesterday_price - close.iloc[-6]) / close.iloc[-6] if len(close) > 5 else 0
    in_bear_3 = d5 < g.bear_d5_pct
    # 单日跌>3%
    d1 = (yesterday_price - close.iloc[-2]) / close.iloc[-2]
    in_bear_4 = d1 < g.bear_d1_pct
    
    # 跌破65日线，且跌超15日线8%以上，15日线拐头
    in_bear_5 =  below13_0 and below3_8 and ma15_turn_dwon
    # 涨超65日线20%以上, 均值回归
    in_bear_6 = high_too_much
    # 跌破120日线2%以上，65日线拐头向下
    in_bear_7 = below120_02 and ma65_turn_dwon
    if in_bear_1 or in_bear_5 or in_bear_6 or in_bear_7:
        g.bear_mode = True
        log.info(f"[大盘] 创业板 → 熊市 {in_bear_1} {in_bear_2} {in_bear_3} {in_bear_4} {in_bear_5} {in_bear_6}")
        return not g.bear_mode
    
    # 牛市判断
    # 出熊: 3周MA上穿13周MA
    out_bear_1 = (p3 < p13 and c3 > c13)
    # 超过65日线且涨超15日线8%以上 15日线拐头
    out_bear_2 =  above13_0 and above3_8 and ma15_turn_up
    # 超过120线1.5%以上 阳线
    out_bear_3 =  above120_15 and red_line
    # 在15日线上且跌幅超65日线-20%以上 熊转牛
    out_bear_4 =  low_too_much and above13_0
    # 超过65日线2%以上 阳线
    out_bear_5 =  above13_02 and red_line
    if out_bear_1 or out_bear_2 or out_bear_3 or out_bear_4 or out_bear_5:
        g.bear_mode = False
        log.info(f"[大盘] 创业板 → 牛市")
    
    log.info(f"{g.benchmark_code} 现价={cur_price} 最终结果熊市={g.bear_mode} {out_bear_1} {out_bear_2} {out_bear_3} {out_bear_4} {out_bear_5}")
    return not g.bear_mode


def can_sell(context, code):
    if code not in g.entry_dates:
        return True
    if can_not_deal(code):
        return False
    return (context.current_dt.date()-g.entry_dates[code]).days >= g.min_hold_days


def check_stop_single(context, code):
    holdings = context.portfolio.positions
    if code not in holdings:
        g.high_prices.pop(code,None)
        return
    pos = holdings[code]
    closeable_amount = pos.closeable_amount
    if closeable_amount <= 0:
        return
    px=get_current_data()[code].last_price
    g.high_prices[code]=max(g.high_prices.get(code,px),px)
    hp=g.high_prices[code]
    lp=(pos.avg_cost-px)/pos.avg_cost if pos.avg_cost>0 else 0
    if lp>g.stop_loss_pct:
        log.info(f"check_stop_single 跌幅止损卖出{code} {mingcheng(code)} 亏损={lp*100}% 阈值={g.stop_loss_pct*100}%")
        order(code,-closeable_amount)
        g.high_prices.pop(code,None); g.entry_dates.pop(code,None); g.last_rebalance.pop(code,None); return
    df=attribute_history(code,g.atr_period+1,'1d',['high','low','close'],skip_paused=True)
    if len(df)>=g.atr_period:
        h=df['high']; l=df['low']; cp=df['close'].shift(1)
        tr=pd.concat([h-l,(h-cp).abs(),(l-cp).abs()],axis=1).max(axis=1)
        mp = hp - g.atr_mult*tr.tail(g.atr_period).mean()
        if px < mp :
            log.info(f"check_stop_single 价格跌破止损卖出{code} {mingcheng(code)} 现价={px} 阈值均价={mp}")
            order(code,-closeable_amount)
            g.high_prices.pop(code,None)
            g.entry_dates.pop(code,None)
            g.last_rebalance.pop(code,None)


def check_stops(context):
    for code in list(context.portfolio.positions):
        check_stop_single(context, code)
            
    
def compute_signals(context):
    """
    第一步：判断牛熊状态，计算当日的目标持仓列表（牛市 ETF+个股，熊市清空目标）
    """
    # 更新牛熊状态（内部维护 g.bear_mode）
    check_market(context)
    bear = g.bear_mode
    if bear:
        # 熊市：无主动买入目标（安全资产在买入函数中统一处理）
        g.etf_targets = []
        g.stock_targets = []
        g.all_targets = []
    else:
        # 牛市：基于已有的周度排名（g.etf_ranking / g.stock_ranking）计算最终目标
        ve = filter_liquidity(g.etf_ranking[:10]) if g.etf_ranking else []
        vs = filter_liquidity(g.stock_ranking[:30]) if g.stock_ranking else []
        
        etf_targets = get_rank(ve)[:g.etf_num] if ve else []
        stock_targets = get_rank(vs)[:g.stock_num] if vs else []
        
        g.etf_targets = etf_targets
        g.stock_targets = stock_targets
        g.all_targets = etf_targets + stock_targets
    log.info(f"compute_signals etf_targets={g.etf_targets} stock_targets={g.stock_targets}")

def execute_sell_stop(context):
    """
    第二步：先执行全局止损检查，然后根据牛熊状态清仓不应持有的标的
    """
    # 1. 对所有持仓执行止损（基于回撤和ATR）
    # check_stops(context)
    total_value = context.portfolio.total_value
    holdings = context.portfolio.positions
    bear = g.bear_mode
    if bear:
        # 熊市：清空所有非安全资产（黄金、纳指以外的持仓）
        safe = g.safe_etfs
        for code in holdings:
            closeable_amount = holdings[code].closeable_amount
            if code not in safe and  closeable_amount > 0:
                safe_order(context, code, -closeable_amount)
                # 清理记录
                g.high_prices.pop(code, None)
                g.entry_dates.pop(code, None)
                g.last_rebalance.pop(code, None)
            elif code in safe:
                order_by_pct(context,code,g.bear_each_pct,total_value,'sell')
    else:
        # 牛市：清空安全资产（黄金、纳指）
        for code in holdings:
            closeable_amount = holdings[code].closeable_amount
            if closeable_amount > 0 and code in g.safe_etfs:
                safe_order(context, code, -closeable_amount)
                g.high_prices.pop(code, None)
                g.entry_dates.pop(code, None)
        
        # 清仓不在目标列表中的其他持仓（需满足最短持有期）
        all_targets = g.all_targets if hasattr(g, 'all_targets') else []
        for code in holdings:
            closeable_amount = holdings[code].closeable_amount
            if code not in all_targets and closeable_amount > 0:
                # 标普500可随时卖出，其他需持有满 g.min_hold_days 天
                if code == g.sp500_etf or can_sell(context, code):
                    safe_order(context, code, -closeable_amount)
                    g.high_prices.pop(code, None)
                    g.entry_dates.pop(code, None)
                    g.last_rebalance.pop(code, None)
        # 需要卖出的再平衡
        rebalance(context,g.etf_targets,g.etf_pct,'sell')
        rebalance(context,g.stock_targets,g.stock_pct,'sell')
        
def safe_order(context,code,amount):
    style = None
    if can_not_deal(code):
        return
    if code[:2]=='68':
        px = get_current_data()[code].last_price
        ratio = px*(1+0.015) if amount > 0 else px*(1-0.015)
        style = MarketOrderStyle(ratio)
    order(code, amount,style=style)
    
def safe_order_target_value(context,side,code,value):
    style = None
    if can_not_deal(code):
        return
    if code[:2]=='68':
        px = get_current_data()[code].last_price
        ratio = px*(1+0.015) if side == 'buy' else px*(1-0.015)
        style = MarketOrderStyle(px*1.015)
    order_target_value(code, value,style=style)
    
def rebalance(context,targets,pct,side='buy'):
    today = context.current_dt.date()
    total_value = context.portfolio.total_value
    holdings = context.portfolio.positions
    for code in targets:
        ld = g.last_rebalance.get(code)
        if ld and (today - ld).days < g.rebalance_freq_days:
            continue
        if code not in holdings:
            continue
        pos = holdings[code]
        px = get_current_data()[code].last_price
        tv = total_value * pct
        if px > 0 and abs(pos.value - tv) / tv > 0.2:
            log.info(f"仓位平衡 {side} {code}({mingcheng(code)}) pct={pct} 目标市值{total_value} 现有市值{pos.value}")
            order_by_pct(context, code, pct, total_value , side)
            g.last_rebalance[code] = today
        
def execute_buy(context):
    """
    第三步：根据牛熊状态买入目标标的，并进行再平衡和现金管理
    """
    # log.info(f"execute_buy {datetime.datetime.now()}")
    total_value = context.portfolio.total_value
    bear = g.bear_mode
    holdings = context.portfolio.positions
    if bear:
        # 熊市：将资金平均分配到黄金和纳指（各50%）
        for code in g.safe_etfs:
            order_by_pct(context,code,g.bear_each_pct,total_value,'buy')
    else:
        etf_targets = g.etf_targets if hasattr(g, 'etf_targets') else []
        stock_targets = g.stock_targets if hasattr(g, 'stock_targets') else []
        
        # ① 买入尚未持仓的目标标的
        for code in etf_targets:
            if code not in holdings:
                order_by_pct(context, code, g.etf_pct, total_value , 'buy')
        for code in stock_targets:
            if code not in holdings:
                order_by_pct(context, code, g.stock_pct, total_value , 'buy')
        
        # ② 再平衡：对已有目标持仓，若偏离目标比例超20%且距上次调仓≥20天，则调整至目标仓位
        rebalance(context,etf_targets,g.etf_pct,'buy')
        rebalance(context,stock_targets,g.stock_pct,'buy')
        
        # ③ 现金管理：若现金超过总资产10%，将超出部分买入标普500ETF
        cash = context.portfolio.cash
        tv2 = context.portfolio.total_value
        if tv2 > 0 and cash / tv2 > 0.10:
            excess = cash - tv2 * 0.10
            px = get_current_data()[g.sp500_etf].last_price
            if px and px > 0:
                s = int(excess / px / 100) * 100
                if s >= 100:
                    order(g.sp500_etf, s)
                    g.high_prices[g.sp500_etf] = px


def mingcheng(stock):
    try: return get_security_info(stock).display_name
    except: return stock

