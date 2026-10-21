# -*- coding: utf-8 -*-
"""
Redis 消息驱动的同花顺自动交易机器人（无价格输入版）

架构说明：
┌──────────────────┐     Redis Pub/Sub     ┌──────────────────────┐
│  量化策略系统     │ ────────────────────> │  本机器人            │
│  (产生交易信号)   │     trade_signals     │  (执行买卖操作)      │
└──────────────────┘                       └──────────┬───────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────────┐
                                              │  同花顺客户端         │
                                              │  (键盘模拟下单)       │
                                              └──────────────────────┘

核心流程：
1. 订阅 Redis 频道，实时监听交易信号
2. 收到信号后解析 JSON 数据
3. 验证信号有效性（策略名称、标的、操作方向、数量）
4. 通过 AutoTrader 键盘模拟操作同花顺客户端下单
5. 不手动输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）

与原版区别：
- 移除了滑点计算逻辑（Slippage_ETF / Slippage_Stock）
- 移除了 truncate_price 函数
- 买入/卖出时不传价格参数，使用同花顺界面自动填充的价格
- 导入 PythonAutoTrade_noprice 而非 PythonAutoTrade

信号格式（JSON）：
{
    "strategy_name": "策略名称_True",      // 策略名称必须在 strategy_list 中，才被视为实盘信号
    "security": "600000.XSHG",             // 标的代码（支持聚宽格式，自动截取前6位）
    "action": "buy",                        // 操作方向：buy 或 sell
    "amount_diff": 1000,                    // 下单数量（股），优先使用此字段
    "current_price": 10.5,                  // 当前价格（本版本不使用此字段计算下单价格）
    "weight": "10%",                        // 持仓权重
    "trade_value": 10500.0                  // 交易金额
}

安全机制：
1. 全局 asyncio.Lock 确保同一时刻只处理一笔交易，避免窗口/键盘冲突
2. 买入前校验可用资金，资金不足直接跳过，避免废单
3. 卖出价异常（<= 0）时直接跳过
4. 交易成功后刷新账户信息缓存

环境要求：
1. Windows 系统（键盘模拟依赖 ctypes）
2. 运行同花顺客户端（xiadan.exe）并登录账户
3. 在 .env 文件中配置 REDIS_URL
4. 在 自动交易配置.json 中配置同花顺窗口标题关键词（可选）
5. 安装依赖：pip install redis
6. 同花顺客户端需设置自动填充卖二/买二价格
"""

import asyncio
import json
import logging
import logging.handlers
import redis
import sys
import time
from datetime import datetime
from PythonAutoTrade_noprice import AutoTrader

# 要处理的策略名称列表，在这列表中表示实盘信号
strategy_list = ["五福52V2_多ETF"]

# 全局日志配置（输出到控制台和文件）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 文件记录（滚动模式，单文件最大 10MB，保留 3 个备份）
file_handler = logging.handlers.RotatingFileHandler(
    'redis_trade.log', encoding='utf-8', maxBytes=10*1024*1024, backupCount=3
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 日志别名
log = logger

# 全局变量：同花顺交易器实例（单例模式）
trader = None

# 全局锁，防止并发交易导致窗口/键盘混乱
trade_lock = asyncio.Lock()

# 账户信息缓存
account_info_cache = {}

# Redis 连接配置(根据自己服务器修改)
redis_host = "211.2.2.2"
redis_port = 9527
redis_password = "123654"

# Redis 超时配置（秒）
redis_socket_timeout = 30        # 读取操作超时时间
redis_socket_connect_timeout = 10  # socket连接超时时间
redis_health_check_interval = 30  # 健康检查间隔
redis_max_idle_time = 120        # 最大空闲时间（无消息/Ping响应则断开）

def init_redis():
    """初始化 Redis 连接
    
    使用 IP、端口和密码的连接方式
    启用 TCP 保活机制防止连接空闲断开
    设置超时参数，避免连接长时间阻塞
    连接失败时输出错误日志并退出程序
    """
    try:
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            socket_keepalive=True,
            socket_timeout=redis_socket_timeout,
            socket_connect_timeout=redis_socket_connect_timeout,
            health_check_interval=redis_health_check_interval
        )
        client.ping()
        log.info("✅ 成功连接到 Redis (%s:%d)", redis_host, redis_port)
        log.info("   ├─ 连接超时: %d秒", redis_socket_connect_timeout)
        log.info("   ├─ 读取超时: %d秒", redis_socket_timeout)
        log.info("   └─ 健康检查: %d秒", redis_health_check_interval)
        return client
    except Exception as e:
        log.error(f"❌ Redis 连接失败: {e}")
        sys.exit(1)


