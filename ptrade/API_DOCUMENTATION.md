# PTrade API 文档

> 来源：恒生投研平台 - http://180.169.107.9:7766/hub/help/api
> 用于 PTrade 国金版量化策略开发参考

## 目录

- [API文档](#api文档)
- [使用说明](#使用说明)
- [新建策略](#新建策略)
- [新建回测](#新建回测)
- [新建交易](#新建交易)
- [策略运行周期](#策略运行周期)
- [策略运行时间](#策略运行时间)
- [交易策略委托下单时间](#交易策略委托下单时间)
- [回测支持业务类型](#回测支持业务类型)
- [交易支持业务类型](#交易支持业务类型)
- [交易标的对应最小价差](#交易标的对应最小价差)
- [开始写策略](#开始写策略)
- [简单但是完整的策略](#简单但是完整的策略)
- [添加一些交易](#添加一些交易)
- [实用的策略](#实用的策略)
- [模拟盘和实盘注意事项](#模拟盘和实盘注意事项)
- [策略中支持的代码尾缀](#策略中支持的代码尾缀)
- [关于异常处理](#关于异常处理)
- [关于限价交易的价格](#关于限价交易的价格)
- [策略引擎简介](#策略引擎简介)
- [业务流程框架](#业务流程框架)
- [initialize(必选)](#initialize)
- [before_trading_start(可选)](#before_trading_start)
- [handle_data(必选)](#handle_data)
- [after_trading_end(可选)](#after_trading_end)
- [tick_data(可选)](#tick_data)
- [on_order_response(可选) - 委托主推](#on_order_response)
- [on_trade_response(可选) - 交易主推](#on_trade_response)
- [策略API介绍](#策略api介绍)
- [设置函数](#设置函数)
- [定时周期性函数](#定时周期性函数)
- [获取信息函数](#获取信息函数)
- [交易相关函数](#交易相关函数)
- [融资融券专用函数](#融资融券专用函数)
- [期货专用函数](#期货专用函数)
- [期权专用函数](#期权专用函数)
- [港股通专用函数](#港股通专用函数)
- [计算函数](#计算函数)
- [其他函数](#其他函数)
- [公共资源](#公共资源)
- [数据字典](#数据字典)
- [策略示例](#策略示例)
- [常见问题](#常见问题)
- [支持的三方库](#支持的三方库)

---

## 使用说明

### 新建策略

开始回测和交易前需要先新建策略，点击下图中左上角标识进行策略添加。可以选择不同的业务类型(比如股票)，然后给策略设定一个名称，添加成功后可以在默认策略模板基础上进行策略编写。

### 新建回测

策略添加完成后就可以开始进行回测操作了。回测之前需要对开始时间、结束时间、回测资金、回测基准、回测频率几个要素进行设定，设定完毕后点击保存。然后再点击回测按键，系统就会开始运行回测，回测的评价指标、收益曲线、日志都会在界面中展现。

### 新建交易

交易界面点击新增按键进行新增交易操作，策略方案中的对象为所有策略列表中的策略，给本次交易设定名称并点击确定后系统就开始运行交易了。

交易开始运行后，可以实时看到总资产和可用资金情况，同时可以在交易列表查询交易状态。

交易开始运行后，可以点击交易详情，查看策略评价指标、交易明细、持仓明细、交易日志。

### 策略运行周期

**回测支持：** 日线级别、分钟级别运行

**交易支持：** 日线级别、分钟级别、tick级别运行

**频率说明：**
- 日线级别：每天运行一次，回测在15:00执行，交易在尾盘固定时间(默认14:50)
- 分钟级别：每分钟运行一次，回测9:31-15:00，交易9:30-14:59
- tick级别：最小频率3秒运行一次

### 策略运行时间

- 盘前运行：9:30之前，支持 before_trading_start 和 run_daily(如time='09:15')
- 盘中运行：9:31(回测)/9:30(交易)~15:00，支持 handle_data、run_interval、tick_data
- 盘后运行：15:30，支持 after_trading_end

### 交易支持业务类型

1. 普通股票买卖(单位：股)
2. 可转债买卖(T+0)
3. 融资融券交易(单位：股)
4. ETF申赎、套利(单位：份)
5. 国债逆回购(单位：份)
6. 期货投机类型交易(单位：手，T+0)
7. LOF基金买卖(单位：股)
8. ETF基金买卖(单位：股)
9. 期权交易(单位：手)
10. 港股通交易(单位：股)

### 交易标的对应最小价差

| 标的类型 | 最小价差 |
|---------|---------|
| 股票 | 0.01 |
| 可转债 | 0.001 |
| LOF | 0.001 |
| ETF | 0.001 |
| 国债逆回购 | 0.005 |
| 股指期货 | 0.2 |
| 国债期货 | 0.005 |

---

## 开始写策略

### 简单但是完整的策略

```python
def initialize(context):
    set_universe('600570.SS')

def handle_data(context, data):
    pass
```

### 添加一些交易

```python
def initialize(context):
    g.security = '600570.SS'
    g.flag = False
    set_universe(g.security)

def handle_data(context, data):
    if not g.flag:
        order(g.security, 1000)
        g.flag = True
```

### 实用的策略示例

```python
def initialize(context):
    g.security = '600570.SS'
    set_universe(g.security)

def handle_data(context, data):
    security = g.security
    sid = g.security

    # 获取过去五天的历史价格
    df = get_history(5, '1d', 'close', security, fq=None, include=False)

    # 获取过去五天的平均价格
    average_price = round(df['close'][-5:].mean(), 3)

    # 获取上一时间点价格
    current_price = data[sid]['close']

    # 获取当前的现金
    cash = context.portfolio.cash

    # 如果上一时间点价格高出五天平均价1%, 则全仓买入
    if current_price > 1.01*average_price:
        order_value(g.security, cash)
        log.info('buy %s' % g.security)
    # 如果上一时间点价格低于五天平均价, 则清仓卖出
    elif current_price < average_price and get_position(security).amount > 0:
        order_target(g.security, 0)
        log.info('sell %s' % g.security)
```

---

## 策略引擎简介

### 业务流程框架

ptrade量化引擎以事件触发为基础：

1. **initialize** - 初始化（必选）
2. **before_trading_start** - 盘前事件（可选）
3. **handle_data** - 盘中事件（必选，日线/分钟级别）
4. **tick_data** - tick级别盘中处理（可选）
5. **after_trading_end** - 盘后事件（可选）
6. **on_order_response** - 委托主推（可选）
7. **on_trade_response** - 交易主推（可选）

### initialize(必选)

```python
def initialize(context)
```

- 用于初始化全局变量
- 在回测和交易启动时只运行一次
- 可调用接口：set_universe, set_benchmark, set_commission, run_daily等

### before_trading_start(可选)

```python
def before_trading_start(context, data)
```

- 每天开始交易前调用一次
- 回测：每个交易日8:30执行
- 交易：开启时立即执行，从隔日开始每天9:10(默认)执行

### handle_data(必选)

```python
def handle_data(context, data)
```

- 交易时间内按指定周期频率运行
- 日线级别：每天执行一次
- 分钟级别：每分钟执行一次
- 不会在非交易日触发

### after_trading_end(可选)

```python
def after_trading_end(context, data)
```

- 每天收盘后调用一次
- 回测和交易都在15:30执行

### tick_data(可选)

```python
def tick_data(context, data)
```

- tick级别策略使用
- 3秒触发一次

---

## 策略API介绍

### 设置函数

#### set_universe - 设置股票池

```python
set_universe(security_list)
```

**参数说明：**
- security_list: list类型，股票代码列表，如['600570.SS', '000001.SZ']

#### set_benchmark - 设置基准

```python
set_benchmark(security)
```

#### set_commission - 设置佣金费率

```python
set_commission(commission_ratio, min_commission=5.0, type='stock')
```

#### set_fixed_slippage - 设置固定滑点

```python
set_fixed_slippage(slippage)
```

#### set_slippage - 设置滑点

```python
set_slippage(slippage)
```

#### set_volume_ratio - 设置成交比例

```python
set_volume_ratio(volume_ratio)
```

#### set_limit_mode - 设置回测成交数量限制模式

```python
set_limit_mode(mode)
```

#### set_yesterday_position - 设置底仓(股票)

```python
set_yesterday_position(position_dict)
```

#### set_parameters - 设置策略配置参数

```python
set_parameters(params_dict)
```

#### set_email_info - 设置邮件信息

```python
set_email_info(email_info)
```

### 定时周期性函数

#### run_daily - 按日周期处理

```python
run_daily(func, time='09:30', reference_security='000001.SZ')
```

**参数说明：**
- func: 要执行的函数
- time: 执行时间，格式'HH:MM'
- reference_security: 参考标的

#### run_interval - 按设定周期处理

```python
run_interval(func, interval_sec=3, reference_security='000001.SZ')
```

**参数说明：**
- interval_sec: 执行间隔秒数，最小3秒

### 获取信息函数

#### 获取基础信息

##### get_trading_day - 获取交易日期

```python
get_trading_day()
```

返回当前交易日，格式：YYYYMMDD

##### get_all_trades_days - 获取全部交易日期

```python
get_all_trades_days()
```

##### get_trade_days - 获取指定范围交易日期

```python
get_trade_days(start_date, end_date)
```

##### get_trading_day_by_date - 按日期获取指定交易日

```python
get_trading_day_by_date(date, n=0)
```

#### 获取市场信息

##### get_market_list - 获取市场列表

```python
get_market_list()
```

##### get_market_detail - 获取市场详细信息

```python
get_market_detail(market_code)
```

#### 获取行情信息

##### get_history - 获取历史行情

```python
get_history(count, frequency, field, security, fq=None, include=False)
```

**参数说明：**
- count: 数量
- frequency: 频率，'1d'(日线)、'1m'(分钟)
- field: 字段，'close'(收盘价)、'open'(开盘价)等
- security: 标的代码
- fq: 复权类型，None(不复权)、'pre'(前复权)、'post'(后复权)
- include: 是否包含当前bar

##### get_price - 获取历史数据

```python
get_price(security, start_date=None, end_date=None, frequency='daily', fields=None, fq='pre')
```

##### get_individual_entrust - 获取逐笔委托行情

```python
get_individual_entrust(security)
```

##### get_individual_transaction - 获取逐笔成交行情

```python
get_individual_transaction(security)
```

##### get_tick_direction - 获取分时成交行情

```python
get_tick_direction(security)
```

##### get_sort_msg - 获取板块、行业的涨幅排名

```python
get_sort_msg(sort_type)
```

##### get_gear_price - 获取指定代码的档位行情价格

```python
get_gear_price(security)
```

##### get_snapshot - 取行情快照

```python
get_snapshot(security)
```

##### get_trend_data - 获取集中竞价期间代码数据

```python
get_trend_data(security)
```

#### 获取证券信息

##### get_stock_name - 获取证券名称

```python
get_stock_name(security)
```

##### get_stock_info - 获取证券基础信息

```python
get_stock_info(security)
```

##### get_stock_status - 获取证券状态信息

```python
get_stock_status(security)
```

##### get_underlying_code - 获取证券的关联代码

```python
get_underlying_code(security)
```

##### get_stock_exrights - 获取证券除权除息信息

```python
get_stock_exrights(security)
```

##### get_stock_blocks - 获取证券所属板块信息

```python
get_stock_blocks(security)
```

##### get_index_stocks - 获取指数成份股

```python
get_index_stocks(index_code, date=None)
```

##### get_industry_stocks - 获取行业成份股

```python
get_industry_stocks(industry_code, date=None)
```

##### get_fundamentals - 获取财务数据信息

```python
get_fundamentals(query, date=None)
```

##### get_Ashares - 获取指定日期A股代码列表

```python
get_Ashares(date=None)
```

##### get_etf_list - 获取ETF代码

```python
get_etf_list()
```

##### get_etf_info - 获取ETF信息

```python
get_etf_info(etf_code)
```

##### get_etf_stock_list - 获取ETF成分券列表

```python
get_etf_stock_list(etf_code)
```

##### get_etf_stock_info - 获取ETF成分券信息

```python
get_etf_stock_info(etf_code, stock_code)
```

##### get_ipo_stocks - 获取当日IPO申购标的

```python
get_ipo_stocks()
```

##### get_cb_list - 获取可转债市场代码表

```python
get_cb_list()
```

##### get_cb_info - 获取可转债基础信息

```python
get_cb_info(cb_code)
```

##### get_reits_list - 获取基础设施公募REITs基金代码列表

```python
get_reits_list()
```

#### 获取其他信息

##### get_position - 获取单只标的持仓信息

```python
get_position(security)
```

##### get_positions - 获取多只标的持仓信息

```python
get_positions(security_list)
```

##### get_all_positions - 获取全部持仓信息

```python
get_all_positions()
```

##### get_trades_file - 获取对账数据文件

```python
get_trades_file(date)
```

##### convert_position_from_csv - 获取设置底仓的参数列表

```python
convert_position_from_csv(file_path)
```

##### get_user_name - 获取登录终端的资金账号

```python
get_user_name()
```

##### get_deliver - 获取历史交割单信息

```python
get_deliver(start_date, end_date)
```

##### get_fundjour - 获取历史资金流水信息

```python
get_fundjour(start_date, end_date)
```

##### get_research_path - 获取研究路径

```python
get_research_path()
```

##### get_trade_name - 获取交易名称

```python
get_trade_name()
```

##### get_lucky_info - 获取历史中签信息

```python
get_lucky_info(start_date, end_date)
```

### 交易相关函数

#### 股票交易函数

##### order - 按数量买卖

```python
order(security, amount, limit_price=None)
```

**参数说明：**
- security: 标的代码
- amount: 数量，正数买入，负数卖出
- limit_price: 限价，默认None为市价

##### order_target - 指定目标数量买卖

```python
order_target(security, amount, limit_price=None)
```

##### order_value - 指定目标价值买卖

```python
order_value(security, value, limit_price=None)
```

##### order_target_value - 指定持仓市值买卖

```python
order_target_value(security, value, limit_price=None)
```

##### order_market - 按市价进行委托

```python
order_market(security, amount, limit_price=None)
```

##### ipo_stocks_order - 新股一键申购

```python
ipo_stocks_order()
```

##### after_trading_order - 盘后固定价委托

```python
after_trading_order(security, amount, limit_price)
```

##### after_trading_cancel_order - 盘后固定价委托撤单

```python
after_trading_cancel_order(order_id)
```

##### etf_basket_order - ETF成分券篮子下单

```python
etf_basket_order(etf_code, amount, price_type='market', cash_replace_flag='0')
```

##### etf_purchase_redemption - ETF基金申赎接口

```python
etf_purchase_redemption(etf_code, amount, side)
```

#### 公共交易函数

##### order_tick - tick行情触发买卖

```python
order_tick(security, amount, limit_price=None)
```

##### cancel_order - 撤单

```python
cancel_order(order_id)
```

##### cancel_order_ex - 撤单(扩展)

```python
cancel_order_ex(order_id)
```

##### debt_to_stock_order - 债转股委托

```python
debt_to_stock_order(security, amount)
```

##### get_open_orders - 获取未完成订单

```python
get_open_orders()
```

##### get_order - 获取指定订单

```python
get_order(order_id)
```

##### get_orders - 获取全部订单

```python
get_orders()
```

##### get_all_orders - 获取账户当日全部订单

```python
get_all_orders()
```

##### get_trades - 获取当日成交订单

```python
get_trades()
```

### 融资融券专用函数

#### 融资融券交易类函数

##### margin_trade - 担保品买卖

```python
margin_trade(security, amount, limit_price=None)
```

##### margincash_open - 融资买入

```python
margincash_open(security, amount, limit_price=None)
```

##### margincash_close - 卖券还款

```python
margincash_close(security, amount, limit_price=None)
```

##### margincash_direct_refund - 直接还款

```python
margincash_direct_refund(amount)
```

##### marginsec_open - 融券卖出

```python
marginsec_open(security, amount, limit_price=None)
```

##### marginsec_close - 买券还券

```python
marginsec_close(security, amount, limit_price=None)
```

##### marginsec_direct_refund - 直接还券

```python
marginsec_direct_refund(security, amount)
```

#### 融资融券查询类函数

##### get_margincash_stocks - 获取融资标的列表

```python
get_margincash_stocks()
```

##### get_marginsec_stocks - 获取融券标的列表

```python
get_marginsec_stocks()
```

##### get_margin_contract - 合约查询

```python
get_margin_contract()
```

##### get_margin_contractreal - 实时合约查询

```python
get_margin_contractreal()
```

##### get_margin_asset - 信用资产查询

```python
get_margin_asset()
```

##### get_assure_security_list - 担保券查询

```python
get_assure_security_list()
```

##### get_margincash_open_amount - 融资标的最大可买数量查询

```python
get_margincash_open_amount(security)
```

##### get_margincash_close_amount - 卖券还款标的最大可卖数量查询

```python
get_margincash_close_amount(security)
```

##### get_marginsec_open_amount - 融券标的最大可卖数量查询

```python
get_marginsec_open_amount(security)
```

##### get_marginsec_close_amount - 买券还券标的最大可买数量查询

```python
get_marginsec_close_amount(security)
```

##### get_margin_entrans_amount - 现券还券数量查询

```python
get_margin_entrans_amount(security)
```

##### get_enslo_security_info - 融券信息查询

```python
get_enslo_security_info(security)
```

##### get_crdt_fund - 可融资金信息查询

```python
get_crdt_fund()
```

### 期货专用函数

#### 期货交易类函数

##### buy_open - 开多

```python
buy_open(security, amount, limit_price=None)
```

##### sell_close - 多平

```python
sell_close(security, amount, limit_price=None)
```

##### sell_open - 空开

```python
sell_open(security, amount, limit_price=None)
```

##### buy_close - 空平

```python
buy_close(security, amount, limit_price=None)
```

#### 期货查询类函数

##### get_margin_rate - 获取用户设置的保证金比例

```python
get_margin_rate()
```

##### get_instruments - 获取合约信息

```python
get_instruments(security)
```

##### get_dominant_contract - 获取主力合约代码

```python
get_dominant_contract(underlying_code)
```

#### 期货设置类函数

##### set_future_commission - 设置期货手续费

```python
set_future_commission(commission_ratio, min_commission=0.0)
```

##### set_margin_rate - 设置期货保证金比例

```python
set_margin_rate(margin_rate)
```

### 期权专用函数

#### 期权查询类函数

##### get_opt_objects - 获取期权标的列表

```python
get_opt_objects()
```

##### get_opt_last_dates - 获取期权标的到期日列表

```python
get_opt_last_dates(underlying_code)
```

##### get_opt_contracts - 获取期权标的对应合约列表

```python
get_opt_contracts(underlying_code, last_date)
```

##### get_contract_info - 获取期权合约信息

```python
get_contract_info(contract_code)
```

##### get_covered_lock_amount - 获取期权标的可备兑锁定数量

```python
get_covered_lock_amount(underlying_code)
```

##### get_covered_unlock_amount - 获取期权标的允许备兑解锁数量

```python
get_covered_unlock_amount(underlying_code)
```

#### 期权交易类函数

##### option_buy_open - 权利仓开仓

```python
option_buy_open(contract_code, amount, limit_price=None)
```

##### option_sell_close - 权利仓平仓

```python
option_sell_close(contract_code, amount, limit_price=None)
```

##### option_sell_open - 义务仓开仓

```python
option_sell_open(contract_code, amount, limit_price=None)
```

##### option_buy_close - 义务仓平仓

```python
option_buy_close(contract_code, amount, limit_price=None)
```

##### open_prepared - 备兑开仓

```python
open_prepared(contract_code, amount, limit_price=None)
```

##### close_prepared - 备兑平仓

```python
close_prepared(contract_code, amount, limit_price=None)
```

##### option_exercise - 行权

```python
option_exercise(contract_code, amount)
```

#### 期权其他函数

##### option_covered_lock - 期权标的备兑锁定

```python
option_covered_lock(underlying_code, amount)
```

##### option_covered_unlock - 期权标的备兑解锁

```python
option_covered_unlock(underlying_code, amount)
```

### 港股通专用函数

#### 港股通查询类函数

##### get_hks_list - 获取港股通代码

```python
get_hks_list()
```

##### get_hks_price_gap - 港股通价差查询

```python
get_hks_price_gap(security)
```

##### get_hks_unit_amount - 获取港股通标的委托单位数量

```python
get_hks_unit_amount(security)
```

#### 港股通交易类函数

##### hks_order - 港股通买卖

```python
hks_order(security, amount, limit_price=None)
```

##### hks_odd_lot_order - 港股通零股卖出

```python
hks_odd_lot_order(security, amount, limit_price=None)
```

### 计算函数

#### 技术指标计算函数

##### get_MACD - 异同移动平均线

```python
get_MACD(security, fastperiod=12, slowperiod=26, signalperiod=9)
```

##### get_KDJ - 随机指标

```python
get_KDJ(security, fastk_period=9, slowk_period=3, slowd_period=3)
```

##### get_RSI - 相对强弱指标

```python
get_RSI(security, period=14)
```

##### get_CCI - 顺势指标

```python
get_CCI(security, period=14)
```

### 其他函数

##### log - 日志记录

```python
log.info(msg)
log.warn(msg)
log.error(msg)
```

##### is_trade - 业务代码场景判断

```python
is_trade()
```

##### check_limit - 代码涨跌停状态判断

```python
check_limit(security)
```

##### send_email - 发送邮箱信息

```python
send_email(subject, content, receiver)
```

##### send_qywx - 发送企业微信信息

```python
send_qywx(content)
```

##### permission_test - 权限校验

```python
permission_test()
```

##### create_dir - 创建文件路径

```python
create_dir(path)
```

##### get_frequency - 获取当前业务代码的周期

```python
get_frequency()
```

##### get_business_type - 获取当前策略的业务类型

```python
get_business_type()
```

##### get_current_kline_count - 获取股票业务当前时间的分钟bar数量

```python
get_current_kline_count()
```

##### filter_stock_by_status - 过滤指定状态的股票代码

```python
filter_stock_by_status(security_list, status)
```

##### check_strategy - 检查策略内容

```python
check_strategy()
```

##### fund_transfer - 资金调拨

```python
fund_transfer(amount, side)
```

##### market_fund_transfer - 市场间资金调拨

```python
market_fund_transfer(amount, from_market, to_market)
```

---

## 公共资源

### 对象

#### g - 全局对象

用于存储全局变量，可在各函数间共享数据。

```python
g.security = '600570.SS'
g.amount = 1000
```

注意事项：
- 以'__'开头的变量不会被持久化保存
- 不可序列化对象(如IO对象)需以'__'开头命名

#### Context - 上下文对象

包含账户及持仓信息：
- `context.portfolio` - 资产组合对象
- `context.portfolio.cash` - 可用现金
- `context.portfolio.positions` - 持仓字典
- `context.portfolio.total_value` - 总资产

#### BarData - K线数据对象

包含单个K线的数据：
- `close` - 收盘价
- `open` - 开盘价
- `high` - 最高价
- `low` - 最低价
- `volume` - 成交量

#### Portfolio - 资产对象

包含账户资产信息：
- `cash` - 可用现金
- `total_value` - 总资产
- `positions` - 持仓字典
- `available_cash` - 可用资金

#### Position - 持仓对象

包含单个标的持仓信息：
- `security` - 标的代码
- `amount` - 持仓数量
- `total_amount` - 总持仓
- `sellable_amount` - 可卖数量
- `value` - 持仓市值
- `avg_cost` - 成本价
- `price` - 当前价格

#### Order - 委托对象

包含委托信息：
- `order_id` - 委托ID
- `security` - 标的代码
- `amount` - 委托数量
- `filled` - 已成交数量
- `price` - 委托价格
- `avg_cost` - 成交均价
- `status` - 委托状态
- `created_at` - 创建时间

---

## 数据字典

### status - 订单状态

| 值 | 说明 |
|----|------|
| 0 | 未报 |
| 1 | 待报 |
| 2 | 已报 |
| 3 | 已报待撤 |
| 4 | 部成待撤 |
| 5 | 部撤 |
| 6 | 已撤 |
| 7 | 部成 |
| 8 | 已成 |
| 9 | 废单 |

### entrust_type - 委托类别

| 值 | 说明 |
|----|------|
| 0 | 买卖 |
| 1 | 融资买入 |
| 2 | 融券卖出 |

### entrust_prop - 委托属性

| 值 | 说明 |
|----|------|
| 0 | 限价 |
| 1 | 市价 |

### business_direction - 成交方向

| 值 | 说明 |
|----|------|
| 0 | 买入 |
| 1 | 卖出 |

### trans_kind - 委托类型

| 值 | 说明 |
|----|------|
| 0 | 普通 |
| 1 | 融资 |
| 2 | 融券 |

### trade_status - 交易状态

| 值 | 说明 |
|----|------|
| 0 | 正常 |
| 1 | 停牌 |
| 2 | 退市 |

### exchange_type - 交易类别

| 值 | 说明 |
|----|------|
| 1 | 上海 |
| 2 | 深圳 |

---

## 策略中支持的代码尾缀

| 市场品种 | 尾缀全称 | 尾缀简称 |
|---------|---------|---------|
| 上海市场证券 | XSHG | SS |
| 深圳市场证券 | XSHE | SZ |
| 指数 | XBHS | - |
| 中金所期货 | CCFX | - |
| 上海股票期权 | XSHO | - |
| 深圳股票期权 | XSZO | - |
| 上海港股通 | XHKG-SS | - |
| 深圳港股通 | XHKG-SZ | - |

---

## 模拟盘和实盘注意事项

### 关于持久化

#### 为什么要做持久化处理

服务器异常、策略优化等诸多场景，都会使得正在进行的模拟盘和实盘策略存在中断后再重启的需求，但是一旦交易中止后，策略中存储在内存中的全局变量就清空了，因此通过持久化处理为量化交易保驾护航必不可少。

#### 量化框架持久化处理

使用pickle模块保存股票池、账户信息、订单信息、全局变量g定义的变量等内容。

注意事项：
1. 框架会在 before_trading_start(隔日开始)、handle_data、after_trading_end 事件后触发持久化信息更新及保存操作
2. 券商升级/环境重启后恢复交易时，框架会先执行策略initialize函数再执行持久化信息恢复操作
3. 如果持久化信息保存有策略定义的全局对象g中的变量，将会以持久化信息中的变量覆盖掉initialize函数中初始化的该变量
4. 全局变量g中不能被序列化的变量将不会被保存，可在initialize中初始化该变量时名字以'__'开头
5. 涉及到IO(打开的文件，实例化的类对象等)的对象是不能被序列化的
6. 全局变量g中以'__'开头的变量为私有变量，持久化时将不会被保存

#### 策略中持久化处理方法示例

```python
import pickle
from collections import defaultdict

def initialize(context):
    g.notebook_path = get_research_path()
    #尝试启动pickle文件
    try:
        with open(g.notebook_path+'hold_days.pkl','rb') as f:
            g.hold_days = pickle.load(f)
    except:
        #定义空的全局字典变量
        g.hold_days = defaultdict(list)
    g.security = '600570.SS'
    set_universe(g.security)

# 仓龄增加一天
def before_trading_start(context, data):
    if g.hold_days:
        g.hold_days[g.security] += 1

# 每天将存储仓龄的字典对象进行pickle保存
def handle_data(context, data):
    if g.security not in list(context.portfolio.positions.keys()) and g.security not in g.hold_days:
        order(g.security, 100)
        g.hold_days[g.security] = 1
    if g.hold_days:
        if g.hold_days[g.security] > 5:
            order(g.security, -100)
            del g.hold_days[g.security]
    with open(g.notebook_path+'hold_days.pkl','wb') as f:
        pickle.dump(g.hold_days,f,-1)
```

### 关于异常处理

#### 为什么要做异常处理

交易场景数据缺失等原因会导致策略运行过程中常规的处理出现语法错误，导致策略终止，所以需要做一些异常处理的保护。

#### 示例

```python
try:
    # 尝试执行的代码
    print(a)
except Exception as e:
    # 使用as关键字可以获取异常的实例
    print("出现异常，error为: %s" % e)
    a = 1
    print(a)
```

```python
try:
    a = 1
    print(a)
except:
    print(a)
else:
    # 如果try块成功执行，没有引发异常，可以选择性地添加一个else块。
    print('执行正常')
```

```python
try:
    a = 1
    print(a)
except:
    print(a)
finally:
    # 无论是否发生异常，finally块中的代码都将被执行
    print('执行完毕')
```

### 关于限价交易的价格

- 可转债、ETF、LOF的价格是小数点三位
- 股票的价格是小数点两位
- 股指期货的价格是小数点一位
- ETF期权的价格是小数点四位

用户在使用限价单委托和市价委托保护限价的场景时务必要对入参价格的小数点位数进行处理，否则会导致委托失败。

---

## 常见问题

1. **策略中的全局变量如何持久化？**
   - 使用pickle模块将变量保存到文件，以'__'开头的变量不会被自动持久化

2. **如何处理策略运行中的异常？**
   - 使用try-except语句包裹可能出错的代码块

3. **如何设置策略的股票池？**
   - 在initialize函数中使用set_universe设置

4. **如何获取历史行情数据？**
   - 使用get_history或get_price函数

5. **策略支持哪些交易品种？**
   - 股票、可转债、ETF、LOF、期货、期权、港股通等

---

## 支持的三方库

PTrade支持以下常用第三方库：
- numpy - 数值计算
- pandas - 数据处理
- talib - 技术分析
- pickle - 数据持久化
- json - JSON处理
- datetime - 日期时间
- math - 数学运算
- collections - 集合类

---

*文档版本：PTrade国金版 API文档*  
*更新时间：2024年*
