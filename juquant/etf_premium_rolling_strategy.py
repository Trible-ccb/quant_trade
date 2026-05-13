# 克隆自聚宽文章：https://www.joinquant.com/post/69301的评论
# 标题：7年收益30倍、回测16.4%、单仓位的稳健ETF轮动策略
# 作者：陨石对撞测试

# 导入必要的库
from jqdata import *

# =======================实盘配置Start=======================================

import bullet_trade_jq_wrapper as bt_wrapper
import datetime

# 默认下单函数
TRADE_TYPE = 'live_no_buy'  # 'live':实盘模式,live_no_buy:实盘下单但不真实买入,其他值：用聚宽平台默认下单函数
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

# ===== 策略配置区域 =====
ETF_COUNT=10 # 每次选取折价率最大的前n只ETF进行交易
MAX_PER_ETF = 50000 # 每只ETF的最大投资金额，避免过度集中
MIN_MONEY=2e7 # 成交额下限，过滤掉过于冷门的ETF
MAX_MONEY=5e7 # 成交额上限，过滤掉过于热门的ETF，避免过度竞争和滑点
TAX_RATE = 0.00005 # 买入佣金率，假设为万分之0.5，实际根据券商费率调整
MIN_TAX = 5 # 最小佣金，假设为5元，实际根据券商费率调整
SLIPPAGE_RATE = 0.002 # 滑点率，假设为千分之二，实际根据市场情况调整

def initialize(context):
    """
    初始化函数，设定策略参数
    """
    # 设置日志级别
    log.set_level('system', 'error')
    set_option('order_volume_ratio', 0.2)

    # 避免使用未来数据
    set_option("avoid_future_data", True)
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式（真实价格）
    set_option('use_real_price', True)
    # 设置交易成本
    set_order_cost(OrderCost(close_tax=0.000, open_commission=TAX_RATE, 
                            close_commission=TAX_RATE, min_commission=MIN_TAX), 
                  type='fund')
    # 设置滑点
    set_slippage(FixedSlippage(SLIPPAGE_RATE))  # 设置固定滑点为0.1%
    
    # 每天09:20运行before_market_open函数
    run_daily(before_market_open, '09:20', reference_security='000300.XSHG')
    # 每天09:25运行process_after_auction函数（集合竞价结束，开盘价确定，计算交易信号）
    run_daily(process_after_auction, '09:27', reference_security='000300.XSHG')
    # 每天09:30运行market_open函数（执行交易）
    run_daily(market_open, '09:30', reference_security='000300.XSHG')
    
    # 初始化全局变量
    g.selected_funds_data = None  # 存储筛选后的基金数据
    g.hold_list = []  # 继续持有的ETF
    g.buy_list = []   # 需要买入的ETF
    g.sell_list = []  # 需要卖出的ETF
    g.target_values = {}  # 需要买入的目标市值
    g.trading_plan = None  # 交易计划

def before_market_open(context):
    """
    09:20运行 - 数据准备阶段
    """
    try:
        # 获取所有ETF基金
        fund_list = get_all_securities(['etf'], context.previous_date).index.tolist()

        # 获取历史数据
        high_df = history(count=1, unit='1d', field="high", security_list=fund_list).T
        low_df = history(count=1, unit='1d', field="low", security_list=fund_list).T
        volume_df = history(count=1, unit='1d', field="money", security_list=fund_list).T

        # 合并数据
        df = high_df.merge(low_df, left_index=True, right_index=True)
        df = df.merge(volume_df, left_index=True, right_index=True)
        df.columns = ['high_price', 'low_price', 'money']

        # 过滤成交额在500万到2000万之间的ETF
        df = df[(df['money'] < MAX_MONEY) & (df['money'] > MIN_MONEY)]
        
        if df.empty:
            log.warning("没有符合条件的ETF基金（成交额500万-2000万）")
            g.selected_funds_data = None
            return

        # 获取单位净值
        unit_net_df = get_extras('unit_net_value', df.index.tolist(), 
                                end_date=context.previous_date, df=True, count=1).T
        unit_net_df.columns = ['unit_net_value']
        
        # 合并净值数据
        df = df.merge(unit_net_df, left_index=True, right_index=True)

        # 存储筛选后的基金数据到全局变量
        g.selected_funds_data = df
        log.info(f"数据准备完成，粗筛选出{len(df)}只ETF基金")
        
    except Exception as e:
        log.error(f"before_market_open异常: {e}")
        g.selected_funds_data = None

