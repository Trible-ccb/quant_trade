# 克隆自聚宽文章：https://www.joinquant.com/post/74563
# 标题：全球宽基ETF轮动策略（实*策略）
# 作者：lucas3060

# ============================================================
# 策略名称：全球宽基ETF轮动策略 V1.2
# 平台：聚宽 JoinQuant
#
# 策略来源：
#   克隆自：https://www.joinquant.com/post/42673
#   标题：【回顾3】ETF策略之核心资产轮动
#   作者：wywy1995
#
# 运行逻辑（一句话）：
#   每天11:00，对ETF池中19只标的逐一计算动量得分，
#   选得分最高的一只全仓买入，其他全部卖出。
#
# 动量得分计算：
#   取最近25个交易日收盘价+当日价格，做对数变换，
#   用加权线性回归（近端权重更高）拟合趋势线，
#   得分 = 年化收益率 × R²（趋势越陡+越稳定，得分越高）。
#   同时加了一道保护：近3天有任何一天跌幅超过5%，得分直接归零。
#
# V1.2 优化内容：
#   1. 标的改造 — 从"A股行业ETF"改为"跨市场全球宽基"，
#      覆盖境外5只+商品5只+债券/货币2只+港股2只+A股宽基5只，
#      共19只低相关标的（核心改动，部分同市场的ETF相关性还是较高，可以继续精简）。
#   2. 日志优化 — ETF得分排名表格化输出。
#   3. 优化了代码执行效率。
# ==================== 参数调整区域开始 ====================

# ----- 策略基本参数 -----
STRATEGY_PARAMS = {
    'stock_sum': 1,      # 持仓ETF数量
    'm_days': 25,        # 动量参考天数
    'min_money': 500,    # 最小交易金额（低于此金额不交易）
}

# ----- ETF池（v1.2 修订：19只，不包含行业主题ETF）-----
ETF_POOL = [
    # ── 境外 ──
    "513100.XSHG",  # 纳指ETF
    "513500.XSHG",  # 标普500ETF
    "159509.XSHE",  # 纳指科技ETF
    "513520.XSHG",  # 日经ETF
    "513030.XSHG",  # 德国ETF
    # ── 商品 ──
    "518880.XSHG",  # 黄金ETF
    "159980.XSHE",  # 有色ETF
    "159985.XSHE",  # 豆粕ETF
    "159981.XSHE",  # 能源化工ETF
    "501018.XSHG",  # 南方原油
    # ── 债券/货币 ──
    "511090.XSHG",  # 30年国债ETF
    "511360.XSHG",  # 短融ETF
    # ── 香港 ──
    "513130.XSHG",  # 恒生科技
    "513690.XSHG",  # 港股红利
    # ── 国内宽基 ──
    # "510180.XSHG",  # 上证180
    # "159922.XSHE",  # 中证500ETF
    # "159531.XSHE",  # 中证2000ETF
    # "159915.XSHE",  # 创业板ETF
    # "588080.XSHG",  # 科创板50ETF
]
# ==================== 风险控制参数（新增） ====================
RISK_PARAMS = {
    'take_profit': 0.03,      # 止盈阈值（+5%）
    'stop_loss': -0.05,       # 止损阈值（-5%）
    'max_hold_days': 20,      # 最大持仓天数（可选，防止长期横盘）
}
# ----- 过滤条件 -----
FILTER_PARAMS = {
    'max_score': 6,           # score 上限（超出归零）
    'min_score': 0,           # score 下限
    'drop_threshold': 0.95,   # 近3日跌幅阈值（<0.95 的 score 归零）
    'r2_weight': True,        # 是否用 R² 加权年化收益作为 score
}

# ----- 交易参数 -----
TRADE_PARAMS = {
    'adjust_sell_time': "11:00",     # 调仓，卖出执行时间
    'adjust_buy_time': "11:01",     # 买入执行时间
    'end_trade_time': "14:55",  # 尾盘处理时间
    'slippage_fund': 0.0001,   # 基金滑点
    'slippage_stock': 0.003,   # 股票滑点
    'commission': 0.0003,      # 佣金
    'tax': 0.001,              # 印花税
}
# ==================== 参数调整区域结束 ====================

