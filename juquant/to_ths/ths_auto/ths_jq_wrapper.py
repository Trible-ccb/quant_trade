# -*- coding: utf-8 -*-
"""
THS 交易助手 ↔ 聚宽 包装模块（字段已对齐 THS 真实返回）

"""

import traceback

from ths_client import THSClient

# ===== 实盘配置区域 =====
ECS_HOST = "***"
THS_TOKEN    = "***"

THS_BASE_URL = f"http://{ECS_HOST}:80"
THS_TIMEOUT  = 30

_client = None
_ORDERS_FUNC = {'live': False}

# ----------------------------------------------------------------------
# 1. 配置 / 检查
# ----------------------------------------------------------------------
def configured(context, live=False,
               base_url=THS_BASE_URL, token=THS_TOKEN, timeout=THS_TIMEOUT):
    """配置 THS 交易助手客户端。

    :param live: True 才把 wrap_order* 的下单镜像到 THS 实盘；否则只走聚宽模拟盘
    """
    global _client
    if not base_url or "你的ECS" in base_url:
        raise RuntimeError("请先填写 THS 服务地址 base_url")

    _client = THSClient(base_url=base_url, token=token, timeout=timeout)
    _ORDERS_FUNC['live'] = bool(live)
    print("✅ 已配置 THS 交易助手，base_url=%s, live=%s" % (base_url, _ORDERS_FUNC['live']))
    return _client


def _require_client():
    if _client is None:
        raise RuntimeError("THS 客户端未配置，请先调用 configured()")
    return _client


def is_ok():
    """健康检查 + 资金可达性检查。返回 bool。"""
    try:
        client = _require_client()
        h = client.health()
        bal = client.get_balance() or {}
        ok = isinstance(h, dict) and h.get("status") == "success"

        total = bal.get("总资产")
        avail = bal.get("可用金额")
        if ok:
            print("✅ THS 交易助手状态正常，资金：总资产=%s 可用=%s" % (total, avail))
        else:
            print("❌ THS 交易助手状态异常：%s" % h)
        return ok
    except Exception as e:
        print("❌ THS 交易助手检查异常: %s\n%s" % (e, traceback.format_exc()))
        return False


# ----------------------------------------------------------------------
# 2. 工具函数（字段兜底 + 数值解析）
# ----------------------------------------------------------------------
def _normalize_code(security):
    """聚宽 600000.XSHG -> 600000；无后缀则原样返回。"""
    if not security:
        return security
    return str(security).strip().split(".")[0]


