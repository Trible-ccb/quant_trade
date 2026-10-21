# 导入函数库
from jqdata import *

# =======================实盘配置Start=======================================
import bullet_trade_jq_wrapper as bt_wrapper
# 默认下单函数
Live_Type = True  # 'True':启用实盘模式 ,False：不实盘
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
        ok = bt_wrapper.qmt_is_ok()
        if not ok:
            send_message("QMT服务端异常，检查云服务器是否正常登录qmt")
    except Exception as e:
        print(f"before_trading_start检查qmt异常")
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