def init_ths_trader():
    """初始化同花顺交易器
    
    创建 AutoTrader 实例，后续用于键盘模拟下单
    初始化失败时输出错误详情并返回 False
    """
    global trader
    
    try:
        trader = AutoTrader()
        log.info("✅ 同花顺交易器初始化成功")
        return True
    except Exception as e:
        log.error(f"❌ 同花顺交易器初始化失败: {e}", exc_info=True)
        return False


async def execute_trade(signal):
    """执行交易信号（线程安全，无价格输入版）
    
    通过全局 trade_lock 串行化所有交易操作，避免并发导致同花顺窗口/键盘状态混乱。
    不计算下单价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）。
    
    参数：
        signal: dict，解析后的交易信号 JSON
    
    返回：
        bool，交易是否成功
    
    信号验证逻辑：
    1. 策略名称必须在 strategy_list 中（实盘信号标识）
    2. 必须包含 security（标的）和 action（操作方向）
    3. action 只能是 buy 或 sell
    4. 下单数量必须大于 0
    
    执行流程：
    1. 解析信号字段
    2. 验证信号有效性
    3. 买入前检查可用资金（避免废单）
    4. 调用 AutoTrader 执行买入/卖出（不传价格，使用界面自动填充）
    5. 交易成功后刷新账户信息缓存
    """
    global trader, account_info_cache
    
    async with trade_lock:
        try:
            # 1. 解析信号字段
            strategy_name = signal.get('strategy_name', '未知策略')
            security = signal.get('security')
            action = signal.get('action')
            price = signal.get('current_price')
            weight = signal.get('weight', '0%')
            
            # 优先使用 amount_diff（策略计算的实际下单数量），兼容 amount 字段
            amount = signal.get('amount_diff', signal.get('amount', 0))
            
            # 2. 信号有效性验证,strategy_list中的策略名称表示实盘信号
            if strategy_name not in strategy_list:
                log.warning(f"⚠️ 跳过模拟信号 [{strategy_name}]")
                return False
            
            # 必要字段检查
            if not security or not action:
                log.warning("⚠️ 信号缺少必要字段: security 或 action")
                return False
            
            # 操作方向验证
            if action not in ['buy', 'sell']:
                log.warning(f"⚠️ 无效操作类型: {action}")
                return False
            
            # 输出信号详情日志
            log.info(f"📡 收到交易信号 [{strategy_name}]")
            log.info(f"   ├─ 操作: {action.upper()}")
            log.info(f"   ├─ 标的: {security}")
            log.info(f"   ├─ 价格: {price:.3f} 元（参考，实际由界面自动填充）")
            log.info(f"   ├─ 数量: {amount} 股")
            log.info(f"   └─ 权重: {weight}")
            
            # 确保交易器实例存在
            if not trader:
                trader = AutoTrader()
            
            # 买入操作
            if action == 'buy':            
                if amount <= 0:
                    log.warning("⚠️ 下单数量无效（<= 0）")
                    return False
                
                # 买入前实时查询可用资金（不使用缓存，确保数据准确）
                account_info = trader.query() or {}
                account_info_cache = account_info
                available = account_info.get('available', 0)
                estimated_cost = (price or 0) * amount
                if available > 0 and estimated_cost > available:
                    log.warning(f"⚠️ 可用资金不足: 需要 {estimated_cost:.2f}，仅有 {available:.2f}，跳过买入")
                    return False
                
                log.info(f"   ├─ 下单价格: 由同花顺界面自动填充（卖二价）")
                
                # 不传价格参数，使用同花顺界面自动填充
                success = trader.buy(security, amount)
                time.sleep(1)  # 等待键盘模拟完成
                
                if success:
                    log.info(f"✅ 买入成功: {security} {amount}股")
                else:
                    log.error(f"❌ 买入失败: {security}")
            
            # 卖出操作
            else:
                if amount <= 0:
                    log.warning("⚠️ 下单数量无效（<= 0）")
                    return False
                
                log.info(f"   ├─ 下单价格: 由同花顺界面自动填充（买二价）")
                
                # 不传价格参数，使用同花顺界面自动填充
                success = trader.sell(security, amount)
                time.sleep(5)  # 卖出后等待5秒，确保卖单成交、资金到账后再查询
                
                if success:
                    log.info(f"✅ 卖出成功: {security} {amount}股")
                else:
                    log.error(f"❌ 卖出失败: {security}")
            
            # 交易成功后刷新账户信息
            if success:
                log.info("📊 交易成功后刷新账户信息...")
                account_info_cache = trader.query() or {}
                if account_info_cache:
                    log.info(f"   ├─ 可用金额: {account_info_cache.get('available', 0):.2f}")
                    log.info(f"   └─ 总资产: {account_info_cache.get('total_asset', 0):.2f}")
            
            return success
                
        except Exception as e:
            log.error(f"❌ 执行交易失败: {e}", exc_info=True)
            return False


