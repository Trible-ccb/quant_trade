# 克隆自聚宽文章：https://www.joinquant.com/post/1399
# 标题：【量化课堂】多因子策略入门
# 作者：JoinQuant量化课堂

# 克隆自聚宽文章：https://www.joinquant.com/post/67552
# 标题：实盘多策略
# 作者：贪财好色No1

# 克隆自聚宽文章：https://www.joinquant.com/post/67552
# 标题：实盘多策略
# 作者：小牛无价

from jqdata import *
from jqfactor import get_factor_values
import datetime
import math
from scipy.optimize import minimize
import pandas as pd
import numpy as np
from datetime import timedelta

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    # set_benchmark("515080.XSHG")
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 开启动态复权模式(真实价格)
    set_option("use_real_price", True)
    # 输出内容到日志 log.info()
    log.info("初始函数开始运行且全局只运行一次")
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level("order", "error")
    # 固定滑点设置ETF 0.001(即交易对手方一档价)
    set_slippage(FixedSlippage(0.001), type="fund")
    # 股票交易总成本0.3%(含固定滑点0.02)
    set_slippage(FixedSlippage(0.0003), type="stock")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=1/1000,
            open_commission=0.0001,
            close_commission=0.0001,
            close_today_commission=0,
            min_commission=5,
        ),
        type="stock",
    )
    # 设置货币ETF交易佣金0
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0,
            close_commission=0,
            close_today_commission=0,
            min_commission=0,
        ),
        type="mmf",
    )
    # 全局变量 "搅屎棍策略""全天候策略""高股息小市值策略""弱周期价投策略""核心资产轮动策略"
    g.strategys = {}
    # 原资金比例 [0.4, 0.2, 0.2, 0, 0.2]
    # 现在新增第六个策略“五福ETF策略”，默认比例为0，方便用户自行调整
    g.portfolio_value_proportion = [0.3, 0, 0.2, 0.15, 0.15, 0.2]  # 标准版 + 五福ETF(0)
    #g.portfolio_value_proportion = [0, 0.3, 0.1, 0.5, 0.1, 0]  # 养老版 + 五福ETF(0)
    g.positions = {i: {} for i in range(len(g.portfolio_value_proportion))}  # 记录每个子策略的持仓股票

    # === 新增代码：初始化动态止损变量 ===
    g.high_prices = {}  # 记录每个股票的历史最高价

    # 策略变量
    g.jsg_signal = True  # 搅屎棍开仓信号

    # 子策略执行计划
    if g.portfolio_value_proportion[0] > 0:
        run_weekly(jsg_adjust, 1, "11:00")
        run_daily(jsg_check, "14:45")
    if g.portfolio_value_proportion[1] > 0:
        run_monthly(all_day_adjust, 1, "11:05")
    if g.portfolio_value_proportion[2] > 0:
        run_monthly(high_dividend_adjust, 1, "11:15")  # 高股息策略调仓
        run_daily(high_dividend_check, "14:45")  # 高股息策略检查
    if g.portfolio_value_proportion[3] > 0:
        run_weekly(weak_cyc_adjust, 1, "11:10")
    if g.portfolio_value_proportion[4] > 0:
        run_daily(etf_rotation_adjust, "9:35")
    # === 新增：五福ETF策略 ===
    if g.portfolio_value_proportion[5] > 0:
        run_daily(wufu_update_pool, "09:00")   # 动态ETF池更新
        run_daily(wufu_adjust, "13:10")        # 调仓（卖出+买入）
        run_daily(wufu_stop_loss, "14:50")     # 止损检查
    # 每日剩余资金购买货币ETF
    run_daily(get_stock_list, '9:05')
    run_daily(end_trade, "14:55")
    # === 新增代码：每日执行止损检查 ===
    run_daily(check_stop_loss, "14:50")  # 在收盘前检查止损
    run_daily(print_position_info, time='14:55')

#1-2 选股模块
def get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = get_index_stocks(MKT_index)
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_limitup_stock(context, initial_list)
    initial_list = filter_limitdown_stock(context, initial_list)
    
    # 原始查询，只获取code和eps
    q = query(valuation.code,indicator.adjusted_profit).filter(valuation.code.in_(initial_list),indicator.adjusted_profit > 0).order_by(valuation.market_cap.asc())
    df = get_fundamentals(q)
    stock_list = list(df.code)
    stock_list = stock_list[:100]
    final_list = stock_list[:10]
    # 创建代码和名称对应的列表
    stocks_with_names = []
    for code in final_list:
    # 获取股票信息，然后取显示名称（中文）
        stock_info = get_security_info(code)
        if stock_info:
           stock_name = stock_info.display_name
        else:
           stock_name = '未知'
        stocks_with_names.append(f"{code}({stock_name})")

    # 将列表转化为字符串，用逗号分隔
    formatted_list = ', '.join(stocks_with_names)
    log.info('今日股票池: %s' % formatted_list)
    return final_list

def print_position_info(context):
    all_stocks = get_all_securities()
    print('————————————————————————— 持仓信息 —————————————————————————')
    for position in list(context.portfolio.positions.values()):
        securities = position.security
        # 获取股票中文名称
        stock_info = get_security_info(securities)
        stock_name = stock_info.display_name if stock_info else "未知"
        cost = position.avg_cost
        price = position.price
        ret = 100 * (price/cost - 1) if cost > 0 else 0
        value = position.value
        amount = position.total_amount    
        print(f'代码: {securities}')
        print(f'名称: {stock_name}')
        print(f'成本价: {cost:.2f}')
        print(f'现  价: {price:.2f}')
        print(f'收益率: {ret:.2f}%')
        print(f'持仓(股): {amount:.0f}')
        print(f'市  值: {value:.2f}')
        print('———————————————————————————————————————————————————————') 

#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] <    current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date <  datetime.timedelta(days=375)]

#2-6.5 过滤股价
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] <= 100]

#2-7 删除本周一买入的股票
def filter_not_buy_again(stock_list):
    return [stock for stock in stock_list if stock not in g.not_buy_again]
 
  
def process_initialize(context):
    print("重启程序")
    g.strategys["搅屎棍策略"] = JSG_Strategy(context, index=0, name="搅屎棍策略")
    g.strategys["全天候策略"] = All_Day_Strategy(context, index=1, name="全天候策略")
    # 替换：高股息策略 替代 简单ROA策略
    g.strategys["高股息小市值策略"] = HighDividendStrategy(context, index=2, name="高股息小市值策略")
    g.strategys["弱周期价投策略"] = Weak_Cyc_Strategy(context, index=3, name="弱周期价投策略")
    g.strategys["核心资产轮动策略"] = Etf_Rotation_Strategy(context, index=4, name="核心资产轮动策略")
    # === 新增：五福ETF策略 ===
    g.strategys["五福ETF策略"] = WuFuETF_Strategy(context, index=5, name="五福ETF策略")
  
  
