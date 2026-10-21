      
# 导入函数库
from jqdata import *

# =======================实盘配置Start=======================================
# 在这行代码from jqdata import * 后面粘贴以下代码块
LIVE_TRADE = True  # true表示实盘下单，False表示聚宽模拟盘下单
if LIVE_TRADE:
    from redis_signal_interceptor import RedisSignalInterceptor
    # 创建拦截器实例并安装
    interceptor = RedisSignalInterceptor()
    (order, order_target, order_value, order_target_value) = interceptor.wrap_orders(order, order_target, order_value, order_target_value)
# =======================实盘配置End=======================================


# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    set_order_cost(OrderCost(close_tax=0, open_commission=0.0001, close_commission=0.0001, min_commission=5), type='fund')
    g.etf_hs300 = '510300.XSHG'
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘时运行
    run_daily(market_open, time='open')
    
def market_open(context):
    cur_data = get_current_data()
    p = cur_data[g.etf_hs300].last_price
    # 市价买入100股沪深300
    order(g.etf_hs300, 100)
    
    # 一般深市标的需要和科创板需要加限价
    # 限价单
    style = LimitOrderStyle(p)
    # order(g.etf_hs300, 100,style)
    
    # 带限价的市价单，一般是做价格笼子
    style = MarketOrderStyle(p*0.96)
    # order(g.etf_hs300, 100,style)
    

## 收盘后运行函数
def after_trading_end(context):
    """
    聚宽模拟盘对账 ↔ 实盘 持仓对账（以模拟盘为准）
    """
    if 'sim_trade' == context.run_params.type:
        bt_wrapper.sync_check_jq_sim_vs_real(context.portfolio.positions)

    