import math

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

def before_trading_start(context):
    try:
        if 'sim_trade' != context.run_params.type:
            return
        ok = bt_wrapper.qmt_is_ok()
        if not ok:
            send_message("QMT服务端异常，检查云服务器是否正常登录qmt")
    except Exception as e:
        print(f"before_trading_start检查qmt异常")
        
# =======================实盘配置End=======================================

# ============================================================
# 运行调度函数
# ============================================================
# ==================== 修改 initialize 增加全局状态 ====================
def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    log.info("【反向版】ETF轮动V1.2 启动（19只ETF池）")
    log.set_level('order', 'warning')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')

    # 滑点 & 交易成本（保持原样）
    set_slippage(FixedSlippage(TRADE_PARAMS['slippage_fund']), type="fund")
    set_slippage(FixedSlippage(TRADE_PARAMS['slippage_stock']), type="stock")
    set_order_cost(OrderCost(open_tax=0, close_tax=TRADE_PARAMS['tax'],
                             open_commission=TRADE_PARAMS['commission'],
                             close_commission=TRADE_PARAMS['commission'],
                             close_today_commission=0, min_commission=5), type="stock")
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=1/10000,
                             close_commission=1/10000,
                             close_today_commission=0, min_commission=5), type="fund")
    set_order_cost(OrderCost(open_tax=0, close_tax=0,
                             open_commission=0, close_commission=0,
                             close_today_commission=0, min_commission=0), type="mmf")

    # --- 全局状态 ---
    g.positions = {0:{}}
    g.virtual_holdings = []      # 原策略虚拟持仓
    g.candidate_pool = set()     # 候选买入池
    g.candidate_time = {}        # 候选加入时间
    g.entry_price = {}           # 记录每只标的的开仓价 {code: price}
    g.buy_date = {}              # 记录买入日期 {code: date}

    # 创建策略对象（仅作信号源）
    g.strategy = Etf_Rotation_Strategy(context, index=0, name="信号源")

    # 注册定时任务
    run_daily(rotation_signal, '14:50')  # 11:00 处理信号&买入
    run_daily(do_buy, '14:51')            
    run_daily(check_stop_profit_loss, "14:52")                    # 14:45 检查止盈止损


# ============================================================
# 模块级函数
# ============================================================

# ==================== 重写 rotation_sell（核心反向逻辑） ====================
def rotation_signal(context):
    """
    11:00 执行：仅更新候选池，不执行任何买入操作
    """
    # ----- 1. 获取原策略信号 -----
    candidates = g.strategy.filter()
    stock_sum = STRATEGY_PARAMS['stock_sum']
    new_virtual = candidates[:stock_sum]
    old_virtual = g.virtual_holdings

    # ----- 2. 原策略拟买入 -> 加入候选池 -----
    to_buy = [s for s in new_virtual if s not in old_virtual]
    for s in to_buy:
        if s not in g.candidate_pool:
            g.candidate_pool.add(s)
            g.candidate_time[s] = context.current_dt
            log.info(f"[候选池] 加入 {s}")

    # ----- 3. 候选池过期清理（保留5天） -----
    from datetime import timedelta
    expire_time = context.current_dt - timedelta(days=15)
    for s, t in list(g.candidate_time.items()):
        if t < expire_time:
            g.candidate_pool.discard(s)
            del g.candidate_time[s]
            log.info(f"[候选池] 移除过期标的 {s}")

    # ----- 4. 更新虚拟持仓（供下次判断使用） -----
    g.virtual_holdings = new_virtual

