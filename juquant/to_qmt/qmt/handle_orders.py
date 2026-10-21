# encoding:gbk
import redis
import json
import time
import datetime
import base64   # 新增导入，用于 Base64 解码

# ---------- 配置区域 ----------
ACCOUNT_ID = 'xxx'
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = '1A2B3C4D'

SIGNAL_MAX_DELAY = 30   # 最大允许延迟（秒）
REDIS_KEY = 'QMT_SIGNAL'

# -----------------------------

# 幂等去重集合
PROCESSED_IDS = set()

def init(ContextInfo):
    ContextInfo.account_id = ACCOUNT_ID
    ContextInfo.set_account(ACCOUNT_ID)
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    ContextInfo.run_time('poll_redis_signals', '500nMilliSecond', formatted_time)
    print(f"✅ QMT信号接收器已启动，账号：{ACCOUNT_ID}")

def order_callback(ContextInfo, orderInfo):
    print(f'orderInfo {orderInfo}')

def is_kcb_stock(stock_code):
    """判断是否为科创板股票（代码以688开头）"""
    return stock_code.startswith('688')

def poll_redis_signals(ContextInfo):
    r = None
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=0,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3
        )
        
        while True:
            item = r.rpop(REDIS_KEY)
            if not item:
                break
            
            # ---------- 新增：对 item 进行 Base64 解码 ----------
            try:
                decoded_item = base64.b64decode(item).decode('utf-8')
            except Exception as e:
                print(f"[解码失败] 跳过该消息: {e}")
                continue
            # ----------------------------------------------------
            
            msg_data = json.loads(decoded_item)   # 使用解码后的字符串
            signal_id = msg_data.get('id')
            gen_time = float(msg_data.get('gen_time', 0))
            action = msg_data.get('action')
            strategy = msg_data.get('strategy')

            stock_code = msg_data.get('stock')
            amount = int(msg_data.get('amount', 0))
            signal_price = float(msg_data.get('price', 0))   # 聚宽传来的价格
            
            current_time = datetime.datetime.now()
            now = current_time.timestamp()
            delay = now - gen_time if gen_time > 0 else -1
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

            print(f"{formatted_time}[接收信号] id={signal_id} 延迟{delay:.3f}秒, 策略={strategy}, action={action}, stock={stock_code}, amount={amount}, price={signal_price}")

            # 幂等检查
            if signal_id is None or signal_id in PROCESSED_IDS:
                print(f"[幂等忽略] 已处理过信号 id={signal_id}")
                continue
            
            if delay > SIGNAL_MAX_DELAY:   # 超过30秒丢弃
                continue   # 不执行下单，直接处理下一条

            PROCESSED_IDS.add(signal_id)
            
            if amount == 0:
                print(f"[amount为0] 跳过下单, id={signal_id}")
                continue
            
            # ---------- 科创板保护限价处理 ----------
            is_kcb = is_kcb_stock(stock_code)
            
            # 确定操作类型和订单类型
            if action == 'buy':
                op_type = 23   # 买入
                # 限价单：使用聚宽传来的价格作为限价
                # 如果是科创板，该价格同时作为"买入保护限价"（最高买价）
                order_price = signal_price * (1 + 0.005) if signal_price > 0 else 0
                print(f"[准备买入] {stock_code} {amount}股, 限价={order_price}" +
                         (f", 科创板保护限价={order_price}" if is_kcb else ""))
                         
            elif action == 'sell':
                op_type = 24   # 卖出
                order_price = signal_price * (1 - 0.005) if signal_price > 0 else 0
                print(f"[准备卖出] {stock_code} {amount}股, 限价={order_price}" +
                         (f", 科创板保护限价={order_price}" if is_kcb else ""))
            else:
                print(f"[未知指令] {action}，跳过, id={signal_id}")
                continue
            
            # 执行下单（使用passorder，支持限价）
            # orderType=1101 表示限价单
            # prType=11 表示按股数下单
            # quickTrade=1 表示快速下单
            try:
                passorder(
                    op_type,                           # 23买入 / 24卖出
                    1101,                              # 1101=限价单
                    ContextInfo.account_id,            # 资金账号
                    stock_code,                        # 股票代码
                    11,                                # 11=按股数下单
                    order_price,                       # 限价价格（科创板同时作为保护限价）
                    amount,                            # 数量（正数）
                    f"QMT_{strategy}",                # 用户自定义ID
                    1,                                 # 快速下单
                    f"{signal_id}",                     # 订单信息
                    ContextInfo                        # 上下文
                )
                print(f"[执行{action}] {stock_code} {amount}股, 价格={order_price} 订单Id={signal_id}" +
                         (f", 科创板保护限价已设置" if is_kcb else ""))
            except Exception as e:
                print(f"[下单失败] {e}, id={signal_id}")
            
            time.sleep(0.1)
            
    except Exception as e:
        import traceback
        # https://zhuanlan.zhihu.com/p/719313500 
        print(f"[轮询异常] {e}\n{traceback.format_exc()}")
    finally:
        if r:
            try:
                r.connection_pool.disconnect()
            except:
                pass