名称
QMT实盘交易连接（基于 bullet_trade 远程辅助模块）

描述
该 Skill 提供通过 bullet_trade_jq_remote_helper 模块连接 QMT 实盘账户的能力。模块封装了与远程交易服务器（通常部署在本地或云上）的 TCP 通信，支持同步/异步下单、账户查询、持仓管理、订单撤销等常见交易操作。

核心特点：

短连接设计：每次请求重新建立 TCP 连接，适配聚宽策略频繁重启的环境。

服务端统一处理：自动完成最小手数/步进取整、停牌检查、价格笼子、涨跌停校验、可卖数量检查等。

支持按数量、按市值、调仓到目标数量/市值等多种下单方式。

支持同步等待（轮询订单状态）或异步返回。

提供与聚宽风格一致的 order、order_target、get_account、get_positions 等 API。

配置依赖
服务器地址：host = "8.141.101.156"

端口：port = 58620（默认）

认证令牌：token = "0011223344"

账户标识（可选）：account_key 和 sub_account_id，用于多账户场景。

安装与导入
将 bullet_trade_jq_remote_helper.py 文件复制到环境的根目录（或任意可导入路径）。在策略中导入：

python
import bullet_trade_jq_remote_helper as bt
初始化配置
在策略的 initialize 或 handle_data 开始处调用 configure：

python
bt.configure(
    host='8.141.101.156',
    token='0011223344',
    port=58620,                 # 默认
    account_key='main',         # 可选
    sub_account_id='demo@main', # 可选
    debug=True                  # 开启调试日志
)
主要 API
1. 下单
order(security, amount, price=None, side=None, wait_timeout=0)
按数量下单。amount 正数买入，负数卖出；price=None 表示市价单。返回 RemoteOrder 对象。

order_value(security, value, price=None, wait_timeout=0)
按市值下单（正数买入，负数卖出）。服务端会自动根据价格计算数量并取整。

order_target(security, target, price=None, wait_timeout=0)
调仓到目标持仓数量（正数）。target 为目标股数，内部计算差值后下单。

order_target_value(security, target_value, price=None, wait_timeout=0)
调仓到目标持仓市值。根据当前价格计算目标股数并调仓。

参数说明：

wait_timeout：>0 时函数会阻塞等待订单完成（或超时），0 表示异步提交后立即返回。

price：指定限价，None 表示市价单（服务端自动处理价格笼子）。

2. 查询
get_account() -> RemoteAccount
返回账户可用资金和总资产。

get_positions() -> List[RemotePosition]
返回当前持仓列表，每个持仓包含证券代码、数量、可用数量、成本价、市值等。

get_orders(order_id=None, security=None, status=None, from_broker=False) -> Dict[str, RemoteOrder]
查询订单。可指定订单ID、证券代码、状态等过滤条件。

get_open_orders() -> Dict[str, RemoteOrder]
查询所有未成交或部分成交的订单。

get_order_status(order_id) -> Dict
查询单个订单的详细状态。

3. 撤销
cancel_order(order_id) -> Dict
撤销指定订单，返回操作结果。

4. 成交查询
get_trades(order_id=None, security=None) -> Dict[str, RemoteTrade]
获取成交记录，可按订单或证券过滤。

数据辅助（可选）
模块还提供了 RemoteDataClient 用于获取历史行情、交易日、快照等，但通常可直接使用聚宽原生数据 API。

注意事项
实盘开关：若同时使用聚宽模拟和实盘，可通过 wrap_orders 函数将聚宽原生下单函数代理，并设置 live=True 启用实盘。否则直接调用 bt.order 等函数默认走实盘（需先 configure）。

数量取整：服务端会自动将下单数量调整为最小交易单位（如100股整数倍），RemoteOrder 的 actual_amount 字段反映实际委托数量。

价格处理：市价单（price=None）由服务端根据当前行情计算参考价并处理价格笼子；限价单会校验涨跌停范围。

错误处理：下单失败会抛出 RuntimeError，建议用 try...except 捕获。

网络超时：可配置 rpc_timeout（默认15秒）和重试次数 retries。