# -*- coding: utf-8 -*-
"""
Windows 服务端 - 从 Redis 获取聚宽下单信号，通过 EasyTHS HTTP API 驱动同花顺自动交易

依赖安装：
    pip install redis httpx

使用前提：
    1. 已启动 EasyTHS 服务端（默认 http://127.0.0.1:7648）
    2. 同花顺下单程序 xiadan.exe 已打开并登录

运行：
    python redis_to_ths_server.py
"""

import redis
import json
import base64
import time
import sys
import logging
from datetime import datetime

import httpx

# ==================== 配置区域 ====================
# --- Redis 配置（与聚宽发送端一致）---
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = '1A2B3C4D'
REDIS_KEY = 'QMT_SIGNAL'
REDIS_DB = 0

# --- EasyTHS 服务端配置 ---
EASYTHS_BASE_URL = 'http://127.0.0.1:7648'
# 优先从环境变量读取（BAT 会注入），便于集中管理；也可直接硬编码字符串
import os
EASYTHS_API_KEY = os.environ.get('EASYTHS_API_KEY', '')   # 留空则不带认证头
EASYTHS_TIMEOUT = 30.0

# --- 下单重试配置 ---
MAX_RETRY = 3
RETRY_DELAY = 2
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ths_trader.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class RedisSignalConsumer:
    """从 Redis 消费聚宽下单信号，通过 EasyTHS API 驱动同花顺下单"""

    def __init__(self):
        self.redis_client = None
        self.http_client = None
        self.running = False

    # ---------- 连接初始化 ----------
    def connect_redis(self):
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=None,
            health_check_interval=30,
            protocol=2
        )
        self.redis_client.ping()
        logger.info(f"✅ Redis 连接成功 ({REDIS_HOST}:{REDIS_PORT}, db={REDIS_DB})")

    def connect_easyths(self):
        """初始化 HTTP 客户端并检查 EasyTHS 服务健康状态"""
        headers = {}
        if EASYTHS_API_KEY:
            headers['Authorization'] = f'Bearer {EASYTHS_API_KEY}'

        self.http_client = httpx.Client(
            base_url=EASYTHS_BASE_URL,
            headers=headers,
            timeout=EASYTHS_TIMEOUT
        )

        # 健康检查
        try:
            resp = self.http_client.get('/api/v1/system/health')
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"✅ EasyTHS 服务端连接成功 (health={data.get('data', data)})")
        except Exception as e:
            logger.error(f"❌ EasyTHS 服务端连接失败: {e}")
            raise

    # ---------- 信号解析与校验（与之前完全一致）----------
    def decode_signal(self, raw_data):
        try:
            json_str = base64.b64decode(raw_data.encode('ascii')).decode('utf-8')
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"❌ 信号解析失败: {e}, raw={raw_data[:100]}")
            return None

    def validate_signal(self, signal):
        required_fields = ['id', 'action', 'stock', 'amount']
        for field in required_fields:
            if field not in signal:
                logger.error(f"❌ 信号缺少字段 '{field}': {signal}")
                return False
        if signal['action'] not in ('buy', 'sell'):
            logger.error(f"❌ 非法操作类型: {signal['action']}")
            return False
        if signal['amount'] <= 0:
            logger.error(f"❌ 非法数量: {signal['amount']}")
            return False
        return True

    # ---------- EasyTHS 下单执行 ----------
    def execute_order(self, signal):
        """
        通过 EasyTHS RESTful API 执行下单
        EasyTHS 的 buy/sell 接口参数：
            - stock_code: 股票代码（纯数字，如 '600519'）
            - price: 委托价格（float）
            - amount: 委托数量（int）
            - account_name: 可选，多账户时指定目标账户
        """
        action = signal['action']          # 'buy' 或 'sell'
        stock = signal['stock']             # QMT 格式，如 '600519.SH'
        amount = int(signal['amount'])
        price = float(signal.get('price', 0.0))
        signal_id = signal['id']

        # QMT 格式 -> 纯数字代码
        stock_code = stock.split('.')[0]

        # 如果价格为 0，说明发送端未提供有效价格，使用市价单
        use_market = (price <= 0)

        logger.info(
            f"📤 执行下单 | id={signal_id} | {action} {stock_code} "
            f"{amount}股 | price={'市价' if use_market else price}"
        )

        for attempt in range(1, MAX_RETRY + 1):
            try:
                if use_market:
                    # 市价单接口（EasyTHS 1.7.0+ 支持）
                    endpoint = f'/api/v1/operations/market_{action}'
                    payload = {
                        'stock_code': stock_code,
                        'amount': amount,
                    }
                else:
                    # 限价单接口
                    endpoint = f'/api/v1/operations/{action}'
                    payload = {
                        'stock_code': stock_code,
                        'price': price,
                        'amount': amount,
                    }

                resp = self.http_client.post(endpoint, json=payload)
                resp.raise_for_status()
                result = resp.json()

                # EasyTHS 统一响应信封：{"data": {...}, "error_code": null, ...}
                error_code = result.get('error_code')
                if error_code:
                    logger.warning(
                        f"⚠️ EasyTHS 返回错误 (尝试 {attempt}/{MAX_RETRY}) | "
                        f"id={signal_id} | error_code={error_code} | {result}"
                    )
                    # client_rejected 表示同花顺拒绝（涨跌停/资金不足等），不可原样重试
                    if error_code == 'client_rejected':
                        logger.error(f"❌ 同花顺拒绝委托 | id={signal_id}")
                        return False
                    # not_connected 表示客户端未连接，需重连
                    if error_code == 'not_connected':
                        logger.warning("🔄 尝试重连同花顺客户端...")
                        self.http_client.post('/api/v1/system/reconnect')
                    if attempt < MAX_RETRY:
                        time.sleep(RETRY_DELAY)
                        continue
                    return False

                logger.info(f"✅ 下单成功 | id={signal_id} | {action} {stock_code}")
                return True

            except httpx.TimeoutException:
                logger.warning(
                    f"⚠️ EasyTHS 请求超时 (尝试 {attempt}/{MAX_RETRY}) | id={signal_id}"
                )
                # 超时情况下操作可能仍在执行，不重复提交，等待后查询确认
                if attempt < MAX_RETRY:
                    time.sleep(RETRY_DELAY * 2)  # 超时后等待更长时间
                    continue
                return False

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"⚠️ HTTP 错误 {e.response.status_code} "
                    f"(尝试 {attempt}/{MAX_RETRY}) | id={signal_id}"
                )
                # 408 表示等待结果超时（操作仍在执行），勿重复提交
                if e.response.status_code == 408:
                    logger.warning(f"⏳ EasyTHS 返回 408，操作可能仍在执行，不重复提交 | id={signal_id}")
                    return False
                if attempt < MAX_RETRY:
                    time.sleep(RETRY_DELAY)
                    continue
                return False

            except Exception as e:
                logger.warning(
                    f"⚠️ 下单异常 (尝试 {attempt}/{MAX_RETRY}) | "
                    f"id={signal_id} | 错误: {e}"
                )
                if attempt < MAX_RETRY:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"❌ 下单最终失败 | id={signal_id} | {action} {stock_code}")
                    return False

        return False

    # ---------- 主循环 ----------
    def run(self):
        self.running = True
        logger.info("🚀 服务端启动，开始监听 Redis 信号...")
        logger.info(f"   队列键名: {REDIS_KEY}")
        logger.info(f"   EasyTHS: {EASYTHS_BASE_URL}")

        while self.running:
            try:
                result = self.redis_client.blpop(REDIS_KEY, timeout=5)

                if result is None:
                    continue

                _, raw_data = result
                signal = self.decode_signal(raw_data)
                if signal is None:
                    continue

                if not self.validate_signal(signal):
                    continue

                self.execute_order(signal)

            except redis.ConnectionError as e:
                logger.error(f"🔌 Redis 连接断开: {e}，5秒后重连...")
                time.sleep(5)
                try:
                    self.connect_redis()
                except Exception as re:
                    logger.error(f"Redis 重连失败: {re}")

            except KeyboardInterrupt:
                logger.info("收到退出信号")
                self.running = False
                break

            except Exception as e:
                logger.error(f"处理信号时发生未预期错误: {e}", exc_info=True)
                time.sleep(1)

    def stop(self):
        self.running = False
        if self.http_client:
            self.http_client.close()
        logger.info("服务端已停止")


# ==================== 入口 ====================
if __name__ == '__main__':
    consumer = RedisSignalConsumer()

    try:
        consumer.connect_redis()
        consumer.connect_easyths()
        consumer.run()
    except Exception as e:
        logger.critical(f"服务端启动失败: {e}", exc_info=True)
        sys.exit(1)