async def process_message(message):
    """处理 Redis 消息
    
    参数：
        message: dict，Redis pubsub 返回的消息结构
    
    处理流程：
    1. 提取频道名称和消息内容
    2. 尝试解析 JSON 格式
    3. 如果是交易信号频道（trade_signals），调用 execute_trade 执行
    4. 非交易信号仅记录日志
    
    异常处理：
    - JSON 解析失败时输出原始消息内容，方便排查问题
    """
    if message['type'] == 'message':
        # 提取频道和消息内容
        channel = message['channel'].decode('utf-8')
        data_raw = message['data'].decode('utf-8')
        
        log.info(f"\n📩 收到来自频道 [{channel}] 的消息")
        
        # 尝试解析 JSON
        try:
            data_json = json.loads(data_raw)
            log.info(f"📋 解析后的信号: {json.dumps(data_json, indent=2, ensure_ascii=False)}")
            
            # 交易信号频道处理，防止有其他频道消息干扰
            if channel == 'trade_signals':
                await execute_trade(data_json)
            else:
                log.info(f"ℹ️ 非交易信号，频道: {channel}")
                
        except json.JSONDecodeError:
            log.warning("⚠️ 消息不是有效的 JSON 格式")
            log.info(f"📝 原始内容: {data_raw}")


