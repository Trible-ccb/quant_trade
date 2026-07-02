#coding:gbk
import datetime
import requests
import time


API_URL = "https://www.cifangquant.com"
API_KEY = "ak_hTbZWpGMy94Ds0susW-AixYQd1RNlxI6IA5HtFyAgwk"

# 运行的时候请填入自己的账户ID
account = ''

# version 2026-06-17
# 1.委托时间调整为1分钟，1分钟后未成交，即触发发送微信通知，可自行在下方修改；2.超时未成交的订单会自动撤单避免重复买入；

PR_TYPE_SELL_5 = 0
PR_TYPE_BUY_5 = 10
MAX_WAIT_TIME = 60  # 委托单最大等待时间（秒）

class CiFangQuantClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
          "x-api-key": self.api_key
        }
        self.signals = []

    def format_position_code(self, position):
        if position.startswith("1"):
            return f"{position}.SZ"
        elif position.startswith("5"):
            return f"{position}.SH"
        else:
            return position
        
    def get_trading_list(self):
        """获取实盘交易策略信息"""
        try:
            url = f"{self.base_url}/api/trading/list?account={account}"
            response = requests.get(url, headers=self.headers, timeout=100)
            response.raise_for_status()
            result = response.json()
            if result["code"] == 0:
                return result["data"]
            else:
                print(f"API返回错误: {result['message']}")
                return []
        except Exception as e:
            print(f"获取订阅信息失败: {e}")
            return []

    def get_trading_signal(self, strategy_id):
        """获取最新持仓"""
        try:
            url = f"{self.base_url}/api/trading/get_strategy_signal?strategy_id={strategy_id}"
            response = requests.get(url, headers=self.headers, timeout=100)
            response.raise_for_status()

            result = response.json()
            if result["code"] == 0:
                return result["data"]
            else:
                print(f"API返回错误: {result['message']}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"获取策略信息失败: {e}")
            return None
        except Exception as e:
            print(f"未知错误: {e}")
            return None


    def send_notify(self, strategy_id: int, order_info: dict = None):
        """交易通知"""
        try:
            url = f"{self.base_url}/api/trading/update_trade_record"
            response = requests.post(url, headers=self.headers, timeout=100, 
                                     json={"strategy_id": strategy_id,
                                           "is_success": order_info.get('success'),
                                           "trade_results": order_info.get('trade_results'),
                                           "error_message": order_info.get('error_message')})
            response.raise_for_status()
        except Exception as e:
            print(f"交易成功通知失败: {e}")



def is_trading_day(C) -> bool:
    """检查是否为交易日"""
    current_date = datetime.datetime.now().date().strftime("%Y%m%d")
    trading_dates = C.get_trading_dates('SZ', current_date, current_date, 1)
    return len(trading_dates) > 0


client = CiFangQuantClient(API_URL, API_KEY)


def append_trade_result(signal: dict, order_info: dict):
    if "_trade_results" not in signal:
        signal["_trade_results"] = []
    signal["_trade_results"].append(order_info)


def flush_trade_notify(signal: dict, strategy_id: int):
    trade_results = signal.get("_trade_results", [])
    failed_results = [item for item in trade_results if not item.get("success")]
    failed_count = len(failed_results)
    summary_message = None
    if failed_count > 0:
        failed_messages = [item.get("error_message") for item in failed_results if item.get("error_message")]
        summary_message = "; ".join(failed_messages) if failed_messages else f"共{failed_count}笔交易失败"

    notify_payload = {
        "success": failed_count == 0 and len(trade_results) > 0,
        "trade_results": trade_results,
        "error_message": summary_message
    }

    client.send_notify(strategy_id, order_info=notify_payload)


def get_available_cash():
    accounts = get_trade_detail_data(account, 'stock', 'account')
    acct = accounts[0]
    available_cash = acct.m_dAvailable
    return available_cash

def place_stock_order(C, strategy_id, position, quantity, action, pr_type):
    now = datetime.datetime.now()
    userOrderId = f"{now.strftime('%Y%m%d%H%M%S')}_{position}_{action}_{quantity}股"
    op_type = 23 if action == 'buy' else 24
    passorder(op_type, 1101, account, position, pr_type, -1, quantity, f'次方量化策略_{strategy_id}', 2, userOrderId, C)
    print(f'提交{action}订单: {position}, 数量: {quantity}, prType: {pr_type}, userOrderId: {userOrderId}')
    return userOrderId


def wait_for_order_completion(userOrderId, strategy_id, after_func, order_quantity=None, C=None):
    """等待指定委托完成（成交或失败）"""
    check_interval = 2   # 检查间隔（秒）
    waited_time = 0
    order_id = None

    while waited_time < MAX_WAIT_TIME:
        print(f'次方量化策略_{strategy_id}委托查询：{userOrderId}')
        orders = get_trade_detail_data(account, 'stock', 'order', f"次方量化策略_{strategy_id}")
        for order in orders:
            if order.m_strRemark == userOrderId:
                order_id = order.m_strOrderSysID
                print(f'委托状态：{order.m_nOrderStatus}')
                if order.m_nOrderStatus == 56:
                    # 已成
                    order_info = {
                        "etf_code": order.m_strInstrumentID,
                        "etf_name": order.m_strInstrumentName,
                        "action": 'buy' if order.m_nOffsetFlag == 48 else 'sell',
                        "quantity": order.m_nVolumeTraded,
                        "price": order.m_dTradedPrice,
                        'success': True
                    }

                    # 如果是卖出，检查金额是否到账
                    if order_info.get('action') == 'sell':
                        available_cash = get_available_cash()
                        if available_cash >= order_info.get('price') * order_info.get('quantity'):
                            print(order_info)
                            after_func(order_info)
                            return True
                    else:
                        print(order_info)
                        after_func(order_info)
                        return True

                elif order.m_nOrderStatus == 57:
                    # 废单
                    order_info = {
                        "etf_code": order.m_strInstrumentID,
                        "etf_name": order.m_strInstrumentName,
                        "action": 'buy' if order.m_nOffsetFlag == 48 else 'sell',
                        "quantity": order.m_nVolumeTotal,
                        "price": None,
                        'success': False,
                        'error_message': order.m_strCancelInfo
                    }
                    print(order_info)
                    after_func(order_info)
                    return True

        time.sleep(check_interval)
        waited_time += check_interval

    print(f"委托监控超时，策略{strategy_id}委托单{userOrderId}超时未成交")
    order_info = {
        "action": "unknown",
        "quantity": order_quantity,
        "price": None,
        "success": False,
        "error_message": "委托单超时未成交"
    }
    print(f"撤单{order_id}:{cancel(order_id, account, 'stock', C)}")
    after_func(order_info)
    return False


def after_action(signal, C):
    print(f'执行完成')
    

def sell_stock(signal, C, strategy_id, position_dict_available, sell_index=0):
    """卖出股票，支持批量卖出
    
    Args:
        signal: 交易信号
        C: QMT上下文
        strategy_id: 策略ID
        position_dict_available: 可用持仓字典
        sell_index: 当前卖出的股票索引
    """
    sell_stocks = signal.get("sell_stocks")
    
    # 如果已经处理完所有卖出股票，开始买入
    if sell_index >= len(sell_stocks):
        print(f'所有卖出订单已完成，开始买入')
        buy_stock(signal, C)
        return
    
    stock = sell_stocks[sell_index]
    position = client.format_position_code(stock["etf_code"])
    
    print(f'处理卖出信号 [{sell_index + 1}/{len(sell_stocks)}]: {stock["etf_code"]}, 数量: {stock.get("quantity")}')
    
    if position in position_dict_available and position_dict_available[position] > 0:
        quantity = stock.get("quantity")
        # 确保卖出数量不超过可用持仓
        available_quantity = position_dict_available[position]
        if quantity > available_quantity:
            msg = f"卖出数量 {quantity} 超过可用持仓 {available_quantity}，跳过卖出"
            print(msg)
            append_trade_result(signal, {
                "etf_code": stock["etf_code"],
                "etf_name": stock.get("etf_name"),
                "action": "sell",
                "quantity": quantity,
                "price": None,
                "success": False,
                "error_message": msg
            })
            sell_stock(signal, C, strategy_id, position_dict_available, sell_index + 1)
            return
        
        userOrderId = place_stock_order(
            C=C,
            strategy_id=strategy_id,
            position=position,
            quantity=quantity,
            action='sell',
            pr_type=PR_TYPE_BUY_5
        )

        # 等待订单完成后，继续卖出下一只股票
        wait_for_order_completion(
            userOrderId,
            strategy_id,
            after_func=lambda order_info: (
                append_trade_result(signal, order_info),
                sell_stock(signal, C, strategy_id, position_dict_available, sell_index + 1)
            ),
            order_quantity=quantity,
            C=C,
        )
    else:
        msg = f"{position} 持仓不存在或可用数量为0，跳过卖出"
        print(msg)
        append_trade_result(signal, {
            "etf_code": stock["etf_code"],
            "etf_name": stock.get("etf_name"),
            "action": "sell",
            "quantity": stock.get("quantity"),
            "price": None,
            "success": False,
            "error_message": msg
        })
        # 继续卖出下一只股票
        sell_stock(signal, C, strategy_id, position_dict_available, sell_index + 1)


def buy_stock(signal, C, buy_index=0):
    """买入股票，支持批量买入
    
    Args:
        signal: 交易信号
        C: QMT上下文
        buy_index: 当前买入的股票索引
    """
    if not signal.get('buy_stocks'):
        
        if signal.get('sell_stocks'):
            flush_trade_notify(signal, signal.get("strategy_id"))
        
        after_action(signal, C)
        return
    
    buy_stocks = signal.get("buy_stocks")
    
    # 如果已经处理完所有买入股票，执行完成回调
    if buy_index >= len(buy_stocks):
        flush_trade_notify(signal, signal.get("strategy_id"))
        after_action(signal, C)
        return
    
    stock = buy_stocks[buy_index]
    position = client.format_position_code(stock["etf_code"])
    
    print(f'获取到买入信号 [{buy_index + 1}/{len(buy_stocks)}]: {stock["etf_code"]}, 数量: {stock["quantity"]}')
    quantity = stock["quantity"]

    userOrderId = place_stock_order(
        C=C,
        strategy_id=signal.get("strategy_id"),
        position=position,
        quantity=quantity,
        action='buy',
        pr_type=PR_TYPE_SELL_5
    )

    # 等待订单完成后，继续买入下一只股票
    wait_for_order_completion(
        userOrderId,
        signal.get("strategy_id"),
        after_func=lambda order_info: (
            append_trade_result(signal, order_info),
            buy_stock(signal, C, buy_index + 1)
        ),
        order_quantity=quantity,
        C=C,
    )

def run_trading_task(C, current_strategy_id):
    now = datetime.datetime.now()
    if not is_trading_day(C):
        return
    
    # 检查是否已经收盘，收盘后直接退出
    if now.hour >= 15:
        print(f'当前已收盘，任务{current_strategy_id}停止执行调仓检查')
        return
    
    print('='*40)
    print(f'开始执行任务{current_strategy_id}调仓检查')
    
    # 尝试获取交易信号
    signal = client.get_trading_signal(current_strategy_id)
    
    if not signal:
        print(f'任务{current_strategy_id}信号未生成，5秒后重新查询...')
        # 计算5秒后的时间点
        next_time = (now + datetime.timedelta(seconds=5)).strftime('%Y%m%d%H%M%S')
        # 创建可调度的交易函数
        trading_func = create_trading_function(current_strategy_id)
        # 使用C.schedule_run在5秒后重新执行
        C.schedule_run(
            func=trading_func,
            time_point=next_time,
            repeat_times=1,
            interval=None,
            name=f'trading_task_{current_strategy_id}'
        )
        print('='*40)
        return
    
    print(f'任务{current_strategy_id}信号获取成功')
    signal["strategy_id"] = current_strategy_id
    signal["_trade_results"] = []
        
    position_list = get_trade_detail_data(account, 'stock', 'position', f"次方量化策略_{current_strategy_id}")
    position_dict_available = {i.m_strInstrumentID + '.' + i.m_strExchangeID : int(i.m_nCanUseVolume) for i in position_list}
    print(f'当前持仓: {position_dict_available}')
    
    if signal.get('sell_stocks'):
        print(f'获取到卖出信号: {signal.get("sell_stocks")}')
        # 开始批量卖出，从第一只开始
        sell_stock(signal, C, current_strategy_id, position_dict_available, 0)
    else:
        print(f'没有卖出信号, 跳过卖出')
        buy_stock(signal, C)
    
    print(f'任务{current_strategy_id}调仓任务执行完成')
    print('='*40)



def init(C):
    print(f"初始化策略执行任务")
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    execute_time = today.strftime('%Y%m%d%H%M%S')
    C.is_first_run = True
    
    C.schedule_run(
        func=add_schedule,
        time_point=execute_time,
        repeat_times=-1,
        interval=datetime.timedelta(hours=1),
        name='add_trading_task'
    )
    # C.run_time("add_schedule", "1nDay", '2020-01-01 14:00:00')
    

def create_trading_function(item_id):
    """创建一个包含策略id的闭包函数"""
    def trading_function(C):
        run_trading_task(C, item_id)
    
    return trading_function


def add_schedule(C):
    now = datetime.datetime.now()
    if (now.time() >= datetime.time(15, 0) or now.time() < datetime.time(9, 0)) and not C.is_first_run:
        C.is_first_run = False
        print('当前为非交易时间，跳过任务检查')
        return
    
    C.is_first_run = False
    trading_list = client.get_trading_list()
    
    C.cancel_schedule_run('trading_task')
    
    logs = f"添加策略交易任务："
    
    for item in trading_list:
        execute_time_str = item["execute_time"]
        strategy_id = item.get('id', 'unknown')  # 获取item的id，如果没有则使用'unknown'
        trading_relation_id = item.get('trading_relation_id', None)
        
        execute_time = datetime.datetime.strptime(execute_time_str, "%H:%M:%S")
        
        time_point = datetime.datetime(now.year, now.month, now.day, execute_time.hour, execute_time.minute, execute_time.second).strftime('%Y%m%d%H%M%S')
        
        # 创建包含item_id的闭包函数
        trading_func = create_trading_function(strategy_id)
        
        # 定时器，每天执行一次
        C.schedule_run(
            func=trading_func,
            time_point=time_point,
            repeat_times=1,
            interval=datetime.timedelta(days=1),
            name=f'trading_task'
        )
        
        logs += f"策略ID: {trading_relation_id}（{execute_time_str}） "
    
    print(logs)