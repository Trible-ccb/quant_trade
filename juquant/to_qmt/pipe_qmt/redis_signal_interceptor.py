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
POSITION_KEY = 'QMT_POSITION'      # QMT 持仓快照键（与 bridge 一致）
QMT_OK_MAX_AGE_SECONDS = 3600      # qmt_is_ok 判定：快照时间戳距今不超过 1 小时

class RedisSignalInterceptor:
    """
    聚宽下单拦截器，将所有 order 系列函数的调用自动转换为 Redis 信号
    """
    
    def __init__(self, host=HOST, password=PASSWORD, port=6379, key='QMT_SIGNAL', strategy_name=STRATEGY_NAME, position_key=POSITION_KEY):
        """
        初始化拦截器配置
        
        Args:
            host: Redis 服务器公网 IP
            port: Redis 端口
            password: Redis 密码
            key: 信号队列的键名（QMT端需保持一致）
            strategy_name: 策略标识，用于多策略区分
            position_key: 持仓快照键名（与 QMT bridge 端一致）
        """
        self.config = {
            'host': host,
            'port': port,
            'password': password,
            'key': key,
            'strategy_name': strategy_name,
            'position_key': position_key,
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
    
    # ---------- 持仓快照读取 & 对账 ----------
    def _get_position_snapshot(self):
        """
        读取 QMT 最新一份持仓快照（仅最近一次）。
        返回 dict，失败或不存在返回 None。
        """
        r = None
        try:
            r = self._get_redis_client()
            raw = r.get(self.config['position_key'])
            if not raw:
                return None
            return json.loads(raw)
        except Exception as e:
            print(f"[持仓快照读取失败] {e}")
            return None
        finally:
            if r is not None:
                try:
                    r.connection_pool.disconnect()
                except Exception:
                    pass

    def qmt_is_ok(self):
        """
        判断 QMT 是否正常：
          1. 能读到持仓快照（空持仓数组 [] 也算有数据，即 snapshot 存在且含 holdings 字段）
          2. 快照时间戳距当前不超过 1 小时
        返回 True/False。
        """
        try:
            snapshot = self._get_position_snapshot()
            if snapshot is None:
                print("[qmt_is_ok] ❌ 未读取到持仓快照（QMT 可能未运行或未连接）")
                return False

            # holdings 字段必须存在（空数组也算有数据）
            if 'holdings' not in snapshot:
                print("[qmt_is_ok] ❌ 快照缺少 holdings 字段，判定异常")
                return False

            # 时间戳校验
            ts = snapshot.get('ts')
            if ts is None:
                print("[qmt_is_ok] ❌ 快照缺少 ts 时间戳，判定异常")
                return False

            age = time.time() - float(ts)
            if age > QMT_OK_MAX_AGE_SECONDS:
                print(f"[qmt_is_ok] ❌ 快照过期，age={age:.0f}s > {QMT_OK_MAX_AGE_SECONDS}s")
                return False

            holdings = snapshot.get('holdings', [])
            print(f"[qmt_is_ok] ✅ QMT 正常，持仓 {len(holdings)} 条，快照 age={age:.0f}s")
            return True
        except Exception as e:
            print(f"[qmt_is_ok] ❌ 检查异常: {e}")
            return False

    def sync_check_jq_sim_vs_real(self, sim_positions):
        """
        聚宽模拟盘 ↔ QMT 实盘 持仓对账（以模拟盘为准）。
        参考 bullet_trade_jq_wrapper.py 的 sync_check_jq_sim_vs_real，
        但实盘数据来源改为 Redis 中的持仓快照（仅最近一次快照）。

        Args:
            sim_positions: 聚宽模拟盘持仓，dict[security] = Position 对象
                或 dict[security] = dict(total_amount, closeable_amount, avg_cost, price, value)
        Returns:
            dict: {"success": bool, "total_diff": int, "rows": [...], "snapshot_ts": ...}
        """
        try:
            # 1. 读取实盘快照（最近一次）
            snapshot = self._get_position_snapshot()
            if snapshot is None:
                print("[对账] ❌ 未读取到 QMT 持仓快照")
                return {"success": False, "error": "no position snapshot"}

            real_holdings = snapshot.get('holdings', [])
            # 实盘持仓字典：code -> 快照条目
            real_dict = {}
            for h in real_holdings:
                code = h.get('code')
                if code:
                    real_dict[code] = h

            # 2. 规范化模拟盘持仓为统一结构
            sim_dict = {}
            for code, pos in sim_positions.items():
                if isinstance(pos, dict):
                    sim_dict[code] = {
                        'total_amount': pos.get('total_amount', 0) or 0,
                        'closeable_amount': pos.get('closeable_amount', 0) or 0,
                        'avg_cost': pos.get('avg_cost', 0.0) or 0.0,
                        'price': pos.get('price', 0.0) or 0.0,
                        'value': pos.get('value', 0.0) or 0.0,
                    }
                else:
                    # 聚宽 Position 对象
                    sim_dict[code] = {
                        'total_amount': getattr(pos, 'total_amount', 0) or 0,
                        'closeable_amount': getattr(pos, 'closeable_amount', 0) or 0,
                        'avg_cost': getattr(pos, 'avg_cost', 0.0) or 0.0,
                        'price': getattr(pos, 'price', 0.0) or 0.0,
                        'value': getattr(pos, 'value', 0.0) or 0.0,
                    }

            # 3. 对账
            check_rows = []
            total_diff = 0

            headers = [
                "股票代码", "模拟持仓", "实盘持仓", "差异",
                "模拟成本价", "实盘成本价",
                "模拟市值", "实盘市值", "对账状态"
            ]

            # 以模拟盘为准遍历
            for security, sim in sim_dict.items():
                real = real_dict.get(security)

                sim_qty = int(sim.get('total_amount', 0))
                sim_price = float(sim.get('avg_cost', 0.0))
                sim_value = float(sim.get('value', 0.0))

                if real:
                    real_qty = int(real.get('volume', 0))
                    real_price = float(real.get('open_price', 0.0))
                    real_value = float(real.get('market_value', 0.0))
                else:
                    real_qty = 0
                    real_price = 0.0
                    real_value = 0.0

                diff = sim_qty - real_qty
                total_diff += abs(diff)
                diff_price = sim_price - real_price

                if diff == 0 and abs(diff_price) < 0.0001:
                    status = "✅ 完全一致"
                elif diff != 0:
                    if real_qty == 0:
                        status = "🅾️ 模拟盘有，实盘无"
                    else:
                        status = f"🅾️ 持仓量不一致，与模拟盘差={diff}股"
                elif abs(diff_price) >= 0.0001:
                    status = f"🅾️ 价格不一致，差价={diff_price:.5f}"
                else:
                    status = "✅ 一致"

                check_rows.append([
                    security,
                    sim_qty, real_qty, diff,
                    round(sim_price, 3), round(real_price, 3),
                    round(sim_value, 2), round(real_value, 2),
                    status
                ])

            # 实盘多余持仓（可选，默认不纳入差异统计，仅记录）
            for security in real_dict:
                if security not in sim_dict:
                    real = real_dict[security]
                    check_rows.append([
                        security,
                        0, int(real.get('volume', 0)), -int(real.get('volume', 0)),
                        round(0.0, 3), round(float(real.get('open_price', 0.0)), 3),
                        round(0.0, 2), round(float(real.get('market_value', 0.0)), 2),
                        "⚠️ 实盘有，模拟盘无"
                    ])

            # 4. 打印表格
            print("📊 聚宽模拟盘 ↔ QMT实盘 持仓对账表（以模拟盘为准）")
            fmt = "{:<14} {:<8} {:<8} {:<6} {:<10} {:<10} {:<12} {:<12} {:<12}"
            print(fmt.format(*headers))
            for row in check_rows:
                print(fmt.format(*row))
            if total_diff == 0:
                print("✅ 对账结果：完全一致")
            else:
                print(f"⚠️ 对账结果：存在差异")
            print("=" * 160 + "\n")

            return {
                "success": True,
                "total_diff": total_diff,
                "rows": check_rows,
                "snapshot_ts": snapshot.get('ts'),
                "snapshot_ts_str": snapshot.get('ts_str'),
            }

        except Exception as exc:
            import traceback
            print(f"[对账异常] {exc}")
            print(traceback.format_exc())
            return {"success": False, "error": str(exc)}

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