# === 新增代码：动态止损函数 ===
def check_stop_loss(context):
    current_data = get_current_data()
    for security in context.portfolio.positions:
        # 跳过已清仓的股票
        if context.portfolio.positions[security].total_amount == 0:
            continue
          
        # 获取当前价格和持仓信息
        price = current_data[security].last_price
        position = context.portfolio.positions[security]
          
        # 初始化最高价（取持仓成本价和当前价的较大值）
        if security not in g.high_prices:
            g.high_prices[security] = max(position.avg_cost, price)
        else:
            g.high_prices[security] = max(g.high_prices[security], price)
          
        # 计算回撤比例
        drawdown = 1 - price / g.high_prices[security]
          
        # 触发12%止损
        if drawdown >= 0.15:
            # 执行卖出操作（使用策略基类的下单方法保证合规性）
            for strategy in g.strategys.values():
                if security in g.positions[strategy.index]:
                    if strategy.order_target_value_(security, 0):
                        log.info(f"[动态止损] {security} 回撤{drawdown*100:.1f}%, 触发止损")
                        del g.high_prices[security]  # 清除记录
                    break
  
  
# 尾盘处理
def end_trade(context):
    current_data = get_current_data()

    # 卖出未记录的股票（比如送股）
    keys = [key for d in g.positions.values() if isinstance(d, dict) for key in d.keys()]
    for stock in context.portfolio.positions:
        # 跳过已清仓的股票
        if context.portfolio.positions[stock].total_amount == 0:
            continue
        if stock not in keys and current_data[stock].last_price < current_data[stock].high_limit:
            if order_target_value(stock, 0):
                log.info(f"卖出{stock}因送股未记录在持仓中")

    # 不再买入货币ETF，剩余资金保留
  
  
