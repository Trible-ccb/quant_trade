import bullet_trade_remote_helper as bt

# ===== 配置区域 =====
BT_REMOTE_HOST = 'x.x.x.x'  #远程qmt服务器
BT_REMOTE_PORT = 58620              #远程qmt服务器端口
BT_REMOTE_TOKEN = ''  #服务器token秘钥
ACCOUNT_KEY = None  # 可选
SUB_ACCOUNT = None  # 可选

# 连接配置和远程服务器
def _ensure_configured():
    if not BT_REMOTE_TOKEN:
        raise RuntimeError("请先在 BT_REMOTE_HOST/BT_REMOTE_PORT/BT_REMOTE_TOKEN/ACCOUNT_KEY/SUB_ACCOUNT 填写远程服务器配置")
    bt.configure(
        host=BT_REMOTE_HOST,
        port=BT_REMOTE_PORT,
        token=BT_REMOTE_TOKEN,
        account_key=ACCOUNT_KEY,
        sub_account_id=SUB_ACCOUNT,
    )
    # 让券商端可用数据补价
    bt.get_broker_client().bind_data_client(bt.get_data_client())
_ensure_configured()

# 获取实盘资金账户的账户信息和持仓信息
def get_account_positions():
    try:
        acct = bt.get_account()
        positions = bt.get_positions()
        print(
            f"[账号] 现金={acct.available_cash:.2f} 总资产={acct.total_value:.2f} 持仓数量={len(positions)}"
        )
        for pos in positions:
            print(f"[持仓] {pos.security} 数量={pos.amount} 可用={pos.available} 冻结={pos.frozen} 成本={pos.avg_cost:.4f} 市值={pos.market_value:.2f}")
    except Exception as exc:
        print(f"获取账户/持仓失败: {exc}")

# 测试按市值下单
def test_order_value():
    """
    测试按市值下单：买入 1000 元市值的股票。
    服务端会自动按 100 股取整，实际市值可能与请求略有偏差。
    """
    symbol = "000001.XSHE"
    try:
        last = bt.get_data_client().get_last_price(symbol)
        if not last:
            print(f"[按市值下单] 无法获取 {symbol} 价格，跳过")
            return
        
        target_value = 1000.0  # 目标市值 1 千元
        estimated_qty = int(target_value / last)
        print(f"[按市值下单] {symbol} 当前价={last:.4f}，目标市值={target_value:.2f}，预计数量={estimated_qty}")
        
        # 使用市价单（price=None），服务端会自动计算价格笼子
        oid = bt.order_value(symbol, target_value, price=None, wait_timeout=10)
        print(f"[按市值下单] 下单成功，order_id={oid}")
        
        # 查询订单状态
        if oid:
            status = bt.get_order_status(oid)
            print(f"[订单状态] {status}")
    except Exception as exc:
        print(f"[按市值下单] 异常: {exc}")

# 取消注释以执行测试
test_order_value()

# 测试调仓到目标数量
def test_order_target():
    """
    测试调仓到目标数量：将持仓调整到 200 股。
    如果当前持仓不足 200，则买入；如果超过 200，则卖出。
    """
    symbol = "000001.XSHE"
    try:
        positions = bt.get_positions()
        current = 0
        for pos in positions:
            if pos.security == symbol:
                current = pos.amount
                break
        
        target = 200  # 目标持仓 200 股（建议为 100 的整数倍）
        delta = target - current
        print(f"[调仓] {symbol} 当前持仓={current}，目标={target}，需要{'买入' if delta > 0 else '卖出' if delta < 0 else '不变'} {abs(delta)} 股")
        
        if delta == 0:
            print(f"[调仓] 当前持仓已等于目标，无需交易")
            return
        
        # 使用市价单
        oid = bt.order_target(symbol, target, price=None, wait_timeout=10)
        print(f"[调仓] 下单成功，order_id={oid}")
        
        # 查询订单状态
        if oid:
            status = bt.get_order_status(oid)
            print(f"[订单状态] {status}")
    except Exception as exc:
        print(f"[调仓] 异常: {exc}")

# 取消注释以执行测试
test_order_target()

# 测试调仓到目标市值
def test_order_target_value():
    """
    测试调仓到目标市值：将持仓市值调整到 1000 元。
    服务端会自动按 100 股取整，实际市值可能与目标略有偏差。
    """
    symbol = "000001.XSHE"
    try:
        last = bt.get_data_client().get_last_price(symbol)
        if not last:
            print(f"[调仓市值] 无法获取 {symbol} 价格，跳过")
            return
        
        positions = bt.get_positions()
        current_amount = 0
        for pos in positions:
            if pos.security == symbol:
                current_amount = pos.amount
                break
        
        current_value = current_amount * last
        target_value = 1000.0  # 目标市值 1 千元
        delta_value = target_value - current_value
        estimated_delta_qty = int(abs(delta_value) / last)
        
        print(f"[调仓市值] {symbol} 当前持仓={current_amount} 股，当前市值={current_value:.2f}")
        print(f"[调仓市值] 目标市值={target_value:.2f}，需要{'买入' if delta_value > 0 else '卖出' if delta_value < 0 else '不变'} 约 {estimated_delta_qty} 股")
        
        if abs(delta_value) < 100:  # 市值差异小于 100 元，不交易
            print(f"[调仓市值] 市值差异过小，跳过交易")
            return
        
        # 使用市价单
        oid = bt.order_target_value(symbol, target_value, price=None, wait_timeout=10)
        print(f"[调仓市值] 下单成功，order_id={oid}")
        
        # 查询订单状态
        if oid:
            status = bt.get_order_status(oid)
            print(f"[订单状态] {status}")
    except Exception as exc:
        print(f"[调仓市值] 异常: {exc}")

