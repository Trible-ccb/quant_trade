# encoding:gbk
"""
QMT 飞书信号接收器
功能：轮询飞书群消息 -> 解析下单指令 -> passorder 下单
"""
import re
import json
import time
import datetime
import traceback
import requests

# ==================== 配置区域 ====================
FEISHU_APP_ID     = '***'      # 飞书应用 App ID
FEISHU_APP_SECRET = '***'  # 飞书应用 App Secret
FEISHU_CHAT_ID    = '***'       # 目标群 chat_id

ACCOUNT_ID        = '***'                        # QMT 资金账号

# 轮询与过滤
POLL_INTERVAL_SEC   = 2       # run_time 轮询间隔（秒）
POLL_PAGE_SIZE      = 50      # 每页拉取条数（飞书最大 50）
SIGNAL_MAX_DELAY    = 60      # 消息超过此秒数则丢弃
STARTUP_LOOKBACK    = 10      # 首次启动回看秒数（避免拉取历史消息）
OVERLAP_SEC         = 2       # 每次拉取向前重叠秒数，防漏消息（靠 msg_id 去重）

# 价格保护比例（与 Redis 版本保持一致）
PRICE_BUY_ADJUST    = 1.005
PRICE_SELL_ADJUST   = 0.995

FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'
# =================================================

# ---------- 全局状态 ----------
PROCESSED_MSG_IDS = set()          # 已处理的 message_id（幂等）
LAST_FETCH_TS     = 0.0            # 上次拉取到的结束时间（秒）
_TOKEN_CACHE      = {'token': None, 'expire_at': 0}


# ==================== 初始化 ====================
def init(ContextInfo):
    ContextInfo.account_id = ACCOUNT_ID
    ContextInfo.set_account(ACCOUNT_ID)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ContextInfo.run_time('poll_feishu_signals', f'{POLL_INTERVAL_SEC}nSecond', now_str)
    print(f"✅ QMT 飞书信号接收器已启动 | 账号={ACCOUNT_ID} | 群={FEISHU_CHAT_ID}")


def order_callback(ContextInfo, orderInfo):
    print(f'orderInfo {orderInfo}')


# ==================== 飞书 token ====================
def get_tenant_access_token():
    """获取/复用 tenant_access_token（提前 60 秒刷新）"""
    now = time.time()
    if _TOKEN_CACHE['token'] and _TOKEN_CACHE['expire_at'] - 60 > now:
        return _TOKEN_CACHE['token']

    url = f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal'
    try:
        resp = requests.post(url, json={
            'app_id': FEISHU_APP_ID,
            'app_secret': FEISHU_APP_SECRET,
        }, timeout=5)
        data = resp.json()
        if data.get('code') != 0:
            print(f"[飞书Token失败] {data}")
            return None
        _TOKEN_CACHE['token'] = data['tenant_access_token']
        _TOKEN_CACHE['expire_at'] = now + int(data.get('expire', 7200))
        return _TOKEN_CACHE['token']
    except Exception as e:
        print(f"[飞书Token异常] {e}")
        return None


# ==================== 拉取消息 ====================
def fetch_feishu_messages(token, start_ts, end_ts):
    """拉取 [start_ts, end_ts] 秒区间内的群消息（自动翻页）"""
    url = f'{FEISHU_API_BASE}/im/v1/messages'
    headers = {'Authorization': f'Bearer {token}'}
    all_items = []
    page_token = None
    max_pages = 5  # 一次最多拉 5 页，避免卡死

    for _ in range(max_pages):
        params = {
            'container_id_type': 'chat',
            'container_id': FEISHU_CHAT_ID,
            'start_time': int(start_ts),
            'end_time': int(end_ts),
            'sort_type': 'ByCreateTimeAsc',
            'page_size': POLL_PAGE_SIZE,
        }
        if page_token:
            params['page_token'] = page_token

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            data = resp.json()
        except Exception as e:
            print(f"[飞书拉取异常] {e}")
            return all_items

        if data.get('code') != 0:
            print(f"[飞书拉取失败] {data}")
            return all_items

        page_data = data.get('data', {})
        all_items.extend(page_data.get('items', []))

        if not page_data.get('has_more'):
            break
        page_token = page_data.get('page_token')
        if not page_token:
            break

    return all_items


