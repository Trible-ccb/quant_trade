# -*- coding: utf-8 -*-
"""
风控模块 - 下单前的安全检查
"""
import time
import logging
from datetime import datetime
from config import RISK

logger = logging.getLogger("risk_manager")


class RiskManager:
    """风控管理器：拦截不合规的下单请求"""

    def __init__(self):
        self._daily_order_count = {}      # {stream_key: count}
        self._last_order_time = {}        # {security: timestamp}
        self._current_date = None

    def _reset_daily_if_needed(self):
        today = datetime.now().date()
        if self._current_date != today:
            self._current_date = today
            self._daily_order_count.clear()
            logger.info(f"[风控] 日计数器已重置，日期={today}")

    def check(self, order_msg: dict) -> tuple:
        """
        风控检查，返回 (passed: bool, reason: str)
        order_msg 格式: {security, action, amount, price, stream_key, ...}
        """
        self._reset_daily_if_needed()

        security = order_msg.get("security", "")
        stream_key = order_msg.get("stream_key", "unknown")
        action = order_msg.get("action", "")
        amount = order_msg.get("amount", 0)
        price = order_msg.get("price", 0)

        # 1. 单笔金额检查（0=不限制）
        order_value = amount * price if amount and price else 0
        max_value = RISK.get("max_single_order_value", 0)
        if max_value > 0 and order_value > max_value:
            reason = f"单笔金额{order_value:.0f}超限(上限{max_value})"
            logger.warning(f"[风控拦截] {security} {action} {amount}股@{price}: {reason}")
            return False, reason

        # 2. 每日下单次数检查（0=不限制）
        daily_limit = RISK.get("max_daily_orders_per_stream", 0)
        count = self._daily_order_count.get(stream_key, 0)
        if daily_limit > 0 and count >= daily_limit:
            reason = f"Stream[{stream_key}]今日下单{count}次已达上限{daily_limit}"
            logger.warning(f"[风控拦截] {reason}")
            return False, reason

        # 3. 最小下单间隔检查（防短时间内重复下单同一标的）
        min_interval = RISK.get("min_order_interval_sec", 5)
        last_time = self._last_order_time.get(security, 0)
        elapsed = time.time() - last_time
        if elapsed < min_interval:
            reason = f"{security}距上次下单仅{elapsed:.1f}秒(最小间隔{min_interval}秒)"
            logger.warning(f"[风控拦截] {reason}")
            return False, reason

        # 4. 集合竞价期间过滤
        if RISK.get("skip_auction_period", True):
            now = datetime.now()
            t = now.strftime("%H:%M")
            if "09:15" <= t < "09:25":
                reason = f"集合竞价期间(09:15-09:25)不下单"
                logger.info(f"[风控拦截] {security}: {reason}")
                return False, reason

        # 5. 涨跌停过滤（需要实时行情，这里预留接口）
        if RISK.get("filter_limit_up_down", True) and action in ("buy",):
            # 实际实现需要查询实时行情判断是否涨跌停
            # 这里先记录，由执行端在下单前做最终判断
            pass

        # 通过风控
        self._daily_order_count[stream_key] = count + 1
        self._last_order_time[security] = time.time()
        logger.info(f"[风控通过] {security} {action} {amount}股@{price} 金额={order_value:.0f}")
        return True, "OK"