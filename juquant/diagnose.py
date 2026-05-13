"""
诊断脚本：测试低位3连阳首板的量价过滤为什么返回0只股票
"""
from jqdatasdk import *
import pandas as pd
import numpy as np
from config_local import JQ_USER, JQ_PASS
from datetime import datetime

auth(JQ_USER, JQ_PASS)

# 模拟2019-01-02的选股，上一交易日为2018-12-28
date = "2018-12-28"

# 获取全市场股票
all_stocks = get_all_securities('stock', date).index.tolist()
print(f'全市场: {len(all_stocks)} 只')

# 简单基础过滤（模仿策略的filter_basic, 但用dated数据）
# 过滤ST
stock_info = get_security_info(list(all_stocks))
stock_names = {}
for s in all_stocks[:100]:  # 只测试前100只
    try:
        info = get_security_info(s)
        stock_names[s] = info.display_name
    except:
        pass

# 测试get_price的各种参数组合
print("\n=== 测试 high_limit 数据 ===")
test_stocks = all_stocks[:5]
print(f"测试前5只股票: {test_stocks}")

for s in test_stocks:
    try:
        df = get_price(s, end_date=date, frequency='daily', 
                       fields=['open', 'close', 'high', 'low', 'volume', 'money', 'high_limit', 'low_limit'],
                       count=4, panel=False, fill_paused=False)
        print(f"\n{s} ({get_security_info(s).display_name}):")
        print(df[['time', 'open', 'close', 'high_limit', 'volume', 'money']])
    except Exception as e:
        print(f"{s} error: {e}")

print("\n=== 测试 high_limit 比较 ===")
# 检查close == high_limit的准确度
for s in test_stocks:
    try:
        df = get_price(s, end_date=date, frequency='daily',
                       fields=['close', 'high_limit'],
                       count=1, panel=False, fill_paused=False)
        close = df.iloc[0]['close']
        hl = df.iloc[0]['high_limit']
        print(f"{s}: close={close}, high_limit={hl}, equal={close == hl}, diff={abs(close-hl):.6f}")
    except Exception as e:
        print(f"{s} error: {e}")

print("\n=== 测试 skip_paused 的影响 ===")
test_large = all_stocks[:100]
try:
    df1 = get_price(test_large, end_date=date, frequency='daily',
                    fields=['open', 'close', 'high', 'low', 'volume', 'money', 'high_limit'],
                    count=4, panel=False, fill_paused=False)
    print(f"fill_paused=False, skip_paused=False: {len(df1)} rows, codes: {df1['code'].nunique()}")
except Exception as e:
    print(f"Test 1 error: {e}")

try:
    df2 = get_price(test_large, end_date=date, frequency='daily',
                    fields=['open', 'close', 'high', 'low', 'volume', 'money', 'high_limit'],
                    count=4, panel=False, fill_paused=False, skip_paused=True)
    print(f"fill_paused=False, skip_paused=True: {len(df2)} rows, codes: {df2['code'].nunique()}")
except Exception as e:
    print(f"Test 2 error: {e}")

print("\n=== 测试 2018-12-28 涨停股票 ===")
try:
    df = get_price(all_stocks, end_date=date, frequency='daily',
                   fields=['close', 'high_limit'],
                   count=1, panel=False, fill_paused=False)
    df_limit = df[df['close'] == df['high_limit']]
    limit_stocks = list(df_limit['code'].unique())
    print(f"涨停股票数量: {len(limit_stocks)}")
    for s in limit_stocks[:20]:
        name = get_security_info(s).display_name
        print(f"  {s} ({name})")
except Exception as e:
    print(f"Error: {e}")

print("\n=== 测试 money 字段 ===")
try:
    df_money = get_price(test_stocks[:3], end_date=date, frequency='daily',
                         fields=['money'],
                         count=1, panel=False, fill_paused=False)
    print(f"money data: {df_money}")
except Exception as e:
    print(f"money error: {e}")

