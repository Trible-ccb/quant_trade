# -*- coding: utf-8 -*-
"""
聚宽 -> Redis 信号拦截器 (独立类)
集成授权验证服务 (产品码: jq_and_qmt)

用法：
    from redis_signal_interceptor import RedisSignalInterceptor
    interceptor = RedisSignalInterceptor(
        host='你的公网IP',
        port=6379,
        password='你的密码',
        key='QMT_SIGNAL',
        strategy_name='我的策略',
        authorization_code='LIC-DEMO-XXXX-XXXX'   # 必填，用于激活
    )
    # 安装拦截器（返回包装后的下单函数）
    order, order_target, order_value, order_target_value = interceptor.wrap_orders(
        order, order_target, order_value, order_target_value
    )
    # 此后所有 order 调用自动推送信号，并保持授权心跳
"""

import redis
import json
import time
import uuid
import functools
import base64
import hashlib
import socket
import platform
import requests

# -------------------- 配置区域（可覆盖） --------------------
HOST = 'xxx'                 # Redis 服务器公网 IP
AUTH_CODE = 'yyy' # 授权码

PASSWORD = '1A2B3C4D'        # Redis 密码
STRATEGY_NAME = 'JQ_STRATEGY'
API_BASE_URL = 'https://lic.cedar-v.com'   # 授权云平台地址
PRODUCT_CODE = 'jq_and_qmt'                # 固定产品码
# ----------------------------------------------------------