async def redis_listener(redis_client):
    """Redis 消息监听协程（带自动重连机制和超时断开检测）
    
    参数：
        redis_client: redis.Redis，Redis 客户端实例
    
    功能：
    1. 订阅指定频道（默认 trade_signals）
    2. 循环监听消息，收到后调用 process_message 处理
    3. 每 redis_health_check_interval 秒发送 Ping 保活
    4. 空闲超时检测：超过 redis_max_idle_time 秒无响应则主动断开重连
    5. 连接断开时自动重连（指数退避策略）
    
    重连机制：
    - 初始等待 1 秒
    - 每次失败后等待时间翻倍（最大 60 秒）
    - 重连成功后重置等待时间为 1 秒
    
    退出方式：
    - 按 Ctrl+C 终止程序
    """
    channel_name = "trade_signals"
    pubsub = None
    last_activity_time = time.time()
    last_ping_time = time.time()
    reconnect_delay = 1  # 初始重连等待时间（秒）
    
    def create_pubsub():
        """创建新的 pubsub 订阅对象
        
        先清理旧连接（如果存在），再创建新订阅
        """
        nonlocal pubsub
        if pubsub:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except:
                pass
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel_name)
        log.info(f"📡 已订阅频道: '{channel_name}'，正在等待消息... (按 Ctrl+C 退出)")
    
    # 初始订阅
    create_pubsub()
    
    try:
        while True:
            try:
                # 获取消息（非阻塞模式，立即返回）
                message = pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    await process_message(message)
                    last_activity_time = time.time()
                
                # 健康检查：发送 Ping 保活
                if time.time() - last_ping_time > redis_health_check_interval:
                    try:
                        redis_client.ping()
                        last_ping_time = time.time()
                        last_activity_time = time.time()
                        log.debug("📡 Redis 连接保活 Ping")
                    except redis.exceptions.TimeoutError:
                        log.warning(f"⚠️ Redis Ping 超时（{redis_socket_timeout}秒），主动断开重连")
                        raise redis.exceptions.ConnectionError("Ping timeout")
                    except redis.exceptions.ConnectionError as ce:
                        log.warning(f"⚠️ Redis Ping 失败: {ce}")
                        raise ce
                
                # 空闲超时检测：超过最大空闲时间则主动断开重连
                idle_time = time.time() - last_activity_time
                if idle_time > redis_max_idle_time:
                    log.warning(f"⚠️ Redis 连接空闲超时（{idle_time:.1f}秒 > {redis_max_idle_time}秒），主动断开重连")
                    raise redis.exceptions.ConnectionError("Idle timeout")
                
                # 短暂休眠，降低 CPU 占用
                await asyncio.sleep(0.1)
                
                # 重置重连等待时间（连接正常时）
                reconnect_delay = 1
                
            except redis.exceptions.ConnectionError as e:
                # Redis 连接断开处理
                log.error(f"❌ Redis 连接断开: {e}")
                log.info(f"🔄 等待 {reconnect_delay} 秒后重新连接...")
                await asyncio.sleep(reconnect_delay)
                
                try:
                    # 尝试恢复连接
                    redis_client.ping()
                    log.info("✅ Redis 连接恢复")
                    create_pubsub()
                    last_activity_time = time.time()
                    last_ping_time = time.time()
                    reconnect_delay = 1
                except Exception as re:
                    # 重连失败，增加等待时间
                    log.error(f"❌ 重新连接失败: {re}")
                    reconnect_delay = min(reconnect_delay * 2, 60)
            
            except redis.exceptions.TimeoutError as e:
                # 操作超时处理
                log.error(f"❌ Redis 操作超时: {e}")
                log.info("🔄 尝试重新连接...")
                reconnect_delay = min(reconnect_delay * 2, 60)
                await asyncio.sleep(reconnect_delay)
                try:
                    redis_client.ping()
                    log.info("✅ Redis 连接恢复")
                    create_pubsub()
                    last_activity_time = time.time()
                    last_ping_time = time.time()
                    reconnect_delay = 1
                except Exception as re:
                    log.error(f"❌ 重新连接失败: {re}")
            
            except Exception as e:
                # 其他异常处理
                log.error(f"❌ 消息处理异常: {e}")
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        # 用户中断处理
        log.info("\n👋 正在停止监听...")
        if pubsub:
            pubsub.unsubscribe(channel_name)
            pubsub.close()


async def main():
    """主程序入口
    
    执行流程：
    1. 初始化 Redis 连接
    2. 初始化同花顺交易器
    3. 启动时查询账户信息
    4. 启动 Redis 消息监听协程
    
    异常处理：
    - 任何步骤失败都会记录日志并终止程序
    """
    log.info("="*60)
    log.info("Redis 消息驱动的同花顺自动交易机器人（无价格输入版）")
    log.info("="*60)
    
    try:
        # 1. 连接 Redis
        log.info("🔌 连接 Redis...")
        redis_client = init_redis()
        
        # 2. 初始化同花顺交易器
        log.info("🔌 初始化同花顺交易器...")
        if not init_ths_trader():
            return
        
        # 3. 启动时查询账户信息
        log.info("📊 启动时查询账户信息...")
        account_info = trader.query()
        if account_info:
            log.info("   ├─ 资金余额: %.2f" % account_info.get('fund_balance', 0))
            log.info("   ├─ 可用金额: %.2f" % account_info.get('available', 0))
            log.info("   ├─ 可取金额: %.2f" % account_info.get('withdrawable', 0))
            log.info("   ├─ 股票市值: %.2f" % account_info.get('stock_market_value', 0))
            log.info("   ├─ 持仓盈亏: %.2f" % account_info.get('position_pnl', 0))
            log.info("   └─ 总资产: %.2f" % account_info.get('total_asset', 0))
        else:
            log.info("   └─ 控件读取失败（请手动查看）")
        
        # 4. 启动消息监听（阻塞直到用户中断）
        await redis_listener(redis_client)
        
    except Exception as e:
        log.error(f"❌ 主程序异常: {e}", exc_info=True)


if __name__ == "__main__":
    # 启动异步事件循环
    asyncio.run(main())
    
#-------------------------------------以上为re_dis_trading_bot_ths_noprice.py代码-----------------------------#
