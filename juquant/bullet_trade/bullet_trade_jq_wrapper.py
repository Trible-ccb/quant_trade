import json
from jqdata import *
import bullet_trade_jq_remote_helper as bt

# ===== 实盘配置区域 =====
BT_REMOTE_HOST = 'x.x.x.x'  #远程qmt服务器ECS公网IP
BT_REMOTE_TOKEN = 'xxx'  #修改为你自己的服务器QMT_SERVER_TOKEN秘钥
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

def sync_check_jq_sim_vs_real(sim_positions):
    """
    聚宽模拟盘 ↔ 实盘 持仓对账（以模拟盘为准）
    适配：实盘 RemotePosition 对象 + 聚宽模拟盘 Position 对象
    增加：持仓成本价对比
    """
    try:
        # ====================== 1. 获取持仓（对象格式） ======================
        # 实盘：RemotePosition 列表
        real_positions = bt.get_positions()
        real_dict = {p.security: p for p in real_positions}

        positions_list = []
        for code, pos in sim_positions.items():
            positions_list.append({
                "security": code,
                "total_amount": pos.total_amount,
                "closeable_amount": pos.closeable_amount,
                "avg_cost": pos.avg_cost,  # 持仓成本价
                "price": pos.price,
                "value": pos.value
            })
            
        # ====================== 2. 获取模拟盘持仓（JSON → 字典列表）======================
        sim_dict = {p["security"]: p for p in positions_list}  # 字典用 [] 取值

        # ====================== 2. 对账表格 ======================
        check_rows = []
        total_diff = 0

        headers = [
            "股票代码", "模拟持仓", "实盘持仓", "差异",
            "模拟成本价", "实盘成本价",
            "模拟市值", "实盘市值", "对账状态"
        ]

        # 遍历模拟盘（以模拟盘为准）
        for security, sim in sim_dict.items():
            real = real_dict.get(security)

            # -------- 模拟盘（字典）--------
            sim_qty = sim.get("total_amount", 0) + sim.get("locked_amount", 0)
            sim_avail = sim.get("closeable_amount", 0)
            sim_price = sim.get("avg_cost", 0.0)
            sim_value = sim.get("value", 0.0)

            # 实盘字段（RemotePosition）
            if real:
                real_qty = real.amount
                real_avail = real.available
                real_price = real.avg_cost
                real_value = real.market_value
            else:
                real_qty = 0
                real_avail = 0
                real_price = 0.0
                real_value = 0.0

            # 差异
            diff = sim_qty - real_qty
            total_diff += abs(diff)

            # 状态
            if diff == 0 and abs(sim_price - real_price) < 0.0001:
                status = "✅ 完全一致"
            elif diff != 0:
                if real_qty == 0:
                    status = "🅾️ 模拟盘有，实盘无"
                else:
                    status = f"🅾️ 持仓量不一致，与模拟盘差={diff}股"
            elif abs(sim_price - real_price) >= 0.0001:
                status = f"🅾️ 价格不一致，与模拟盘差价={sim_price - real_price}"
            else:
                status = "✅ 一致"

            check_rows.append([
                security,
                sim_qty, real_qty, diff,
                round(sim_price, 3), round(real_price, 3),
                round(sim_value, 2), round(real_value, 2),
                status
            ])

        # 实盘多余持仓
        for security, real in real_dict.items():
            if security not in sim_dict:
                sim_qty = 0
                sim_avail = 0
                sim_price = 0.0
                sim_value = 0.0

                real_qty = real.amount
                real_avail = real.available
                real_price = real.avg_cost
                real_value = real.market_value

                diff = -real_qty
                total_diff += abs(diff)

                check_rows.append([
                    security,
                    sim_qty, real_qty, diff,
                    round(sim_price, 3), round(real_price, 3),
                    round(sim_value, 2), round(real_value, 2),
                    "⚠️ 实盘有，模拟盘无"
                ])

        # ====================== 3. 打印表格 ======================
        print_table=True
        if print_table:
            print("📊 聚宽模拟盘 ↔ 实盘 持仓对账表（以模拟盘为准）")
            fmt = "{:<14} {:<8} {:<8} {:<6} {:<10} {:<10} {:<12} {:<12} {:<12}"
            print(fmt.format(*headers))
            for row in check_rows:
                print(fmt.format(*row))
            if total_diff == 0:
                print("✅ 对账结果：完全一致")
            else:
                print(f"⚠️ 对账结果：存在差异")
            print("=" * 160 + "\n")

        return {
            "success": True,
            "total_diff": total_diff,
            "rows": check_rows
        }

    except Exception as exc:
        import traceback
        print(f"[对账异常] {exc}")
        print(traceback.format_exc())
        return {"success": False, "error": str(exc)}
       
__all__ = [
    "configured",
    "wrap_orders",
    "sync_check_jq_sim_vs_real",
    "BT_REMOTE_HOST",
    "BT_REMOTE_TOKEN"
]