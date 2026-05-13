
import bullet_trade_jq_remote_helper as bt

# ===== 实盘配置区域 =====
BT_REMOTE_HOST = 'x.x.x.x'  #远程qmt服务器ECS公网IP
BT_REMOTE_TOKEN = 'xxxx'  #修改为你自己的服务器QMT_SERVER_TOKEN秘钥
BT_REMOTE_PORT = 58620              #远程qmt服务器端port
ACCOUNT_KEY = None  # 可选
SUB_ACCOUNT = None  # 可选

def configured():
    if not BT_REMOTE_TOKEN:
        raise RuntimeError("请先在 BT_REMOTE_HOST/BT_REMOTE_PORT/BT_REMOTE_TOKEN/ACCOUNT_KEY/SUB_ACCOUNT 填写远程服务器配置")
    bt.configure(
        host=BT_REMOTE_HOST,
        port=BT_REMOTE_PORT,
        token=BT_REMOTE_TOKEN,
        account_key=ACCOUNT_KEY,
        sub_account_id=SUB_ACCOUNT,
    )
    # 让券商端可用数据补价
    bt.get_broker_client().bind_data_client(bt.get_data_client())

def wrap_orders(_order, _order_target_value, _order_value, _order_target,trade_type,log_func=None):
    if log_func is None:
        log_func = print
    if trade_type == 'live':
        log_func(f"实盘下单order时，保持在聚宽模拟盘下单函数动作")
        bt.wrap_orders(_order, _order_target_value, _order_value, _order_target, True)
        return bt.order,bt.order_target_value,bt.order_value,bt.order_target
    elif trade_type == 'live_no_buy':
        log_func(f"走实盘下单链路，但是不真实下单，保持在聚宽模拟盘下单函数动作")
        bt.wrap_orders(_order, _order_target_value, _order_value, _order_target, False)
        return bt.order,bt.order_target_value,bt.order_value,bt.order_target
    else:
        log_func(f"使用聚宽平台自带order")
        return _order, _order_target_value, _order_value, _order_target
       
__all__ = [
    "configured",
    "wrap_orders"
]