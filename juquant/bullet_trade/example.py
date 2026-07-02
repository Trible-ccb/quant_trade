# -*- coding: utf-8 -*-
"""
QMT 实盘交易示例
演示如何使用 bullet_trade_jq_remote_helper 连接远程 QMT 服务并进行交易操作。
"""

import bullet_trade_jq_remote_helper as bt
import time
import pandas as pd

# 配置连接（请根据实际环境修改）
HOST = '8.141.101.156'
TOKEN = '0011223344'
PORT = 58620
ACCOUNT_KEY = ''
SUB_ACCOUNT_ID = ''

def initialize(context):
    """聚宽初始化函数"""
    # 1. 配置远程连接
    bt.configure(
        host=HOST,
        token=TOKEN,
        port=PORT,
        account_key=ACCOUNT_KEY,
        sub_account_id=SUB_ACCOUNT_ID,
        debug=True,              # 开启调试日志，便于排查问题
        retries=2,               # 网络失败重试2次
        retry_interval=1.0,      # 重试间隔1秒
        rpc_timeout=20.0         # RPC超时20秒
    )
    print("远程交易连接已初始化。")

    # 2. 设置定时任务（每日开盘后9:31执行交易）
    run_daily(trade, time='09:31')

def trade(context):
    """每日交易逻辑"""
    print("\n===== 开始执行交易 =====")

    # ---------- 查询账户和持仓 ----------
    try:
        account = bt.get_account()
        print(f"账户可用资金: {account.available_cash:.2f} 元")
        print(f"账户总资产: {account.total_value:.2f} 元")
    except Exception as e:
        print(f"获取账户信息失败: {e}")
        return

    try:
        positions = bt.get_positions()
        print(f"当前持仓数量: {len(positions)}")
        for pos in positions:
            print(f"  {pos.security} 持仓 {pos.amount} 股, 可用 {pos.available} 股, 成本 {pos.avg_cost:.2f}, 市值 {pos.market_value:.2f}")
    except Exception as e:
        print(f"获取持仓失败: {e}")
        return

    # ---------- 示例：买入测试 ----------
    # 选择一只股票（平安银行）
    security = '000001.XSHE'
    # 获取当前价格（可选，用于显示）
    try:
        # 使用远程数据客户端（需要先获取）
        data_client = bt.get_data_client()
        last_price = data_client.get_last_price(security)
        print(f"{security} 最新价: {last_price}")
    except Exception as e:
        print(f"获取行情失败: {e}")
        last_price = None

    # 按数量买入 1000 股（市价单，等待10秒确认）
    if last_price is not None:
        try:
            print(f"买入 {security} 1000 股（市价）...")
            order = bt.order(security, 1000, price=None, wait_timeout=10)
            if order:
                print(f"订单号: {order.order_id}, 状态: {order.status}, 实际委托数量: {order.actual_amount}")
            else:
                print("下单返回空，可能无需交易。")
        except Exception as e:
            print(f"买入失败: {e}")

    # ---------- 示例：按市值卖出 ----------
    # 假设买入后，尝试卖出 5000 元市值的持仓（限价，异步）
    try:
        print(f"按市值卖出 {security} 5000 元（限价，异步）...")
        order_val = bt.order_value(security, -5000, price=last_price*1.01 if last_price else None, wait_timeout=0)
        if order_val:
            print(f"订单号: {order_val.order_id}, 状态: {order_val.status}")
        else:
            print("按市值下单返回空。")
    except Exception as e:
        print(f"按市值卖出失败: {e}")

    # ---------- 示例：调仓到目标数量 ----------
    # 目标持仓 500 股
    try:
        print(f"调仓 {security} 到目标数量 500 股...")
        order_tgt = bt.order_target(security, 500, wait_timeout=5)
        if order_tgt:
            print(f"调仓订单号: {order_tgt.order_id}, 状态: {order_tgt.status}")
        else:
            print("无需调仓（当前持仓已是目标数量）。")
    except Exception as e:
        print(f"调仓失败: {e}")

    # ---------- 查询订单列表 ----------
    try:
        all_orders = bt.get_orders()
        print(f"所有订单数量: {len(all_orders)}")
        for oid, o in list(all_orders.items())[:5]:  # 只显示前5个
            print(f"  {oid}: {o.security} {o.amount}股, 状态 {o.status}, 已成交 {o.filled}")
    except Exception as e:
        print(f"查询订单失败: {e}")

    # ---------- 撤销未成交订单（示例） ----------
    try:
        open_orders = bt.get_open_orders()
        if open_orders:
            print(f"发现 {len(open_orders)} 个未成交订单，尝试撤销...")
            for oid in open_orders:
                result = bt.cancel_order(oid)
                print(f"撤销订单 {oid} 结果: {result}")
        else:
            print("没有未成交订单。")
    except Exception as e:
        print(f"撤销订单失败: {e}")

    print("===== 交易执行完毕 =====\n")

# 注意：在聚宽研究环境中，需要运行此脚本，且 `initialize` 会被自动调用。
# 如果在本地测试，可以手动调用 initialize 和 trade，但需注意聚宽特定函数（如 run_daily）仅在回测/实盘引擎中有效。