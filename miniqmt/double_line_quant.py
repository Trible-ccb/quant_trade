# -*- coding: gbk -*-
# 双均线策略：五日均线上穿十日均线买入，下穿卖出

import time
import datetime
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant


# ==================== 策略参数配置 ====================
PATH = r'D:\qmt\userdata_mini'       # MiniQMT 客户端 userdata_mini 路径
ACCOUNT_ID = '1000000365'            # 资金账号
STOCK_CODE = '600000.SH'             # 交易标的
ORDER_VOLUME = 100                   # 每次买入/卖出股数
PERIOD = '1d'                        # K线周期：日线
MA_SHORT = 5                         # 短期均线周期
MA_LONG = 10                         # 长期均线周期
CHECK_INTERVAL = 10                  # 定时检查间隔（秒）
# =====================================================


class _State:
    """策略运行状态容器"""
    position = 0          # 当前持仓数量
    last_signal = None    # 上一次信号，避免重复下单（'buy' 或 'sell'）


state = _State()


class MyCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print(f"[{datetime.datetime.now()}] 交易连接断开")

    def on_stock_order(self, order):
        print(f"[{datetime.datetime.now()}] 委托回报 | 代码:{order.stock_code} "
              f"状态:{order.order_status} 合同号:{order.order_sysid}")

    def on_stock_trade(self, trade):
        print(f"[{datetime.datetime.now()}] 成交回报 | 代码:{trade.stock_code} "
              f"成交价:{trade.traded_price} 成交量:{trade.traded_volume} "
              f"方向:{trade.offset_flag}")

    def on_order_error(self, order_error):
        print(f"[{datetime.datetime.now()}] 下单失败 | 订单号:{order_error.order_id} "
              f"错误信息:{order_error.error_msg}")

    def on_cancel_error(self, cancel_error):
        print(f"[{datetime.datetime.now()}] 撤单失败 | 订单号:{cancel_error.order_id} "
              f"错误信息:{cancel_error.error_msg}")

    def on_order_stock_async_response(self, response):
        print(f"[{datetime.datetime.now()}] 异步下单回报 | 账号:{response.account_id} "
              f"订单号:{response.order_id} 序号:{response.seq}")

    def on_account_status(self, status):
        print(f"[{datetime.datetime.now()}] 账号状态变化 | 账号:{status.account_id} "
              f"状态:{status.status}")


def get_ma(stock_code, period, ma_period):
    """
    获取指定标的最新的均线值
    :param stock_code: 合约代码
    :param period: K线周期
    :param ma_period: 均线周期
    :return: 最新均线值，若数据不足则返回 None
    """
    # 多取一些数据，确保均线计算有足够的历史数据
    data = xtdata.get_market_data(
        field_list=['close'],
        stock_list=[stock_code],
        period=period,
        count=ma_period + 5
    )
    if not data or 'close' not in data:
        print(f"[{datetime.datetime.now()}] 获取行情数据失败")
        return None

    close_df = data['close']
    if stock_code not in close_df.index:
        print(f"[{datetime.datetime.now()}] 未找到标的 {stock_code} 的收盘价数据")
        return None

    close_series = close_df.loc[stock_code].dropna()
    if len(close_series) < ma_period:
        print(f"[{datetime.datetime.now()}] 数据量不足，无法计算 MA{ma_period}，当前数据量:{len(close_series)}")
        return None

    ma_value = close_series.iloc[-ma_period:].mean()
    return ma_value


def query_position(xt_trader, acc, stock_code):
    """
    查询指定标的的当前可用持仓数量
    :return: 可用持仓数量，查询失败返回 0
    """
    positions = xt_trader.query_stock_positions(acc)
    if positions is None:
        return 0
    for pos in positions:
        if pos.stock_code == stock_code:
            return pos.can_use_volume
    return 0


