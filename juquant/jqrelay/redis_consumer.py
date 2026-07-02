# -*- coding: utf-8 -*-
"""
Redis Stream 消费者 - 服务端主进程
从Redis Stream读取聚宽信号，经风控检查后调用执行引擎下单

流程（与fangan1一致）：
  1. XREADGROUP 阻塞读取新消息
  2. 解析消息 → 去重检查
  3. 风控检查
  4. 调用执行引擎下单
  5. XACK确认消息
  6. 将执行结果写回Redis（供聚宽侧查询）
"""
import sys
import os
import json
import time
import signal
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from threading import Thread, Event

import redis

from config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    REDIS_DECODE_RESPONSES,
    STREAM_KEYS, CONSUMER_GROUP, CONSUMER_NAME,
    STREAM_MAXLEN, BLOCK_TIMEOUT_MS,
    DEDUP_SET_KEY, DEDUP_TTL_SEC,
    LOG_DIR, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT,
    QUERY_POSITIONS_REQ_KEY, QUERY_POSITIONS_RESP_KEY, QUERY_TIMEOUT_SEC,
)

# ==================== 健康监控 ====================
HEARTBEAT_KEY = "jq:heartbeat:consumer"  # Consumer心跳key
HEARTBEAT_INTERVAL = 300  # 心跳间隔（秒）5分钟
QMT_HEALTH_CHECK_INTERVAL = 60  # QMT连接健康检查间隔（秒）
QMT_RECONNECT_MAX_RETRY = 6     # 重连最大重试次数
QMT_RECONNECT_RETRY_INTERVAL = 10  # 重连重试间隔（秒）
from execution_engine import create_engine
from risk_manager import RiskManager

# ==================== 涨跌停判断 ====================
def _check_limit_price(security: str, action: str) -> tuple:
    """
    检查股票是否涨跌停，用于对账补单保护
    返回: (should_skip: bool, reason: str)
    
    规则：
    - 涨停 + 需补买 → 跳过（买不进）
    - 跌停 + 需补卖 → 跳过（卖不出）
    - 跌停 + 需补买 → 跳过（不应追跌）
    - 涨停 + 需补卖 → 正常执行（涨停卖得出）
    """
    try:
        from xtquant import xtdata
        # 聚宽代码转QMT代码
        qmt_code = security.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")
        tick = xtdata.get_full_tick([qmt_code])
        if not tick or qmt_code not in tick:
            return False, ""
        
        data = tick[qmt_code]
        last_price = data.get("lastPrice", 0)
        last_close = data.get("lastClose", 0)
        
        if last_close <= 0 or last_price <= 0:
            return False, ""
        
        # 判断涨跌停：涨幅>=9.9%视为涨停，跌幅>=9.9%视为跌停
        # ETF/创业板20%，但用9.9%可覆盖所有10%场景，20%场景更宽松
        change_pct = (last_price - last_close) / last_close
        
        is_limit_up = change_pct >= 0.099   # 涨幅>=9.9%
        is_limit_down = change_pct <= -0.099  # 跌幅>=9.9%
        
        # 特殊处理：创业板/科创板20%涨跌停
        if qmt_code.startswith("3") or qmt_code.startswith("68"):
            is_limit_up = change_pct >= 0.199
            is_limit_down = change_pct <= -0.199
        
        if is_limit_up and action == "buy":
            return True, f"涨停补买跳过(涨幅{change_pct*100:.1f}%，涨停买不进)"
        elif is_limit_down and action == "sell":
            return True, f"跌停补卖跳过(跌幅{change_pct*100:.1f}%，跌停卖不出)"
        elif is_limit_down and action == "buy":
            return True, f"跌停补买跳过(跌幅{change_pct*100:.1f}%，不应追跌)"
        
        return False, ""
    except Exception as e:
        logger.warning(f"[涨跌停检查异常] {security}: {e}")
        return False, ""  # 查询失败时不阻止下单

# ==================== 日志配置 ====================
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 控制台
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)

# 文件
file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "consumer.log"),
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger("consumer")

# ==================== 全局状态 ====================
shutdown_event = Event()


def signal_handler(sig, frame):
    logger.info(f"收到信号 {sig}，准备关闭...")
    shutdown_event.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ==================== Redis连接 ====================
def create_redis_client() -> redis.Redis:
    """创建Redis连接"""
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD if REDIS_PASSWORD else None,
        db=REDIS_DB,
        decode_responses=REDIS_DECODE_RESPONSES,
        socket_connect_timeout=10,
        socket_keepalive=True,
        retry_on_timeout=True,
    )
    client.ping()
    logger.info(f"[Redis] 连接成功 {REDIS_HOST}:{REDIS_PORT}")
    return client