# ==================== 消息解析 ====================
def normalize_action(a):
    a = str(a).strip().lower()
    if a in ('buy', 'b', '买入', '买', '多', '开多'):
        return 'buy'
    if a in ('sell', 's', '卖出', '卖', '空', '平多', '清仓'):
        return 'sell'
    return None


def normalize_stock(code):
    code = str(code).strip().upper()
    if '.XSHG' in code:
        return code.replace('.XSHG', '.SH')
    if '.XSHE' in code:
        return code.replace('.XSHE', '.SZ')
    return code


def parse_signal(text):
    """
    解析下单指令，支持两种格式：
      1) JSON: {"action":"buy","stock":"600519.SH","amount":100,"price":1720.5}
      2) 文本: "买入 600519.SH 100 1720.5"  /  "buy 600519.SH 100"
    返回 (action, stock, amount, price) 或 None
    """
    if not text:
        return None
    text = text.strip()

    # --- JSON 优先 ---
    if text.startswith('{'):
        try:
            obj = json.loads(text)
            action = normalize_action(obj.get('action', ''))
            stock = normalize_stock(obj.get('stock', ''))
            amount = int(float(obj.get('amount', 0) or 0))
            price = float(obj.get('price', 0) or 0)
            if action and stock and amount > 0:
                return action, stock, amount, price
        except Exception as e:
            print(f"[JSON解析失败] {e} | 原文: {text}")
        return None

    # --- 文本格式 ---
    parts = text.replace(',', ' ').split()
    if len(parts) < 3:
        return None
    action = normalize_action(parts[0])
    if not action:
        return None
    stock = normalize_stock(parts[1])
    try:
        amount = int(float(parts[2]))
    except Exception:
        return None
    price = 0.0
    if len(parts) >= 4:
        try:
            price = float(parts[3])
        except Exception:
            price = 0.0
    if not stock or amount <= 0:
        return None
    return action, stock, amount, price


# ==================== 下单执行 ====================
def execute_order(ContextInfo, action, stock_code, amount, price, msg_id):
    is_kcb = stock_code.startswith('688')  # 科创板

    if action == 'buy':
        op_type = 23
        order_price = price * PRICE_BUY_ADJUST if price > 0 else 0
    elif action == 'sell':
        op_type = 24
        order_price = price * PRICE_SELL_ADJUST if price > 0 else 0
    else:
        print(f"[未知指令] {action} msg_id={msg_id}")
        return

    try:
        passorder(
            op_type,                          # 23买入 / 24卖出
            1101,                             # 1101=限价单
            ContextInfo.account_id,
            stock_code,
            11,                               # 11=按股数下单
            order_price,                      # 限价（科创板同时作为保护限价）
            amount,
            f"FS_{ContextInfo.account_id}",   # 自定义ID
            1,                                # 快速下单
            str(msg_id),                      # 订单信息
            ContextInfo,
        )
        print(f"[执行{action}] {stock_code} {amount}股 价格={order_price} "
              f"msg_id={msg_id}{' (科创板)' if is_kcb else ''}")
    except Exception as e:
        print(f"[下单失败] {e} msg_id={msg_id}")

# ==================== 卡片解析 ====================
def _extract_field(card, label):
    """
    从交互式卡片的 div.fields 中按 label 提取内容
    label 形如 '代码' / '数量' / '成交价' / '消息 ID'
    返回去掉前后空白与反引号后的字符串，找不到返回 None
    """
    for elem in card.get('elements', []):
        if elem.get('tag') != 'div':
            continue
        for field in elem.get('fields', []):
            text_obj = field.get('text', {})
            content = text_obj.get('content', '')
            # 格式固定为：**标签**\n值
            if content.startswith(f'**{label}**'):
                value = content.split('\n', 1)[-1].strip()
                # 去掉 markdown 反引号
                value = value.replace('`', '').strip()
                return value
    return None


