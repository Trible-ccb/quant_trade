# -*- coding: utf-8 -*-
"""
中继桥接服务 - HTTP接口层
接收聚宽侧的HTTP信号，写入Redis Stream
同时提供持仓查询和对账接口

API:
  POST /signal              — 接收聚宽信号，XADD到对应Stream
  POST /reconcile           — 影子对账：聚宽持仓 vs QMT持仓，自动补单
  GET  /query/positions     — 代理查询执行端持仓
  GET  /health              — 健康检查
  GET  /stats               — 统计信息
"""
import json
import time
import uuid
import logging
from datetime import datetime
from flask import Flask, request, jsonify

import redis as redis_lib
from config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    STREAM_KEYS, STREAM_MAXLEN,
    QUERY_POSITIONS_REQ_KEY, QUERY_POSITIONS_RESP_KEY, QUERY_TIMEOUT_SEC,
)

app = Flask(__name__)
logger = logging.getLogger("relay_bridge")

# Redis连接（线程安全，Flask的每个请求都在主线程处理）
_redis_client = None


def get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD if REDIS_PASSWORD else None,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=10,
        )
    return _redis_client


# ==================== 辅助：查询QMT持仓 ====================
def _query_qmt_positions(r: redis_lib.Redis, timeout=QUERY_TIMEOUT_SEC):
    """
    通过Redis请求-响应模式查询执行端持仓
    返回: (positions_list, balance_dict) 或 (None, None)
    """
    req_id = str(uuid.uuid4())[:8]
    request_data = json.dumps({
        "query": "positions",
        "req_id": req_id,
        "time": datetime.now().isoformat(),
    }, ensure_ascii=False)

    # 清空可能残留的旧响应
    r.delete(QUERY_POSITIONS_RESP_KEY)

    # 发送请求
    r.rpush(QUERY_POSITIONS_REQ_KEY, request_data)

    # 等待响应
    result = r.blpop(QUERY_POSITIONS_RESP_KEY, timeout=timeout)
    if result is None:
        return None, None

    _, response_json = result
    try:
        response = json.loads(response_json)
        # 检查不可靠标记（QMT连接断开时持仓/余额可能为空）
        if response.get("unreliable"):
            reason = response.get("reason", "QMT连接疑似断开")
            logger.error(f"[对账] QMT数据不可靠: {reason}，拒绝执行对账")
            return None, None
        positions = json.loads(response.get("positions", "[]"))
        balance = json.loads(response.get("balance", "{}"))
        return positions, balance
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"[对账] 解析QMT持仓失败: {e}")
        return None, None


