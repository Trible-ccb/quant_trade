# -*- coding: utf-8 -*-
"""
聚宽侧信号推送模块 - redis_trade.py


API与jqmt.py完全兼容，策略代码无需修改：
  from redis_trade import *
  order = push_order(order)
  order_target = push_order(order_target)
  order_value = push_order_value(order_value)
  order_target_value = push_order(order_target_value)

===== 装饰器链执行顺序（从外到内）=====
  strategy调用 → ensure_price → push_order wrapper → JoinQuant原始函数

ensure_price 将 price 追加到参数末尾:
  func(*args, price, **kwargs)
  即: func(security, amount/value, [order_style], price, pindex=...)

push_order wrapper 检测末尾注入的 price，剥离后传给 JoinQuant 原始函数。
"""
import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

logger = logging.getLogger("redis_trade")

# ==================== 聚宽可见日志 ====================
_jq_log_fn = None  # 由策略代码在initialize中注册

def set_log_fn(fn):
    """注册聚宽log函数（由策略代码调用: set_log_fn(log)）"""
    global _jq_log_fn
    _jq_log_fn = fn

def log_relay(tag, security, action, amount, detail=""):
    """写入聚宽可见日志（优先用注册的聚宽log，fallback到logging/print）"""
    msg = f"[中继{tag}] {security} {action} {amount}股 {detail}".strip()
    logged = False
    # 优先使用策略注册的聚宽log函数
    if _jq_log_fn is not None:
        try:
            _jq_log_fn('info', msg)
            logged = True
        except Exception:
            pass
    # 备选1：直接调用聚宽内置log（可能在某些环境下可用）
    if not logged:
        try:
            log('info', msg)
            logged = True
        except Exception:
            pass
    # 备选2：Python logging
    if not logged:
        try:
            logger.info(msg)
        except Exception:
            pass
    # 备选3：print（聚宽回测可能重定向到日志）
    if not logged:
        try:
            print(msg)
        except Exception:
            pass

# ==================== 配置 ====================
RELAY_URL = "http://云服务器IP:5000"
_IS_BACKTEST = None  # 缓存回测检测结果，避免重复计算
_JQ_ENV = None       # 聚宽环境类型: 'backtest'/'simulation'/'live_trading'/None
HTTP_TIMEOUT = 10
MAX_RETRIES = 2
MAX_WORKERS = 10
ENABLED = True

# ==================== 内部状态 ====================
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

_STRATEGY_NAMES = {
    0: "S1_4ETF轮动",
    1: "S2_4支红利",
    2: "S3_QDII套利",
    3: "S4_博收益ETF",
    4: "S5_小市值",
}


def _get_strategy_name(pindex):
    return _STRATEGY_NAMES.get(pindex, "unknown_p%s" % pindex)


def _extract_pindex(kwargs):
    """从kwargs中提取pindex"""
    pindex = kwargs.get("pindex", -1)
    if pindex != -1:
        return pindex
    try:
        import sys
        for depth in range(3, 8):
            try:
                frame = sys._getframe(depth)
                ctx = frame.f_locals.get("context")
                if ctx and hasattr(ctx, "run_params"):
                    return getattr(ctx.run_params, "pindex", -1)
            except ValueError:
                break
    except Exception:
        pass
    return -1


def _get_price(security):
    """获取当前价格（备用）"""
    try:
        tick = get_current_tick(security)
        if tick is not None:
            if tick['current'] > 0:
                return round(tick['current'], 3)
            for field in ['a1_p', 'b1_p', 'a2_p', 'b2_p']:
                if tick[field] > 0:
                    return round(tick[field], 3)
    except Exception:
        pass
    return 0


def register_env(context):
    """注册聚宽运行环境（由策略代码在initialize中调用）

    聚宽 context.run_params.type 实测取值：
      'full_backtest' → 回测环境，无外网，跳过推送
      'simulation'    → 模拟交易，有外网，正常推送

    必须在 initialize() 中调用，此时 context 对象可用。
    """
    global _JQ_ENV, _IS_BACKTEST
    try:
        env_type = getattr(context.run_params, 'type', None)
    except Exception:
        env_type = None
    _JQ_ENV = env_type
    # 回测环境判断：type 包含 'backtest' 即视为回测
    if env_type and 'backtest' in env_type:
        _IS_BACKTEST = True
        log_relay("环境检测", "-", "-", "-", f"检测到回测环境(type={env_type})，推送已禁用")
    else:
        _IS_BACKTEST = False
        log_relay("环境检测", "-", "-", "-", f"检测到模拟交易环境(type={env_type})，推送已启用")