print("\n=== 完整模拟量价过滤（前100只） ===")
test_stocks_100 = all_stocks[:100]
try:
    df = get_price(test_stocks_100, end_date=date, frequency='daily',
                   fields=['open', 'close', 'high', 'low', 'volume', 'money', 'high_limit'],
                   count=4, panel=False, fill_paused=False)
    
    df.index = df.code
    candidates = []
    for stock in test_stocks_100:
        try:
            if stock not in df.index:
                continue
            sub = df.loc[stock]
            valid_data = sub.dropna(subset=['close', 'open', 'high', 'low', 'volume'])
            if len(valid_data) < 3:
                continue
            
            recent = valid_data.iloc[-3:]
            
            # 条件a: 3连阳
            for _, row in recent.iterrows():
                if row['close'] <= row['open']:
                    raise ValueError('非阳线')
            
            # 条件a补充: 昨日涨停
            yesterday_row = recent.iloc[-1]
            if yesterday_row['close'] != yesterday_row['high_limit']:
                raise ValueError(f'昨日未涨停: close={yesterday_row["close"]}, high_limit={yesterday_row["high_limit"]}')
            
            # 条件c: 前两日涨幅 < 5%
            gain_t2 = (recent.iloc[-2]['close'] - recent.iloc[-2]['open']) / recent.iloc[-2]['open']
            gain_t3 = (recent.iloc[-3]['close'] - recent.iloc[-3]['open']) / recent.iloc[-3]['open']
            
            if abs(gain_t2) >= 0.05 or abs(gain_t3) >= 0.05:
                raise ValueError(f'涨幅超5%: T-2={gain_t2:.2%}, T-3={gain_t3:.2%}')
            
            # 条件b: 放量2倍
            vol_y = recent.iloc[-1]['volume']
            vol_t2 = recent.iloc[-2]['volume']
            if vol_t2 > 0 and vol_y / vol_t2 < 2.0:
                raise ValueError(f'放量不足: {vol_y/vol_t2:.2f}倍')
            
            # 条件e: 成交额5-30亿
            money = recent.iloc[-1]['money']
            if money < 5e8 or money > 30e8:
                raise ValueError(f'成交额不符: {money/1e8:.2f}亿')
            
            candidates.append(stock)
            
        except ValueError as e:
            continue
        except Exception as e:
            continue
    
    print(f"量价过滤后: {len(candidates)} 只")
    for s in candidates:
        name = get_security_info(s).display_name
        print(f"  {s} ({name})")
    
    if not candidates:
        print("\n=== 诊断: 检查过滤条件逐一通过情况 ===")
        for stock in test_stocks_100[:20]:
            try:
                if stock not in df.index:
                    print(f"{stock}: 不在df中")
                    continue
                sub = df.loc[stock]
                valid_data = sub.dropna(subset=['close', 'open', 'high', 'low', 'volume'])
                if len(valid_data) < 3:
                    print(f"{stock}: 有效数据<3, 共{len(valid_data)}")
                    continue
                recent = valid_data.iloc[-3:]
                
                # 逐一检查条件
                # 条件a: 3连阳
                is_yang = all(row['close'] > row['open'] for _, row in recent.iterrows())
                is_limit = recent.iloc[-1]['close'] == recent.iloc[-1]['high_limit']
                
                if not is_yang:
                    print(f"{stock}: FAIL 3连阳")
                    continue
                    
                gain_t2 = (recent.iloc[-2]['close'] - recent.iloc[-2]['open']) / recent.iloc[-2]['open']
                gain_t3 = (recent.iloc[-3]['close'] - recent.iloc[-3]['open']) / recent.iloc[-3]['open']
                
                vol_ratio = recent.iloc[-1]['volume'] / recent.iloc[-2]['volume'] if recent.iloc[-2]['volume'] > 0 else 0
                money = recent.iloc[-1]['money']
                
                print(f"{stock}: yang_lines={is_yang}, limit_up={is_limit}, "
                      f"gain_t2={gain_t2:.2%}, gain_t3={gain_t3:.2%}, "
                      f"vol_ratio={vol_ratio:.2f}, money={money/1e8:.2f}亿")
                if not is_limit:
                    print(f"  -> close={recent.iloc[-1]['close']}, high_limit={recent.iloc[-1]['high_limit']}")
                    
            except Exception as e:
                print(f"{stock}: 异常 {e}")

except Exception as e:
    import traceback
    print(f"Critical error: {e}")
    traceback.print_exc()

print("\n可用查询次数:", get_query_count())