def process_after_auction(context):
    """
    09:25运行 - 集合竞价结束，使用开盘价计算交易信号
    仅计算信号，不执行交易
    """
    try:
        # 清空之前的交易信号
        g.hold_list = []
        g.buy_list = []
        g.sell_list = []
        g.target_values = {}
        
        # 检查是否有准备好的数据
        if g.selected_funds_data is None or g.selected_funds_data.empty:
            log.warning("没有准备好的基金数据，无法计算交易信号")
            return
        
        df = g.selected_funds_data.copy()
        current_data = get_current_data()
        
        # 获取当前持仓列表
        current_positions = list(context.portfolio.positions.keys())
        buy_price_dict = {}
        
        # 使用开盘价并过滤掉停牌的
        valid_funds = []
        open_prices = []
        for fund in df.index.tolist():
            if not current_data[fund].paused:  # 排除停牌的
                today_call = get_call_auction(fund, context.current_dt, context.current_dt)
                open_price = None
                if today_call.empty:
                    log.warning(f"{fund}没有{context.current_dt}集合竞价数据")
                else:
                    open_price = today_call['current'].iloc[-1]
                    
                if open_price is not None and open_price > 0:
                    valid_funds.append(fund)
                    open_prices.append(open_price)
                    buy_price_dict[fund] = open_price
        
        if len(valid_funds) == 0:
            log.warning("没有有效的ETF可以交易")
            return
            
        df = df.loc[valid_funds].copy()
        df['open_price'] = open_prices

        # 计算溢价率（实际为折价率）
        df['premium'] = (df['open_price'] / df['unit_net_value'] - 1) * 100

        # 按折价率排序并过滤折价ETF（premium<0）
        df = df.sort_values(['premium'], ascending=True)
        df = df[df['premium'] < 0]

        # 选择折价率最大的前n只ETF
        selected_funds = df.head(ETF_COUNT)
        order_fund = selected_funds.index.tolist()
        
        # 分类持仓
        hold_list = []  # 已在持仓中且继续持有
        buy_list = []   # 需要新买入
        sell_list = []  # 需要卖出
        
        # 确定卖出列表：在当前持仓中但不在选中列表中的
        for fund in current_positions:
            if fund not in order_fund:
                sell_list.append(fund)
        
        # 确定持有和买入列表
        for fund in order_fund:
            if fund in current_positions:
                hold_list.append(fund)
            else:
                buy_list.append(fund)
        
        # 计算预期卖出总资金
        expected_sale_value = 0
        for fund in sell_list:
            position = context.portfolio.positions[fund]
            open_price = current_data[fund].day_open if not current_data[fund].paused else position.price
            expected_sale_value += position.total_amount * open_price
        
        # 当前可用资金
        current_cash = context.portfolio.available_cash
        
        # 预期总可用资金（当前现金 + 卖出预期收入）
        expected_total_cash = current_cash + expected_sale_value
        
        # 计算权重分配（使用折价率绝对值作为权重）
        weights = selected_funds['premium'].abs().tolist()  # 取绝对值计算权重
        total_weight = sum(weights) if sum(weights) > 0 else 1
        
        # 计算目标市值并存储 - 基于预期总资金
        target_values = {}
        for fund, weight in zip(order_fund, weights):
            target_value = expected_total_cash * (weight / total_weight)
            target_values[fund] = target_value
        
        # 更新全局变量
        g.hold_list = hold_list
        g.buy_list = buy_list
        g.sell_list = sell_list
        g.target_values = target_values
        
        # 创建交易计划
        g.trading_plan = {
            'signal_time': context.current_dt,
            'selected_funds': order_fund,
            'sell_list': sell_list,
            'buy_list': buy_list,
            'buy_price_dict':buy_price_dict,
            'hold_list': hold_list,
            'target_values': target_values,
            'selected_funds_df': selected_funds[['open_price', 'unit_net_value', 'premium']],
            'expected_total_cash': expected_total_cash,
            'weights': weights,
            'total_weight': total_weight
        }
        
        # 输出交易信号
        log.info(f"✅ 09:25 交易信号生成 @ {context.current_dt}")
        if not df.empty:
            log.info(f"📈 折价率统计 - 最小: {df['premium'].min():.2f}%,最大: {df['premium'].max():.2f}%, 平均: {df['premium'].mean():.2f}%")
        log.info(f"🎯 选中基金数量：{len(order_fund)}只,当前现金: {current_cash:.2f}元,预期卖出收入: {expected_sale_value:.2f}元,预期总资金: {expected_total_cash:.2f}元")
        # 输出持仓分类
        log.info(f"📋 持仓分类：继续持有({len(hold_list)}只),需要买入({len(buy_list)}只)，需要卖出({len(sell_list)}只)")
        
        # 详细列出每只基金的操作类型
        if order_fund:
            # 列出选中的基金信息
            for i, (fund, row) in enumerate(selected_funds.iterrows(), 1):
                detail_txt = f"    {i}. {fund}:开盘价: {row['open_price']:.3f}, 净值: {row['unit_net_value']:.3f}，折价率: {row['premium']:.2f}%"
                if fund in hold_list:
                    position = context.portfolio.positions[fund]
                    position_value = position.total_amount * position.price
                    detail_txt += f"，继续持有,当前持仓: {position.total_amount}股，市值: {position_value:.2f}元"
                elif fund in buy_list:
                    detail_txt += f"，需要买入,目标市值: {target_values[fund]:.2f}元"
                log.info(f"{detail_txt}")
            
            # 列出需要卖出的持仓（不在选中列表中）
            if sell_list:
                for i, fund in enumerate(sell_list, 1):
                    position = context.portfolio.positions[fund]
                    position_value = position.total_amount * position.price
                    cost_basis = position.avg_cost
                    current_price = position.price
                    profit_pct = ((current_price - cost_basis) / cost_basis * 100) if cost_basis > 0 else 0
                    open_price = current_data[fund].day_open if hasattr(current_data[fund], 'day_open') else current_price
                    log.info(f"    {i}. {fund}: 需要卖出 {position.total_amount}股，当前市值: {position_value:.2f}元，开盘价: {open_price:.3f}元,盈亏: {profit_pct:.1f}%")
            
        log.info("ℹ️  交易信号已生成，将在09:30以市价单执行")

    except Exception as e:
        log.error(f"process_after_auction异常: {e}")
        g.trading_plan = None

