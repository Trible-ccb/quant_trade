# -*- coding: utf-8 -*-
"""
THSAutoTrader 客户端（聚宽研究环境 / Jupyter 版）
"""

import json
import time
import requests


class THSClient(object):
    """同花顺自动下单 HTTP 客户端。

    用法：
        client = THSClient("http://你的ECS公网IP:5000")
        client.health()
        client.get_position()
        client.buy("600000", 100)
        client.sell("600000", 100)
        client.get_today_trades()
        client.get_balance()
    """

    def __init__(self, base_url="http://127.0.0.1:5000",
                 token=None, timeout=30, max_retries=2, retry_interval=1.0):
        """
        :param base_url: THSAutoTrader 服务地址（含协议和端口，末尾不带斜杠）
        :param token:    鉴权 token（可选）。服务端用 nginx 或 before_request
                          校验 X-Auth-Token 时传入。设置后所有请求自动带上。
        :param timeout:   单次请求超时（秒）。查询类接口可能因 OCR/窗口切换较慢，
                          建议 >= 30 秒。
        :param max_retries: 连接错误/超时时的重试次数。
        :param retry_interval: 重试间隔（秒）。
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        # 复用连接，避免频繁 TCP 握手（聚宽云端网络抖动时更稳）
        self.session = requests.Session()
        headers = {
            "User-Agent": "THSAutoTrader-Client/1.0",
            "Accept": "application/json",
        }
        if token:
            # 服务端 nginx/before_request 校验的鉴权头
            headers["X-Auth-Token"] = token
        self.session.headers.update(headers)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _request(self, method, path, params=None, retries=None):
        """统一请求入口，带重试与错误包装。"""
        url = self.base_url + path
        retries = self.max_retries if retries is None else retries

        last_err = None
        for attempt in range(retries + 1):
            try:
                resp = self.session.request(
                    method, url, params=params, timeout=self.timeout
                )
                # HTTP 层错误
                if resp.status_code == 429:
                    # GUI 锁繁忙，稍等重试
                    last_err = RuntimeError(
                        "服务忙(GUI锁占用)，HTTP 429: %s" % resp.text[:200])
                    time.sleep(self.retry_interval * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    raise RuntimeError(
                        "HTTP %s 错误: %s" % (resp.status_code, resp.text[:300]))
                return self._parse_json(resp)
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt < retries:
                    time.sleep(self.retry_interval * (attempt + 1))
                    continue
                break

        raise RuntimeError("请求失败: %s" % last_err)

    @staticmethod
    def _parse_json(resp):
        try:
            return resp.json()
        except ValueError:
            raise RuntimeError("返回非 JSON 内容: %s" % resp.text[:200])

    @staticmethod
    def _check_status(data, ok_values=("success",)):
        """校验业务 status 字段。返回 data 供链式使用。"""
        if isinstance(data, dict) and data.get("status") not in ok_values:
            raise RuntimeError("业务失败: %s" % json.dumps(data, ensure_ascii=False))
        return data

    # ------------------------------------------------------------------
    # 1. 健康检查
    # ------------------------------------------------------------------
    def health(self):
        """健康检查。返回 dict，含 status / timestamp。"""
        return self._check_status(self._request("GET", "/health"))

    # ------------------------------------------------------------------
    # 2. 获取持仓
    # ------------------------------------------------------------------
    def get_position(self):
        """获取当前持仓列表。

        返回 list[dict]，字段随券商不同而不同，常见字段：
        证券代码/证券名称/股票余额/可用余额/成本价/市价/市值/当日盈亏 等。

        注意：不同券商返回的表头名称/顺序可能不一样，请按实际解析。
        """
        data = self._check_status(self._request("GET", "/position"))
        return data.get("data", [])

    # ------------------------------------------------------------------
    # 3. 指定数量下单
    # ------------------------------------------------------------------
    def buy(self, code, amount=None):
        """买入。status=1。

        :param code:   股票代码，如 600000
        :param amount: 买入数量（股）。不传则按「一键买入/金额锁定」配置满仓买入。
        """
        return self._order(code, status=1, amount=amount)

    def sell(self, code, amount=None):
        """卖出。status=2。

        :param code:   股票代码，如 600000
        :param amount: 卖出数量（股）。不传则由客户端/一键卖出逻辑决定。
        """
        return self._order(code, status=2, amount=amount)

    # def _order(self, code, status, amount=None):
    #     params = {"code": code, "status": status}
    #     if amount is not None:
    #         params["amount"] = amount
    #     return self._check_status(self._request("GET", "/xiadan", params=params))
    
    def _order(self, code, status, amount=None, retries=1):
        """下单。status=1 买，status=2 卖。

        异常情况下重试一次（retries 默认 1，即最多尝试 2 次）。
        注意：重试是“无状态”的——若第一次请求实际已成功但响应丢失，
        重试可能造成重复下单，请配合券商侧「资金/持仓」校验使用。

        :param code:   股票代码，如 600000
        :param status: 1 买 2 卖
        :param amount: 股数；None 表示按服务端一键买入/卖出逻辑
        :param retries: 异常时额外重试次数（默认 1）
        """
        params = {"code": code, "status": status}
        if amount is not None:
            params["amount"] = amount

        last_err = None
        for attempt in range(retries + 1):
            try:
                # retries=0：禁掉 _request 内部重试，避免网络层与业务层叠加
                data = self._request("GET", "/xiadan", params=params, retries=0)
                return self._check_status(data)
            except Exception as e:
                last_err = e
                if attempt < retries:
                    wait = self.retry_interval * (attempt + 1)
                    print("[THS] 下单异常，%.1fs 后重试 (%d/%d): %s"
                        % (wait, attempt + 1, retries, str(e)[:160]))
                    time.sleep(wait)
                    continue
                break

        raise RuntimeError("下单失败（共尝试 %d 次）: %s" % (retries + 1, last_err))
    # ------------------------------------------------------------------
    # 4. 查当日成交
    # ------------------------------------------------------------------
    def get_today_trades(self):
        """查询当日成交。

        返回 list[dict]，字段随券商不同，常见：
        合同编号/委托时间/成交时间/成交均价/成交数量/成交金额/操作/证券代码/证券名称。
        """
        data = self._check_status(self._request("GET", "/today_trades"))
        return data.get("data", [])

    # ------------------------------------------------------------------
    # 5. 查资金
    # ------------------------------------------------------------------
    def get_balance(self):
        """查询资金余额。

        返回 dict，常见字段：
        总资产/资金余额/可用金额/可取金额/股票市值/当日盈亏/持仓盈亏 等。
        """
        data = self._check_status(self._request("GET", "/balance"))
        return data.get("data", {})


# ----------------------------------------------------------------------
# 快捷入口（聚宽研究环境直接改这里即可）
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # TODO: 改成你 ECS 上 THSAutoTrader 的公网地址（含 IP 白名单安全组）
    THS_BASE_URL = "http://***:5000"
    # TODO: 改成与服务端一致的鉴权 token（服务端未开启鉴权则传 None 或省略）
    THS_TOKEN = "你的随机长token"

    client = THSClient(THS_BASE_URL, token=THS_TOKEN)

    # 1. 健康检查
    print("=== 健康检查 ===")
    print(client.health())

    # 2. 查资金
    print("\n=== 资金 ===")
    print(client.get_balance())

    # 3. 查持仓
    print("\n=== 持仓 ===")
    print(client.get_position())

    # 4. 查当日成交
    print("\n=== 当日成交 ===")
    print(client.get_today_trades())

    # 5. 下单（示例，谨慎执行！建议先模拟盘）
    # print(client.buy("600000", 100))    # 买入 100 股
    # print(client.sell("600000", 100))   # 卖出 100 股
