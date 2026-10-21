# THSAutoTrader 聚宽客户端使用说明

## 一、文件

- `ths_client.py` — 聚宽研究环境（Jupyter）可用的 THSAutoTrader HTTP 客户端

## 二、功能

| 方法                   | 对应接口                   | 功能     |
| -------------------- | ---------------------- | ------ |
| `health()`           | `GET /health`          | 健康检查   |
| `get_position()`     | `GET /position`        | 获取持仓列表 |
| `buy(code, amount)`  | `GET /xiadan?status=1` | 指定数量买入 |
| `sell(code, amount)` | `GET /xiadan?status=2` | 指定数量卖出 |
| `get_today_trades()` | `GET /today_trades`    | 查当日成交  |
| `get_balance()`      | `GET /balance`         | 查资金    |

## 三、网络前提（关键）

聚宽研究环境在云端，**无法直连 ECS 内网 IP**。需满足：

1. ECS 上 THSAutoTrader 服务绑定 `0.0.0.0:5000`。
2. ECS 安全组开放 5000 端口，但**仅对你的出口 IP 白名单放行**。
3. 出口 IP 查询：在聚宽研究环境执行
   ```python
   import requests
   print(requests.get("https://api.ipify.org").text)
   ```
4. 把得到的 IP 以 `x.x.x.x/32` 加入 ECS 安全组「授权对象」。

## 四、在聚宽研究环境使用

把 `ths_client.py` 的完整代码粘贴到聚宽研究 Notebook 一个 cell 里执行，  
然后：

```python
client = THSClient("http://你的ECS公网IP:5000")

client.health()            # 健康检查
client.get_balance()       # 查资金
client.get_position()      # 查持仓
client.get_today_trades()  # 查当日成交

client.buy("600000", 100)  # 买入 100 股
client.sell("600000", 100) # 卖出 100 股
```

## 五、注意事项

1. **安全**：裸暴露公网极危险，务必用 nginx 反代加 basic auth/token，或至少  
   严格 IP 白名单。
2. **勿并发**：查询接口会切换交易客户端页面，内部有互斥锁，请逐个调用。
3. **字段差异**：持仓/成交/资金返回字段随券商不同，需按实际解析。
4. **先模拟盘**：实盘前务必在模拟盘充分测试。
5. **验证码**：识别失败会抛异常，客户端已带重试，但仍可能失败需人工介入。

## 六、THSAutoTrader 参考（项目本体）

- 仓库：`https://github.com/linlb/THSAutoTrader`
- 关键配置：`config/app_config.json`（default_app_path 填交易进程真实 exe 路径，  
  通常是 `xiadan.exe`，而非 `hexin.exe`）
- 窗口激活失败「未找到匹配窗口」根因：进程 exe 路径不匹配