class RedisSignalInterceptor:
    """
    聚宽下单拦截器，将所有 order 系列函数的调用自动转换为 Redis 信号，
    并集成授权验证（激活 + 心跳保活）。
    """

    def __init__(self,
                 host=HOST,
                 password=PASSWORD,
                 port=6379,
                 key='QMT_SIGNAL',
                 strategy_name=STRATEGY_NAME,
                 authorization_code=AUTH_CODE,
                 product_code=PRODUCT_CODE,
                 software_version='1.0.0',
                 auto_activate=True):
        """
        初始化拦截器配置

        Args:
            host: Redis 服务器公网 IP
            port: Redis 端口
            password: Redis 密码
            key: 信号队列的键名（QMT端需保持一致）
            strategy_name: 策略标识，用于多策略区分
            authorization_code: 授权码（必填，否则无法激活）
            product_code: 产品码，固定为 'jq_and_qmt'
            software_version: 客户端软件版本
            auto_activate: 是否自动激活并启动心跳（默认 True）
        """
        self.config = {
            'host': host,
            'port': port,
            'password': password,
            'key': key,
            'strategy_name': strategy_name,
            'db': 0,
            'socket_connect_timeout': 5,
            'socket_timeout': 5
        }
        self._original_funcs = {}   # 保存原始下单函数引用
        self._installed = False     # 拦截器是否已安装

        # ---------- 授权相关属性 ----------
        self.authorization_code = authorization_code
        self.product_code = product_code
        self.software_version = software_version
        self.hardware_fingerprint = self._generate_fingerprint()
        self.license_key = None
        self.license_file = None
        self.public_key = None
        self.heartbeat_interval = 300          # 默认值，激活后会覆盖
        self.activated = False
        self.config_updated_at = None          # 上次配置更新时间（RFC3339）
        self.usage_data = {}                   # 可自定义上报的使用数据
        self._heartbeat_thread = None
        self._stop_heartbeat = False

        # 自动激活 & 心跳
        if auto_activate and authorization_code:
            self.activate()
            self.heartbeat()

    # -------------------- 硬件指纹生成 --------------------
    def _generate_fingerprint(self):
        """生成当前设备的唯一硬件指纹（基于主机名 + MAC 地址的 SHA256）"""
        try:
            mac = uuid.getnode()
            hostname = socket.gethostname()
            fingerprint_str = f"{hostname}-{mac}"
            return hashlib.sha256(fingerprint_str.encode()).hexdigest()
        except Exception as e:
            # 保底方案：使用随机 UUID（不推荐，但避免程序崩溃）
            print(f"⚠️ 生成硬件指纹失败，使用备用方案: {e}")
            return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()

    # -------------------- 授权激活 --------------------
    def activate(self):
        """
        调用在线激活接口，获取许可证和公钥。
        激活失败会抛出异常。
        """
        if not self.authorization_code:
            raise ValueError("缺少授权码，请在初始化时传入 authorization_code")

        url = f"{API_BASE_URL}/api/v1/activate"
        payload = {
            "authorization_code": self.authorization_code,
            "hardware_fingerprint": self.hardware_fingerprint,
            "product_code": self.product_code,
            "software_version": self.software_version,
            "device_info": {
                "os": platform.system(),
                "hostname": socket.gethostname()
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get('code') == '000000':
                data = result['data']
                self.license_key = data['license_key']
                self.license_file = data['license_file']
                self.public_key = data['public_key']
                self.heartbeat_interval = data.get('heartbeat_interval', 300)
                self.activated = True
                self.config_updated_at = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
                print(f"✅ 授权激活成功，许可证: {self.license_key}")
            else:
                raise Exception(f"激活失败 [{result.get('code')}]: {result.get('message')}")
        except requests.RequestException as e:
            raise Exception(f"激活网络异常: {e}")
        except Exception as e:
            raise Exception(f"激活异常: {e}")

    # -------------------- 心跳同步 --------------------
    def heartbeat(self):
        """
        执行一次心跳同步，上报状态并检查配置更新。
        若返回新的 license_file，则自动替换本地许可证（简化版，未做验签）。
        """
        if not self.activated or not self.license_key:
            print("⚠️ 未激活，跳过心跳")
            return

        url = f"{API_BASE_URL}/api/v1/heartbeat"
        payload = {
            "license_key": self.license_key,
            "hardware_fingerprint": self.hardware_fingerprint,
            "config_updated_at": self.config_updated_at,
            "usage_data": self.usage_data,
            "software_version": self.software_version
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get('code') == '000000':
                data = result['data']
                # 检查是否有配置更新
                if data.get('config_updated') and data.get('license_file'):
                    new_license_file = data['license_file']
                    # 建议此处使用本地保存的公钥验签，这里简化直接替换
                    self.license_file = new_license_file
                    print("🔄 许可证已更新（配置变更）")
                if data.get('heartbeat_interval'):
                    self.heartbeat_interval = data['heartbeat_interval']
                # 更新本地配置时间
                self.config_updated_at = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            else:
                # 处理错误码（如许可证撤销等）
                if result.get('code') in ('300007',):  # 许可证已被撤销
                    self.activated = False
                    print(f"❌ 许可证已被撤销，授权失效")
                else:
                    print(f"⚠️ 心跳失败 [{result.get('code')}]: {result.get('message')}")
        except requests.RequestException as e:
            print(f"⚠️ 心跳网络异常: {e}")
        except Exception as e:
            print(f"⚠️ 心跳异常: {e}")

    # -------------------- Redis 信号推送 --------------------
    def _get_redis_client(self):
        """获取 Redis 连接（每次使用后自动释放）"""
        return redis.Redis(
            host=self.config['host'],
            port=self.config['port'],
            password=self.config['password'],
            db=self.config['db'],
            decode_responses=True,
            socket_connect_timeout=self.config['socket_connect_timeout'],
            socket_timeout=self.config['socket_timeout']
        )

    def _push_signal(self, action, security, amount, price=None):
        """
        推送信号到 Redis List（Base64 编码）
        """
        try:
            # 聚宽代码格式转换 -> QMT格式
            if '.XSHG' in security:
                qmt_code = security.replace('.XSHG', '.SH')
            elif '.XSHE' in security:
                qmt_code = security.replace('.XSHE', '.SZ')
            else:
                qmt_code = security

            signal = {
                'id': uuid.uuid4().hex,
                'gen_time': time.time(),
                'strategy': self.config['strategy_name'],
                'action': action,          # 'buy' 或 'sell'
                'stock': qmt_code,
                'amount': int(amount),
                'price': float(price) if price is not None else 0.0
            }

            json_str = json.dumps(signal)
            encoded_signal = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

            r = self._get_redis_client()
            r.lpush(self.config['key'], encoded_signal)
            r.ltrim(self.config['key'], 0, 999)   # 保留最近1000条
            r.connection_pool.disconnect()

            print(f"[信号推送] {action} {qmt_code} {amount}股, price={price}, id={signal['id']}")
        except Exception as e:
            print(f"[信号推送失败] {e}")

    # ---------- 包装下单函数 ----------
    def _wrap_order(self, security, amount, style=None):
        result = self._original_funcs['order'](security, amount, style)
        if result and result.filled > 0:
            self._push_signal(
                'buy' if result.is_buy else 'sell',
                security,
                abs(result.filled),
                getattr(result, 'price', None)
            )
        return result

    def _wrap_order_target(self, security, target_amount, style=None):
        result = self._original_funcs['order_target'](security, target_amount, style)
        if result and result.filled > 0:
            self._push_signal(
                'buy' if result.is_buy else 'sell',
                security,
                abs(result.filled),
                getattr(result, 'price', None)
            )
        return result

    def _wrap_order_value(self, security, value, style=None):
        result = self._original_funcs['order_value'](security, value, style)
        if result and result.filled > 0:
            self._push_signal(
                'buy' if result.is_buy else 'sell',
                security,
                abs(result.filled),
                getattr(result, 'price', None)
            )
        return result

    def _wrap_order_target_value(self, security, target_value, style=None):
        result = self._original_funcs['order_target_value'](security, target_value, style)
        if result and result.filled > 0:
            self._push_signal(
                'buy' if result.is_buy else 'sell',
                security,
                abs(result.filled),
                getattr(result, 'price', None)
            )
        return result

    # ---------- 安装拦截器 ----------
    def wrap_orders(self, order, order_target, order_value, order_target_value):
        """
        安装拦截器：保存原始下单函数，并返回包装后的函数。
        调用后，请将返回的四个函数赋值回原全局变量以生效。
        若未激活，将抛出异常。

        Args:
            order: 原始 order 函数
            order_target: 原始 order_target 函数
            order_value: 原始 order_value 函数
            order_target_value: 原始 order_target_value 函数

        Returns:
            (wrapped_order, wrapped_order_target, wrapped_order_value, wrapped_order_target_value)
        """
        if not self.activated:
            raise RuntimeError("未激活，请先激活授权或设置 auto_activate=True 并提供授权码")

        if self._installed:
            print("[拦截器] 已经安装，跳过重复安装")
            return (self._wrap_order, self._wrap_order_target,
                    self._wrap_order_value, self._wrap_order_target_value)

        # 保存原始函数
        self._original_funcs = {
            'order': order,
            'order_target': order_target,
            'order_value': order_value,
            'order_target_value': order_target_value,
        }
        self._installed = True
        print("✅ 聚宽下单拦截器已安装，下单信号将自动推送至 Redis（Base64 编码）")
        return (self._wrap_order, self._wrap_order_target,
                self._wrap_order_value, self._wrap_order_target_value)

    # ---------- 辅助方法 ----------
    def is_activated(self):
        """返回当前激活状态"""
        return self.activated

    def set_usage_data(self, data):
        """更新使用数据（将在下一次心跳时上报）"""
        self.usage_data.update(data)