# ==================== 信号接收 ====================
@app.route("/signal", methods=["POST"])
def receive_signal():
    """
    接收聚宽侧推送的交易信号，写入Redis Stream
    请求体: {"order_id", "security", "action", "amount", "price", "strategy", "pindex", ...}
    """
    try:
        signal = request.get_json(force=True)
        if not signal:
            return jsonify({"success": False, "message": "空请求体"}), 400

        strategy = signal.get("strategy", "default")
        security = signal.get("security", "")
        action = signal.get("action", "")
        order_id = signal.get("order_id", "")

        # 确定目标Stream（精确匹配 → 前缀匹配 → default）
        stream_key = STREAM_KEYS.get(strategy)
        if not stream_key:
            for key, sk in STREAM_KEYS.items():
                if key != "default" and strategy.startswith(key[:2]):
                    stream_key = sk
                    logger.info(f"[路由] 前缀匹配: '{strategy}' → {key}")
                    break
        if not stream_key:
            stream_key = STREAM_KEYS.get("default")
            logger.warning(f"[路由] 未匹配策略'{strategy}'，使用default stream")

        signal["relay_received_at"] = str(time.time())

        r = get_redis()
        msg_id = r.xadd(stream_key, signal, maxlen=STREAM_MAXLEN)

        logger.info(f"[桥接] 信号入队: {strategy} {action} {security} "
                     f"{signal.get('amount', '')}股@{signal.get('price', '')} "
                     f"→ {stream_key} id={msg_id}")

        return jsonify({
            "success": True,
            "stream": stream_key,
            "msg_id": msg_id,
            "message": "信号已入队",
        })

    except redis_lib.ConnectionError as e:
        logger.error(f"[桥接] Redis连接失败: {e}")
        return jsonify({"success": False, "message": f"Redis连接失败: {e}"}), 503

    except Exception as e:
        logger.error(f"[桥接] 处理信号异常: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ==================== 影子对账 ====================
@app.route("/reconcile", methods=["POST"])
def reconcile():
    """
    影子对账：聚宽持仓 vs QMT持仓，生成差异补单

    请求体:
    {
        "pindex": "3",
        "strategy": "S4_博收益ETF",
        "positions": [
            {"security": "513100.XSHG", "amount": 25400, "closeable_amount": 25400},
            ...
        ]
    }

    返回:
    {
        "success": true,
        "qmt_positions": [...],
        "diff_orders": [
            {"security": "002715.XSHG", "action": "sell", "amount": "600",
             "price": "15.90", "reason": "QMT多持仓(聚宽无,QMT有600股)",
             "strategy": "S5_小市值", "pindex": "4"},
            ...
        ],
        "pushed": 2,
        "report": "..."
    }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"success": False, "message": "空请求体"}), 400

        pindex = data.get("pindex", "-1")
        strategy = data.get("strategy", "unknown")
        jq_positions = data.get("positions", [])

        log_relay_req = f"[对账] 收到请求: pindex={pindex} strategy={strategy} 聚宽持仓{len(jq_positions)}只"
        logger.info(log_relay_req)

        # Step 1: 查询QMT持仓
        r = get_redis()
        qmt_positions, qmt_balance = _query_qmt_positions(r)

        if qmt_positions is None:
            logger.error("[对账] 查询QMT持仓超时")
            return jsonify({
                "success": False,
                "message": "查询QMT持仓超时，Consumer可能未运行",
            }), 504

        logger.info(f"[对账] QMT持仓{len(qmt_positions)}只")

        # Step 2: 代码格式转换 — QMT用 .SH/.SZ，聚宽用 .XSHG/.XSHE
        def jq_to_qmt(code):
            return code.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")

        def qmt_to_jq(code):
            return code.replace(".SH", ".XSHG").replace(".SZ", ".XSHE")

        # 构建聚宽持仓字典 {qmt_code: amount}
        jq_pos_dict = {}
        for pos in jq_positions:
            qmt_code = jq_to_qmt(pos.get("security", ""))
            amt = int(pos.get("amount", 0))
            if qmt_code and amt > 0:
                jq_pos_dict[qmt_code] = amt

        # 构建QMT持仓字典 {qmt_code: available_amount}
        qmt_pos_dict = {}
        for pos in qmt_positions:
            qmt_code = pos.get("security", "")
            amt = int(pos.get("available", 0))
            total = int(pos.get("amount", 0))
            if qmt_code and total > 0:
                qmt_pos_dict[qmt_code] = {"available": amt, "total": total,
                                           "cost": float(pos.get("cost", 0))}

        # Step 3: 逐只对比，生成差异单
        diff_orders = []
        all_codes = set(list(jq_pos_dict.keys()) + list(qmt_pos_dict.keys()))

        for code in sorted(all_codes):
            jq_amt = jq_pos_dict.get(code, 0)
            qmt_info = qmt_pos_dict.get(code, {"available": 0, "total": 0, "cost": 0})
            qmt_total = qmt_info["total"]
            qmt_avail = qmt_info["available"]
            jq_code = qmt_to_jq(code)

            if jq_amt > 0 and qmt_total == 0:
                # QMT少持仓 — 聚宽有但QMT没有 → 补买
                buy_amount = jq_amt
                # 补买单按聚宽持仓量买入
                diff_orders.append({
                    "security": jq_code,
                    "action": "buy",
                    "amount": str(buy_amount),
                    "price": "0",  # Consumer侧会用LATEST_PRICE
                    "reason": f"QMT少持仓(聚宽{jq_amt}股,QMT无)",
                    "strategy": strategy,
                    "pindex": pindex,
                    "source": "reconcile",
                })
                logger.info(f"[对账] 补买: {jq_code} {buy_amount}股 (聚宽{jq_amt}/QMT 0)")

            elif jq_amt == 0 and qmt_total > 0:
                # QMT多持仓 — QMT有但聚宽没有 → 补卖
                sell_amount = qmt_avail
                if sell_amount > 0:
                    diff_orders.append({
                        "security": jq_code,
                        "action": "sell",
                        "amount": str(sell_amount),
                        "price": "0",
                        "reason": f"QMT多持仓(聚宽无,QMT {qmt_total}股可用{qmt_avail})",
                        "strategy": strategy,
                        "pindex": pindex,
                        "source": "reconcile",
                    })
                    logger.info(f"[对账] 补卖: {jq_code} {sell_amount}股 (聚宽0/QMT {qmt_total})")
                else:
                    logger.info(f"[对账] 多持仓但无可卖: {jq_code} QMT总量{qmt_total}可用0")

            elif jq_amt > 0 and qmt_total > 0 and jq_amt != qmt_total:
                # 数量差异 → QMT对齐聚宽：少了补买，多了补卖
                diff = jq_amt - qmt_total
                if diff > 0:
                    # QMT少持仓 → 补买差额
                    diff_orders.append({
                        "security": jq_code,
                        "action": "buy",
                        "amount": str(diff),
                        "price": "0",
                        "reason": f"数量差异补买(聚宽{jq_amt}股,QMT{qmt_total}股,补买{diff}股)",
                        "strategy": strategy,
                        "pindex": pindex,
                        "source": "reconcile",
                    })
                    logger.info(f"[对账] 数量差异补买: {jq_code} {diff}股 (聚宽{jq_amt}/QMT{qmt_total})")
                else:
                    # QMT多持仓 → 补卖差额
                    sell_diff = abs(diff)
                    # 不能卖超过可用量
                    sell_diff = min(sell_diff, qmt_avail)
                    if sell_diff > 0:
                        diff_orders.append({
                            "security": jq_code,
                            "action": "sell",
                            "amount": str(sell_diff),
                            "price": "0",
                            "reason": f"数量差异补卖(聚宽{jq_amt}股,QMT{qmt_total}股,补卖{sell_diff}股)",
                            "strategy": strategy,
                            "pindex": pindex,
                            "source": "reconcile",
                        })
                        logger.info(f"[对账] 数量差异补卖: {jq_code} {sell_diff}股 (聚宽{jq_amt}/QMT{qmt_total})")
                    else:
                        logger.warning(f"[对账] 数量差异无可卖: {jq_code} 聚宽{jq_amt} vs QMT{qmt_total}(可用{qmt_avail})")

        # Step 4: 将差异补单推入Redis Stream
        pushed = 0
        for order in diff_orders:
            signal = {
                "order_id": f"rc_{uuid.uuid4().hex[:8]}",
                "security": order["security"],
                "action": order["action"],
                "amount": order["amount"],
                "price": order["price"],
                "strategy": order["strategy"],
                "pindex": order["pindex"],
                "source": "reconcile",
                "reason": order["reason"],
                "timestamp": str(time.time()),
            }

            # 确定目标Stream
            stream_key = STREAM_KEYS.get(strategy)
            if not stream_key:
                for key, sk in STREAM_KEYS.items():
                    if key != "default" and strategy.startswith(key[:2]):
                        stream_key = sk
                        break
            if not stream_key:
                stream_key = STREAM_KEYS.get("default")

            msg_id = r.xadd(stream_key, signal, maxlen=STREAM_MAXLEN)
            pushed += 1
            logger.info(f"[对账补单] {order['action']} {order['security']} "
                        f"{order['amount']}股 → {stream_key} id={msg_id} | {order['reason']}")

        # Step 5: 生成对账报告
        report_lines = [
            f"策略{strategy}(pindex={pindex}) 对账完成",
            f"聚宽持仓: {len(jq_pos_dict)}只",
            f"QMT持仓: {len(qmt_pos_dict)}只",
            f"差异单: {len(diff_orders)}笔(卖出{sum(1 for o in diff_orders if o['action']=='sell')}笔,"
            f"买入{sum(1 for o in diff_orders if o['action']=='buy')}笔)",
            f"已推送: {pushed}笔(买{sum(1 for o in diff_orders if o['action']=='buy')}笔+卖{sum(1 for o in diff_orders if o['action']=='sell')}笔)"
        ]
        report = " | ".join(report_lines)

        logger.info(f"[对账] {report}")

        return jsonify({
            "success": True,
            "pindex": pindex,
            "strategy": strategy,
            "qmt_positions": qmt_positions,
            "jq_position_count": len(jq_pos_dict),
            "qmt_position_count": len(qmt_pos_dict),
            "diff_orders": diff_orders,
            "pushed": pushed,
            "report": report,
        })

    except redis_lib.ConnectionError as e:
        logger.error(f"[对账] Redis连接失败: {e}")
        return jsonify({"success": False, "message": f"Redis连接失败: {e}"}), 503

    except Exception as e:
        logger.error(f"[对账] 异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


# ==================== 持仓查询代理 ====================
@app.route("/query/positions", methods=["GET"])
def query_positions():
    """代理查询执行端持仓"""
    try:
        r = get_redis()
        positions, balance = _query_qmt_positions(r)

        if positions is None:
            return jsonify({
                "success": False,
                "message": "查询超时，执行端消费者可能未运行",
            }), 504

        return jsonify({
            "success": True,
            "positions": positions,
            "balance": balance,
            "time": datetime.now().isoformat(),
        })

    except Exception as e:
        logger.error(f"[持仓查询异常] {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ==================== 健康检查 & 统计 ====================
@app.route("/health", methods=["GET"])
def health():
    try:
        r = get_redis()
        redis_ok = r.ping()
        heartbeat_val = r.get("jq:heartbeat:consumer") if redis_ok else None
        consumer_alive = heartbeat_val is not None
    except Exception:
        redis_ok = False
        consumer_alive = False

    if redis_ok and consumer_alive:
        status = "healthy"
    elif redis_ok:
        status = "degraded"
    else:
        status = "down"

    return jsonify({
        "status": status,
        "redis": redis_ok,
        "consumer_alive": consumer_alive,
        "time": datetime.now().isoformat(),
    })


@app.route("/stats", methods=["GET"])
def stats():
    try:
        r = get_redis()
        result = {"streams": {}, "time": datetime.now().isoformat()}

        for name, stream_key in STREAM_KEYS.items():
            try:
                info = r.xinfo_stream(stream_key)
                result["streams"][name] = {
                    "key": stream_key,
                    "length": info.get("length", 0),
                    "first_entry": str(info.get("first-entry", ["", ""])[0]),
                    "last_entry": str(info.get("last-entry", ["", ""])[0]),
                }
            except Exception:
                result["streams"][name] = {"key": stream_key, "length": 0}

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 启动 ====================
if __name__ == "__main__":
    import sys
    from logging.handlers import RotatingFileHandler
    import os

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    handler = RotatingFileHandler(
        os.path.join(log_dir, "bridge.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=30,
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logging.getLogger().addHandler(handler)
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    logging.getLogger().setLevel(logging.INFO)

    logger.info("=" * 50)
    logger.info("  中继桥接服务启动 - 端口5000")
    logger.info(f"  Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info("=" * 50)

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)