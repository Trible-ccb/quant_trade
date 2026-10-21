# -*- coding: utf-8 -*-
"""
聚宽 -> 飞书群 信号拦截器（飞书应用版）

用法：
    from feishu_signal_interceptor import FeishuSignalInterceptor
    interceptor = FeishuSignalInterceptor(
        app_id='cli_xxxxxxxxxxxx',
        app_secret='xxxxxxxxxxxxxxxx',
        chat_id='oc_xxxxxxxxxxxxxxxx',      # 目标群 chat_id
        strategy_name='我的策略'
    )
    order, order_target, order_value, order_target_value = \
        interceptor.wrap_orders(order, order_target, order_value, order_target_value)
"""

import json
import time
import uuid
import requests

# ---------- 默认配置 ----------
APP_ID       = '***'
APP_SECRET   = '***'
CHAT_ID      = '***'      # 目标群 ID
STRATEGY_NAME = 'JQ_STRATEGY'
FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'


class FeishuSignalInterceptor:
    """聚宽下单拦截器：将所有 order 调用以飞书应用身份发到指定群"""

    def __init__(self,
                 app_id=APP_ID,
                 app_secret=APP_SECRET,
                 chat_id=CHAT_ID,
                 strategy_name=STRATEGY_NAME,
                 timeout=5,
                 enable=True,
                 notify_empty=False):
        """
        Args:
            app_id / app_secret: 飞书企业自建应用凭证
            chat_id: 目标群 chat_id（oc_ 开头）
            strategy_name: 策略标识
            timeout: HTTP 超时（秒）
            enable: 是否启用推送
            notify_empty: 成交量为 0 是否也推送
        """
        self.config = {
            'app_id': app_id,
            'app_secret': app_secret,
            'chat_id': chat_id,
            'strategy_name': strategy_name,
            'timeout': timeout,
            'enable': enable,
            'notify_empty': notify_empty,
        }
        self._original_funcs = {}
        self._installed = False
        # token 缓存
        self._token = None
        self._token_expire_at = 0.0

    # ---------- 获取 tenant_access_token（带缓存）----------
    def _get_token(self):
        now = time.time()
        if self._token and self._token_expire_at - 60 > now:
            return self._token

        url = f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal'
        try:
            resp = requests.post(url, json={
                'app_id': self.config['app_id'],
                'app_secret': self.config['app_secret'],
            }, timeout=self.config['timeout'])
            data = resp.json()
            if data.get('code') != 0:
                print(f"[飞书Token失败] {data}")
                return None
            self._token = data['tenant_access_token']
            self._token_expire_at = now + int(data.get('expire', 7200))
            return self._token
        except Exception as e:
            print(f"[飞书Token异常] {e}")
            return None

    # ---------- 发送飞书卡片 ----------
    def _send_feishu(self, signal):
        if not self.config['enable']:
            return

        action = signal['action']
        if action == 'buy':
            template, emoji, action_cn = 'green', '🟢', '买入'
        else:
            template, emoji, action_cn = 'red', '🔴', '卖出'

        amount = signal['amount']
        price = signal['price']
        est_value = f"{amount * price:,.2f}" if price > 0 else "市价"
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(signal['gen_time']))

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} {action_cn}信号 | {signal['strategy']}"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**代码**\n{signal['stock']}"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**数量**\n{amount} 股"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**成交价**\n{price if price > 0 else '市价'}"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**预估金额**\n{est_value}"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**下单时间**\n{time_str}"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**毫秒时间戳**\n{signal['timestamp']}"}},
                        {"is_short": True, "text": {"tag": "lark_md",
                            "content": f"**消息 ID**\n`{signal['msg_id']}`"}},
                    ]
                },
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text",
                         "content": f"策略: {signal['strategy']}  |  msg_id={signal['msg_id']}"}
                    ]
                }
            ]
        }

        token = self._get_token()
        if not token:
            print("[飞书发送跳过] 无有效 token")
            return

        url = f'{FEISHU_API_BASE}/im/v1/messages'
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=utf-8',
        }
        # 关键：content 必须是"字符串形式的 JSON"
        payload = {
            'receive_id': self.config['chat_id'],
            'msg_type': 'interactive',
            'content': json.dumps(card, ensure_ascii=False),
        }

        try:
            resp = requests.post(
                url,
                params={'receive_id_type': 'chat_id'},
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers=headers,
                timeout=self.config['timeout'],
            )
            result = resp.json()
            if result.get('code') != 0:
                print(f"[飞书发送失败] {result}")
            else:
                print(f"[飞书发送] msg_id={signal['msg_id']} {action_cn} "
                      f"{signal['stock']} {amount}股 price={price} ts={signal['timestamp']}")
        except Exception as e:
            print(f"[飞书发送异常] {e}")

    # ---------- 构造信号并推送 ----------
    def _push_signal(self, action, security, amount, price=None):
        try:
            if '.XSHG' in security:
                stock = security.replace('.XSHG', '.SH')
            elif '.XSHE' in security:
                stock = security.replace('.XSHE', '.SZ')
            else:
                stock = security

            now = time.time()
            signal = {
                'msg_id': uuid.uuid4().hex[:12],
                'timestamp': int(now * 1000),
                'gen_time': now,
                'strategy': self.config['strategy_name'],
                'action': action,
                'stock': stock,
                'amount': int(amount),
                'price': float(price) if price is not None else 0.0,
            }
            self._send_feishu(signal)
        except Exception as e:
            print(f"[信号构造失败] {e}")

    def _handle_result(self, result, security):
        try:
            if result is None:
                return
            filled = getattr(result, 'filled', 0) or 0
            if filled > 0 or self.config['notify_empty']:
                self._push_signal(
                    'buy' if getattr(result, 'is_buy', True) else 'sell',
                    security,
                    abs(filled),
                    getattr(result, 'price', None),
                )
        except Exception as e:
            print(f"[结果处理异常] {e}")

    # ---------- 包装函数 ----------
    def _wrap_order(self, security, amount, style=None):
        result = self._original_funcs['order'](security, amount, style)
        self._handle_result(result, security)
        return result

    def _wrap_order_target(self, security, target_amount, style=None):
        result = self._original_funcs['order_target'](security, target_amount, style)
        self._handle_result(result, security)
        return result

    def _wrap_order_value(self, security, value, style=None):
        result = self._original_funcs['order_value'](security, value, style)
        self._handle_result(result, security)
        return result

    def _wrap_order_target_value(self, security, target_value, style=None):
        result = self._original_funcs['order_target_value'](security, target_value, style)
        self._handle_result(result, security)
        return result

    # ---------- 安装 ----------
    def wrap_orders(self, order, order_target, order_value, order_target_value):
        if self._installed:
            print("[拦截器] 已安装，跳过重复安装")
            return (self._wrap_order, self._wrap_order_target,
                    self._wrap_order_value, self._wrap_order_target_value)

        self._original_funcs = {
            'order': order,
            'order_target': order_target,
            'order_value': order_value,
            'order_target_value': order_target_value,
        }
        self._installed = True
        print("✅ 聚宽下单拦截器已安装（飞书应用版），信号将发送到群:", self.config['chat_id'])
        return (self._wrap_order, self._wrap_order_target,
                self._wrap_order_value, self._wrap_order_target_value)