def _detect_backtest():
    """检测是否在回测环境（优先使用register_env注册的环境，否则尝试栈帧检测）"""
    global _IS_BACKTEST, _JQ_ENV
    # 优先使用 register_env 注册的环境类型
    if _JQ_ENV is not None:
        _IS_BACKTEST = ('backtest' in _JQ_ENV)
        return _IS_BACKTEST
    if _IS_BACKTEST is not None:
        return _IS_BACKTEST
    # 兜底：栈帧检测（不依赖调用深度，仅做最后手段）
    try:
        import sys
        for depth in range(3, 12):
            try:
                frame = sys._getframe(depth)
                ctx = frame.f_locals.get('context')
                if ctx and hasattr(ctx, 'run_params'):
                    rp = ctx.run_params
                    if hasattr(rp, 'type'):
                        _IS_BACKTEST = ('backtest' in rp.type)
                        _JQ_ENV = rp.type
                        return _IS_BACKTEST
            except (ValueError, AttributeError):
                continue
    except Exception:
        pass
    # 未知环境默认按模拟交易处理（宁可误推不可漏推）
    _IS_BACKTEST = False
    _JQ_ENV = 'unknown'
    return False


_push_fail_count = 0  # 连续推送失败计数

def reset_backtest_flag():
    """每日重置回测检测标记（在process_initialize中调用）

    聚宽模拟盘保持Python进程跨日运行，模块级变量持久化。
    每日09:00重置检测状态，让 register_env 或 _detect_backtest 重新判定环境。
    同时重置推送失败计数。
    """
    global _IS_BACKTEST, _push_fail_count
    _IS_BACKTEST = None
    _push_fail_count = 0
    log_relay("每日重置", "-", "-", "-", f"回测标记已重置(当前环境={_JQ_ENV}), 推送计数清零")