def check_stop_profit_loss(context):
    """
    14:45 执行：
    检查当前真实持仓的盈亏，触发止盈或止损则清仓。
    """
    current_real = list(g.positions[0].keys())
    if not current_real:
        return

    stock = current_real[0]  # 策略只持有一只
    pos = context.portfolio.positions.get(stock)
    if not pos or pos.closeable_amount <= 0:
        return

    # 计算盈亏比例
    current_price = pos.price
    avg_cost = pos.avg_cost
    pnl_pct = (current_price / avg_cost) - 1

    # 获取持仓天数（辅助判断，可选项）
    hold_days = 0
    if stock in g.buy_date:
        hold_days = (context.current_dt.date() - g.buy_date[stock]).days

    log.info(f"[持仓监控] {stock} 盈亏: {pnl_pct:.2%} (持仓{hold_days}天)")

    # ----- 触发止盈/止损 -----
    take_profit = RISK_PARAMS['take_profit']
    stop_loss = RISK_PARAMS['stop_loss']

    if pnl_pct >= take_profit:
        log.info(f"[止盈触发] {stock} 盈利 {pnl_pct:.2%} >= {take_profit:.2%}，清仓")
        g.strategy._order_to_target(stock, 0)
        # 清理记录
        _clean_position_record(stock)

    elif pnl_pct <= stop_loss:
        log.info(f"[止损触发] {stock} 亏损 {pnl_pct:.2%} <= {stop_loss:.2%}，清仓")
        g.strategy._order_to_target(stock, 0)
        _clean_position_record(stock)

    # （可选）最大持仓天数保护
    elif hold_days > RISK_PARAMS.get('max_hold_days', 999):
        log.info(f"[时间止损] {stock} 持仓{hold_days}天，超时清仓")
        g.strategy._order_to_target(stock, 0)
        _clean_position_record(stock)

def _clean_position_record(stock):
    """清仓后清理记录"""
    if stock in g.entry_price:
        del g.entry_price[stock]
    if stock in g.buy_date:
        del g.buy_date[stock]
    if stock in g.candidate_pool:
        g.candidate_pool.discard(stock)

# ==================== do_buy 置空（所有交易已在 rotation_sell 完成） ====================
def do_buy(context):
    """
    11:01 执行买入逻辑（独立于候选池维护）
    1. 从候选池中筛选跌幅超过 -5% 的标的（相对5个交易日前收盘价）
    2. 按跌幅从大到小排序
    3. 用可用资金等权买入
    4. 买入前清空所有现有持仓（实现换仓）
    """
    # ----- 1. 检查候选池 -----
    if not g.candidate_pool:
        log.debug("[买入] 候选池为空，跳过")
        return

    candidates = list(g.candidate_pool)
    current_data = get_current_data()
    buy_list = []

    # ----- 2. 计算跌幅并筛选 -----
    for etf in candidates:
        try:
            # ----- 新增：时间过滤，加入时间需 > 1天 -----
            if etf not in g.candidate_time:
                continue
            add_time = g.candidate_time[etf]
            if (context.current_dt - add_time).days < 1:   # 至少隔日
                log.debug(f"[买入] {etf} 加入候选池不足1天，跳过")
                continue
            # 获取过去5个交易日数据（含今日？不含今日，用 attribute_history 取前5天）
            hist = attribute_history(etf, 20, '1d', ['close'])
            if len(hist) < 20:
                log.debug(f"[买入] {etf} 历史数据不足7天，跳过")
                continue
            # 5个交易日前收盘价（最早一天）
            ma20 = hist['close'].rolling(20).mean().iloc[-1]
            ma5 = hist['close'].rolling(5).mean().iloc[-1]
            current_price = current_data[etf].last_price
            lower_ma20 = current_price<ma20
            drop_pct = (current_price - ma5) / ma5  # 负值表示下跌
            log.info(f"{etf}当前跌幅{drop_pct:.2%} lower_ma20={lower_ma20}")
            if drop_pct <= -0.1 or lower_ma20:
                buy_list.append((etf, drop_pct))
        except Exception as e:
            log.warning(f"[买入] 计算 {etf} 跌幅失败：{e}")

    if not buy_list:
        log.debug("[买入] 无符合跌幅条件的标的")
        return

    # ----- 3. 按跌幅从大到小排序（跌幅越负越靠前） -----
    buy_list.sort(key=lambda x: x[1])   # 从小到大（即跌幅最大）

    # ----- 4. 清空当前所有持仓 -----
    current_real = list(g.positions[0].keys())
    for stock in current_real:
        # 如果该标的已在待买列表中，为避免重复卖出再买，这里先全部清空
        g.strategy._order_to_target(stock, 0)
        log.info(f"[换仓] 清仓 {stock}")

    # ----- 5. 等权分配可用资金 -----
    total_cash = context.portfolio.available_cash
    if total_cash <= 0:
        log.warning("[买入] 可用资金为0，无法买入")
        return

    per_target = total_cash / len(buy_list)
    min_money = STRATEGY_PARAMS['min_money']

    for etf, drop in buy_list:
        if per_target < min_money:
            log.info(f"[买入] {etf} 分配金额 {per_target:.2f} < {min_money}，跳过")
            continue
        # 执行买入（目标市值 = per_target）
        success = g.strategy._order_to_target(etf, per_target)
        if success:
            log.info(f"[买入] {etf} 跌幅 {drop:.2%}，目标市值 {per_target:.2f}")
            # 记录开仓价与买入日期（用于止盈止损）
            g.entry_price[etf] = current_data[etf].last_price
            g.buy_date[etf] = context.current_dt.date()

            # ----- 6. 从候选池中移除已买入的标的（防止重复） -----
            g.candidate_pool.remove(etf)
            if etf in g.candidate_time:
                del g.candidate_time[etf]   
        else:
            log.warning(f"[买入] {etf} 下单失败")




