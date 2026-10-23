import json
import traceback

from jqdata import *
import bullet_trade_jq_remote_helper as bt

# ===== 实盘配置区域 =====
BT_REMOTE_HOST = 'xxx'   #远程qmt服务器ECS公网IP
BT_REMOTE_TOKEN = 'xxx'  #修改为你自己的服务器QMT_SERVER_TOKEN秘钥
BT_REMOTE_PORT = 58620              #远程qmt服务器端port
ACCOUNT_KEY = None  # 可选
SUB_ACCOUNT = None  # 可选

_ORDERS_FUNC = {'live':False}

def configured(context, live = False, host=BT_REMOTE_HOST, token=BT_REMOTE_TOKEN):
    if not BT_REMOTE_HOST or not BT_REMOTE_TOKEN:
        raise RuntimeError("请先在填写远程服务器配置")
    
    bt.configure(
        host=host,
        port=BT_REMOTE_PORT,
        token=token,
        account_key=ACCOUNT_KEY,
        sub_account_id=SUB_ACCOUNT,
    )
    # 模拟盘的情况下才生效live
    run_type = bt._run_type_from_context(context)
    _ORDERS_FUNC['live'] = live
    print(f"✅ 已配置远程QMT交易助手，host={host}, port={BT_REMOTE_PORT}, {_ORDERS_FUNC}")

def qmt_is_ok():
    """
    检查远程QMT交易助手是否可用
    """
    try:
        acct = bt.get_account()
        if acct:
            print(f"✅ 远程QMT交易助手状态正常，账户信息:现金={acct.available_cash:.2f} 总资产={acct.total_value:.2f}")
            return True
        else:
            print(f"❌ 远程QMT交易助手状态异常")
            return False
    except Exception as e:
        print(f"❌ 远程QMT交易助手检查异常: {e} \n {traceback.format_exc()}")
        return False
    
def get_orders_func(_order, _order_target, _order_value, _order_target_value):
    _ORDERS_FUNC['order'] = _order
    _ORDERS_FUNC['order_target_value'] = _order_target_value
    _ORDERS_FUNC['order_value'] = _order_value
    _ORDERS_FUNC['order_target'] = _order_target
    return (wrap_order, wrap_order_target, wrap_order_value, wrap_order_target_value)

def wrap_order(security: str, amount: int, style=None,pindex=0):
    order = _ORDERS_FUNC.get('order')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None
    if order:
        print(f"聚宽下单{security},数量{amount} style={style}")
        order_result = order(security, amount,style=style,pindex=pindex)
    if is_live:
        try:
            real_order_id = bt.order(security, amount, style=style)
        except Exception as e:
            print(f"[RPC] order实盘下单失败: {e} \n {traceback.format_exc()}")
    return order_result

def wrap_order_value(security: str, value: float,style=None,pindex=0):
    order_value = _ORDERS_FUNC.get('order_value')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None
    if order_value:
        print(f"代理聚宽下单{security},市值{value} style={style}")
        order_result = order_value(security, value,style=style,pindex=pindex)

    if is_live:
        try:
            real_order_id = bt.order_value(security, value,style=style)
        except Exception as e:
            print(f"[RPC] order_value实盘下单失败: {e} \n {traceback.format_exc()}")
    return order_result


def wrap_order_target(security: str, target: int, style=None,pindex=0):
    order_target = _ORDERS_FUNC.get('order_target')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None
    if order_target:
        print(f"代理聚宽下单{security},目标数量{target} style={style}")
        order_result = order_target(security, target,style=style,pindex=pindex)
    if is_live:
        try:
            order_result = bt.order_target(security, target, style=style)
        except Exception as e:
            print(f"[RPC] order_target实盘下单失败: {e} \n {traceback.format_exc()}")
    return order_result


def wrap_order_target_value(security: str, target_value: float, style=None,pindex=0) :
    order_target_value = _ORDERS_FUNC.get('order_target_value')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None
    if order_target_value:
        print(f"代理聚宽下单{security},目标市值{target_value} style={style}")
        order_result = order_target_value(security, target_value,style=style,pindex=pindex)
    if is_live:
        try:
            real_order_id = bt.order_target_value(security, target_value, style=style)
        except Exception as e:
            print(f"[RPC] order_target_value实盘下单失败: {e} \n {traceback.format_exc()}")
    return order_result

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
            diff_price = sim_price - real_price
            diff_rate =  diff_price / sim_price if sim_price != 0 else 0.0

            # 状态
            if diff == 0 and abs(diff_price) < 0.0001:
                status = "✅ 完全一致"
            elif diff != 0:
                if real_qty == 0:
                    status = "🅾️ 模拟盘有，实盘无"
                else:
                    status = f"🅾️ 持仓量不一致，与模拟盘差={diff}股"
            elif abs(diff_price) >= 0.0001:
                status = f"🅾️ 价格不一致，滑点={diff_rate:.2%}，差价={diff_price:.5f}"
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

                # total_diff += abs(diff)
                # check_rows.append([
                #     security,
                #     sim_qty, real_qty, diff,
                #     round(sim_price, 3), round(real_price, 3),
                #     round(sim_value, 2), round(real_value, 2),
                #     "⚠️ 实盘有，模拟盘无"
                # ])

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
    "qmt_is_ok",
    "get_orders_func",
    "sync_check_jq_sim_vs_real",
    "BT_REMOTE_HOST",
    "BT_REMOTE_TOKEN"
]