# 策略基类
class Strategy:

    def __init__(self, context, index, name):
        self.context = context
        self.index = index
        self.name = name
        self.stock_sum = 1
        self.hold_list = []
        self.min_volume = 2000
        self.pass_months = [1, 4]
        self.def_stocks = ["511260.XSHG", "518880.XSHG", "512890.XSHG"]  # 债券ETF、黄金ETF、红利低波ETF

    # 获取策略当前持仓市值
    def get_total_value(self):
        if not g.positions[self.index]:
            return 0
        return sum(self.context.portfolio.positions[key].price * value for key, value in g.positions[self.index].items())

    # 卖出非连板股票，并且返回成功卖出的股票列表
    def _check(self):
        # 获取已持有列表
        self.hold_list = list(g.positions[self.index].keys())
        stocks = []
        # 获取昨日涨停、前日涨停昨日跌停列表
        if self.hold_list != []:
            df = get_price(
                self.hold_list,
                end_date=self.context.previous_date,
                frequency="daily",
                fields=["close", "high_limit"],
                count=3,
                panel=False,
                fill_paused=False,
            )
            df = df[df["close"] == df["high_limit"]]
            for stock in df.code.drop_duplicates():
                if self.order_target_value_(stock, 0):
                    stocks.append(stock)
        return stocks

    # 调仓(等权购买target中按顺序排列固定数量的的标的)
    def _adjust(self, target):

        # 获取已持有列表
        self.hold_list = list(g.positions[self.index].keys())

        # 调仓卖出
        for stock in self.hold_list:
            if stock not in target:
                self.order_target_value_(stock, 0)

        # 调仓买入
        target = [stock for stock in target if stock not in self.hold_list]
        sum = self.stock_sum - len(self.hold_list)
        self.buy(target[: min(len(target), sum)])

    # 调仓2(targets为字典，key为股票代码，value为目标市值)
    def _adjust2(self, targets):

        # 获取已持有列表
        self.hold_list = list(g.positions[self.index].keys())
        current_data = get_current_data()
        portfolio = self.context.portfolio

        # 清仓被调出的
        for stock in self.hold_list:
            if stock not in targets:
                self.order_target_value_(stock, 0)

        # 先卖出
        for stock, target in targets.items():
            price = current_data[stock].last_price
            value = g.positions[self.index].get(stock, 0) * price
            if value - target > self.min_volume and value - target > price * 100:
                self.order_target_value_(stock, target)

        # 后买入
        for stock, target in targets.items():
            price = current_data[stock].last_price
            value = g.positions[self.index].get(stock, 0) * price
            if target - value > self.min_volume and target - value > price * 100:
                # 仅使用现有可用现金，不卖出货币ETF获取现金
                if portfolio.available_cash > price * 100 and portfolio.available_cash > self.min_volume:
                    self.order_target_value_(stock, target)

    # 可用现金等比例买入
    def buy(self, target):

        count = len(target)
        portfolio = self.context.portfolio

        # target为空或者持仓数量已满，不进行操作
        if count == 0 or self.stock_sum <= len(self.hold_list):
            return

        # 目标市值
        target_value = portfolio.total_value * g.portfolio_value_proportion[self.index]

        # 当前市值
        position_value = self.get_total_value()

        # 可用现金:仅使用账户当前可用现金，不包含货币ETF市值
        available_cash = portfolio.available_cash

        # 买入股票的总市值
        value = max(0, min(target_value - position_value, available_cash))

        # 等价值买入每一个未买入的标的
        for security in target:
            self.order_target_value_(security, value / count)

    # 自定义下单(涨跌停不交易)
    def order_target_value_(self, security, value):
        current_data = get_current_data()

        # 检查标的是否停牌、涨停、跌停
        if current_data[security].paused:
            log.info(f"{security}: 今日停牌")
            return False

        # 检查是否涨停
        if current_data[security].last_price == current_data[security].high_limit:
            log.info(f"{security}: 当前涨停")
            return False

        # 检查是否跌停
        if current_data[security].last_price == current_data[security].low_limit:
            log.info(f"{security}: 当前跌停")
            return False

        # 获取当前标的的价格
        price = current_data[security].last_price

        # 获取当前策略的持仓数量
        current_position = g.positions[self.index].get(security, 0)

        # 计算目标持仓数量
        target_position = (int(value / price) // 100) * 100 if price != 0 else 0

        # 计算调整量（新增代码）
        adjustment = target_position - current_position

        # 检查是否当天买入卖出
        closeable_amount = self.context.portfolio.positions[security].closeable_amount if security in self.context.portfolio.positions else 0
        if adjustment < 0 and closeable_amount == 0:
            log.info(f"{security}: 当天买入不可卖出")
            return False

        # 下单并更新持仓
        if adjustment != 0:
            o = order(security, adjustment)
            if o:
                # === 新增代码：更新最高价记录 ===
                if adjustment > 0:  # 买入操作
                    if security not in g.high_prices:
                        g.high_prices[security] = price
                    else:
                        g.high_prices[security] = max(g.high_prices[security], price)
                
                # 更新持仓数量
                amount = o.amount if o.is_buy else -o.amount
                g.positions[self.index][security] = amount + current_position
                # 如果目标持仓为零，移除该证券
                if target_position == 0:
                    g.positions[self.index].pop(security, None)
                # 更新持有列表
                self.hold_list = list(g.positions[self.index].keys())
                return True
        return False

    # 基础过滤(过滤科创北交、ST、停牌、次新股)
    def filter_basic_stock(self, stock_list):

        current_data = get_current_data()
        return [
            stock
            for stock in stock_list
            if not current_data[stock].paused
            and not current_data[stock].is_st
            and "ST" not in current_data[stock].name
            and "*" not in current_data[stock].name
            and "退" not in current_data[stock].name
            and not (stock[0] == "4" or stock[0] == "8" or stock[:2] == "68")
            and not self.context.previous_date - get_security_info(stock).start_date < datetime.timedelta(375)
        ]

    # 过滤当前时间涨跌停的股票
    def filter_limitup_limitdown_stock(self, stock_list):
        current_data = get_current_data()
        return [
            stock
            for stock in stock_list
            if current_data[stock].last_price < current_data[stock].high_limit and current_data[stock].last_price > current_data[stock].low_limit
        ]

    # 过滤近几日涨停过的股票
    def filter_limitup_stock(self, stock_list, days):
        df = get_price(
            stock_list,
            end_date=self.context.previous_date,
            frequency="daily",
            fields=["close", "high_limit"],
            count=days,
            panel=False,
        )
        df = df[df["close"] == df["high_limit"]]
        filterd_stocks = df.code.drop_duplicates().tolist()
        return [stock for stock in stock_list if stock not in filterd_stocks]

    # 判断今天是在空仓月
    def is_empty_month(self):
        month = self.context.current_dt.month
        return month in self.pass_months
  
  
# 搅屎棍策略
class JSG_Strategy(Strategy):

    def __init__(self, context, index, name):
        super().__init__(context, index, name)

        self.stock_sum = 5
        # 判断买卖点的行业数量
        self.num = 1
        # 空仓的月份
        self.pass_months = [1, 4]

    def getStockIndustry(self, stocks):
        industry = get_industry(stocks)
        return pd.Series({stock: info["sw_l1"]["industry_name"] for stock, info in industry.items() if "sw_l1" in info})

    # 获取市场宽度
    def get_market_breadth(self):
        # 指定日期防止未来数据
        yesterday = self.context.previous_date
        # 获取初始列表
        stocks = get_index_stocks("000985.XSHG")
        count = 3
        h = get_price(
            stocks,
            end_date=yesterday,
            frequency="1d",
            fields=["close"],
            count=count + 20,
            panel=False,
        )
        h["date"] = pd.DatetimeIndex(h.time).date
        df_close = h.pivot(index="code", columns="date", values="close").dropna(axis=0)
        # 计算20日均线
        df_ma20 = df_close.rolling(window=20, axis=1).mean().iloc[:, -count:]
        # 计算偏离程度
        df_bias = df_close.iloc[:, -count:] > df_ma20
        df_bias["industry_name"] = self.getStockIndustry(stocks)
        # 计算行业偏离比例
        df_ratio = ((df_bias.groupby("industry_name").sum() * 100.0) / df_bias.groupby("industry_name").count()).round()
        # 获取偏离程度最高的行业
        top_values = df_ratio.loc[:, yesterday].nlargest(self.num)
        I = top_values.index.tolist()
        return I

    # 过滤股票
    def filter(self):
        stocks = get_index_stocks("399101.XSHE")
        stocks = self.filter_basic_stock(stocks)
        stocks = self.filter_limitup_stock(stocks, 10)
        stocks = (
            get_fundamentals(
                query(
                    valuation.code,
                )
                .filter(
                    valuation.code.in_(stocks),
                    indicator.adjusted_profit > 0,
                )
                .order_by(valuation.market_cap.asc())
            )
            .head(20)
            .code
        )
        stocks = self.filter_limitup_limitdown_stock(stocks)
        return stocks

    # 择时
    def select(self):
        I = self.get_market_breadth()
        industries = {"银行I", "煤炭I", "交通运输I", "钢铁I"}
        if not industries.intersection(I) and not self.is_empty_month():
            return True
        return False

    # 调仓
    def adjust(self):
        if self.select():
            stocks = self.filter()[: self.stock_sum]
            self._adjust(stocks)
        else:
            total_value = self.context.portfolio.total_value * g.portfolio_value_proportion[self.index]
            self._adjust2({stock: total_value / len(self.def_stocks) for stock in self.def_stocks})

    # 检查昨日涨停票
    def check(self):
        banner_stocks = self._check()
        if banner_stocks:
            target = [stock for stock in self.filter() if stock not in banner_stocks and stock not in self.hold_list][: len(banner_stocks)]
            self.buy(target)
  
  
# 全天候ETF策略
class All_Day_Strategy(Strategy):

    def __init__(self, context, index, name):
        super().__init__(context, index, name)

        # 最小交易额(限制手续费)
        self.min_volume = 1000
        # 全天候ETF组合参数
        self.etf_pool = [
            "512890.XSHG",  # 红利低波ETF
            "513100.XSHG",  # 纳指100
            "511010.XSHG",  # 国债ETF
            "518800.XSHG",  # 黄金ETF
        ]
        # 标的仓位占比
        self.rates = [0.25, 0.25, 0.25, 0.25]

    # 调仓
    def adjust(self):
        total_value = self.context.portfolio.total_value * g.portfolio_value_proportion[self.index]
        # 计算每个 ETF 的目标价值
        targets = {etf: total_value * rate for etf, rate in zip(self.etf_pool, self.rates)}
        self._adjust2(targets)
  
  
# 高股息小市值策略（替换原简单ROA策略）
class HighDividendStrategy(Strategy):
    def __init__(self, context, index, name):
        super().__init__(context, index, name)
        self.stock_sum = 5  # 持仓数量，可根据需要调整
        self.div_ratio_top_pct = 0.15  # 取股息率前15%的股票
        self.max_market_cap = 80  # 最大市值（亿）
        self.max_price = 20  # 最高股价（元）

    # 计算股息率并筛选前N%的股票
    def get_high_dividend_stocks(self, stock_list):
        if not stock_list:
            return []
        
        time1 = self.context.previous_date
        time0 = time1 - datetime.timedelta(days=365)  # 过去1年
        
        # 获取过去1年分红数据
        q = query(
            finance.STK_XR_XD.code,
            finance.STK_XR_XD.bonus_amount_rmb
        ).filter(
            finance.STK_XR_XD.code.in_(stock_list),
            finance.STK_XR_XD.a_registration_date >= time0,
            finance.STK_XR_XD.a_registration_date <= time1
        )
        df_div = finance.run_query(q).fillna(0)
        df_div = df_div.groupby('code')['bonus_amount_rmb'].sum().reset_index()  # 累计分红
        
        # 获取市值数据
        q = query(
            valuation.code,
            valuation.market_cap  # 市值（亿）
        ).filter(valuation.code.in_(df_div['code'].tolist()))
        df_cap = get_fundamentals(q, date=time1)
        
        # 计算股息率（分红总额/市值）
        df = pd.merge(df_div, df_cap, on='code')
        df['dividend_ratio'] = (df['bonus_amount_rmb'] / 10000) / df['market_cap']  # 分红（万元）/市值（亿）
        
        # 取股息率前N%的股票
        df = df.sort_values('dividend_ratio', ascending=False)
        top_n = int(len(df) * self.div_ratio_top_pct)
        return df['code'].iloc[:top_n].tolist()

    # 过滤股票：结合估值、市值、股价
    def filter(self):
        # 初始股票池（深证A股指数成分股）
        stocks = get_index_stocks("399101.XSHE")
        
        # 基础过滤：排除科创北交、ST、停牌、次新股（继承父类方法）
        stocks = self.filter_basic_stock(stocks) 
        # 修正：使用self.context访问上下文变量
        stocks = filter_highprice_stock(self.context, stocks)  # 过滤10元股
        if not stocks:
            return []
        # 筛选高股息股票
        stocks = self.get_high_dividend_stocks(stocks)
        if not stocks:
            return []
        
        # 进一步筛选：低PEG、小市值、低股价
        q = query(
            valuation.code,
            (valuation.pe_ratio / indicator.inc_net_profit_year_on_year).label('peg'),  # PEG（估值/成长性）
            valuation.market_cap,  # 市值
            ).filter(
            valuation.code.in_(stocks),
            indicator.inc_net_profit_year_on_year > 0,  # 净利润正增长（避免PEG为负）
            (valuation.pe_ratio / indicator.inc_net_profit_year_on_year) < 3,  # PEG < 3（低估值）
            valuation.market_cap <= self.max_market_cap,  # 小市值
        ).order_by(valuation.market_cap.asc())  # 按市值从小到大排序
        
        df = get_fundamentals(q)
        stocks = df['code'].tolist()
        
        # 过滤当前涨跌停股票
        stocks = self.filter_limitup_limitdown_stock(stocks)
        return stocks
    
    # 过滤股价高于10元的股票    
    def filter_highprice_stock(self, stocks):
        last_prices = history(1, unit='1m', field='close', security_list=stocks)
        return [stock for stock in stocks if stock in self.context.portfolio.positions.keys()
                or last_prices[stock][-1] < self.max_price]
                
    # 调仓逻辑：买入筛选后的股票，等权配置
    def adjust(self):
        target_stocks = self.filter()[:self.stock_sum]  # 取前N只股票
        self._adjust(target_stocks)  # 调用父类调仓方法

    # 检查涨停股票：若昨日涨停今日打开，卖出
    def check(self):
        banner_stocks = self._check()  # 父类方法：获取昨日涨停股票
        if banner_stocks:
            # 卖出后补仓新股票
            target = [stock for stock in self.filter() if stock not in banner_stocks and stock not in self.hold_list]
            self.buy(target[:len(banner_stocks)])  # 补仓同等数量的股票
  

# 弱周期价投策略
class Weak_Cyc_Strategy(Strategy):
    def __init__(self, context, index, name):
        super().__init__(context, index, name)

        self.bond_etf = "511260.XSHG"
        self.targets = {}
        # 最小交易额(限制手续费)
        self.min_volume = 10000
        # 行业比例（公用事业、交通运输）
        self.industry_ratio = [0.2, 0.2]
        # 个股比例(龙一龙二)
        self.stock_ratio = [1]
        self.total_value = 0

    # 分红过滤(近几年的分红总和满足股息率与股利支付率)
    def filter_dividend(self, stocks, year, div_yield, payout_rate):

        if not stocks:
            return []

        time1 = self.context.previous_date
        time0 = time1 - timedelta(days=(year + 0.1) * 365)
        f = finance.STK_XR_XD
        q = query(f.code, f.bonus_amount_rmb).filter(
            f.code.in_(stocks),
            f.board_plan_pub_date >= time0,
            f.board_plan_pub_date <= time1,
        )
        df = finance.run_query(q).fillna(0).set_index("code").groupby("code").sum()

        # 获取市值相关数据
        q = query(valuation.code, valuation.market_cap, valuation.pe_ratio).filter(valuation.code.in_(list(df.index)))
        cap = get_fundamentals(q, date=time1).set_index("code")

        # 计算股息率, 股利支付率
        df = pd.concat([df, cap], axis=1, sort=False)
        df["div_yield"] = df["bonus_amount_rmb"] / (df["market_cap"] * 10000) / year
        df["payout_rate"] = df["bonus_amount_rmb"] / ((df["market_cap"] * 10000) / df["pe_ratio"]) / year
        df = df.query("div_yield > @div_yield and payout_rate > @payout_rate")
        return list(df.index)

    # 利润过滤(近几年的营业收入、净利率、毛利率)
    def filter_profit(self, stocks, year, net_profit_margin, gross_profit_margin):

        if not stocks:
            return []

        df = get_history_fundamentals(
            stocks,
            fields=[income.operating_revenue, indicator.net_profit_margin, indicator.gross_profit_margin],
            watch_date=self.context.previous_date,
            count=4 * year,
            interval="1q",
            stat_by_year=False,
        )

        def agg_func(group):
            revenue = group["operating_revenue"].sum()
            return pd.Series(
                {
                    "operating_revenue": revenue,
                    "weighted_net_profit_margin": (group["operating_revenue"] * group["net_profit_margin"]).sum() / revenue,
                    "weighted_gross_profit_margin": (group["operating_revenue"] * group["gross_profit_margin"]).sum() / revenue,
                }
            )

        df = df.groupby("code").apply(agg_func).reset_index()
        df = df.query("weighted_net_profit_margin > @net_profit_margin and weighted_gross_profit_margin > @gross_profit_margin")
        return list(df.code)

    # 获取净利润波动率(近几年的净利润标准差)
    def get_profit_vol(self, stocks, year):

        df = get_history_fundamentals(
            stocks,
            fields=[income.net_profit],
            watch_date=self.context.previous_date,
            count=4 * year,
            interval="1q",
            stat_by_year=False,
        )
        df["rolling_profit"] = df.groupby("code")["net_profit"].rolling(4).sum().reset_index(level=0, drop=True)
        df["growth_rate"] = df.groupby("code")["rolling_profit"].pct_change()
        return df.groupby("code")["growth_rate"].std().reset_index(name="volatility")

    # 801160: 公用事业I
    def select1(self):
        stocks = get_industry_stocks("801160")
        # 基本面过滤
        stocks = self.filter_basic_stock(stocks)
        df = get_fundamentals(
            query(valuation.code, valuation.pe_ratio).filter(
                valuation.code.in_(stocks),
                # 现金流
                cash_flow.net_operate_cash_flow > 0,
                cash_flow.subtotal_operate_cash_inflow / indicator.adjusted_profit > 1.0,
                # 资产
                balance.total_liability / balance.total_assets < 0.8,
                # 市值
                valuation.market_cap > 200,
            )
        )

        stocks = self.filter_dividend(list(df.code), 3, 0.02, 0.4)
        stocks = self.filter_profit(stocks, 1, 20, 30)

        if not stocks:
            return

        # 业绩排序
        vol = self.get_profit_vol(stocks, 3)
        df = vol.merge(df[["code", "pe_ratio"]], on="code", how="left")
        df["score"] = 1 / df["pe_ratio"] * (1 - 2 * df["volatility"])
        df = df.sort_values(by="score", ascending=False).reset_index(drop=True)

        for i, ratio in enumerate(self.stock_ratio[: len(df)]):
            self.targets[df.code[i]] = self.total_value * ratio * self.industry_ratio[0]

    # 801170: 交通运输I
    def select2(self):
        stocks = get_industry_stocks("801170")
        # 基本面过滤
        stocks = self.filter_basic_stock(stocks)
        df = get_fundamentals(
            query(valuation.code, valuation.pe_ratio, indicator.roa).filter(
                valuation.code.in_(stocks),
                # 现金流
                cash_flow.net_operate_cash_flow > 0,
                cash_flow.subtotal_operate_cash_inflow / indicator.adjusted_profit > 1.0,
                # 资产
                balance.total_liability / balance.total_assets < 0.6,
                # 市值
                valuation.market_cap > 200,
            )
        )
        stocks = self.filter_dividend(list(df.code), 3, 0.02, 0.3)
        stocks = self.filter_profit(stocks, 1, 20, 30)

        if not stocks:
            return

        # 业绩排序
        vol = self.get_profit_vol(stocks, 3)
        df = vol.merge(df[["code", "pe_ratio"]], on="code", how="left")
        df["score"] = 1 / df["pe_ratio"] * (1 - 2 * df["volatility"])
        df = df.sort_values(by="score", ascending=False).reset_index(drop=True)

        for i, ratio in enumerate(self.stock_ratio[: len(df)]):
            self.targets[df.code[i]] = self.total_value * ratio * self.industry_ratio[1]

    def adjust(self):
        self.targets = {}
        self.total_value = self.context.portfolio.total_value * g.portfolio_value_proportion[self.index]
        self.select1()
        self.select2()
        self.targets[self.bond_etf] = self.total_value - sum(list(self.targets.values()))
        self._adjust2(self.targets)
  
  
# 核心资产轮动策略
class Etf_Rotation_Strategy(Strategy):
    def __init__(self, context, index, name):
        super().__init__(context, index, name)

        self.stock_sum = 1
        self.etf_pool = [
            # 境外
            "513100.XSHG",  # 纳指ETF
            "513520.XSHG",  # 日经ETF
            "513030.XSHG",  # 德国ETF
            # 商品
            "518880.XSHG",  # 黄金ETF
            "159980.XSHE",  # 有色ETF
            "501018.XSHG",  # 南方原油
            # 债券
            "511090.XSHG",  # 30年国债ETF
            # 国内
            "513130.XSHG",  # 恒生科技
            "512890.XSHG",  # 红利低波
            "520550.XSHG",  # 恒生红利低波
            "515450.XSHG",  # 标普红利低波
            "159915.XSHE",  # 创业板
        ]
        self.m_days = 22  # 动量参考天数

    def get_etf_rank(self):
        data = pd.DataFrame(index=self.etf_pool, columns=["annualized_returns", "r2", "score"])
        current_data = get_current_data()
        for etf in self.etf_pool:
            # 获取数据
            df = attribute_history(etf, self.m_days, "1d", ["close", "high"])
            prices = np.append(df["close"].values, current_data[etf].last_price)

            # 设置参数
            y = np.log(prices)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))

            # 计算年化收益率
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            data.loc[etf, "annualized_returns"] = math.exp(slope * 250) - 1

            # 计算R²
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            data.loc[etf, "r2"] = 1 - ss_res / ss_tot if ss_tot else 0

            # 计算得分
            data.loc[etf, "score"] = data.loc[etf, "annualized_returns"] * data.loc[etf, "r2"]

            # 过滤近3日跌幅超过5%的ETF
            if min(prices[-1] / prices[-2], prices[-2] / prices[-3], prices[-3] / prices[-4]) < 0.95:
                data.loc[etf, "score"] = 0

        # 过滤ETF，并按得分降序排列
        data = data.query("0 < score < 6").sort_values(by="score", ascending=False)

        return data.index.tolist()

    def adjust(self):
        target = self.get_etf_rank()
        self._adjust(target[: min(self.stock_sum, len(target))])