def market_open(context):
    """
    09:30运行 - 执行交易，使用市价单
    """
    try:
        log.info(f"⏰ 09:30 开始执行交易 @ {context.current_dt}")
        
        # 检查是否有交易计划
        if g.trading_plan is None:
            log.warning("没有交易计划，无法执行交易")
            return
        
        # 获取当前市场数据
        current_data = get_current_data()
        
        # 1. 执行卖出操作 - 使用最简单的直接方式
        sell_list = g.trading_plan['sell_list']
        
        if sell_list:
            log.info(f"📤 开始执行卖出操作 ({len(sell_list)}只)")
            
            for i, fund in enumerate(sell_list, 1):
                try:
                    # 检查是否停牌
                    if current_data[fund].paused:
                        log.warning(f"  {i}. {fund} 停牌，无法卖出，跳过")
                        continue
                    
                    # 获取持仓信息
                    position = context.portfolio.positions[fund]
                    
                    if position.total_amount == 0:
                        log.warning(f"  {i}. {fund} 持仓为0，无需卖出")
                        continue
                    
                    # 获取当前价格
                    current_price = current_data[fund].last_price
                    if current_price is None or current_price <= 0:
                        current_price = position.price
                    
                    # 获取持仓数量
                    sell_amount = position.total_amount
                    money = sell_amount * current_price

                    # 最简单的卖出方式：直接卖出所有持仓
                    # 使用负号表示卖出
                    order_info = order(fund, -sell_amount)
                    if order_info is None:
                        log.warning(f"  {i}. {fund} 卖出订单未成功创建")
                        continue

                    order_id = order_info.order_id
                    status = order_info.status
                    commission = order_info.commission if hasattr(order_info, 'commission') else 0
                    # 实际平均成交价（聚宽order对象包含）
                    fill_price = order_info.price
                    # 成交数量
                    filled_amount = order_info.filled
                    # 滑点：(实际价 - 基准价) × 数量
                    slippage = (abs(fill_price - current_price)  * 100) / current_price
                    slippage_cost = (current_price - fill_price) * filled_amount
                    total_money = fill_price * filled_amount
                    log.info(f"  {i}. {fund}: 计划卖出 {sell_amount}股，卖价: {current_price:.3f}元，回笼资金：{money:.2f}元"
                             f" 实际订单{order_id} 状态{status}"
                             f"成交价{fill_price},成交量{filled_amount}股(回笼：{total_money:.2f}元),税费：{commission:.2f},滑点: {slippage:.3f}%, 滑点成本: {slippage_cost:.2f}元")
                    
                except Exception as e:
                    log.error(f"  {i}. 卖出 {fund} 失败: {e}")
        else:
            log.info("📤 没有需要卖出的持仓")
        
        # 2. 执行买入操作
        buy_list = g.trading_plan['buy_list']
        
        if buy_list:
            # 获取实际可用资金
            available_cash = context.portfolio.available_cash
            log.info(f"💰 当前可用资金: {available_cash:.2f}元")
            
            if available_cash < 100:
                log.warning("可用资金不足，跳过买入操作")
                return
            
            # 使用交易计划中的权重
            weights = g.trading_plan['weights']
            total_weight = g.trading_plan['total_weight']
            
            log.info(f"📥 开始执行买入操作 ({len(buy_list)}只)")
            
            # 计算每只基金的目标市值（按权重分配）
            total_target_value = 0
            buy_targets = {}
            
            for fund, weight in zip(buy_list, weights):
                target_value = available_cash * (weight / total_weight)
                if target_value > MAX_PER_ETF:
                    target_value = MAX_PER_ETF
                buy_targets[fund] = target_value
                total_target_value += target_value
            
            # 如果总目标市值超过可用资金，按比例调整
            if total_target_value > available_cash:
                adjustment_ratio = available_cash / total_target_value
                for fund in buy_targets:
                    buy_targets[fund] *= adjustment_ratio
            
            # 执行买入
            for i, fund in enumerate(buy_list, 1):
                try:
                    # 检查是否停牌
                    if current_data[fund].paused:
                        log.warning(f"  {i}. {fund} 停牌，无法买入，跳过")
                        continue
                    
                    # 获取当前价格
                    current_price = current_data[fund].last_price
                    if current_price is None or current_price <= 0:
                        log.warning(f"  {i}. {fund} 当前价格无效，跳过")
                        continue
                    
                    # 获取目标市值
                    target_value = buy_targets[fund]
                    
                    # 检查最小购买金额
                    min_amount = current_price * 100  # 最小购买100股
                    min_value = min_amount
                    
                    if target_value < min_value:
                        # 如果资金不足买100股，调整为目标购买100股
                        target_value = min_value
                        log.info(f"  {i}. {fund}: 目标市值调整为最小购买要求: {target_value:.2f}元")
                    
                    # 再次确认有足够资金
                    if target_value > available_cash:
                        log.warning(f"  {i}. {fund}: 资金不足，跳过 (需要: {target_value:.2f}元, 可用: {available_cash:.2f}元)")
                        continue
                    
                    # 计算需要购买的数量
                    buy_amount = int(target_value / current_price / 100) * 100  # 按手数购买
                    
                    # 确保至少购买100股
                    if buy_amount < 100:
                        buy_amount = 100
                    
                    # 计算实际购买价值
                    actual_value = buy_amount * current_price
                    
                    # 确保不超过可用资金
                    if actual_value > available_cash:
                        # 如果超过，调整为可以购买的最大手数
                        max_amount = int(available_cash / current_price / 100) * 100
                        if max_amount < 100:
                            log.warning(f"  {i}. {fund}: 资金不足购买100股，跳过")
                            continue
                        buy_amount = max_amount
                        actual_value = buy_amount * current_price
                    
                    # 使用order函数买入
                    order_info = order(fund, buy_amount)

                    if order_info is None:
                        log.warning(f"  {i}. {fund} 买入订单未成功创建")
                        continue

                    order_id = order_info.order_id
                    status = order_info.status
                    commission = order_info.commission if hasattr(order_info, 'commission') else 0
                    # 实际平均成交价（聚宽order对象包含）
                    fill_price = order_info.price
                    # 成交数量
                    filled_amount = order_info.filled
                    # 买入滑点：(实际价 - 基准价) × 数量
                    slippage = ((fill_price - current_price)  * 100) / current_price
                    slippage_cost = (fill_price - current_price) * filled_amount
                    use_money = fill_price * filled_amount
                    # 记录实际下单的情况
                    planned_value = g.trading_plan['target_values'].get(fund, 0)
                    log.info(f"  {i}. {fund}: 计划买入 {buy_amount}股，买价: {current_price:.3f}元，金额{actual_value:.2f}元 (原计划: {planned_value:.2f}元)"
                             f" 实际订单{order_id} 状态{status}"
                             f" 成交价{fill_price},成交量{filled_amount}股(成交金额：{use_money:.2f}元),税费：{commission:.2f},滑点: {slippage:.3f}%, 滑点成本: {slippage_cost:.2f}元")
                    
                except Exception as e:
                    log.error(f"  {i}. 买入 {fund} 失败: {e}")
        else:
            log.info("📥 没有需要买入的基金")
        
        # 获取当前所有持仓
        current_positions = list(context.portfolio.positions.keys())
        
        # 计算实际持仓分类
        actual_hold = []
        actual_bought = []
        actual_sold = []
        
        for fund in g.trading_plan['hold_list']:
            if fund in current_positions:
                actual_hold.append(fund)
        
        for fund in g.trading_plan['buy_list']:
            if fund in current_positions:
                actual_bought.append(fund)
        
        for fund in g.trading_plan['sell_list']:
            if fund not in current_positions:
                actual_sold.append(fund)
        
        log.info(f"  最终持仓分类:继续持有/已持有: {len(actual_hold)}只,已成功买入: {len(actual_bought)}只,已成功卖出: {len(actual_sold)}只")
        # 输出当前资金情况
        log.info(f"💰 最终资金情况:可用资金: {context.portfolio.available_cash:.2f}元,总资产: {context.portfolio.total_value:.2f}元")
        
        # 清理交易计划
        g.trading_plan = None
        
        log.info("=" * 80)
        
    except Exception as e:
        log.error(f"market_open异常: {e}")