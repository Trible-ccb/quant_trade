皮皮虾实盘下单接口

技能名称：bullet_trade

版本：v1.0

说明：基于QMT量化交易平台的远程下单接口

接口概述

本接口通过TCP短连接方式连接QMT量化交易服务端，实现实盘下单功能。

核心文件：

bullet_trade_remote_helper.py - 核心连接模块
bullet_trade_test.py - 测试用例（包含敏感密钥）

凭证存储：从 ./SECRET.md 读取远程连接配置

初始化配置

python
import bullet_trade_remote_helper as bt

# 从SECRET.md读取配置
bt.configure(
    host='x.x.x.x',      # QMT服务器地址
    port=58620,                 # 服务器端口
    token='xxx',                # 认证token（存储在SECRET.md）
    account_key=None,           # 账户键（可选）
    sub_account_id=None,        # 子账户ID（可选）
)

# 绑定数据客户端用于价格补全
bt.get_broker_client().bind_data_client(bt.get_data_client())


核心下单函数

1. 按数量下单 order()

python
# 买入指定数量（市价单）
order = bt.order("000001.XSHE", 1000, price=None, side='BUY', wait_timeout=10)

# 卖出指定数量（限价单）
order = bt.order("000001.XSHE", 500, price=12.50, side='SELL', wait_timeout=10)


参数：

表格
参数	类型	说明
security	str	证券代码，如"000001.XSHE"
amount	int	数量（正数买入，负数卖出）
price	float	委托价格，None表示市价单
side	str	"BUY"或"SELL"
wait_timeout	float	等待超时秒数，0表示异步返回

返回：RemoteOrder 对象

2. 按市值下单 order_value()

python
# 买入1000元市值的股票（服务端自动按100股取整）
order = bt.order_value("000001.XSHE", 1000.0, price=None, wait_timeout=10)


特点：

服务端自动计算股数（按100股取整）
实际成交市值可能与请求略有偏差

3. 调仓到目标数量 order_target()

python
# 将持仓调整到200股（不够则买，多了则卖）
order = bt.order_target("000001.XSHE", 200, price=None, wait_timeout=10)


特点：

自动判断买卖方向
建议target为100的整数倍

4. 调仓到目标市值 order_target_value()

python
# 将持仓市值调整到10000元
order = bt.order_target_value("000001.XSHE", 10000.0, price=None, wait_timeout=10)


账户与持仓查询

获取账户信息

python
account = bt.get_account()
print(f"可用现金: {account.available_cash:.2f}")
print(f"总资产: {account.total_value:.2f}")


获取持仓列表

python
positions = bt.get_positions()
for pos in positions:
    print(f"{pos.security}: 数量={pos.amount}, 可用={pos.available}, 成本={pos.avg_cost:.4f}, 市值={pos.market_value:.2f}")


获取最新价格

python
price = bt.get_data_client().get_last_price("000001.XSHE")
print(f"最新价: {price}")


订单管理

查询订单状态

python
status = bt.get_order_status(order.order_id)
print(status)


查询所有订单

python
orders = bt.get_broker_client().get_orders()
for oid, order in orders.items():
    print(f"{oid}: {order.security}, 状态={order.status}, 数量={order.amount}")


查询今日成交

python
trades = bt.get_broker_client().get_trades()
for tid, trade in trades.items():
    print(f"{trade.security}: 成交{trade.amount}股@{trade.price}")


撤单

python
result = bt.cancel_order(order_id)
print(result)


完整下单示例

python
import bullet_trade_remote_helper as bt

# 1. 初始化连接
bt.configure(
    host='x.x.x.x',
    port=58620,
    token='xxx',  # 从SECRET.md读取
)
bt.get_broker_client().bind_data_client(bt.get_data_client())
询问用户提供host和token，并保存到SECRET.md

# 2. 查询账户
account = bt.get_account()
print(f"可用现金: {account.available_cash:.2f}")

# 3. 查询持仓
positions = bt.get_positions()
print(f"当前持仓: {len(positions)}只")

# 4. 获取价格
price = bt.get_data_client().get_last_price("300265.XSHE")
print(f"通光线缆价格: {price}")

# 5. 下单买入
order = bt.order("300265.XSHE", 1000, price=None, side='BUY', wait_timeout=10)
print(f"订单ID: {order.order_id}, 状态: {order.status}")

# 6. 查询订单状态
if order.order_id:
    status = bt.get_order_status(order.order_id)
    print(f"订单详情: {status}")


证券代码格式

表格
市场	后缀	示例
深市	.XSHE	000001.XSHE, 300265.XSHE
沪市	.XSHG	600519.XSHG, 601168.XSHG

订单状态说明

表格
状态	说明
new	已提交
open	已报
filling	部分成交
filled	全部成交
cancelled	已撤单
rejected	已拒绝

注意事项

市价单：price=None时自动使用市价单，服务端计算价格笼子
数量取整：A股最小交易单位为100股（1手），服务端自动取整
同步/异步：wait_timeout>0时同步等待，=0时异步返回
重试机制：默认重试2次，间隔0.5秒
超时设置：默认RPC超时60秒

错误处理

python
try:
    order = bt.order("000001.XSHE", 1000, price=None, side='BUY', wait_timeout=10)
except RuntimeError as e:
    print(f"下单失败: {e}")
    # 处理错误


本接口用于皮皮虾量化交易系统的实盘下单