def _do_push(signal):
    """HTTP推送（可在线程池或主线程中运行）"""
    global _IS_BACKTEST, _push_fail_count
    import urllib.request
    import json as _json
    url = "%s/signal" % RELAY_URL
    data = _json.dumps(signal, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                result = _json.loads(body)
                if result.get("success"):
                    _push_fail_count = 0  # 成功则重置计数
                    log_relay("推送成功", signal.get("security"), signal.get("action"), signal.get("amount"))
                    return True
                last_err = "server returned success=false"
        except Exception as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(1)
    _push_fail_count += 1
    # 注意：不再根据失败次数自动标记为回测环境（之前的做法导致粘滞Bug）
    # 如果环境已由 register_env 确认为非回测，推送失败只是网络问题，不应禁用推送
    log_relay("推送失败", signal.get("security"), signal.get("action"), signal.get("amount"), f"err={last_err}(累计失败{_push_fail_count}次)")
    return False


def _build_and_push(func_name, security, amount, price, kwargs):
    """构建信号并推送"""
    # 回测环境自动跳过推送（回测沙箱无法连接外网，推送只会失败并灌入Redis）
    if _detect_backtest():
        log_relay("回测跳过", security, "buy" if amount > 0 else "sell" if amount < 0 else "target0", str(abs(int(amount))), f"price={price:.3f} func={func_name}")
        return
    if not ENABLED or not security:
        log_relay("跳过推送", security, "-", str(amount), "ENABLED=%s security=%s" % (ENABLED, bool(security)))
        return
    # order_target(stock, 0) 清仓卖出: amount=0 但仍需推送
    is_target_zero = (func_name in ('order_target', 'order_target_value') and amount == 0)
    if amount == 0 and not is_target_zero:
        log_relay("跳过推送", security, "-", "0", "amount=0且非order_target清仓")
        return
    pindex = _extract_pindex(kwargs)
    if is_target_zero:
        action = "sell"
        sell_amount = "0"  # consumer侧查持仓确定实际卖出数量
    else:
        action = "buy" if amount > 0 else "sell"
        # A股ETF必须为100的整数倍(1手=100股)
        # order_target_value 产生的amount是浮点数，需向下取整到100倍数
        raw_amount = abs(int(amount))
        if func_name in ('order_target_value', 'order_value'):
            # 按目标市值/价值计算出的股数，必须取整
            sell_amount = str(raw_amount - raw_amount % 100)
        else:
            # order/order_target 的amount应该已经是整数，但仍做保护
            sell_amount = str(raw_amount)
        if action == 'sell':
            # 卖出不需要100股倍数限制(A股可以零股卖出)
            sell_amount = str(raw_amount)
    signal = {
        "order_id": str(uuid.uuid4())[:8],
        "security": str(security),
        "action": action,
        "amount": sell_amount,
        "price": str(price),
        "strategy": _get_strategy_name(pindex),
        "pindex": str(pindex),
        "func": func_name,
        "timestamp": str(time.time()),
    }
    log_relay("准备推送", security, action, sell_amount, f"price={price} func={func_name}")
    # v2: 优先同步推送，确保信号不丢失；失败时回退到异步
    try:
        ok = _do_push(signal)
        if not ok:
            _executor.submit(_do_push, signal)
    except Exception:
        _executor.submit(_do_push, signal)


def _strip_injected_price(args):
    """
    检测并剥离 ensure_price 追加到末尾的 price 参数。

    ensure_price 调用方式: func(*args, price, **kwargs)
    即 price 总是追加到位置参数的最后一个。

    JoinQuant 原始函数签名:
      order(security, amount, side=None, order_style=None, pindex=None)
      → 最多2个必填位置参数(security, amount)，其余都是关键字参数
    
    所以:
      - ensure_price 注入前: args = (security, amount)  或  (security, amount, order_style)
      - ensure_price 注入后: args = (security, amount, price)  或  (security, amount, order_style, price)
    
    检测方法: 最后一个位置参数是数字(int/float)，且前面还有至少2个参数
    剥离方法: 去掉最后一个参数，返回 (clean_args, price)
    """
    if len(args) >= 3 and isinstance(args[-1], (int, float)):
        price = float(args[-1])
        clean_args = args[:-1]
        return clean_args, price
    return args, 0


def push_order(func):
    """
    装饰器：包装 order / order_target / order_target_value

    确保兼容 ensure_price 装饰器的 price 注入。
    幂等：已被 push_order 包装的函数不会重复包装。
    """
    # 幂等检查：已被push_order包装过则直接返回
    if getattr(func, '_push_order_wrapped', False):
        return func
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 剥离 ensure_price 注入的末尾 price
        real_args, injected_price = _strip_injected_price(args)

        # 调用 JoinQuant 原始函数（不带注入的 price）
        result = func(*real_args, **kwargs)

        # 异步推送信号到中继
        try:
            security = args[0] if args else ""
            amount = args[1] if len(args) >= 2 else 0

            # v2: 从 LimitOrderStyle/MarketOrderStyle 提取真实限价（优先级最高）
            # order(security, amount, LimitOrderStyle(price), pindex=3)
            # → args[2] = LimitOrderStyle, args[-1] = injected(ensure_price)
            style = kwargs.get('style')
            if not style and len(args) >= 3 and hasattr(args[2], 'limit_price'):
                style = args[2]

            actual_price = injected_price  # ensure_price 注入的备用值
            if style is not None and hasattr(style, 'limit_price') and style.limit_price > 0:
                actual_price = style.limit_price  # 真实限价覆盖

            if actual_price <= 0:
                actual_price = _get_price(security)

            log_relay("捕获下单", security, "buy" if amount > 0 else "sell", str(abs(amount)), f"price={actual_price:.3f} func={func.__name__}")
            _build_and_push(func.__name__, security, amount, actual_price, kwargs)
        except Exception as e:
            logger.error("[push_order异常] %s", e)

        return result
    wrapper._push_order_wrapped = True  # 幂等标记
    return wrapper


def push_order_value(func):
    """
    装饰器：包装 order_value

    value > 0 = 买入金额, value < 0 = 卖出金额
    幂等：已被 push_order_value 包装的函数不会重复包装。
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 剥离 ensure_price 注入的末尾 price
        real_args, injected_price = _strip_injected_price(args)

        # 调用 JoinQuant 原始函数
        result = func(*real_args, **kwargs)

        # 异步推送信号到中继
        try:
            security = args[0] if args else ""
            value = float(args[1]) if len(args) >= 2 else 0

            # v2: 从 LimitOrderStyle 提取真实限价
            style = kwargs.get('style')
            if not style and len(args) >= 3 and hasattr(args[2], 'limit_price'):
                style = args[2]

            actual_price = injected_price
            if style is not None and hasattr(style, 'limit_price') and style.limit_price > 0:
                actual_price = style.limit_price

            if actual_price <= 0:
                actual_price = _get_price(security)
            price = actual_price
            if price > 0:
                amount = int(abs(value) / price)
            else:
                amount = 0
            log_relay("捕获下单", security, "buy" if value > 0 else "sell", str(amount), f"price={price:.3f} func={func.__name__}")
            _build_and_push(func.__name__, security,
                            amount if value > 0 else -amount, price, kwargs)
        except Exception as e:
            logger.error("[push_order_value异常] %s", e)

        return result
    wrapper._push_order_value_wrapped = True  # 幂等标记
    return wrapper

# ==================== 影子对账 ====================

def reconcile_positions(context, pindex, strategy_name=None):
    """
    影子对账：将聚宽持仓发送到Bridge，与QMT持仓对比，自动补卖差异股

    在策略代码中通过 run_daily 注册调用：
        run_daily(lambda ctx: reconcile_positions(ctx, 0, 'S1_4ETF轮动'), '09:30')

    参数:
        context: 聚宽context对象
        pindex: 子账户索引 (0-4)
        strategy_name: 策略名 (如 'S1_4ETF轮动')
    """
    if not ENABLED:
        log_relay("跳过对账", "-", "-", "-", "ENABLED=False")
        return

    if _detect_backtest():
        log_relay("跳过对账", strategy_name or "-", "-", "-", "回测环境，跳过对账")
        return

    if strategy_name is None:
        _STRATEGY_NAMES.get(pindex, "unknown")

    try:
        # Step 1: 收集聚宽持仓
        positions = context.subportfolios[pindex].positions
        jq_positions = []
        for sec, pos in positions.items():
            if pos.total_amount > 0:
                jq_positions.append({
                    "security": str(sec),
                    "amount": int(pos.total_amount),
                    "closeable_amount": int(pos.closeable_amount),
                    "avg_cost": float(pos.avg_cost),
                })

        log_relay("对账开始", strategy_name, str(len(jq_positions)), "只持仓",
                  f"pindex={pindex}")

        # Step 2: 发送到Bridge对账端点
        import urllib.request
        import json as _json

        url = "%s/reconcile" % RELAY_URL
        payload = _json.dumps({
            "pindex": str(pindex),
            "strategy": strategy_name,
            "positions": jq_positions,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            diff = result.get("diff_orders", [])
            pushed = result.get("pushed", 0)
            report = result.get("report", "")
            log_relay("对账完成", strategy_name, str(len(diff)), "笔差异",
                      f"推送{pushed}笔 | {report}")
        else:
            err = result.get("message", "未知错误")
            log_relay("对账失败", strategy_name, "-", "-", err)

    except Exception as e:
        log_relay("对账异常", strategy_name, "-", "-", str(e))


def reconcile_all_strategies(context):
    """
    全量影子对账：一次性合并5个策略持仓 → 与QMT全量持仓对比

    ⚠️ 必须合并所有策略持仓后一次性发送，不能逐策略单独对账！
    因为QMT是5策略共用一个账户，逐策略对账会把其他策略的持仓误判为"多余"并卖出。

    在策略代码的 initialize() 中注册:
        run_daily(reconcile_all_strategies, '09:50')
        run_daily(reconcile_all_strategies, '14:00')
        run_daily(reconcile_all_strategies, '14:50')
    """
    if not ENABLED:
        log_relay("跳过对账", "-", "-", "-", "ENABLED=False")
        return

    if _detect_backtest():
        log_relay("跳过对账", "-", "-", "-", "回测环境，跳过对账")
        return

    strategies = [
        (0, "S1_4ETF轮动"),
        (1, "S2_4支红利"),
        (2, "S3_QDII套利"),
        (3, "S4_博收益ETF"),
        (4, "S5_小市值"),
    ]

    # Step 1: 收集所有策略的持仓
    strategies_data = []
    total_jq_positions = 0
    for pindex, name in strategies:
        try:
            positions = context.subportfolios[pindex].positions
            jq_positions = []
            for sec, pos in positions.items():
                if pos.total_amount > 0:
                    jq_positions.append({
                        "security": str(sec),
                        "amount": int(pos.total_amount),
                        "closeable_amount": int(pos.closeable_amount),
                        "avg_cost": float(pos.avg_cost),
                    })
            total_jq_positions += len(jq_positions)
            strategies_data.append({
                "pindex": str(pindex),
                "strategy": name,
                "positions": jq_positions,
            })
        except Exception as e:
            log_relay("对账异常", name, "-", "-", f"收集持仓失败: {e}")

    log_relay("对账", "-", str(total_jq_positions), "只持仓", "开始全量影子对账(5策略合并)")

    # Step 2: 一次性发送给Bridge
    try:
        import urllib.request
        import json as _json

        url = "%s/reconcile" % RELAY_URL
        payload = _json.dumps({
            "mode": "all",
            "strategies": strategies_data,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            diff = result.get("diff_orders", [])
            pushed = result.get("pushed", 0)
            report = result.get("report", "")
            log_relay("对账完成", "-", str(len(diff)), "笔差异",
                      f"推送{pushed}笔 | {report}")
        else:
            err = result.get("message", "未知错误")
            log_relay("对账失败", "-", "-", "-", err)

    except Exception as e:
        log_relay("对账异常", "-", "-", "-", str(e))

    log_relay("对账", "-", "-", "-", "全量影子对账完成")