def ensure_consumer_groups(r: redis.Redis):
    """确保所有Stream的Consumer Group已创建"""
    for name, stream_key in STREAM_KEYS.items():
        try:
            r.xgroup_create(stream_key, CONSUMER_GROUP, id="0", mkstream=True)
            logger.info(f"[Stream] 创建Consumer Group: {stream_key} → {CONSUMER_GROUP}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass  # 已存在
            else:
                raise


# ==================== 消息处理 ====================
def process_message(r: redis.Redis, engine, risk_mgr: RiskManager,
                    stream_key: str, msg_id: str, msg_data: dict):
    """
    处理单条消息的完整流程
    msg_data: {order_id, security, action, amount, price, strategy, pindex, timestamp}
    """
    security = msg_data.get("security", "")
    action = msg_data.get("action", "")
    amount = msg_data.get("amount", "0")
    price = msg_data.get("price", "0")
    strategy = msg_data.get("strategy", "unknown")
    order_id = msg_data.get("order_id", "")

    logger.info(f"[收到信号] id={msg_id} strategy={strategy} "
                f"{action} {security} {amount}股@{price} order_id={order_id}")

    # Step 0b: 对账补单涨跌停保护
    source = msg_data.get("source", "")
    if source == "reconcile":
        skip, reason = _check_limit_price(security, action)
        if skip:
            logger.info(f"[涨跌停保护] {security} {action} → {reason}")
            r.xack(stream_key, CONSUMER_GROUP, msg_id)
            r.sadd(DEDUP_SET_KEY, msg_id)
            r.expire(DEDUP_SET_KEY, DEDUP_TTL_SEC)
            return

    # Step 0: 过期检查 - 丢弃超过5分钟的旧信号（防止回测信号误入实盘）
    SIGNAL_MAX_AGE_SEC = 300
    try:
        signal_ts = float(msg_data.get("timestamp", "0"))
        if signal_ts > 0:
            age = time.time() - signal_ts
            if age > SIGNAL_MAX_AGE_SEC:
                logger.warning(f"[过期丢弃] {security} {action} 信号年龄={age:.0f}秒 > {SIGNAL_MAX_AGE_SEC}秒")
                r.xack(stream_key, CONSUMER_GROUP, msg_id)
                return
    except (ValueError, TypeError):
        pass

    # Step 1: 去重检查
    if r.sismember(DEDUP_SET_KEY, msg_id):
        logger.info(f"[去重] 消息 {msg_id} 已处理过，跳过")
        # 仍然ACK，避免反复读取
        r.xack(stream_key, CONSUMER_GROUP, msg_id)
        return

    # Step 2: 构造风控检查用的消息
    int_amount = int(float(amount))

    # Step 2b: order_target(xxx, 0) 清仓卖出 - amount=0时查询持仓确定实际卖出量
    if action == "sell" and int_amount == 0:
        try:
            positions = engine.get_positions()
            qmt_code = security.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")
            for pos in positions:
                if pos.get("security") == qmt_code and pos.get("available", 0) > 0:
                    int_amount = pos["available"]
                    logger.info(f"[清仓补量] {security} amount=0 → 查持仓可用{int_amount}股")
                    break
            if int_amount == 0:
                logger.warning(f"[清仓跳过] {security} 无可用持仓，跳过卖出")
                r.xack(stream_key, CONSUMER_GROUP, msg_id)
                r.sadd(DEDUP_SET_KEY, msg_id)
                r.expire(DEDUP_SET_KEY, DEDUP_TTL_SEC)
                return
        except Exception as e:
            logger.error(f"[清仓查持仓异常] {security}: {e}")
            r.xack(stream_key, CONSUMER_GROUP, msg_id)
            return

    order_msg = {
        "security": security,
        "action": action,
        "amount": int_amount,
        "price": float(price),
        "stream_key": stream_key,
        "strategy": strategy,
    }

    # Step 3: 风控检查
    passed, reason = risk_mgr.check(order_msg)
    if not passed:
        # 风控拦截 - 记录但不执行，仍然ACK
        result = {
            "order_id": order_id,
            "msg_id": msg_id,
            "status": "rejected",
            "reason": reason,
            "time": datetime.now().isoformat(),
        }
        r.xack(stream_key, CONSUMER_GROUP, msg_id)
        r.sadd(DEDUP_SET_KEY, msg_id)
        r.expire(DEDUP_SET_KEY, DEDUP_TTL_SEC)
        logger.warning(f"[风控拒绝] {security} {action}: {reason}")
        return

    # Step 4: 执行下单（含重试，最多3次）
    MAX_RETRY = 3
    result = None

    for attempt in range(MAX_RETRY):
        result = engine.execute_order(order_msg)
        if result.get("success"):
            break
        if attempt < MAX_RETRY - 1:
            logger.warning(f"[下单重试] {security} {action} 第{attempt+1}次失败: {result.get('message')}，2秒后重试")
            time.sleep(2)
        else:
            logger.error(f"[下单失败] {security} {action}: {result.get('message')}（已重试{MAX_RETRY}次）")

    if not result.get("success"):
        # 下单失败且不重试：ACK + 记录 + 报警（写Redis告警key）
        r.xack(stream_key, CONSUMER_GROUP, msg_id)
        r.sadd(DEDUP_SET_KEY, msg_id)
        r.expire(DEDUP_SET_KEY, DEDUP_TTL_SEC)
        try:
            r.set("jq:alert:order_fail", json.dumps({"security": security, "action": action, "msg": result.get("message"), "time": datetime.now().isoformat()}, ensure_ascii=False), ex=3600)
        except Exception:
            pass
        return

    # Step 5: 记录结果
    result["order_id"] = order_id
    result["msg_id"] = msg_id
    result["strategy"] = strategy
    result["time"] = datetime.now().isoformat()

    if result.get("success"):
        logger.info(f"[下单成功] {security} {action} {amount}股@{price} "
                     f"→ 委托号={result.get('order_id')}")
    else:
        logger.error(f"[下单失败] {security} {action}: {result.get('message')}")

    # Step 6: ACK消息 + 记录去重
    r.xack(stream_key, CONSUMER_GROUP, msg_id)
    r.sadd(DEDUP_SET_KEY, msg_id)
    r.expire(DEDUP_SET_KEY, DEDUP_TTL_SEC)

    # Step 7: 将执行结果写入结果Stream（供聚宽侧查询）
    result_stream = stream_key.replace(":stream:", ":result:")
    try:
        # Redis Stream只接受string值，转换所有字段
        str_result = {k: str(v) for k, v in result.items()}
        r.xadd(result_stream, str_result, maxlen=1000)
    except Exception as e:
        logger.error(f"[写入结果Stream失败] {e}")


# ==================== QMT连接健康检查线程 ====================
def _qmt_health_check_thread(r: redis.Redis, engine):
    """
    QMT连接健康检查线程：每分钟检查一次QMT连接状态。
    如果检测到连接断开，自动重连。
    
    核心逻辑：
    1. 调用 engine.health_check() 查询余额验证连接
    2. 如果不健康，标记断开并尝试重连（最多6次）
    3. 重连成功后写Redis通知
    4. 非交易时段(15:00后~次日9:30)降低检查频率（每5分钟一次）
    """
    logger.info("[QMT健康检查] 监控线程已启动")
    
    def _is_trading_hours():
        """判断当前是否在交易时段"""
        now = datetime.now()
        t = now.strftime("%H:%M")
        # 工作日 + 交易时段
        if now.weekday() >= 5:  # 周六周日
            return False
        return ("09:25" <= t <= "11:35") or ("12:55" <= t <= "15:05")
    
    while not shutdown_event.is_set():
        try:
            # 交易时段每60秒检查，非交易时段每300秒检查
            check_interval = QMT_HEALTH_CHECK_INTERVAL if _is_trading_hours() else 300
            
            # 执行健康检查
            healthy = engine.health_check()
            
            if not healthy:
                logger.warning("[QMT健康检查] ⚠ 检测到QMT连接断开！开始自动重连...")
                # 重连尝试
                reconnected = False
                for attempt in range(1, QMT_RECONNECT_MAX_RETRY + 1):
                    if shutdown_event.is_set():
                        break
                    logger.info(f"[QMT健康检查] 重连第{attempt}/{QMT_RECONNECT_MAX_RETRY}次...")
                    if engine.reconnect():
                        logger.info(f"[QMT健康检查] ✅ 重连成功（第{attempt}次尝试）")
                        reconnected = True
                        # 写Redis通知（Bridge/聚宽侧可读）
                        try:
                            r.set("jq:qmt:reconnect", datetime.now().isoformat(), ex=3600)
                        except Exception:
                            pass
                        break
                    if attempt < QMT_RECONNECT_MAX_RETRY:
                        shutdown_event.wait(QMT_RECONNECT_RETRY_INTERVAL)
                
                if not reconnected:
                    logger.error(f"[QMT健康检查] ❌ 重连失败！已重试{QMT_RECONNECT_MAX_RETRY}次")
                    logger.error("[QMT健康检查] 请检查QMT是否已启动并登录")
            else:
                # 连接正常，静默（不刷日志）
                pass
                
        except Exception as e:
            logger.error(f"[QMT健康检查异常] {e}")
        
        # 等待下次检查，可被shutdown_event提前唤醒
        shutdown_event.wait(check_interval)
    
    logger.info("[QMT健康检查] 监控线程已停止")

def _heartbeat_thread(r: redis.Redis):
    """
    Consumer心跳线程：每5分钟写入Redis，TTL=600秒
    Bridge的/health端点检查此key判断是否存活
    """
    logger.info("[心跳] 心跳线程已启动")
    while not shutdown_event.is_set():
        try:
            r.set(HEARTBEAT_KEY, datetime.now().isoformat(), ex=HEARTBEAT_INTERVAL * 2)
        except Exception:
            pass
        # 等待5分钟或被shutdown_event唤醒
        shutdown_event.wait(HEARTBEAT_INTERVAL)
    logger.info("[心跳] 心跳线程已停止")


def position_query_thread(r: redis.Redis, engine):
    """
    监听持仓查询请求，返回执行端持仓数据
    聚宽侧发送请求到 QUERY_POSITIONS_REQ_KEY
    本线程响应到 QUERY_POSITIONS_RESP_KEY
    """
    logger.info("[持仓查询] 响应线程已启动")
    while not shutdown_event.is_set():
        try:
            # BLPOP等待查询请求
            result = r.blpop(QUERY_POSITIONS_REQ_KEY, timeout=2)
            if result is None:
                continue

            _, req_data = result
            logger.info("[持仓查询] 收到请求")

            # 查询持仓
            positions = engine.get_positions()
            balance = engine.get_balance()

            # 连接健康检查：持仓0 + 余额空 → 连接可能断开
            if len(positions) == 0 and not balance:
                logger.warning("[持仓查询] QMT持仓=0且余额为空，连接可能断开，标记为不可靠")
                # 返回特殊标记，让Bridge侧知道数据不可靠
                response = {
                    "positions": "[]",
                    "balance": "{}",
                    "time": datetime.now().isoformat(),
                    "engine_type": type(engine).__name__,
                    "unreliable": True,
                    "reason": "QMT连接疑似断开：持仓=0且余额为空",
                }
            else:
                response = {
                    "positions": json.dumps(positions, ensure_ascii=False),
                    "balance": json.dumps(balance, ensure_ascii=False),
                    "time": datetime.now().isoformat(),
                    "engine_type": type(engine).__name__,
                }
            r.rpush(QUERY_POSITIONS_RESP_KEY, json.dumps(response, ensure_ascii=False))
            r.expire(QUERY_POSITIONS_RESP_KEY, QUERY_TIMEOUT_SEC * 2)
            logger.info(f"[持仓查询] 响应完成，持仓{len(positions)}只")

        except Exception as e:
            if not shutdown_event.is_set():
                logger.error(f"[持仓查询异常] {e}")
                time.sleep(2)

    logger.info("[持仓查询] 响应线程已停止")


# ==================== Stream消费主循环 ====================
def consume_streams(r: redis.Redis, engine):
    """
    主消费循环：同时监听所有策略的Stream
    使用XREADGROUP阻塞读取
    """
    risk_mgr = RiskManager()

    # 构建监听的Stream列表: {stream_key: ">"} — ">"表示只读新消息
    stream_keys = list(STREAM_KEYS.values())
    read_args = {sk: ">" for sk in stream_keys}

    logger.info(f"[消费循环] 开始监听 {len(stream_keys)} 个Stream:")
    for sk in stream_keys:
        logger.info(f"  - {sk}")

    # 启动持仓查询响应线程
    query_thread = Thread(target=position_query_thread, args=(r, engine), daemon=True)
    query_thread.start()

    # 启动心跳线程
    heartbeat_thread = Thread(target=_heartbeat_thread, args=(r,), daemon=True)
    heartbeat_thread.start()

    # 启动QMT连接健康检查线程
    qmt_health_thread = Thread(target=_qmt_health_check_thread, args=(r, engine), daemon=True)
    qmt_health_thread.start()

    # 先处理pending消息（之前未ACK的）
    _process_pending(r, engine, risk_mgr, stream_keys)

    # 主循环
    while not shutdown_event.is_set():
        try:
            # XREADGROUP阻塞读取
            messages = r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams=read_args,
                count=10,
                block=BLOCK_TIMEOUT_MS if BLOCK_TIMEOUT_MS > 0 else 5000,
            )

            if not messages:
                continue

            for stream_key, stream_messages in messages:
                # 卖单优先：先处理所有sell信号，再处理buy信号
                # 避免"先买入占满资金→卖出无法执行"的竞态
                sorted_messages = sorted(
                    stream_messages,
                    key=lambda m: 0 if m[1].get("action", "") == "sell" else 1
                )
                for msg_id, msg_data in sorted_messages:
                    try:
                        process_message(r, engine, risk_mgr, stream_key, msg_id, msg_data)
                    except Exception as e:
                        logger.error(f"[处理消息异常] stream={stream_key} id={msg_id}: {e}")
                        # 异常时也ACK，避免死循环
                        try:
                            r.xack(stream_key, CONSUMER_GROUP, msg_id)
                        except Exception:
                            pass

        except redis.ConnectionError:
            logger.warning("[Redis] 连接断开，5秒后重连...")
            time.sleep(5)
            try:
                r = create_redis_client()
            except Exception:
                pass

        except Exception as e:
            if not shutdown_event.is_set():
                logger.error(f"[消费循环异常] {e}")
                time.sleep(2)

    logger.info("[消费循环] 已停止")