def _pick_number(d, keys, default=0.0):
    """从 dict 中按 keys 顺序取第一个非空值，转成 float。"""
    for k in keys:
        if k in d and d[k] not in (None, "", "--"):
            try:
                return float(str(d[k]).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
    return default


def _code_of(pos):
    for k in ("证券代码", "股票代码", "code", "代码"):
        v = pos.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _amount_of(pos):
    """当前真实持仓股数。以『实际数量』为准；兼容其他券商字段。"""
    return int(_pick_number(pos, (
        "实际数量",       # ← 实测字段
        "持仓数量", "当前持仓", "股票数量",
        "股票余额",       # 兜底（注意：这是 T-1 余额）
    )))


def _avail_of(pos):
    """可卖数量。"""
    return int(_pick_number(pos, ("可用余额", "可用数量", "可卖数量")))


def _cost_of(pos):
    return _pick_number(pos, ("成本价", "参考成本价", "持仓成本价"))


def _price_of(pos):
    return _pick_number(pos, ("市价", "现价", "最新价", "当前价"))


def _value_of(pos):
    return _pick_number(pos, ("市值", "最新市值", "参考市值"))


# ----------------------------------------------------------------------
# 3. 拉取实盘持仓（过滤掉已清仓的伪行）
# ----------------------------------------------------------------------
def _ths_positions(include_zero=False):
    """拉取 THS 实盘持仓列表（list[dict]）。

    :param include_zero: True 时包含『实际数量=0』的行（今日清仓股，A股 T+1 会残留）
                         默认 False，避免对账表出现幽灵行。
    """
    try:
        raw = _require_client().get_position() or []
    except Exception as e:
        print("[THS] 获取实盘持仓失败: %s" % e)
        return []
    if include_zero:
        return raw
    return [p for p in raw if _amount_of(p) > 0]


def _get_real_amount(security):
    """查实盘某只股票的当前持仓数量（已过滤清仓行）。"""
    code = _normalize_code(security)
    for p in _ths_positions():
        if _code_of(p) == code:
            return _amount_of(p)
    return 0


def _get_real_price(security):
    """取现价：优先 THS 持仓市价，其次聚宽 get_current_data。"""
    code = _normalize_code(security)
    for p in _ths_positions():
        if _code_of(p) == code:
            price = _price_of(p)
            if price > 0:
                return price
    try:
        from jqdata import get_current_data
        return float(get_current_data()[security].last_price)
    except Exception:
        return 0.0


def _round_lot(amount):
    """向下取整到 100 股（A股整手）。"""
    return int(amount / 100) * 100


# ----------------------------------------------------------------------
# 4. 下单代理
# ----------------------------------------------------------------------
def get_orders_func(_order, _order_target, _order_value, _order_target_value):
    """注入聚宽原生下单函数，返回包装后的 4 个下单函数。"""
    _ORDERS_FUNC['order']              = _order
    _ORDERS_FUNC['order_target']       = _order_target
    _ORDERS_FUNC['order_value']        = _order_value
    _ORDERS_FUNC['order_target_value'] = _order_target_value
    return (wrap_order, wrap_order_target, wrap_order_value, wrap_order_target_value)


def _ths_buy(code, amount):
    """实盘买入。THS 只有 buy(code, amount)；成功/失败通过异常区分。"""
    if amount <= 0:
        return
    _require_client().buy(code, int(amount))
    print("[THS] ✅ 买入 %s x %s" % (code, amount))


def _ths_sell(code, amount):
    """实盘卖出。"""
    if amount <= 0:
        return
    _require_client().sell(code, int(amount))
    print("[THS] ✅ 卖出 %s x %s" % (code, amount))


def wrap_order(security, amount, style=None, pindex=0):
    """下指定股数：amount > 0 买，amount < 0 卖。"""
    jq_order = _ORDERS_FUNC.get('order')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None

    if jq_order:
        print("聚宽下单 %s, 数量 %s style=%s" % (security, amount, style))
        order_result = jq_order(security, amount, style=style, pindex=pindex)

    if is_live:
        try:
            code = _normalize_code(security)
            amount = int(amount or 0)
            if amount > 0:
                _ths_buy(code, amount)
            elif amount < 0:
                _ths_sell(code, -amount)
        except Exception as e:
            print("[THS] order 实盘下单异常: %s\n%s" % (e, traceback.format_exc()))
    return order_result


def wrap_order_value(security, value, style=None, pindex=0):
    """下指定市值：value > 0 买，value < 0 卖。"""
    jq_ov = _ORDERS_FUNC.get('order_value')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None

    if jq_ov:
        print("聚宽下单 %s, 市值 %s style=%s" % (security, value, style))
        order_result = jq_ov(security, value, style=style, pindex=pindex)

    if is_live:
        try:
            code = _normalize_code(security)
            price = _get_real_price(code)
            if price <= 0:
                print("[THS] 无法获取 %s 现价，跳过实盘下单" % code)
                return order_result
            amount = _round_lot(abs(float(value)) / price)
            if amount < 100:
                print("[THS] %s 换算不足 1 手，跳过实盘下单" % code)
                return order_result
            if value > 0:
                _ths_buy(code, amount)
            else:
                _ths_sell(code, amount)
        except Exception as e:
            print("[THS] order_value 实盘下单异常: %s\n%s" % (e, traceback.format_exc()))
    return order_result


def wrap_order_target(security, target, style=None, pindex=0):
    """调仓到目标股数（差量下单）。"""
    jq_ot = _ORDERS_FUNC.get('order_target')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None

    if jq_ot:
        print("聚宽下单 %s, 目标数量 %s style=%s" % (security, target, style))
        order_result = jq_ot(security, target, style=style, pindex=pindex)

    if is_live:
        try:
            code = _normalize_code(security)
            target = int(target or 0)
            real_amt = _get_real_amount(code)
            diff = target - real_amt
            if diff == 0:
                print("[THS] %s 实盘 %s 股，与目标一致，无需下单" % (code, real_amt))
                return order_result
            if diff > 0:
                _ths_buy(code, diff)
            else:
                _ths_sell(code, -diff)
        except Exception as e:
            print("[THS] order_target 实盘下单异常: %s\n%s" % (e, traceback.format_exc()))
    return order_result


def wrap_order_target_value(security, target_value, style=None, pindex=0):
    """调仓到目标市值（差量下单）。"""
    jq_otv = _ORDERS_FUNC.get('order_target_value')
    is_live = _ORDERS_FUNC.get('live', False)
    order_result = None

    if jq_otv:
        print("聚宽下单 %s, 目标市值 %s style=%s" % (security, target_value, style))
        order_result = jq_otv(security, target_value, style=style, pindex=pindex)

    if is_live:
        try:
            code = _normalize_code(security)
            price = _get_real_price(code)
            if price <= 0:
                print("[THS] 无法获取 %s 现价，跳过实盘下单" % code)
                return order_result

            real_amt   = _get_real_amount(code)
            real_value = real_amt * price
            diff_value = float(target_value or 0) - real_value

            amount = _round_lot(abs(diff_value) / price)
            if amount < 100:
                print("[THS] %s 差量不足 1 手（%s 股），跳过实盘下单" % (code, amount))
                return order_result

            if diff_value > 0:
                _ths_buy(code, amount)
            else:
                _ths_sell(code, amount)
        except Exception as e:
            print("[THS] order_target_value 实盘下单异常: %s\n%s" % (e, traceback.format_exc()))
    return order_result


# ----------------------------------------------------------------------
# 5. 聚宽模拟盘 ↔ THS实盘 持仓对账
# ----------------------------------------------------------------------
def sync_check_jq_sim_vs_real(sim_positions,log_tips=""):
    """聚宽模拟盘 ↔ THS 实盘 持仓对账（以模拟盘为准）。

    :param sim_positions: context.portfolio.positions（dict: code -> Position）
    :return: {"success": bool, "total_diff": int, "rows": list}
    """
    try:
        if _client is None:
            return {"success": False, "error": "THS 客户端未配置"}

        # ---------- 实盘持仓（已过滤『实际数量=0』的清仓行） ----------
        real_dict = {}
        for p in _ths_positions():
            code = _code_of(p)
            if code:
                real_dict[code] = p

        # ---------- 模拟盘持仓 ----------
        sim_dict = {}
        for code, pos in sim_positions.items():
            sim_dict[_normalize_code(code)] = pos

        headers = [
            "股票代码", "模拟持仓", "实盘持仓", "差异",
            "模拟成本价", "实盘成本价",
            "模拟市值", "实盘市值", "对账状态",
        ]
        # 列宽按你样例里最长的数字做了适配
        fmt = "{:<10} {:<10} {:<10} {:<8} {:<12} {:<12} {:<14} {:<14} {:<26}"

        check_rows = []
        total_diff = 0
        all_codes = sorted(set(sim_dict.keys()) | set(real_dict.keys()))

        for code, sim in sim_dict.items():
            real = real_dict.get(code)

            # 模拟盘（聚宽 Position 对象）
            if sim is not None:
                sim_qty   = int(getattr(sim, "total_amount", 0) or 0)
                sim_price = float(getattr(sim, "avg_cost", 0.0) or 0.0)
                sim_value = float(getattr(sim, "value", 0.0) or 0.0)
            else:
                sim_qty, sim_price, sim_value = 0, 0.0, 0.0

            # 实盘（THS dict）
            if real is not None:
                real_qty   = _amount_of(real)          # ← 用实际数量
                real_price = _cost_of(real)
                real_value = _value_of(real)
                if real_value == 0:
                    real_value = real_qty * _price_of(real)
            else:
                real_qty, real_price, real_value = 0, 0.0, 0.0

            diff = sim_qty - real_qty
            total_diff += abs(diff)

            diff_price = sim_price - real_price
            diff_rate  = diff_price / sim_price if sim_price else 0.0

            if diff == 0 and abs(diff_price) < 1e-4:
                status = "✅ 完全一致"
            elif diff != 0:
                if sim_qty == 0:
                    status = "⚠️ 实盘有，模拟盘无"
                elif real_qty == 0:
                    status = "🅾️ 模拟盘有，实盘无"
                else:
                    status = "🅾️ 持仓量不一致，差=%d 股" % diff
            else:
                status = "🅾️ 价格不一致，滑点=%.2f%%，差价=%.5f" % (
                    diff_rate * 100, diff_price)

            check_rows.append([
                code,
                sim_qty, real_qty, diff,
                round(sim_price, 3), round(real_price, 3),
                round(sim_value, 2), round(real_value, 2),
                status,
            ])

        # ---------- 打印 ----------
        print(f"📊 {log_tips}聚宽模拟盘 ↔ THS实盘 持仓对账表（以模拟盘为准）")
        print(fmt.format(*headers))
        for row in check_rows:
            print(fmt.format(*row))
        if total_diff == 0:
            print("✅ 对账结果：完全一致")
        else:
            print("⚠️ 对账结果：存在差异（总差异股数=%d）" % total_diff)
        print("=" * 140 + "\n")

        return {"success": True, "total_diff": total_diff, "rows": check_rows}

    except Exception as exc:
        print("[对账异常] %s\n%s" % (exc, traceback.format_exc()))
        return {"success": False, "error": str(exc)}


__all__ = [
    "configured",
    "is_ok",
    "get_orders_func",
    "sync_check_jq_sim_vs_real",
    "wrap_order",
    "wrap_order_target",
    "wrap_order_value",
    "wrap_order_target_value",
    "THS_BASE_URL",
    "THS_TOKEN",
    "_ths_buy",
    "_ths_sell",
    "_ths_positions",
]