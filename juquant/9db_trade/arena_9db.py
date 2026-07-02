#-*- coding: utf-8 -*-
# 如果你的文件包含中文, 请在文件的第一行使用上面的语句指定你的文件编码
from kuanke.user_space_api import *
from jqdata import get_call_auction
import requests
import json
import inspect
from typing import Optional, Union
try:
    from kuanke.user_space_api import *
except ImportError:
    pass

# 配置部分
USERTOKEN = "token"  # 用户token
TRADEORDERID = "orderid"  # 交割单ID
_run_mode = None  # 运行模式缓存：None=未检测, sim_trade=模拟盘, 其他=回测

def _detect_run_mode():
    """从调用栈自动检测运行模式（只检测一次，结果缓存）"""
    global _run_mode
    if _run_mode is not None:
        return _run_mode
    # 遍历调用栈，查找 context.run_params.type
    for frame_info in inspect.stack():
        ctx = frame_info[0].f_locals.get('context')
        if ctx and hasattr(ctx, 'run_params') and hasattr(ctx.run_params, 'type'):
            _run_mode = ctx.run_params.type
            print(f"自动检测运行模式：{_run_mode}")
            return _run_mode
    # 获取不到默认为模拟盘
    _run_mode = 'simple_backtest'
    print(f"未检测到context，默认运行模式：{_run_mode}")
    return _run_mode

def set_config(user_token, tradeorder_id):
    global USERTOKEN, TRADEORDERID
    USERTOKEN = user_token
    TRADEORDERID = tradeorder_id

    # 【核心修复】：策略在全局读取的第一遍完全没有 context（此时引发强行探测必然误报错）。
    # 既然规定必须要在启动第一时间且一发指令，那我们就利用 Python 黑科技，
    # 动态把发指令的动作劫持注入给聚宽系统本身自动执行的原生生命周期钩子: `process_initialize(context)` 中。

    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_globals = frame.f_back.f_globals
            
            # 把调用的用户脚本里原本可能定义过的 process_initialize 先保存下来
            original_pi = caller_globals.get('process_initialize')
            
            def injected_process_initialize(context):
                # 此时该函数正被聚宽引擎调度运行，栈内存里天然带回了 context！
                # 执行发车通信（此时 detect 会 100% 鉴别出正确上下文并缓存成功）
                mytrade = MyTrade()
                mytrade.set_connected()
                
                # 放行用户原有的（如果有的话）代码
                if original_pi and callable(original_pi):
                    original_pi(context)
            
            # 强行植入到策略外层
            caller_globals['process_initialize'] = injected_process_initialize
    except Exception as e:
        print("9DB_Arena: 动态握手钩子注入失败:", e)


def get_user_token():
    return USERTOKEN

def get_tradeorder_id():
    return TRADEORDERID