def run_strategy(xt_trader, acc):
    """
    策略主逻辑：计算双均线信号并执行交易
    """
    now = datetime.datetime.now()
    now_time = now.strftime('%H%M%S')

    # 仅在交易时段内运行
    if not ('093000' <= now_time <= '150000'):
        print(f"[{now}] 当前非交易时段，跳过本次检查")
        return

    # 计算短期和长期均线
    ma_short = get_ma(STOCK_CODE, PERIOD, MA_SHORT)
    ma_long = get_ma(STOCK_CODE, PERIOD, MA_LONG)

    if ma_short is None or ma_long is None:
        print(f"[{now}] 均线数据获取失败，跳过本次检查")
        return

    print(f"[{now}] MA{MA_SHORT}={ma_short:.4f}  MA{MA_LONG}={ma_long:.4f}")

    # 获取当前可用持仓
    available_vol = query_position(xt_trader, acc, STOCK_CODE)

    # 获取最新价用于下单
    full_tick = xtdata.get_full_tick([STOCK_CODE])
    if not full_tick or STOCK_CODE not in full_tick:
        print(f"[{now}] 获取最新价失败，跳过本次检查")
        return
    last_price = full_tick[STOCK_CODE]['lastPrice']

    # ---- 买入信号：短期均线 > 长期均线 ----
    if ma_short > ma_long:
        if state.last_signal != 'buy':
            if available_vol == 0:
                print(f"[{now}] 买入信号触发 | MA{MA_SHORT}({ma_short:.4f}) > MA{MA_LONG}({ma_long:.4f})"
                      f" | 以最新价 {last_price} 买入 {ORDER_VOLUME} 股")
                xt_trader.order_stock_async(
                    acc,
                    STOCK_CODE,
                    xtconstant.STOCK_BUY,
                    ORDER_VOLUME,
                    xtconstant.LATEST_PRICE,
                    -1,
                    'dual_ma_strategy',
                    'buy_signal'
                )
                state.last_signal = 'buy'
            else:
                print(f"[{now}] 买入信号触发，但已有持仓 {available_vol} 股，跳过")
                state.last_signal = 'buy'
        else:
            print(f"[{now}] 买入信号持续，已持仓，无需重复操作")

    # ---- 卖出信号：短期均线 < 长期均线 ----
    elif ma_short < ma_long:
        if state.last_signal != 'sell':
            if available_vol > 0:
                sell_vol = available_vol  # 全部卖出
                print(f"[{now}] 卖出信号触发 | MA{MA_SHORT}({ma_short:.4f}) < MA{MA_LONG}({ma_long:.4f})"
                      f" | 以最新价 {last_price} 卖出 {sell_vol} 股")
                xt_trader.order_stock_async(
                    acc,
                    STOCK_CODE,
                    xtconstant.STOCK_SELL,
                    sell_vol,
                    xtconstant.LATEST_PRICE,
                    -1,
                    'dual_ma_strategy',
                    'sell_signal'
                )
                state.last_signal = 'sell'
            else:
                print(f"[{now}] 卖出信号触发，但当前无持仓，跳过")
                state.last_signal = 'sell'
        else:
            print(f"[{now}] 卖出信号持续，已空仓，无需重复操作")

    else:
        print(f"[{now}] 均线相等，无明确信号，持仓观望")


if __name__ == '__main__':
    print("=" * 50)
    print("  双均线策略启动")
    print(f"  标的: {STOCK_CODE}")
    print(f"  短期均线: MA{MA_SHORT}  长期均线: MA{MA_LONG}")
    print("=" * 50)

    # ---------- 初始化交易接口 ----------
    session_id = int(time.time())
    xt_trader = XtQuantTrader(PATH, session_id)
    acc = StockAccount(ACCOUNT_ID, 'STOCK')

    callback = MyCallback()
    xt_trader.register_callback(callback)
    xt_trader.start()

    connect_result = xt_trader.connect()
    if connect_result != 0:
        raise RuntimeError(f"交易连接失败，返回码: {connect_result}")
    print(f"[{datetime.datetime.now()}] 交易连接成功")

    subscribe_result = xt_trader.subscribe(acc)
    if subscribe_result != 0:
        print(f"[{datetime.datetime.now()}] 账号订阅失败，返回码: {subscribe_result}")
    else:
        print(f"[{datetime.datetime.now()}] 账号订阅成功")

    # ---------- 下载并订阅行情数据 ----------
    print(f"[{datetime.datetime.now()}] 正在下载历史行情数据...")
    xtdata.download_history_data(STOCK_CODE, period=PERIOD, incrementally=True)

    # 订阅实时行情，确保 get_market_data 能获取到最新数据
    xtdata.subscribe_quote(STOCK_CODE, period=PERIOD, count=MA_LONG + 5)
    time.sleep(1)
    print(f"[{datetime.datetime.now()}] 行情订阅完成，策略开始运行")

    # ---------- 策略主循环 ----------
    while True:
        try:
            run_strategy(xt_trader, acc)
        except Exception as e:
            import traceback
            print(f"[{datetime.datetime.now()}] 策略运行异常: {e}")
            traceback.print_exc()

        time.sleep(CHECK_INTERVAL)