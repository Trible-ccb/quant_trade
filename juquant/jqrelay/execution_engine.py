# -*- coding: utf-8 -*-
"""
执行引擎 - 封装QMT/THS的下单和查询操作
支持两种执行端：
  1. QMT (miniQMT) - 推荐，原生API
  2. THS (同花顺)  - 备用，UI自动化
"""
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger("execution_engine")


class ExecutionEngine(ABC):
    """执行引擎抽象基类"""

    @abstractmethod
    def connect(self) -> bool:
        """连接交易端，返回是否成功"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass

    @abstractmethod
    def buy(self, security: str, amount: int, price: float) -> dict:
        """买入，返回 {success, order_id, message}"""
        pass

    @abstractmethod
    def sell(self, security: str, amount: int, price: float) -> dict:
        """卖出，返回 {success, order_id, message}"""
        pass

    @abstractmethod
    def get_balance(self) -> dict:
        """查询资金，返回 {total, available, market_value, ...}"""
        pass

    @abstractmethod
    def get_positions(self) -> list:
        """查询持仓，返回 [{security, amount, available, cost, market_value}, ...]"""
        pass

    @abstractmethod
    def get_orders(self) -> list:
        """查询当日委托，返回 [{order_id, security, direction, amount, price, status}, ...]"""
        pass

    @abstractmethod
    def get_trades(self) -> list:
        """查询当日成交"""
        pass

    def execute_order(self, order_msg: dict) -> dict:
        """
        通用下单入口
        order_msg: {security, action, amount, price, strategy, ...}
        返回: {success, order_id, message, action, security}
        """
        action = order_msg.get("action", "")
        security = order_msg.get("security", "")
        amount = int(order_msg.get("amount", 0))
        price = float(order_msg.get("price", 0))

        if not self.is_connected():
            logger.warning("[执行引擎] 未连接，尝试重连...")
            if not self.reconnect():
                return {"success": False, "message": "连接失败", "order_id": None}

        if action == "buy":
            result = self.buy(security, amount, price)
        elif action == "sell":
            result = self.sell(security, amount, price)
        else:
            return {"success": False, "message": f"未知操作: {action}", "order_id": None}

        # 下单返回-1时：可能是连接断开，标记并尝试重连
        if not result.get("success") and "返回-1" in result.get("message", ""):
            logger.warning("[执行引擎] 下单返回-1，疑似连接断开，标记断开")
            self._connected = False

        result["action"] = action
        result["security"] = security
        return result


class QmtEngine(ExecutionEngine):
    """
    QMT执行引擎（通过miniQMT的xtquant库）
    需要在QMT自带的Python环境中运行，或者将xtquant包安装到系统Python
    """

    def __init__(self, qmt_path: str, account: str, account_type: str = "STOCK"):
        self.qmt_path = qmt_path
        self.account = account
        self.account_type = account_type
        self._xt_trader = None
        self._xt_data = None
        self._connected = False

    def connect(self) -> bool:
        try:
            # 动态导入xtquant（需要在QMT Python环境中）
            import sys
            if self.qmt_path not in sys.path:
                sys.path.insert(0, self.qmt_path)

            from xtquant import xttrader, xtdata
            from xtquant.xttype import StockAccount

            self._xt_data = xtdata

            # 创建交易连接
            session_id = int(time.time())
            self._xt_trader = xttrader.XtQuantTrader(self.qmt_path, session_id)
            self._xt_trader.start()

            # 连接QMT
            connect_result = self._xt_trader.connect()
            if connect_result != 0:
                logger.error(f"[QMT] 连接失败，错误码: {connect_result}")
                return False

            # 订阅账号
            acc = StockAccount(self.account, self.account_type)
            subscribe_result = self._xt_trader.subscribe(acc)
            if subscribe_result != 0:
                logger.error(f"[QMT] 账号订阅失败，错误码: {subscribe_result}")
                return False

            self._account = acc
            self._connected = True
            logger.info(f"[QMT] 连接成功，账号: {self.account}")
            return True

        except ImportError:
            logger.error("[QMT] xtquant库未安装。请在QMT Python环境中运行，或安装xtquant包。")
            return False
        except Exception as e:
            logger.error(f"[QMT] 连接异常: {e}")
            return False

    def disconnect(self):
        if self._xt_trader:
            try:
                self._xt_trader.stop()
            except Exception:
                pass
        self._connected = False
        logger.info("[QMT] 已断开连接")

    def is_connected(self) -> bool:
        return self._connected and self._xt_trader is not None

    def health_check(self) -> bool:
        """
        真实连接健康检查：向QMT发起查询，验证session是否存活。
        is_connected()只检查初始化标记，不验证实际连接。
        health_check()会实际查询余额，如果返回有效数据则连接正常。
        返回: True=连接正常, False=连接已断开
        """
        if not self._connected or self._xt_trader is None:
            return False
        try:
            asset = self._xt_trader.query_stock_asset(self._account)
            if asset is not None:
                return True
            # asset为None但没抛异常 = session已死
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"[QMT健康检查异常] {e}")
            self._connected = False
            return False

    def reconnect(self) -> bool:
        """断开后重连，返回是否成功"""
        logger.warning("[QMT] 检测到连接断开，尝试重连...")
        self.disconnect()
        time.sleep(2)
        return self.connect()

    def _to_qmt_code(self, security: str) -> str:
        """聚宽代码 → QMT代码 转换
        513100.XSHG → 513100.SH
        002494.XSHE → 002494.SZ
        """
        code, exchange = security.split(".")
        exchange_map = {"XSHG": "SH", "XSHE": "SZ"}
        return f"{code}.{exchange_map.get(exchange, exchange)}"

    def buy(self, security: str, amount: int, price: float) -> dict:
        try:
            from xtquant.xtconstant import STOCK_BUY, FIX_PRICE, LATEST_PRICE
            qmt_code = self._to_qmt_code(security)
            # 有价格用限价，无价格用最新价
            price_type = FIX_PRICE if price > 0 else LATEST_PRICE
            order_id = self._xt_trader.order_stock(
                self._account, qmt_code, STOCK_BUY,
                amount, price_type, price
            )
            if order_id > 0:
                logger.info(f"[QMT买入] {qmt_code} {amount}股@{price} 委托号={order_id}")
                return {"success": True, "order_id": order_id, "message": "委托已提交"}
            else:
                return {"success": False, "order_id": None, "message": f"下单失败，返回{order_id}"}
        except Exception as e:
            logger.error(f"[QMT买入异常] {security}: {e}")
            return {"success": False, "order_id": None, "message": str(e)}

    def sell(self, security: str, amount: int, price: float) -> dict:
        try:
            from xtquant.xtconstant import STOCK_SELL, FIX_PRICE, LATEST_PRICE
            qmt_code = self._to_qmt_code(security)
            price_type = FIX_PRICE if price > 0 else LATEST_PRICE
            order_id = self._xt_trader.order_stock(
                self._account, qmt_code, STOCK_SELL,
                amount, price_type, price
            )
            if order_id > 0:
                logger.info(f"[QMT卖出] {qmt_code} {amount}股@{price} 委托号={order_id}")
                return {"success": True, "order_id": order_id, "message": "委托已提交"}
            else:
                return {"success": False, "order_id": None, "message": f"下单失败，返回{order_id}"}
        except Exception as e:
            logger.error(f"[QMT卖出异常] {security}: {e}")
            return {"success": False, "order_id": None, "message": str(e)}

    def get_balance(self) -> dict:
        try:
            asset = self._xt_trader.query_stock_asset(self._account)
            if asset:
                return {
                    "total": asset.total_asset,
                    "available": asset.cash,
                    "market_value": asset.market_value,
                    "frozen": asset.frozen_cash,
                }
            # asset为None说明连接可能断开
            self._connected = False
            return {}
        except Exception as e:
            logger.error(f"[QMT查询资金异常] {e}")
            self._connected = False
            return {}

    def get_positions(self) -> list:
        try:
            positions = self._xt_trader.query_stock_positions(self._account)
            result = []
            for pos in positions:
                if pos.volume > 0:
                    result.append({
                        "security": pos.stock_code,
                        "amount": pos.volume,
                        "available": pos.can_use_volume,
                        "cost": pos.avg_price,
                        "market_value": pos.market_value,
                        "profit": pos.profit if hasattr(pos, "profit") else 0,
                    })
            # 连接健康检查：能查到持仓(含现金账户=0只)或能查到余额则连接正常
            # 但如果返回空列表，可能是连接断开导致query无响应
            # 不能仅凭返回空列表就判定断开，因为确实可能没有持仓
            return result
        except Exception as e:
            logger.error(f"[QMT查询持仓异常] {e}")
            self._connected = False
            return []

    def get_orders(self) -> list:
        try:
            orders = self._xt_trader.query_stock_orders(self._account)
            result = []
            for o in (orders or []):
                result.append({
                    "order_id": o.order_id,
                    "security": o.stock_code,
                    "direction": "buy" if o.order_type == 23 else "sell",
                    "amount": o.order_volume,
                    "traded": o.traded_volume,
                    "price": o.price,
                    "status": o.order_status,
                })
            return result
        except Exception as e:
            logger.error(f"[QMT查询委托异常] {e}")
            return []

    def get_trades(self) -> list:
        try:
            trades = self._xt_trader.query_stock_trades(self._account)
            result = []
            for t in (trades or []):
                result.append({
                    "trade_id": t.traded_id,
                    "order_id": t.order_id,
                    "security": t.stock_code,
                    "direction": "buy" if t.order_type == 23 else "sell",
                    "amount": t.traded_volume,
                    "price": t.traded_price,
                })
            return result
        except Exception as e:
            logger.error(f"[QMT查询成交异常] {e}")
            return []


class ThsEngine(ExecutionEngine):
    """
    同花顺执行引擎（备用）
    通过pywinauto UI自动化操作同花顺下单客户端
    注意：需要活跃桌面会话（RDP不能断开）
    """

    def __init__(self, ths_exe_path: str):
        self.ths_exe_path = ths_exe_path
        self._app = None
        self._window = None
        self._connected = False

    def connect(self) -> bool:
        try:
            import pywinauto
            # 连接到已运行的同花顺下单客户端
            self._app = pywinauto.Application(backend="win32").connect(
                path=self.ths_exe_path, timeout=10
            )
            self._window = self._app.window(title_re=".*网上股票交易系统.*")
            self._connected = True
            logger.info("[THS] 已连接到同花顺下单客户端")
            return True
        except Exception as e:
            logger.error(f"[THS] 连接失败: {e}")
            return False

    def disconnect(self):
        self._connected = False
        logger.info("[THS] 已断开连接")

    def is_connected(self) -> bool:
        return self._connected and self._window is not None

    def buy(self, security: str, amount: int, price: float) -> dict:
        try:
            code = security.split(".")[0]
            # 使用SendMessage方式填写表单（无需活跃桌面）
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WM_SETTEXT = 0x000C
            BM_CLICK = 0x00F5

            # 查找控件
            price_edit = user32.GetDlgItem(self._window.handle, 1033)
            amount_edit = user32.GetDlgItem(self._window.handle, 1034)
            code_edit = user32.GetDlgItem(self._window.handle, 1032)
            buy_btn = user32.GetDlgItem(self._window.handle, 3501)

            if not all([price_edit, amount_edit, code_edit, buy_btn]):
                return {"success": False, "order_id": None, "message": "控件未找到"}

            # 填写价格和数量
            user32.SendMessageW(price_edit, WM_SETTEXT, 0, f"{price}")
            user32.SendMessageW(amount_edit, WM_SETTEXT, 0, f"{amount}")
            # 证券代码使用pywinauto的type_keys（SendMessage对代码框无效）
            code_ctrl = self._window.child_window(control_type="Edit", found_index=0)
            code_ctrl.set_edit_text(code)

            # 点击买入
            user32.SendMessageW(buy_btn, BM_CLICK, 0, 0)
            logger.info(f"[THS买入] {code} {amount}股@{price}")
            return {"success": True, "order_id": None, "message": "买入已提交(THS)"}

        except Exception as e:
            logger.error(f"[THS买入异常] {security}: {e}")
            return {"success": False, "order_id": None, "message": str(e)}

    def sell(self, security: str, amount: int, price: float) -> dict:
        try:
            code = security.split(".")[0]
            import ctypes
            user32 = ctypes.windll.user32
            WM_SETTEXT = 0x000C
            BM_CLICK = 0x00F5

            price_edit = user32.GetDlgItem(self._window.handle, 1033)
            amount_edit = user32.GetDlgItem(self._window.handle, 1034)
            sell_btn = user32.GetDlgItem(self._window.handle, 2449)

            if not all([price_edit, amount_edit, sell_btn]):
                return {"success": False, "order_id": None, "message": "控件未找到"}

            user32.SendMessageW(price_edit, WM_SETTEXT, 0, f"{price}")
            user32.SendMessageW(amount_edit, WM_SETTEXT, 0, f"{amount}")
            code_ctrl = self._window.child_window(control_type="Edit", found_index=0)
            code_ctrl.set_edit_text(code)

            user32.SendMessageW(sell_btn, BM_CLICK, 0, 0)
            logger.info(f"[THS卖出] {code} {amount}股@{price}")
            return {"success": True, "order_id": None, "message": "卖出已提交(THS)"}

        except Exception as e:
            logger.error(f"[THS卖出异常] {security}: {e}")
            return {"success": False, "order_id": None, "message": str(e)}

    def get_balance(self) -> dict:
        """通过WMCopy策略读取Grid数据"""
        # 简化实现 - 实际需要切换到资金页面并读取Grid
        return {}

    def get_positions(self) -> list:
        """通过WMCopy策略读取持仓Grid"""
        # 简化实现 - 实际需要切换到持仓页面并读取Grid
        return []

    def get_orders(self) -> list:
        return []

    def get_trades(self) -> list:
        return []


def create_engine(config=None) -> ExecutionEngine:
    """工厂方法：根据配置创建执行引擎"""
    if config is None:
        from config import EXECUTOR_TYPE, QMT_PATH, QMT_ACCOUNT, QMT_ACCOUNT_TYPE, THS_EXE_PATH
        executor_type = EXECUTOR_TYPE
    else:
        executor_type = config.get("executor_type", "qmt")

    if executor_type == "qmt":
        logger.info(f"[执行引擎] 创建QMT引擎")
        return QmtEngine(QMT_PATH, QMT_ACCOUNT, QMT_ACCOUNT_TYPE)
    elif executor_type == "ths":
        logger.info(f"[执行引擎] 创建THS引擎(备用)")
        return ThsEngine(THS_EXE_PATH)
    else:
        raise ValueError(f"不支持的执行端类型: {executor_type}")