# 取消注释以执行测试
test_order_target_value()


# 测试限价单下单和撤单
def place_limit_buy_and_cancel():
    """
    下单示例：以当前价打 99 折挂单买入 100 手，wait_timeout=10s 同步等待，然后尝试撤单。
    """
    symbol = "000001.XSHE"
    try:
        last = bt.get_data_client().get_last_price(symbol)
        if not last:
            print(f"[限价单] 无法获取 {symbol} 价格，跳过")
            return
        limit_price = round(last * 0.99, 2)
        print(f"[限价单] {symbol} 99折买入尝试，限价={limit_price}")
        oid = bt.order(symbol, 100, price=limit_price, wait_timeout=10)
        print(f"[限价单] 下单返回 order_id={oid}，准备撤单")
        if oid:
            try:
                bt.cancel_order(oid)
                print(f"[撤单] 已提交撤单 order_id={oid}")
            except Exception as exc:
                print(f"[撤单] 撤单失败 order_id={oid}, err={exc}")
    except Exception as exc:
        print(f"[限价单] 下单流程异常: {exc}")
        
place_limit_buy_and_cancel()

# 测试市价单下单
def test_market_order():
    """
    测试市价单：买入 200 股，不指定价格（price=None）。
    服务端会自动计算价格笼子保护价。
    """
    symbol = "000001.XSHE"
    try:
        last = bt.get_data_client().get_last_price(symbol)
        if not last:
            print(f"[市价单] 无法获取 {symbol} 价格，跳过")
            return
        
        print(f"[市价单] {symbol} 当前价={last:.4f}，准备买入 200 股（市价单）")
        
        # price=None 表示市价单，服务端会自动计算价格笼子
        oid = bt.order(symbol, 200, price=None, side='BUY', wait_timeout=10)
        print(f"[市价单] 下单成功，order_id={oid}")
        
        # 查询订单状态，查看服务端计算的实际价格
        if oid:
            status = bt.get_order_status(oid)
            print(f"[订单状态] {status}")
            
            # 如果订单对象有 actual_price，显示服务端计算的价格
            broker_client = bt.get_broker_client()
            # 注意：这里需要从返回的响应中获取，实际使用中可以通过订单状态查看
    except Exception as exc:
        print(f"[市价单] 异常: {exc}")

# 取消注释以执行测试
test_market_order()

# 测试服务端统一处理功能
def test_server_validation():
    """
    测试服务端统一处理功能：
    1. 100 股取整：下单 153 股，服务端应自动调整为 100 股
    2. 停牌检查：尝试对停牌股票下单，应被拒绝
    3. 价格校验：限价单价格超出涨跌停范围，应被调整
    """
    symbol = "000001.XSHE"
    
    print("=" * 60)
    print("测试 1: 100 股取整")
    print("=" * 60)
    try:
        # 下单 153 股，服务端应自动取整为 100 股
        oid = bt.order(symbol, 153, price=None, side='BUY', wait_timeout=5)
        if oid:
            status = bt.get_order_status(oid)
            print(f"[取整测试] 下单 153 股，订单状态: {status}")
            # 服务端返回的 amount 应该是 100
            if status.get("amount") == 100:
                print(f"[取整测试] ✅ 服务端已正确取整为 100 股")
            else:
                print(f"[取整测试] ⚠️ 服务端返回数量: {status.get('amount')}")
    except Exception as exc:
        print(f"[取整测试] 异常: {exc}")
    
    print("\n" + "=" * 60)
    print("测试 2: 限价单价格校验（超出涨跌停）")
    print("=" * 60)
    try:
        last = bt.get_data_client().get_last_price(symbol)
        if last:
            # 尝试用涨停价的 1.1 倍下单，服务端应自动调整为涨停价
            invalid_price = last * 1.5  # 明显超出涨停价
            print(f"[价格校验] 当前价={last:.4f}，尝试用 {invalid_price:.4f} 限价买入")
            oid = bt.order(symbol, 100, price=invalid_price, side='BUY', wait_timeout=5)
            if oid:
                status = bt.get_order_status(oid)
                print(f"[价格校验] 订单状态: {status}")
                print(f"[价格校验] 服务端应已自动调整价格到合理范围")
    except Exception as exc:
        print(f"[价格校验] 异常: {exc}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

# 取消注释以执行测试
test_server_validation()