# 以下是原代码中调用的其他函数，保持不变
def jsg_check(context):
    g.strategys["搅屎棍策略"].check()

def jsg_adjust(context):
    g.strategys["搅屎棍策略"].adjust()

def all_day_adjust(context):
    g.strategys["全天候策略"].adjust()

def simple_roa_adjust(context):
    g.strategys["高股息小市值策略"].adjust()  # 替换为高股息策略

def simple_roa_check(context):
    g.strategys["高股息小市值策略"].check()  # 替换为高股息策略

def weak_cyc_adjust(context):
    g.strategys["弱周期价投策略"].adjust()

def etf_rotation_adjust(context):
    g.strategys["核心资产轮动策略"].adjust()

# 新增：高股息策略的调仓和检查函数
def high_dividend_adjust(context):
    g.strategys["高股息小市值策略"].adjust()

def high_dividend_check(context):
    g.strategys["高股息小市值策略"].check()

# === 新增：五福ETF策略的外部调用函数 ===
def wufu_update_pool(context):
    g.strategys["五福ETF策略"].update_dynamic_pool()

def wufu_adjust(context):
    g.strategys["五福ETF策略"].adjust()

def wufu_stop_loss(context):
    g.strategys["五福ETF策略"].stop_loss()


# === 新增：五福ETF策略类定义 ===
class WuFuETF_Strategy(Strategy):
    def __init__(self, context, index, name):
        super().__init__(context, index, name)
        # 五福ETF参数
        self.fixed_etf_pool = [
            '518880.XSHG', '161226.XSHE', '159980.XSHE', '501018.XSHG', '159985.XSHE',
            '513100.XSHG', '513500.XSHG', '513400.XSHG', '159509.XSHE', '159518.XSHE',
            '159529.XSHE', '513290.XSHG', '520830.XSHG', '513520.XSHG', '513030.XSHG',
            '513090.XSHG', '513180.XSHG', '513120.XSHG', '513330.XSHG', '513750.XSHG',
            '159892.XSHE', '159605.XSHE', '513190.XSHG', '159502.XSHE', '510900.XSHG',
            '513630.XSHG', '513920.XSHG', '159323.XSHE', '513970.XSHG',
            '510500.XSHG', '510300.XSHG', '511380.XSHG', '512050.XSHG', '159915.XSHE',
            '588080.XSHG', '512100.XSHG', '159949.XSHE', '588220.XSHG', '563300.XSHG',
            '159967.XSHE', '510760.XSHG'
        ]
        self.dynamic_etf_pool = []
        self.holdings_num = 1
        self.defensive_etf = "511880.XSHG"
        self.safe_haven_etf = '511660.XSHG'
        self.min_money = 5000
        self.lookback_days = 25
        self.min_score_threshold = 0
        self.max_score_threshold = 5
        self.use_short_momentum_filter = False
        self.short_lookback_days = 10
        self.short_momentum_threshold = 0.0
        self.enable_r2_filter = True
        self.r2_threshold = 0.4
        self.enable_annualized_return_filter = False
        self.min_annualized_return = 1.0
        self.enable_ma_filter = False
        self.ma_filter_days = 20
        self.enable_volume_check = True
        self.volume_lookback = 5
        self.volume_threshold = 1.0
        self.enable_loss_filter = True
        self.loss = 0.97
        self.use_rsi_filter = False
        self.rsi_period = 6
        self.rsi_lookback_days = 1
        self.rsi_threshold = 98
        self.use_fixed_stop_loss = True
        self.fixedStopLossThreshold = 0.95
        self.use_pct_stop_loss = False
        self.pct_stop_loss_threshold = 0.95
        self.use_atr_stop_loss = False
        self.atr_period = 14
        self.atr_multiplier = 2
        self.atr_trailing_stop = True
        self.atr_exclude_defensive = True
        self.sell_cooldown_enabled = False
        self.sell_cooldown_days = 3
        self.cooldown_end_date = None

        # ATR追踪状态
        self.position_highs = {}
        self.position_stop_prices = {}
        self.target_etfs_list = []

    # 重写 order_target_value_ 以支持ETF最小交易额和强制一手
    def order_target_value_(self, security, value):
        current_data = get_current_data()
        if current_data[security].paused:
            log.info(f"{security}: 今日停牌")
            return False
        if current_data[security].last_price == current_data[security].high_limit:
            log.info(f"{security}: 当前涨停")
            return False
        if current_data[security].last_price == current_data[security].low_limit:
            log.info(f"{security}: 当前跌停")
            return False

        price = current_data[security].last_price
        if price == 0:
            return False

        # 计算目标数量（100股整数倍）
        target_position = int(value / price) // 100 * 100
        # 如果目标金额>0但不足一手，强制买一手
        if value > 0 and target_position == 0:
            target_position = 100
            # 检查强制一手后是否达到最小交易额
            if target_position * price < self.min_money:
                log.info(f"{security}: 强制一手后交易金额{target_position*price:.2f}仍小于最小交易额{self.min_money}，跳过")
                return False

        current_position = g.positions[self.index].get(security, 0)
        adjustment = target_position - current_position

        # T+1检查
        closeable_amount = self.context.portfolio.positions[security].closeable_amount if security in self.context.portfolio.positions else 0
        if adjustment < 0 and closeable_amount == 0:
            log.info(f"{security}: 当天买入不可卖出")
            return False

        # 买入金额小于最小交易额检查
        if adjustment > 0:
            trade_value = adjustment * price
            if trade_value < self.min_money:
                log.info(f"{security}: 买入金额{trade_value:.2f}小于最小交易额{self.min_money}，跳过")
                return False

        if adjustment != 0:
            o = order(security, adjustment)
            if o:
                # 更新持仓记录
                amount = o.amount if o.is_buy else -o.amount
                g.positions[self.index][security] = amount + current_position
                if target_position == 0:
                    g.positions[self.index].pop(security, None)
                self.hold_list = list(g.positions[self.index].keys())
                # 更新ATR最高价（买入时）
                if adjustment > 0 and security in self.fixed_etf_pool:
                    self.position_highs[security] = price
                return True
        return False

    # 动态ETF池更新
    def update_dynamic_pool(self):
        all_etfs = get_all_securities(['etf']).index.tolist()
        exclude_keywords = ['300', '500', '1000', '50', '上证', '创业板', '科创', '恒生', 'H股', '货币', '纳指', '标普', '债']
        sector_etfs = []
        for code in all_etfs:
            name = get_security_info(code).display_name
            is_sector_etf = True
            for k in exclude_keywords:
                if k in name:
                    is_sector_etf = False
                    break
            if is_sector_etf:
                sector_etfs.append(code)

        if not sector_etfs:
            print("【警告】未能获取到基础 ETF 池！")
            return

        end_date = self.context.previous_date
        try:
            h = get_price(sector_etfs, count=1, end_date=end_date, frequency='daily', fields=['money'])
            yesterday_money = h['money'].iloc[0]
            qualified_etfs = yesterday_money[yesterday_money > 50000000].index.tolist()
            sorted_codes = yesterday_money[qualified_etfs].sort_values(ascending=False).index.tolist()
        except Exception as e:
            print(f"【严重错误】计算成交额时发生异常: {e}")
            return

        final_dynamic_pool = []
        seen_industries = set()
        for code in sorted_codes:
            name = get_security_info(code).display_name
            industry_key = name[:2]
            if industry_key not in seen_industries:
                final_dynamic_pool.append(code)
                seen_industries.add(industry_key)
            if len(final_dynamic_pool) >= 100:
                break

        self.dynamic_etf_pool = final_dynamic_pool
        etf_name_code_list = [f"{get_security_info(c).display_name}({c})" for c in self.dynamic_etf_pool]
        log.info(f"【动态更新完成】热点资金涌入行业池(前{len(self.dynamic_etf_pool)}只): {etf_name_code_list}")

    # 计算单只ETF指标
    def calculate_metrics(self, etf):
        try:
            etf_name = get_security_info(etf).display_name
            lookback = max(
                self.lookback_days,
                self.short_lookback_days,
                self.rsi_period + self.rsi_lookback_days,
                self.ma_filter_days,
                self.volume_lookback
            ) + 20
            prices = attribute_history(etf, lookback, '1d', ['close', 'high', 'low'])
            current_data = get_current_data()
            if len(prices) < max(self.lookback_days, self.ma_filter_days):
                return None
            current_price = current_data[etf].last_price
            price_series = np.append(prices["close"].values, current_price)

            # 动量得分
            recent_price_series = price_series[-(self.lookback_days + 1):]
            y = np.log(recent_price_series)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot else 0
            momentum_score = annualized_returns * r_squared

            # 短期动量
            if len(price_series) >= self.short_lookback_days + 1:
                short_return = price_series[-1] / price_series[-(self.short_lookback_days + 1)] - 1
                short_annualized = (1 + short_return) ** (250 / self.short_lookback_days) - 1
            else:
                short_annualized = -np.inf

            # 均线
            ma_price = np.mean(price_series[-self.ma_filter_days:])
            current_above_ma = current_price >= ma_price

            # 成交量比值
            volume_ratio = self.get_volume_ratio(etf)

            # 短期风控（近3日最低比值）
            day_ratios = []
            passed_loss_filter = True
            if len(price_series) >= 4:
                day1 = price_series[-1] / price_series[-2]
                day2 = price_series[-2] / price_series[-3]
                day3 = price_series[-3] / price_series[-4]
                day_ratios = [day1, day2, day3]
                if min(day_ratios) < self.loss:
                    passed_loss_filter = False

            # RSI
            current_rsi = 0
            max_recent_rsi = 0
            passed_rsi_filter = True
            if self.use_rsi_filter and len(price_series) >= self.rsi_period + self.rsi_lookback_days:
                rsi_values = self.calculate_rsi(price_series, self.rsi_period)
                if len(rsi_values) >= self.rsi_lookback_days:
                    recent_rsi = rsi_values[-self.rsi_lookback_days:]
                    max_recent_rsi = np.max(recent_rsi)
                    current_rsi = recent_rsi[-1]
                    if np.any(recent_rsi > self.rsi_threshold):
                        ma5 = np.mean(price_series[-5:]) if len(price_series) >= 5 else current_price
                        if current_price < ma5:
                            passed_rsi_filter = False

            return {
                'etf': etf,
                'etf_name': etf_name,
                'momentum_score': momentum_score,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'short_annualized': short_annualized,
                'current_price': current_price,
                'ma_price': ma_price,
                'volume_ratio': volume_ratio,
                'day_ratios': day_ratios,
                'current_rsi': current_rsi,
                'max_recent_rsi': max_recent_rsi,
                'passed_momentum': self.min_score_threshold <= momentum_score <= self.max_score_threshold,
                'passed_short_mom': short_annualized >= self.short_momentum_threshold,
                'passed_r2': r_squared > self.r2_threshold,
                'passed_annual_ret': annualized_returns >= self.min_annualized_return,
                'passed_ma': current_above_ma,
                'passed_volume': volume_ratio is not None and volume_ratio < self.volume_threshold,
                'passed_loss': passed_loss_filter,
                'passed_rsi': passed_rsi_filter,
            }
        except Exception as e:
            log.warning(f"计算 {etf} 指标出错: {e}")
            return None

    # 成交量比值计算
    def get_volume_ratio(self, security):
        try:
            hist_data = attribute_history(security, self.volume_lookback, '1d', ['volume'])
            if hist_data.empty or len(hist_data) < self.volume_lookback:
                return None
            past_vol = hist_data['volume']
            if past_vol.isnull().any() or past_vol.eq(0).any():
                return None
            avg_volume = past_vol.mean()
            if avg_volume == 0:
                return None
            today = self.context.current_dt.date()
            df_vol = get_price(security, start_date=today, end_date=self.context.current_dt, frequency='1m', fields=['volume'])
            current_volume = df_vol['volume'].sum()
            return current_volume / avg_volume
        except:
            return None

    # RSI计算
    def calculate_rsi(self, prices, period=6):
        if len(prices) < period + 1:
            return []
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gains = np.zeros_like(prices)
        avg_losses = np.zeros_like(prices)
        avg_gains[period] = np.mean(gains[:period])
        avg_losses[period] = np.mean(losses[:period])
        rsi_values = np.zeros(len(prices))
        rsi_values[:period] = 50
        for i in range(period + 1, len(prices)):
            avg_gains[i] = (avg_gains[i-1] * (period - 1) + gains[i-1]) / period
            avg_losses[i] = (avg_losses[i-1] * (period - 1) + losses[i-1]) / period
            if avg_losses[i] == 0:
                rsi_values[i] = 100
            else:
                rs = avg_gains[i] / avg_losses[i]
                rsi_values[i] = 100 - (100 / (1 + rs))
        return rsi_values[period:]

    # ATR计算
    def calculate_atr(self, security, period=14):
        try:
            needed_days = period + 20
            hist_data = attribute_history(security, needed_days, '1d', ['high', 'low', 'close'])
            if len(hist_data) < period + 1:
                return 0, [], False, "数据不足"
            high_prices = hist_data['high'].values
            low_prices = hist_data['low'].values
            close_prices = hist_data['close'].values
            tr_values = np.zeros(len(high_prices))
            for i in range(1, len(high_prices)):
                tr1 = high_prices[i] - low_prices[i]
                tr2 = abs(high_prices[i] - close_prices[i-1])
                tr3 = abs(low_prices[i] - close_prices[i-1])
                tr_values[i] = max(tr1, tr2, tr3)
            atr_values = np.zeros(len(tr_values))
            for i in range(period, len(tr_values)):
                atr_values[i] = np.mean(tr_values[i-period+1:i+1])
            current_atr = atr_values[-1] if len(atr_values) > 0 else 0
            return current_atr, atr_values[period:], True, "成功"
        except Exception as e:
            return 0, [], False, str(e)

    # 应用过滤器
    def apply_filters(self, metrics_list):
        steps = [
            ('动量得分', lambda m: m['passed_momentum'], True),
            ('短期动量', lambda m: m['passed_short_mom'], self.use_short_momentum_filter),
            ('R²', lambda m: m['passed_r2'], self.enable_r2_filter),
            ('年化收益率', lambda m: m['passed_annual_ret'], self.enable_annualized_return_filter),
            ('均线', lambda m: m['passed_ma'], self.enable_ma_filter),
            ('成交量', lambda m: m['passed_volume'], self.enable_volume_check),
            ('短期风控', lambda m: m['passed_loss'], self.enable_loss_filter),
            ('RSI', lambda m: m['passed_rsi'], self.use_rsi_filter),
        ]
        filtered = metrics_list[:]
        for name, condition, is_enabled in steps:
            if is_enabled:
                filtered = [m for m in filtered if condition(m)]
        return filtered

    # 获取最终排名ETF列表（带日志）
    def get_final_ranked_etfs(self):
        all_metrics = []
        etf_set = set(self.fixed_etf_pool + self.dynamic_etf_pool)
        for etf in etf_set:
            current_data = get_current_data()
            if current_data[etf].paused:
                continue
            metrics = self.calculate_metrics(etf)
            if metrics:
                all_metrics.append(metrics)

        # 处理NaN得分
        for item in all_metrics:
            score = item.get('momentum_score')
            if pd.isna(score) or np.isnan(score):
                item['momentum_score'] = float('-inf')

        all_metrics.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)

        # 日志输出第一步（可选，保留部分关键信息）
        log.info(f"【五福ETF】候选ETF数量: {len(all_metrics)}")

        final_list = self.apply_filters(all_metrics)
        for item in final_list:
            score = item.get('momentum_score')
            if pd.isna(score) or np.isnan(score):
                item['momentum_score'] = float('-inf')
        final_list.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)

        top_10 = final_list[:10]
        if top_10:
            log.info(f"【五福ETF】过滤后前10名: {[(m['etf'], m['momentum_score']) for m in top_10]}")
        else:
            log.info("【五福ETF】无符合条件的ETF")
        return final_list

    # 检查是否在冷却期
    def is_in_cooldown(self):
        if not self.sell_cooldown_enabled or self.cooldown_end_date is None:
            return False
        return self.context.current_dt.date() <= self.cooldown_end_date

    # 设置冷却期
    def set_cooldown(self):
        if self.sell_cooldown_enabled:
            self.cooldown_end_date = self.context.current_dt.date() + timedelta(days=self.sell_cooldown_days)
            log.info(f"【五福ETF】触发冷却期，结束日期: {self.cooldown_end_date.strftime('%Y-%m-%d')}")

    # 进入避险模式（清仓所有本策略持仓，买入避险ETF）
    def enter_safe_haven(self, trigger_reason=""):
        if not self.sell_cooldown_enabled:
            return
        # 清仓所有本策略持仓
        for security in list(g.positions[self.index].keys()):
            if security in self.fixed_etf_pool or security == self.defensive_etf:
                if g.positions[self.index].get(security, 0) > 0:
                    self.order_target_value_(security, 0)
                    self.position_highs.pop(security, None)
                    self.position_stop_prices.pop(security, None)
        # 买入避险ETF
        total_value = self.context.portfolio.total_value * g.portfolio_value_proportion[self.index]
        if total_value > self.min_money:
            success = self.order_target_value_(self.safe_haven_etf, total_value * 0.99)
            if success:
                log.info(f"【五福ETF】买入避险ETF: {self.safe_haven_etf}，金额: {total_value*0.99:.2f}")
            else:
                log.info(f"【五福ETF】买入避险ETF失败")
        else:
            log.info(f"【五福ETF】资金不足，无法买入避险ETF")
        self.set_cooldown()
        log.info(f"【五福ETF】已进入冷却期，由 [{trigger_reason}] 触发")

    # 冷却期结束，卖出避险ETF
    def exit_safe_haven_if_cooldown_ends(self):
        if not self.sell_cooldown_enabled or self.cooldown_end_date is None:
            return
        current_date = self.context.current_dt.date()
        if current_date > self.cooldown_end_date:
            log.info(f"【五福ETF】冷却期结束，当前日期: {current_date.strftime('%Y-%m-%d')}")
            if self.safe_haven_etf in g.positions[self.index]:
                if g.positions[self.index].get(self.safe_haven_etf, 0) > 0:
                    self.order_target_value_(self.safe_haven_etf, 0)
                    self.position_highs.pop(self.safe_haven_etf, None)
                    self.position_stop_prices.pop(self.safe_haven_etf, None)
            self.cooldown_end_date = None
            log.info("【五福ETF】策略恢复正常运行")

    # 止损检查（每日调用）
    def stop_loss(self):
        if self.is_in_cooldown():
            return
        current_data = get_current_data()
        # 遍历本策略持仓
        for security in list(g.positions[self.index].keys()):
            if security not in self.fixed_etf_pool and security != self.defensive_etf:
                continue  # 只处理ETF池内的
            position = self.context.portfolio.positions.get(security)
            if not position or position.total_amount == 0:
                continue
            current_price = current_data[security].last_price
            cost_price = position.avg_cost
            triggered = False
            reason = ""

            # 固定比例止损
            if self.use_fixed_stop_loss and current_price <= cost_price * self.fixedStopLossThreshold:
                triggered = True
                reason = "固定比例止损"
            # 当日跌幅止损
            if not triggered and self.use_pct_stop_loss:
                today_open = current_data[security].day_open
                if today_open and today_open > 0:
                    if current_price <= today_open * self.pct_stop_loss_threshold:
                        triggered = True
                        reason = "当日跌幅止损"
            # ATR止损
            if not triggered and self.use_atr_stop_loss:
                if self.atr_exclude_defensive and security == self.defensive_etf:
                    pass
                else:
                    current_atr, _, success, _ = self.calculate_atr(security, self.atr_period)
                    if success and current_atr > 0:
                        if security not in self.position_highs:
                            self.position_highs[security] = current_price
                        else:
                            self.position_highs[security] = max(self.position_highs[security], current_price)
                        if self.atr_trailing_stop:
                            stop_price = self.position_highs[security] - self.atr_multiplier * current_atr
                        else:
                            stop_price = cost_price - self.atr_multiplier * current_atr
                        self.position_stop_prices[security] = stop_price
                        if current_price <= stop_price:
                            triggered = True
                            reason = "ATR动态止损"

            if triggered:
                security_name = get_security_info(security).display_name
                log.info(f"【五福ETF】{reason}触发: {security} {security_name}，当前价{current_price:.3f}，成本{cost_price:.3f}")
                self.order_target_value_(security, 0)
                self.position_highs.pop(security, None)
                self.position_stop_prices.pop(security, None)
                self.enter_safe_haven(trigger_reason=reason)
                break  # 一次只处理一个止损，避免重复进入冷却期

    # 调仓主逻辑
    def adjust(self):
        # 处理冷却期结束
        self.exit_safe_haven_if_cooldown_ends()

        if self.is_in_cooldown():
            log.info("【五福ETF】当前处于冷却期，跳过正常调仓")
            return

        # 获取最终排名列表
        ranked = self.get_final_ranked_etfs()
        target_etfs = []
        if ranked:
            for metrics in ranked[:self.holdings_num]:
                target_etfs.append(metrics['etf'])
                log.info(f"【五福ETF】确定目标: {metrics['etf']} {metrics['etf_name']}，得分: {metrics['momentum_score']:.4f}")
        else:
            # 无目标时，检查防御ETF是否可用
            if self.check_defensive_available():
                target_etfs = [self.defensive_etf]
                log.info(f"【五福ETF】防御模式: {self.defensive_etf}")
            else:
                log.info("【五福ETF】无目标且防御ETF不可用，空仓")
                target_etfs = []

        self.target_etfs_list = target_etfs

        # 构建目标市值字典
        if not target_etfs:
            # 清仓所有本策略持仓
            for security in list(g.positions[self.index].keys()):
                self.order_target_value_(security, 0)
            return

        total_value = self.context.portfolio.total_value * g.portfolio_value_proportion[self.index]
        target_value_per = total_value / len(target_etfs)
        targets = {etf: target_value_per for etf in target_etfs}

        # 使用基类的_adjust2进行调仓（先卖后买）
        self._adjust2(targets)

    # 检查防御ETF是否可用
    def check_defensive_available(self):
        current_data = get_current_data()
        etf = self.defensive_etf
        if current_data[etf].paused:
            return False
        if current_data[etf].last_price >= current_data[etf].high_limit:
            return False
        if current_data[etf].last_price <= current_data[etf].low_limit:
            return False
        return True