def _process_pending(r: redis.Redis, engine, risk_mgr: RiskManager, stream_keys: list):
    """处理启动时的pending消息（上次未ACK的）"""
    logger.info("[Pending] 检查未ACK的消息...")
    total_pending = 0
    for stream_key in stream_keys:
        try:
            # 读取pending消息（id="0"表示从头读取pending）
            pending = r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={stream_key: "0"},
                count=100,
            )
            if pending:
                for _, msgs in pending:
                    for msg_id, msg_data in msgs:
                        if msg_data:  # 有数据才处理
                            logger.info(f"[Pending] 处理遗留消息: {stream_key} {msg_id}")
                            try:
                                process_message(r, engine, risk_mgr, stream_key, msg_id, msg_data)
                            except Exception as e:
                                logger.error(f"[Pending处理异常] {msg_id}: {e}")
                                r.xack(stream_key, CONSUMER_GROUP, msg_id)
                            total_pending += 1
        except Exception as e:
            logger.warning(f"[Pending检查异常] {stream_key}: {e}")

    logger.info(f"[Pending] 共处理 {total_pending} 条遗留消息")


# ==================== 入口 ====================
def main():
    logger.info("=" * 60)
    logger.info("  聚宽→Redis→执行端 消费者服务启动")
    logger.info(f"  时间: {datetime.now().isoformat()}")
    logger.info(f"  Redis: {REDIS_HOST}:{REDIS_PORT}")
    logger.info(f"  Consumer Group: {CONSUMER_GROUP}")
    logger.info(f"  Consumer Name: {CONSUMER_NAME}")
    logger.info("=" * 60)

    # 1. 连接Redis
    r = create_redis_client()

    # 2. 确保Consumer Group存在
    ensure_consumer_groups(r)

    # 3. 创建执行引擎
    engine = create_engine()
    logger.info(f"[执行引擎] 类型: {type(engine).__name__}")

    # 连接执行引擎（QMT/THS）- 启动时重试最多6次，每次间隔10秒
    # 即使启动时连接失败，健康检查线程也会持续尝试重连
    connected = False
    for attempt in range(1, QMT_RECONNECT_MAX_RETRY + 1):
        if engine.connect():
            logger.info(f"[执行引擎] 连接成功（第{attempt}次尝试）")
            connected = True
            break
        else:
            if attempt < QMT_RECONNECT_MAX_RETRY:
                logger.warning(f"[执行引擎] 连接失败（第{attempt}/{QMT_RECONNECT_MAX_RETRY}次），{QMT_RECONNECT_RETRY_INTERVAL}秒后重试...")
                time.sleep(QMT_RECONNECT_RETRY_INTERVAL)
            else:
                logger.error(f"[执行引擎] 启动时连接失败！已重试{QMT_RECONNECT_MAX_RETRY}次")
                logger.error("[执行引擎] 健康检查线程将在运行中持续尝试重连，请确保QMT已启动并登录")

    # 4. 启动消费循环
    try:
        consume_streams(r, engine)
    finally:
        engine.disconnect()
        logger.info("消费者服务已关闭")


if __name__ == "__main__":
    main()