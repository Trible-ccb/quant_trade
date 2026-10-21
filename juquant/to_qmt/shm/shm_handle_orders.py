# encoding:gbk
import datetime
import time
from shm_queue import SharedMemoryQueue

# ---------- 配置区域 ----------
ACCOUNT_ID = '***'
SIGNAL_MAX_DELAY = 30   # 最大允许延迟（秒）

# -----------------------------

# 幂等去重集合
PROCESSED_IDS = set()
shm_queue = None

def init(ContextInfo):
    global shm_queue
    ContextInfo.account_id = ACCOUNT_ID
    ContextInfo.set_account(ACCOUNT_ID)
    
    # 附加到已存在的共享内存（create=False）
    try:
        shm_queue = SharedMemoryQueue(create=False)
        print("✅ QMT共享内存读取器已启动，成功附加到共享内存")
    except FileNotFoundError:
        print("❌ 启动失败：共享内存未找到，请确保外部Redis桥接进程已启动")
        return

    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    ContextInfo.run_time('poll_shm_signals', '500nMilliSecond', formatted_time)
    print(f"✅ QMT信号接收器已启动，账号：{ACCOUNT_ID}")

def order_callback(ContextInfo, orderInfo):
    print(f'orderInfo {orderInfo}')

def is_kcb_stock(stock_code):
    return stock_code.startswith('688')

def poll_shm_signals(ContextInfo):
    global shm_queue
    if shm_queue is None:
        return
        
    try:
        while True:
            # 从共享内存读取信号
            msg_data = shm_queue.pop()
            if not msg_data:
                break  # 队列为空，跳出循环
            
            signal_id = msg_data.get('id')
            gen_time = float(msg_data.get('gen_time', 0))
            action = msg_data.get('action')
            strategy = msg_data.get('strategy')
            stock_code = msg_data.get('stock')
            amount = int(msg_data.get('amount', 0))
            signal_price = float(msg_data.get('price', 0))
            
            current_time = datetime.datetime.now()
            now = current_time.timestamp()
            delay = now - gen_time if gen_time > 0 else -1
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

            print(f"{formatted_time}[接收信号] id={signal_id} 延迟{delay:.3f}秒, 策略={strategy}, action={action}, stock={stock_code}, amount={amount}, price={signal_price}")

            # 幂等检查
            if signal_id is None or signal_id in PROCESSED_IDS:
                print(f"[幂等忽略] 已处理过信号 id={signal_id}")
                continue
            
            if delay > SIGNAL_MAX_DELAY:
                print(f"[过期信号] 延迟{delay:.3f}秒超过{SIGNAL_MAX_DELAY}秒，丢弃 id={signal_id}")
                continue

            PROCESSED_IDS.add(signal_id)
            
            if amount == 0:
                print(f"[amount为0] 跳过下单, id={signal_id}")
                continue
            
            is_kcb = is_kcb_stock(stock_code)
            
            if action == 'buy':
                op_type = 23
                order_price = signal_price * (1 + 0.005) if signal_price > 0 else 0
                print(f"[准备买入] {stock_code} {amount}股, 限价={order_price}" + (f", 科创板保护限价={order_price}" if is_kcb else ""))
            elif action == 'sell':
                op_type = 24
                order_price = signal_price * (1 - 0.005) if signal_price > 0 else 0
                print(f"[准备卖出] {stock_code} {amount}股, 限价={order_price}" + (f", 科创板保护限价={order_price}" if is_kcb else ""))
            else:
                print(f"[未知指令] {action}，跳过, id={signal_id}")
                continue
            
            try:
                passorder(
                    op_type, 1101, ContextInfo.account_id, stock_code,
                    11, order_price, amount, f"QMT_{strategy}",
                    1, f"{signal_id}", ContextInfo
                )
                print(f"[执行{action}] {stock_code} {amount}股, 价格={order_price} 订单Id={signal_id}")
            except Exception as e:
                print(f"[下单失败] {e}, id={signal_id}")
            
            time.sleep(0.1)
            
    except Exception as e:
        import traceback
        print(f"[轮询异常] {e}\n{traceback.format_exc()}")