class MyTrade():

    def __init__(self):
        self.api_host = 'https://api.qtsig.com/'  # API主机地址
        self.user_token = get_user_token()  # 用户TOKEN
        self.tradeorder_id = get_tradeorder_id()  # 交割单ID

    def set_connected(self):
        """向服务端发送连接确认"""
        try:
            # 自动检测运行模式，回测时跳过发送
            mode = _detect_run_mode()
            if mode != 'sim_trade':
                print("非模拟盘，跳过发送信号数据")
                return
            url = f'{self.api_host}/order/SetConnected'
            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/json"
            }
            data = {
                "UserToken": self.user_token,
                "OrderGUID": self.tradeorder_id
            }
            response = requests.post(url, data=json.dumps(data), headers=headers, timeout=15)
            if response.status_code == 200:
                result = json.loads(response.text)
                if result.get('errorCode', 0) == 0:
                    print("竞技场交割单连接确认成功。")
                else:
                    print(f"竞技场交割单连接失败，原因：{result.get('errorMess')}")
            else:
                print(f"竞技场交割单连接失败，网络状态码：{response.status_code}")
        except Exception as ex:
            print(f"竞技场交割单连接异常，原因：{ex}")
            
    # 写入交易信号
    def insert_order(self,order_info, trade_reason=""):

        try:
            # 自动检测运行模式，回测时跳过发送
            mode = _detect_run_mode()
            if mode != 'sim_trade':
                print("非模拟盘，跳过发送数据")
                return

            if order_info is None:
                return

            # filled==0 时，判断是否为集合竞价预委托（entrust_time 在 09:30 前）
            # 集合竞价期间下单 filled 为 0，finish_time 为 None，但信号需要发出
            is_pre_market = (
                int(order_info.filled) == 0
                and order_info.entrust_time is not None
                and order_info.entrust_time.hour * 60 + order_info.entrust_time.minute < 9 * 60 + 30
            )
            if int(order_info.filled) == 0 and not is_pre_market:
                return  # 非集合竞价且未成交，跳过

            # 交易类型：开多/平空 -> 买、开空/平多 -> 卖
            # action: 开/平 open/close、side: 多/空 long/short
            if (order_info.action == 'open' and order_info.side == 'long') or (order_info.action == 'close' and order_info.side == 'short'):
                trade_type = '买'
            else:
                trade_type = '卖'

            # 集合竞价预委托时用委托数量和委托时间（finish_time 为 None）
            if is_pre_market:
                amount     = order_info.amount
                # 用 get_call_auction 获取竞价期间的实时最新价（current 字段）
                try:
                    trade_date = order_info.entrust_time.strftime('%Y-%m-%d')
                    auction_df = get_call_auction(
                        [order_info.security],
                        start_date=trade_date,
                        end_date=trade_date,
                        fields=['time', 'current']
                    )
                    avg_price = float(auction_df['current'].iloc[-1]) if not auction_df.empty else 0
                except Exception as ex:
                    print(str(order_info.security) + '获取集合竞价最新价失败，原因：' + str(ex))
                    avg_price = 0  # 获取失败降级为 0，服务端根据开盘价补充
                trade_time = order_info.entrust_time.strftime('%Y-%m-%d %H:%M')
            else:
                amount    = order_info.filled
                avg_price = order_info.price
                trade_time = order_info.finish_time.strftime('%Y-%m-%d %H:%M')

            qmt_order = {
                'Token': self.user_token,    # 9db用户token
                'OrderID': self.tradeorder_id,    # 9db交割单ID
                'TradeOrders':[
                    {
                        'TradeNumber': str(order_info.order_id),    # 交易订单ID
                        'StockSymbol': order_info.security.split('.')[0],    # 交易股票代码
                        'Type': trade_type,    # 交易类型 买/卖
                        'Amount': int(amount),      # 成交股数（集合竞价用委托数量）
                        'AvgPrice': avg_price, # 交易平均价格
                        'TradeTime': trade_time,  # 成交/委托时间
                        'TradeReason': trade_reason    # 交易触发条件
                    }
                ]
            }


            #print(qmt_order)

            trade_url = f'{self.api_host}/order/TradeOrderInsert_V3'

            headers = {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Content-Type": "application/json"
            }

            # 加入重试
            for r in range(10):
                try:
                    response = requests.post(trade_url, data=json.dumps(qmt_order), headers=headers, timeout=15)
                    if response.status_code == 200:
                        response_result = json.loads(response.text)
                        if response_result['errorCode'] != 0:
                            print(str(order_info.security) + ' - 交易信号发送到9db智能体交易竞技场失败，原因：' + str(response_result['errorMess']))
                        else:
                            print(str(order_info.security) + '交易信号发送到9db智能体交易竞技场成功~')
                            break
                    else:
                        print(str(order_info.security) + '交易信号发送到9db智能体交易竞技场失败，请求状态：' + str(response.status_code))
                except Exception as ex:
                    print(str(order_info.security) + '交易信号发送到9db智能体交易竞技场失败，原因：' + str(ex))


        except Exception as ex:
            print(str(order_info.security) + '交易信号发送到9db智能体交易竞技场失败，原因：' + str(ex))

# 交易记录全局变量
g_trade_reasons = {}


# 获取交易类型
def get_order_style(args):
    style = None
    strategy_id=None
    for arg in args:
        if isinstance(arg, LimitOrderStyle):
            style = arg
        elif  isinstance(arg, MarketOrderStyle):
            style = arg
        elif isinstance(arg, (int, str)) and "strategy_id" not in locals():
            strategy_id = arg
        elif isinstance(arg, (int, str)) and 'pindex' not in locals():
            style = arg
        else:
            raise TypeError(f"出错的内容: {arg}")

    return style,strategy_id

#按股数下单
def order_trade( security: str, quantity: int,*args):
    style,strategy_id = get_order_style(args)

    # 从全局变量获取交易原因
    trade_reason = g_trade_reasons.get(security, "")

    _order = order(security, quantity, style)

    mytrade = MyTrade()
    mytrade.insert_order(order_info=_order,trade_reason = trade_reason)

    # 清理临时存储
    clear_order_reason(security)

    return _order

def order_target_trade(security: str, quantity: int,*args):

    style,strategy_id = get_order_style(args)

    # 从全局变量获取交易原因
    trade_reason = g_trade_reasons.get(security, "")

    _order = order_target(security, quantity, style)

    mytrade = MyTrade()
    mytrade.insert_order(order_info=_order,trade_reason = trade_reason)

    # 清理临时存储
    clear_order_reason(security)

    return _order

#按价值下单
def order_value_trade(security: str, quantity: int,*args):

    style,strategy_id = get_order_style(args)

    # 从全局变量获取交易原因
    trade_reason = g_trade_reasons.get(security, "")

    _order = order_value(security, quantity, style)

    mytrade = MyTrade()
    mytrade.insert_order(order_info=_order,trade_reason = trade_reason)

    # 清理临时存储
    clear_order_reason(security)

    return _order

#目标价值下单
def order_target_value_trade(security: str, quantity: int,*args):

    style,strategy_id = get_order_style(args)

    # 从全局变量获取交易原因
    trade_reason = g_trade_reasons.get(security, "")

    _order = order_target_value(security, quantity, style)

    mytrade = MyTrade()
    mytrade.insert_order(order_info=_order,trade_reason = trade_reason)

    # 清理临时存储
    clear_order_reason(security)

    return _order

# 设置交易原因的辅助函数
def set_order_reason(security, reason):
    g_trade_reasons[security] = reason

# 清理临时存储
def clear_order_reason(security):
    if security in g_trade_reasons:
        del g_trade_reasons[security]