def parse_interactive_card(card_json_str):
    """
    解析聚宽 _send_feishu 发出的交互式卡片，返回 (action, stock, amount, price, jq_msg_id)
    失败返回 None
    """
    try:
        card = json.loads(card_json_str)
    except Exception as e:
        print(f"[卡片解析失败] JSON 错误: {e}")
        return None

    # ---- 1. 从 header 判断买卖方向 ----
    title = card.get('header', {}).get('title', {}).get('content', '')
    if '买入' in title:
        action = 'buy'
    elif '卖出' in title:
        action = 'sell'
    else:
        print(f"[卡片解析失败] 无法识别方向: title={title!r}")
        return None

    # ---- 2. 逐字段提取 ----
    stock_raw = _extract_field(card, '代码')
    amount_raw = _extract_field(card, '数量')
    price_raw = _extract_field(card, '成交价')
    jq_msg_id = _extract_field(card, '消息 ID')

    if not stock_raw or not amount_raw:
        print(f"[卡片解析失败] 缺少 代码/数量 stock={stock_raw} amount={amount_raw}")
        return None

    stock = normalize_stock(stock_raw)

    # 数量：'100 股' → 100
    try:
        amount = int(re.sub(r'[^\d]', '', amount_raw))
    except Exception:
        print(f"[卡片解析失败] 数量非法: {amount_raw!r}")
        return None

    # 价格：'市价' → 0.0；'1720.5' → 1720.5
    price = 0.0
    if price_raw and '市价' not in price_raw:
        try:
            price = float(re.sub(r'[^\d.]', '', price_raw))
        except Exception:
            price = 0.0

    return action, stock, amount, price, jq_msg_id

# ==================== 主轮询函数 ====================
def poll_feishu_signals(ContextInfo):
    global LAST_FETCH_TS
    try:
        now_ts = time.time()

        if LAST_FETCH_TS == 0:
            LAST_FETCH_TS = now_ts - STARTUP_LOOKBACK

        start_ts = max(0, LAST_FETCH_TS - OVERLAP_SEC)
        end_ts = now_ts

        token = get_tenant_access_token()
        if not token:
            return

        msgs = fetch_feishu_messages(token, start_ts, end_ts)
        LAST_FETCH_TS = end_ts

        for msg in msgs:
            feishu_msg_id = msg.get('message_id')
            if not feishu_msg_id or feishu_msg_id in PROCESSED_MSG_IDS:
                continue

            msg_type = msg.get('msg_type')
            create_time_ms = int(msg.get('create_time', 0))
            delay = now_ts - create_time_ms / 1000.0
            content_str = msg.get('body', {}).get('content', '')

            # ---- 1. 只处理我们关心的两种消息 ----
            if msg_type not in ('interactive', 'text'):
                PROCESSED_MSG_IDS.add(feishu_msg_id)
                continue

            # ---- 2. 过期消息丢弃 ----
            if delay > SIGNAL_MAX_DELAY:
                print(f"[过期忽略] msg_id={feishu_msg_id} 延迟{delay:.1f}s")
                PROCESSED_MSG_IDS.add(feishu_msg_id)
                continue

            # ---- 3. 按类型解析 ----
            signal = None
            jq_msg_id = None

            if msg_type == 'interactive':
                # 聚宽 _send_feishu 发出的卡片
                parsed = parse_interactive_card(content_str)
                if parsed:
                    action, stock, amount, price, jq_msg_id = parsed
                    signal = (action, stock, amount, price)

            elif msg_type == 'text':
                # 兼容手工输入 / 其他程序发来的文本
                try:
                    body = json.loads(content_str)
                    text = str(body.get('text', ''))
                except Exception:
                    text = content_str
                text = re.sub(r'^\s*@\S+\s*', '', text).strip()
                parsed = parse_signal(text)
                if parsed:
                    signal = parsed

            # ---- 4. 解析失败：记录后跳过（避免重复解析同一条）----
            if signal is None:
                PROCESSED_MSG_IDS.add(feishu_msg_id)
                continue

            # ---- 5. 去重 + 下单 ----
            PROCESSED_MSG_IDS.add(feishu_msg_id)
            action, stock, amount, price = signal

            print(f"[接收飞书信号] feishu_msg_id={feishu_msg_id} jq_msg_id={jq_msg_id} "
                  f"延迟{delay:.2f}s action={action} stock={stock} amount={amount} price={price}")

            execute_order(ContextInfo, action, stock, amount, price,
                          jq_msg_id or feishu_msg_id)

    except Exception as e:
        print(f"[轮询异常] {e}\n{traceback.format_exc()}")