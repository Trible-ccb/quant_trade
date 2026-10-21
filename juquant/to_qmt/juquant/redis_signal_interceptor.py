# -*- coding: utf-8 -*-
"""
聚宽 -> Redis 信号拦截器 (独立类)
用法：
    from redis_signal_interceptor import RedisSignalInterceptor
    interceptor = RedisSignalInterceptor(
        host='你的公网IP',
        port=6379,
        password='你的密码',
        key='QMT_SIGNAL',
        strategy_name='我的策略'
    )
    interceptor.install()   # 安装拦截器，之后所有 order 调用自动推送信号
"""

import redis
import json
import time
import uuid
import functools
import base64  # 新增导入，用于 Base64 编码

HOST = 'xxx'
PASSWORD = '1A2B3C4D'
STRATEGY_NAME = 'JQ_STRATEGY'

class RedisSignalInterceptor:
    """
    聚宽下单拦截器，将所有 order 系列函数的调用自动转换为 Redis 信号
    """
    
    def __init__(self, host=HOST, password=PASSWORD, port=6379, key='QMT_SIGNAL', strategy_name=STRATEGY_NAME):
        """
        初始化拦截器配置
        
        Args:
            host: Redis 服务器公网 IP
            port: Redis 端口
            password: Redis 密码
            key: 信号队列的键名（QMT端需保持一致）
            strategy_name: 策略标识，用于多策略区分
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
        self._original_funcs = {}   # 保存原始函数引用
        self._installed = False     # 防止重复安装
        
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
        推送信号到 Redis List
        信号包含唯一ID、时间戳、策略名、买卖方向、代码、数量、价格
        推送前对 JSON 字符串进行 Base64 编码
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
            
            # 将信号 JSON 序列化后进行 Base64 编码
            json_str = json.dumps(signal)
            encoded_signal = base64.b64encode(json_str.encode('utf-8')).decode('ascii')
            
            r = self._get_redis_client()
            r.lpush(self.config['key'], encoded_signal)  # 推送编码后的信号
            r.ltrim(self.config['key'], 0, 999)   # 保留最近1000条
            r.connection_pool.disconnect()
            
            print(f"[信号推送] {action} {qmt_code} {amount}股, price={price}, id={signal['id']}")
        except Exception as e:
            print(f"[信号推送失败] {e}")
    
    # ---------- 包装函数（每个原始函数对应一个） ----------
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
    
    # ---------- 安装/卸载接口 ----------
    def wrap_orders(self,order,order_target,order_value,order_target_value):
        """
        安装拦截器：保存原始函数并替换为包装函数
        可在 initialize 中调用，也可在策略文件任意位置调用（调用后即生效）
        """
        if self._installed:
            print("[拦截器] 已经安装，跳过重复安装")
            return
        
        # 保存原始函数引用
        self._original_funcs = {
            'order': order,
            'order_target': order_target,
            'order_value': order_value,
            'order_target_value': order_target_value,
        }
        
        self._installed = True
        print("✅ 聚宽下单拦截器已安装，下单信号将自动推送至 Redis（Base64 编码）")
        return self._wrap_order, self._wrap_order_target, self._wrap_order_value, self._wrap_order_target_value