# ============================================================
# 策略实现
# ============================================================

class Etf_Rotation_Strategy:
    """核心资产轮动策略：动量评分 → 选Top N → 等权调仓"""

    def __init__(self, context, index, name):
        self.context = context
        self.index = index
        self.name = name
        self.etf_pool = ETF_POOL
        self.hold_list = []

    # ------------------------------------------------------------------
    # 评分 & 选股
    # ------------------------------------------------------------------

    def filter(self):
        """计算ETF池中每只标的的动量得分，返回排序后代码列表"""
        m_days = STRATEGY_PARAMS['m_days']
        r2_weight = FILTER_PARAMS['r2_weight']
        drop_threshold = FILTER_PARAMS['drop_threshold']
        min_score = FILTER_PARAMS['min_score']
        max_score = FILTER_PARAMS['max_score']

        data = pd.DataFrame(
            index=self.etf_pool,
            columns=["annualized_returns", "r2", "score"]
        )
        current_data = get_current_data()

        # 逐ETF评分
        for etf in self.etf_pool:
            df = attribute_history(etf, m_days, "1d", ["close", "high"])
            prices = np.append(df["close"].values, current_data[etf].last_price)

            y = np.log(prices)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))  # 近端权重更高

            slope, _ = np.polyfit(x, y, 1, w=weights)
            annual_ret = math.exp(slope * 250) - 1
            data.loc[etf, "annualized_returns"] = annual_ret

            ss_res = np.sum(weights * (y - np.polyval([slope, _], x)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            data.loc[etf, "r2"] = r2

            score = annual_ret * r2 if r2_weight else annual_ret
            data.loc[etf, "score"] = score

            # 近3日存在大幅下跌 → 得分归零
            if min(prices[-1] / prices[-2],
                   prices[-2] / prices[-3],
                   prices[-3] / prices[-4]) < drop_threshold:
                data.loc[etf, "score"] = 0

        # 打印全量得分表
        try:
            scored = []
            for etf in self.etf_pool:
                name = current_data[etf].name
                s = data.loc[etf, "score"]
                sort_key = s if isinstance(s, (int, float)) and s == s else float("-inf")
                scored.append((etf, name, s, sort_key))
            scored.sort(key=lambda x: x[3], reverse=True)

            lines = ["──── ETF 得分排名（全量）────"]
            lines.append(f"{'代码':<14s} {'名称':<12s} {'得分':>8s}")
            lines.append("─" * 40)
            for code, name, s, _ in scored:
                s_str = f"{float(s):.4f}" if isinstance(s, (int, float)) else "NaN"
                lines.append(f"{code:<14s} {name:<12s} {s_str:>8s}")
            # log.info("\n".join(lines))
        except Exception as e:
            log.error(f"打印ETF得分列表失败：{e}")

        # 过滤并排序
        data = data.query(f"{min_score} < score < {max_score}")
        data = data.sort_values(by="score", ascending=False)
        return data.index.tolist()

    # ------------------------------------------------------------------
    # 调仓执行
    # ------------------------------------------------------------------

    def adjust(self):
        """选Top N → 等权调仓"""
        stock_sum = STRATEGY_PARAMS['stock_sum']
        candidates = self.filter()
        targets = candidates[:stock_sum]

        if not targets:
            log.info("无符合条件的ETF，跳过调仓")
            return

        weight = round(1.0 / len(targets), 4)
        target_map = {etf: weight for etf in targets}

        log.info(f"调仓目标: {', '.join(t + '(' + str(w) + ')' for t, w in target_map.items())}")
        self._adjust_sell(target_map)
        return target_map

    def _adjust_sell(self, targets):
        """执行调仓：先卖，等权分配"""
        current_data = get_current_data()
        min_money = STRATEGY_PARAMS['min_money']
        portfolio = self.context.portfolio

        self.hold_list = list(g.positions[self.index].keys())
        target_value = portfolio.total_value

        # 清仓被调出的
        for stock in self.hold_list:
            if stock not in targets:
                self._order_to_target(stock, 0)

        # 先卖后买
        for stock, weight in targets.items():
            target_val = target_value * weight
            price = current_data[stock].last_price
            current_val = g.positions[self.index].get(stock, 0) * price

            if current_val - target_val > max(min_money, price * 100):
                self._order_to_target(stock, target_val) 
    
    def adjust_buy(self, targets):
        """执行调仓：后买，等权分配"""
        current_data = get_current_data()
        min_money = STRATEGY_PARAMS['min_money']
        portfolio = self.context.portfolio

        self.hold_list = list(g.positions[self.index].keys())
        target_value = portfolio.total_value

        for stock, weight in targets.items():
            target_val = target_value * weight
            price = current_data[stock].last_price
            current_val = g.positions[self.index].get(stock, 0) * price
            gap = target_val - current_val

            if min(gap, portfolio.available_cash) > max(min_money, price * 100):
                self._order_to_target(stock, target_val)   
    

    # ------------------------------------------------------------------
    # 下单封装
    # ------------------------------------------------------------------

    def _order_to_target(self, security, target_value):
        """以目标市值为导向下单，处理停牌/涨跌停/100股取整"""
        current_data = get_current_data()

        if current_data[security].paused:
            log.info(f"{security} 停牌，跳过")
            return False
        last_price = current_data[security].last_price
        if last_price == current_data[security].high_limit:
            log.info(f"{security} 涨停，跳过")
            return False
        if last_price == current_data[security].low_limit:
            log.info(f"{security} 跌停，跳过")
            return False

        current_shares = g.positions[self.index].get(security, 0)
        target_shares = (int(target_value / last_price) // 100) * 100 if last_price > 0 else 0
        delta = target_shares - current_shares

        if delta == 0:
            return False

        closeable = (self.context.portfolio.positions[security].closeable_amount
                     if security in self.context.portfolio.positions else 0)
        if delta < 0 and closeable == 0:
            log.info(f"{security} 当日买入不可卖出，跳过")
            return False

        order_obj = order(security, delta)
        if order_obj:
            filled = order_obj.filled if order_obj.is_buy else -order_obj.filled
            g.positions[self.index][security] = filled + current_shares
            if g.positions[self.index][security] == 0:
                g.positions[self.index].pop(security, None)
            self.hold_list = list(g.positions[self.index].keys())
            return True
        return False


# ============================================================
# 收盘统计
# ============================================================

def after_trading_end(context):
    """收盘后输出当日的持仓与盈亏"""
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(context.portfolio.positions)
    total_value = context.portfolio.total_value
    cash = context.portfolio.available_cash
    log.info("─" * 45)
    log.info(f"收盘 {context.current_dt.date()}  总资产={total_value:.0f}  现金={cash:.0f}")
    for code, pos in context.portfolio.positions.items():
        pnl = (pos.price / pos.avg_cost - 1) * 100 if pos.avg_cost else 0
        log.info(f"  {code}  {pos.total_amount}股  均价={pos.avg_cost:.3f}  现价={pos.price:.3f}  盈亏={pnl:+5.2f}%")
    log.info("─" * 45)
