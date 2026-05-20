#!/usr/bin/env python3
"""
涨停预测完整流程脚本
流程：扫描涨速 → 4维度评分 → 排序 → 飞书推送

用法:
  python scripts/zt_pipeline.py                  # 完整流程(需要Chrome CDP)
  python scripts/zt_pipeline.py --from-file=data/signals/xxx.json  # 从已有文件读取
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import argparse
import requests

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# 从.env加载配置
def load_env():
    env_file = PROJECT_DIR / ".env"
    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key] = value
    return config

CONFIG = load_env()

# ===== Agent 权重配置（从.env读取，默认=1） =====
AGENT_WEIGHTS = {
    "fundamental": float(CONFIG.get("AGENT_WEIGHT_FUNDAMENTAL", "1")),
    "technical": float(CONFIG.get("AGENT_WEIGHT_TECHNICAL", "1")),
    "fundflow": float(CONFIG.get("AGENT_WEIGHT_FUND_FLOW", "1")),
    "sentiment": float(CONFIG.get("AGENT_WEIGHT_SENTIMENT", "1"))
}

# ===== Tushare API 缓存层 =====
# 同一只股票在同一次流水线执行中，相同api_name+params的调用只发一次请求
_TUSHARE_CACHE = {}

def call_tushare(api_name, token, params, fields="", timeout=10):
    """带缓存的Tushare API调用，避免同一股票重复请求同一接口"""
    cache_key = (api_name, json.dumps(params, sort_keys=True), fields)
    if cache_key in _TUSHARE_CACHE:
        return _TUSHARE_CACHE[cache_key]
    try:
        payload = {
            "api_name": api_name,
            "token": token,
            "params": params,
        }
        if fields:
            payload["fields"] = fields
        resp = requests.post("https://api.tushare.pro", json=payload, timeout=timeout)
        result = resp.json()
        _TUSHARE_CACHE[cache_key] = result
        return result
    except Exception:
        _TUSHARE_CACHE[cache_key] = {}  # 缓存失败结果，避免重试
        return {}

def clear_tushare_cache():
    """清空Tushare缓存（流水线开始时调用）"""
    global _TUSHARE_CACHE
    _TUSHARE_CACHE = {}

# ===== 全局工具函数 =====
def safe_float(val):
    """安全转换为float，失败返回0.0"""
    if val is None:
        return 0.0
    try:
        return float(val)
    except:
        return 0.0

def safe_float_none(val):
    """安全转换为float，失败返回None（用于需要区分None和0的场景）"""
    if val is None:
        return None
    try:
        return float(val)
    except:
        return None

def safe_int_none(val):
    """安全转换为int，失败返回None"""
    if val is None:
        return None
    try:
        return int(val)
    except:
        return None

def is_trading_time():
    """判断当前是否在A股交易时间(9:30~15:00，工作日)"""
    from datetime import datetime
    now = datetime.now()
    # 周末不算交易日
    if now.weekday() >= 5:
        return False
    # 9:30~15:00
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 15:
        return False
    return True

def list_to_dict(items, fields):
    """将Tushare返回的list格式转为dict格式"""
    if not items or not fields:
        return []
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, (list, tuple)):
            d = {}
            for i, f in enumerate(fields):
                if i < len(item):
                    d[f] = item[i]
            result.append(d)
    return result

# ===== 1. 扫描涨速数据 =====
def scan_surge():
    """调用scan_cdp.py获取涨速数据"""
    scan_script = PROJECT_DIR / "scripts" / "scan_cdp.py"
    result = subprocess.run(
        [sys.executable, str(scan_script)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_DIR)
    )
    if result.returncode != 0:
        print(f"扫描失败: {result.stderr}")
        return None
    
    # scan_cdp.py 在非交易时段会exit(0)并输出提示，需检查stdout
    if "跳过扫描" in result.stdout:
        print(f"扫描跳过: 非交易时段或周末休市")
        return None
    
    # 找到最新的信号文件
    signals_dir = PROJECT_DIR / "data" / "signals"
    signal_files = sorted(signals_dir.glob("*.json"), reverse=True)
    if not signal_files:
        return None
    
    with open(signal_files[0]) as f:
        raw = json.load(f)
    
    # 兼容两种格式
    if isinstance(raw, dict) and "stocks" in raw:
        stocks = raw["stocks"]
    elif isinstance(raw, list):
        stocks = raw
    else:
        print(f"无法解析信号文件格式")
        return None
    
    # 统一转换为标准格式
    candidates = []
    for s in stocks:
        code = s.get("代码") or s.get("code") or s.get("ts_code", "")
        name = s.get("名称") or s.get("name", "")
        if "." not in code:
            if code.startswith("6"):
                code = f"{code}.SH"
            else:
                code = f"{code}.SZ"
        candidates.append({"code": code, "name": name})
    
    print(f"扫描完成: {len(candidates)} 只候选股")
    return candidates

def load_from_file(filepath):
    """从已有文件加载信号"""
    path = Path(filepath)
    if not path.is_absolute():
        path = PROJECT_DIR / filepath
    
    with open(path) as f:
        raw = json.load(f)
    
    # 兼容两种格式：直接list 或 dict包含stocks
    if isinstance(raw, dict) and "stocks" in raw:
        stocks = raw["stocks"]
    elif isinstance(raw, list):
        stocks = raw
    else:
        print(f"无法解析信号文件格式: {type(raw)}")
        return None
    
    # 统一转换为标准格式 {code, name}
    candidates = []
    for s in stocks:
        code = s.get("代码") or s.get("code") or s.get("ts_code", "")
        name = s.get("名称") or s.get("name", "")
        # 补全ts_code格式 (002971 -> 002971.SZ, 603615 -> 603615.SH)
        if "." not in code:
            if code.startswith("6"):
                code = f"{code}.SH"
            else:
                code = f"{code}.SZ"
        candidates.append({"code": code, "name": name})
    
    print(f"从文件加载: {len(candidates)} 只候选股")
    return candidates

# ===== 1.5 全系统过滤规则 (所有Agent共用) =====
def filter_candidates(candidates):
    """
    全系统7条过滤规则：满足任一条件直接排除，不进入分析
    1. ST/*ST/退市整理期
    2. 上市不满60日新股
    3. 创业板(30xxxx.SZ) / 科创板(688xxx.SH) / 北交所(8xxxxx.BJ)
    4. 当日停牌
    5. 自由流通市值 < 20亿
    6. 5日均换手率 < 2%
    7. 连续一字板（无法买入）
    """
    from datetime import datetime, timedelta
    
    token = CONFIG["TUSHARE_TOKEN"]
    today_str = datetime.now().strftime("%Y%m%d")
    filtered_in = []
    filter_log = []
    
    for stock in candidates:
        code = stock["code"]
        name = stock.get("name", "")
        vetoed = False
        veto_reason = ""
        
        # 规则3: 创业板/科创板/北交所 (纯代码判断，无需API)
        pure_code = code.split(".")[0]
        if pure_code.startswith("30") or pure_code.startswith("688") or pure_code.startswith("8") or pure_code.startswith("4"):
            # 30开头=创业板, 688开头=科创板, 8/4开头=北交所
            suffix = code.split(".")[-1] if "." in code else ""
            if pure_code.startswith("30"):
                vetoed = True
                veto_reason = f"规则3: 创业板({code})"
            elif pure_code.startswith("688"):
                vetoed = True
                veto_reason = f"规则3: 科创板({code})"
            elif pure_code.startswith("8") or pure_code.startswith("4"):
                # 8开头或4开头且后缀BJ(或无后缀)为北交所
                if suffix == "BJ" or suffix == "":
                    vetoed = True
                    veto_reason = f"规则3: 北交所({code})"
        
        if vetoed:
            filter_log.append(f"  [排除] {code} {name}: {veto_reason}")
            continue
        
        # 规则1/2/5/6/7/4 需要Tushare API数据，批量获取daily_basic
        try:
            resp_data = call_tushare(
                "daily_basic", token,
                {"ts_code": code, "trade_date": today_str},
                "ts_code,close,turnover_rate,turnover_rate_f,circ_mv,total_mv,pct_chg"
            )
            items = resp_data.get("data", {}).get("items", [])
            if not items:
                # 当日无数据(可能停牌或非交易日)，取最近一日
                resp_data = call_tushare(
                    "daily_basic", token,
                    {"ts_code": code},
                    "trade_date,ts_code,close,turnover_rate,turnover_rate_f,circ_mv,total_mv,pct_chg"
                )
                items = resp_data.get("data", {}).get("items", [])
            
            if not items:
                filter_log.append(f"  [排除] {code} {name}: 无行情数据")
                continue
            
            latest = items[0]
            field_map = resp_data.get("data", {}).get("fields", [])
            basic = dict(zip(field_map, latest))
            
            # 规则5: 自由流通市值 < 20亿 (circ_mv单位: 万元)
            circ_mv = safe_float(basic.get("circ_mv"))
            if circ_mv and circ_mv < 200000:  # 20亿=200000万
                vetoed = True
                veto_reason = f"规则5: 流通市值{circ_mv/10000:.1f}亿<20亿"
            
            # 规则6: 换手率 < 2% (取turnover_rate_f自由流通换手)
            turnover = safe_float(basic.get("turnover_rate_f")) or safe_float(basic.get("turnover_rate"))
            if not vetoed and turnover and turnover < 2:
                vetoed = True
                veto_reason = f"规则6: 换手率{turnover:.1f}%<2%"
            
            # 规则7: 连续一字板 (pct_chg接近10%或20%且换手极低)
            if not vetoed:
                pct_chg = safe_float(basic.get("pct_chg"))
                if pct_chg and turnover:
                    # 一字涨停: 涨幅>=9.9% 且 换手<0.5%
                    if pct_chg >= 9.9 and turnover < 0.5:
                        vetoed = True
                        veto_reason = f"规则7: 一字板(涨幅{pct_chg:.1f}%换手{turnover:.2f}%)"
                    # 一字跌停
                    elif pct_chg <= -9.9 and turnover < 0.5:
                        vetoed = True
                        veto_reason = f"规则7: 一字跌停(涨幅{pct_chg:.1f}%换手{turnover:.2f}%)"
            
        except Exception as e:
            filter_log.append(f"  [警告] {code} {name}: 数据获取失败({e}), 保留")
        
        if vetoed:
            filter_log.append(f"  [排除] {code} {name}: {veto_reason}")
            continue
        
        # 规则1: ST/*ST — 通过stock_basic查询
        try:
            resp = call_tushare("stock_basic", token, {"ts_code": code}, "ts_code,name,list_date")
            items = resp.get("data", {}).get("items", [])
            if items:
                stock_name = items[0][1] if len(items[0]) > 1 else name
                list_date = items[0][2] if len(items[0]) > 2 else None
                
                # 规则1: ST
                if stock_name and ("ST" in stock_name or "st" in stock_name.lower()):
                    vetoed = True
                    veto_reason = f"规则1: ST股({stock_name})"
                
                # 规则2: 上市不满60日
                if not vetoed and list_date:
                    try:
                        list_dt = datetime.strptime(str(list_date), "%Y%m%d")
                        days_since_list = (datetime.now() - list_dt).days
                        if days_since_list < 60:
                            vetoed = True
                            veto_reason = f"规则2: 上市{days_since_list}日<60日"
                    except:
                        pass
        except:
            pass
        
        if vetoed:
            filter_log.append(f"  [排除] {code} {name}: {veto_reason}")
            continue
        
        filtered_in.append(stock)
    
    print(f"\n[过滤] 输入{len(candidates)}只 → 保留{len(filtered_in)}只 → 排除{len(candidates)-len(filtered_in)}只")
    if filter_log:
        for log in filter_log:
            print(log)
    
    return filtered_in

# ===== 2. 基本面评分 (V1.0 五维度量化) =====
def score_fundamental(code):
    """
    基本面涨停潜力量化评分 V1.0
    五维度：业绩40% + 事件30% + 筹码15% + 财务10% + 估值5%
    含财务避雷一票否决机制
    """
    from datetime import datetime, timedelta
    
    token = CONFIG["TUSHARE_TOKEN"]
    
    # ===== 1. 数据获取 =====
    # 获取daily_basic (估值)
    try:
        resp = call_tushare("daily_basic", token, {"ts_code": code}, "pe,pb,total_mv,circ_mv")
        basic_data = resp.get("data", {}).get("items", [])
        pe, pb, total_mv, circ_mv = (basic_data[0][0], basic_data[0][1], basic_data[0][2], basic_data[0][3]) if basic_data else (None, None, None, None)
    except:
        pe, pb, total_mv, circ_mv = None, None, None, None
    
    # 获取fina_indicator (盈利+财务) - 取最近2期以覆盖年报
    try:
        resp = call_tushare("fina_indicator", token, {"ts_code": code}, "ann_date,end_date,roe,roe_dt,dt_netprofit_yoy,or_yoy,op_yoy,debt_to_assets,current_ratio,ocfps,bps")
        fina_data = resp.get("data", {})
        _fina_fields = fina_data.get("fields", [])
        _fina_items = fina_data.get("items", [])
        fina_latest = dict(zip(_fina_fields, _fina_items[0])) if _fina_items else {}
        # 如果最新是Q1/Q3(非年报/半年报)，取第二期作为补充
        fina_annual = {}
        if fina_latest.get('end_date'):
            _ed = str(fina_latest['end_date'])
            if _ed.endswith('0331') or _ed.endswith('0930'):
                fina_annual = dict(zip(_fina_fields, _fina_items[1])) if len(_fina_items) > 1 else {}
    except:
        fina_latest, fina_annual = {}, {}
    
    # 获取balancesheet (商誉)
    try:
        resp = call_tushare("balancesheet", token, {"ts_code": code}, "ann_date,end_date,goodwill,total_hldr_eqy_exc_min_int")
        _bs = resp.get("data", {})
        _bs_fields = _bs.get("fields", [])
        _bs_items = _bs.get("items", [])
        bs_latest = dict(zip(_bs_fields, _bs_items[0])) if _bs_items else {}
    except:
        bs_latest = {}
    
    # 获取income (营收+非经常性损益)
    try:
        resp = call_tushare("income", token, {"ts_code": code}, "ann_date,end_date,total_revenue,revenue,n_income,non_oper_income,non_oper_exp")
        _inc = resp.get("data", {})
        _inc_fields = _inc.get("fields", [])
        _inc_items = _inc.get("items", [])
        inc_latest = dict(zip(_inc_fields, _inc_items[0])) if _inc_items else {}
        inc_prev = dict(zip(_inc_fields, _inc_items[1])) if len(_inc_items) > 1 else {}
    except:
        inc_latest, inc_prev = {}, {}
    
    # 获取股东户数
    try:
        resp = call_tushare("stk_holdernumber", token, {"ts_code": code}, "ann_date,end_date,holder_num")
        _hld = resp.get("data", {})
        _hld_fields = _hld.get("fields", [])
        _hld_items = _hld.get("items", [])
        holder_latest = dict(zip(_hld_fields, _hld_items[0])) if _hld_items else {}
        holder_prev = dict(zip(_hld_fields, _hld_items[1])) if len(_hld_items) > 1 else {}
    except:
        holder_latest, holder_prev = {}, {}
    
    # 获取概念板块数量
    try:
        resp = call_tushare("concept_detail", token, {"ts_code": code}, "id,concept_name")
        concept_items = resp.get("data", {}).get("items", [])
        concept_count = len(concept_items) if concept_items else 0
    except:
        concept_count = 0
    
    # 获取近期公告 (用于事件窗口判断)
    recent_ann_count = 0
    recent_ann_window = 10  # 事件窗口: 近10个自然日
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        start_str = (datetime.now() - timedelta(days=recent_ann_window)).strftime("%Y%m%d")
        resp = call_tushare("anns_d", token, {"ts_code": code, "start_date": start_str, "end_date": today_str}, "ann_date,title")
        ann_items = resp.get("data", {}).get("items", [])
        recent_ann_count = len(ann_items) if ann_items else 0
    except:
        recent_ann_count = 0
    
    # ===== 2. 一票否决检查 =====
    risk_flags = []
    is_vetoed = False
    
    # 商誉占比 > 30%
    if bs_latest.get('goodwill') and bs_latest.get('total_hldr_eqy_exc_min_int'):
        goodwill_ratio = float(bs_latest['goodwill']) / float(bs_latest['total_hldr_eqy_exc_min_int']) * 100
        if goodwill_ratio > 30:
            is_vetoed = True
            risk_flags.append(f"商誉占比{goodwill_ratio:.0f}%>30%")
    
    # 负债率 > 70% 且 经营现金流连续2季度为负
    if fina_latest.get('debt_to_assets'):
        debt_ratio = float(fina_latest['debt_to_assets'])
        if debt_ratio > 70:
            # 检查经营现金流：ocfps(每股经营现金流)连续2季度为负
            ocfps_latest = safe_float(fina_latest.get('ocfps'))
            ocfps_annual = safe_float(fina_annual.get('ocfps')) if fina_annual else None
            # 两期都为负，或最新期为负且无上期数据（保守处理：仅负债率高也否决）
            if ocfps_latest is not None and ocfps_latest < 0:
                if ocfps_annual is None or ocfps_annual < 0:
                    is_vetoed = True
                    risk_flags.append(f"负债率{debt_ratio:.0f}%>70%且经营现金流为负")
            else:
                # 负债率高但经营现金流正常，仅扣分不否决（在财务健康维度处理）
                pass
    
    # 非经常性损益占比 > 20%
    if inc_latest.get('n_income') and inc_latest['n_income'] != 0:
        non_op = (float(inc_latest.get('non_oper_income') or 0) - float(inc_latest.get('non_oper_exp') or 0))
        non_op_ratio = abs(non_op / float(inc_latest['n_income'])) * 100
        if non_op_ratio > 20:
            is_vetoed = True
            risk_flags.append(f"非经常性损益占比{non_op_ratio:.0f}%>20%")
    
    # 主业营收占比 < 50%
    if inc_latest.get('total_revenue') and inc_latest.get('revenue'):
        main_biz_ratio = float(inc_latest['revenue']) / float(inc_latest['total_revenue']) * 100
        if main_biz_ratio < 50:
            is_vetoed = True
            risk_flags.append(f"主业营收占比{main_biz_ratio:.0f}%<50%")
    
    # 近6个月内存在 > 流通盘10% 的大额解禁
    try:
        from datetime import datetime, timedelta
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=180)
        resp = call_tushare("share_float", token, {
                    "ts_code": code,
                    "start_date": start_dt.strftime('%Y%m%d'),
                    "end_date": end_dt.strftime('%Y%m%d')
                }, "float_date,float_share,float_ratio")
        float_items = resp.get("data", {}).get("items", [])
        if float_items:
            for item in float_items:
                float_ratio = safe_float(item[2]) if len(item) > 2 else 0
                if float_ratio and float_ratio > 10:
                    is_vetoed = True
                    risk_flags.append(f"大额解禁{item[0]}占比{float_ratio:.1f}%")
                    break
    except Exception:
        pass
    
    # 触发否决直接返回0分
    if is_vetoed:
        return 0, f"财务避雷否决: {'; '.join(risk_flags)}"
    
    # ===== 3. 五维度评分 =====
    factors = {}  # 各维度标准化得分 [0,1]
    reasons = []
    
    # --- 3.1 盈利业绩维度 (40%) ---
    profit_score = 0.5  # 基准
    profit_reasons = []
    
    # ROE - 优先用年报/半年报数据
    _roe_source = fina_annual if fina_annual.get('end_date', '').endswith('1231') else fina_latest
    if _roe_source.get('roe'):
        roe = float(_roe_source['roe'])
        if roe > 15:
            profit_score += 0.25
            profit_reasons.append(f"ROE={roe:.1f}%")
        elif roe > 10:
            profit_score += 0.15
            profit_reasons.append(f"ROE={roe:.1f}%")
        elif roe < 5:
            profit_score -= 0.15
            profit_reasons.append(f"ROE={roe:.1f}%偏低")
    
    # 扣非净利润同比 (dt_netprofit_yoy字段)
    if fina_latest.get('dt_netprofit_yoy'):
        profit_yoy = float(fina_latest['dt_netprofit_yoy'])
        if profit_yoy > 50:
            profit_score += 0.25
            profit_reasons.append(f"扣非净利+{profit_yoy:.0f}%")
        elif profit_yoy > 20:
            profit_score += 0.15
            profit_reasons.append(f"扣非净利+{profit_yoy:.0f}%")
        elif profit_yoy < 0:
            profit_score -= 0.20
            profit_reasons.append(f"扣非净利{profit_yoy:.0f}%")
    
    # 营收增速 (or_yoy字段)
    if fina_latest.get('or_yoy'):
        rev_yoy = float(fina_latest['or_yoy'])
        if rev_yoy > 30:
            profit_score += 0.15
            profit_reasons.append(f"营收+{rev_yoy:.0f}%")
        elif rev_yoy < 0:
            profit_score -= 0.10
    
    factors['profit'] = max(0, min(1, profit_score))
    reasons.extend(profit_reasons)
    
    # --- 3.2 题材事件维度 (30%) ---
    event_score = 0.5
    event_reasons = []
    
    # 概念数量 (代理事件热度)
    if concept_count >= 5:
        event_score += 0.25
        event_reasons.append(f"{concept_count}个概念")
    elif concept_count >= 3:
        event_score += 0.15
        event_reasons.append(f"{concept_count}个概念")
    elif concept_count == 0:
        event_score -= 0.10
    
    # TODO: 公告事件强度 (需要NLP解析，V1.5实现)
    
    factors['event'] = max(0, min(1, event_score))
    reasons.extend(event_reasons)
    
    # --- 3.3 股东筹码维度 (15%) ---
    chip_score = 0.5
    chip_reasons = []
    
    # 股东户数环比下降
    if holder_latest.get('holder_num') and holder_prev.get('holder_num'):
        try:
            holder_now = float(holder_latest['holder_num'])
            holder_before = float(holder_prev['holder_num'])
            holder_chg = (holder_before - holder_now) / holder_before
            if holder_chg >= 0.05:  # 下降5%+
                chip_score += 0.30
                chip_reasons.append(f"股东户数-{holder_chg*100:.1f}%")
            elif holder_chg >= 0.02:
                chip_score += 0.15
                chip_reasons.append(f"股东户数-{holder_chg*100:.1f}%")
            elif holder_chg < -0.05:  # 增加5%+
                chip_score -= 0.20
                chip_reasons.append(f"股东户数+{abs(holder_chg)*100:.1f}%")
        except:
            pass
    
    # TODO: 机构净增持 (需十大股东数据，V1.5实现)
    
    factors['chip'] = max(0, min(1, chip_score))
    reasons.extend(chip_reasons)
    
    # --- 3.4 财务健康维度 (10%) ---
    # 已通过否决检查，此维度初始为1.0，风险项扣分
    finance_score = 1.0
    finance_reasons = []
    
    # 负债率风险扣分
    if fina_latest.get('debt_to_assets'):
        debt_ratio = float(fina_latest['debt_to_assets'])
        if debt_ratio > 60:
            finance_score -= 0.20
            finance_reasons.append(f"负债率{debt_ratio:.0f}%")
        elif debt_ratio > 50:
            finance_score -= 0.10
    
    # 流动比率
    if fina_latest.get('current_ratio'):
        current_ratio = float(fina_latest['current_ratio'])
        if current_ratio and current_ratio < 1:
            finance_score -= 0.20
            finance_reasons.append("流动性风险")
    
    factors['finance'] = max(0, min(1, finance_score))
    if finance_reasons:
        reasons.extend(finance_reasons)
    
    # --- 3.5 估值性价比维度 (5%) ---
    value_score = 0.5
    value_reasons = []
    
    # PE相对估值
    if pe and pe > 0:
        if pe < 20:
            value_score += 0.25
            value_reasons.append(f"PE={pe:.1f}")
        elif pe < 30:
            value_score += 0.10
        elif pe > 50:
            value_score -= 0.10
            value_reasons.append(f"PE={pe:.1f}偏高")
    
    # PB
    if pb and pb > 0:
        if pb < 2:
            value_score += 0.15
        elif pb > 5:
            value_score -= 0.10
    
    factors['value'] = max(0, min(1, value_score))
    
    # ===== 4. 综合评分计算 =====
    weights = {
        'profit': 0.40,
        'event': 0.30,
        'chip': 0.15,
        'finance': 0.10,
        'value': 0.05
    }
    
    base_score = sum(factors[k] * weights[k] for k in factors) * 100
    
    # ===== 5. 非线性共振加分 =====
    bonus = 0
    # 条件A: 业绩≥0.8 且 事件≥0.7 且 事件窗口t≤10 (近10日内有公告)
    if factors.get('profit', 0) >= 0.8 and factors.get('event', 0) >= 0.7 and recent_ann_count > 0:
        bonus = 15
        reasons.append(f"业绩+事件共振(窗口{recent_ann_window}日内{recent_ann_count}条公告)")
    # 条件B: 业绩≥0.7 且 筹码≥0.6
    elif factors.get('profit', 0) >= 0.7 and factors.get('chip', 0) >= 0.6:
        bonus = 10
        reasons.append("业绩+筹码共振")
    
    final_score = min(100, base_score + bonus)
    
    # ===== 6. 涨停潜力等级 =====
    if final_score >= 75:
        level = "高"
    elif final_score >= 55:
        level = "中"
    elif final_score >= 35:
        level = "低"
    else:
        level = "无"
    
    reason_str = f"[{level}] " + "; ".join(reasons[:5]) if reasons else f"[{level}] 数据不足"
    
    return round(final_score, 1), reason_str

# ===== 3. 技术面评分 V1.0 (五维度量化) =====
def score_technical(code):
    """
    技术面涨停潜力预判 V1.0
    五维度量化评分：量能40分 + 趋势25分 + 位置12分 + 筹码15分 + 资金8分
    含一票否决规则
    """
    from datetime import datetime, timedelta
    
    token = CONFIG["TUSHARE_TOKEN"]
    
    # 使用模块级 safe_float_none（区分None和0）
    safe_float = safe_float_none
    try:
        _stk_fields = "trade_date,close,open,high,low,pre_close,change,pct_change,vol,amount," \
                      "vol_ratio,turnover_rate,ma_bfq_5,ma_bfq_10,ma_bfq_20,ma_bfq_60," \
                      "macd_dif_bfq,macd_dea_bfq,macd_bfq,kdj_k_bfq,kdj_d_bfq," \
                      "rsi_bfq_6,boll_upper_bfq,boll_mid_bfq,boll_lower_bfq"
        resp = call_tushare("stk_factor_pro", token, {"ts_code": code}, _stk_fields)
        factor_data = resp.get("data", {})
        factor_items = factor_data.get("items", [])
        factor_fields = factor_data.get("fields", [])
    except:
        return 50, "技术数据获取失败"
    
    if not factor_items:
        return 50, "技术数据不足"
    
    # 构建因子字典列表（按日期降序）
    factors = [dict(zip(factor_fields, item)) for item in factor_items]
    factors.sort(key=lambda x: x.get('trade_date', ''), reverse=True)
    
    # 盘中场景：Tushare数据为T-1日，无当日实时数据
    # 量比/换手等实时指标应从CDP获取，当前V1.0暂用T-1日数据
    if is_trading_time() and factors:
        latest_date = factors[0].get('trade_date', '')
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y%m%d")
        if latest_date < today_str:
            pass  # T-1数据，盘中可用但非实时
    
    if len(factors) < 3:
        return 50, "技术数据不足"
    
    today = factors[0]
    yesterday = factors[1] if len(factors) > 1 else {}
    
    # 获取资金流向（T+1）
    try:
        resp = call_tushare("moneyflow", token, {"ts_code": code}, "trade_date,net_mf_amount,buy_lg_amount,sell_lg_amount")
        mf_data = resp.get("data", {}).get("items", [])
    except:
        mf_data = []
    
    # ===== 2. 一票否决检查 =====
    veto_flags = []
    
    # 2.1 放量破位：收盘<MA20 且 量比>1.8
    close = safe_float(today.get('close'))
    ma20 = safe_float(today.get('ma_bfq_20'))
    vol_ratio = safe_float(today.get('vol_ratio'))
    boll_mid = safe_float(today.get('boll_mid_bfq'))  # 提前定义，2.5否决需用
    
    if close and ma20 and close < ma20:
        if vol_ratio and vol_ratio > 1.8:
            return 0, f"放量破位:收盘{close:.2f}<MA20={ma20:.2f},量比{vol_ratio:.2f}>1.8"
    
    # 2.2 高位滞涨：阶段涨幅>60%，换手>25%，长上影
    # 阶段涨幅 = 从阶段低点到当前收盘价 (非振幅)
    if len(factors) >= 20:
        lows_20d = [safe_float(factors[i].get('low')) for i in range(20)]
        stage_low = min((l for l in lows_20d if l), default=None)
        if stage_low and close:
            stage_gain = (close - stage_low) / stage_low * 100  # 阶段涨幅: 低点→当前
            turnover = safe_float(today.get('turnover_rate'))
            high = safe_float(today.get('high'))
            open_price = safe_float(today.get('open'))
            if stage_gain > 60 and turnover and turnover > 25:
                if high and close and open_price:
                    body = abs(close - open_price)
                    upper_shadow = high - max(close, open_price)
                    if body > 0 and upper_shadow / body > 1.5:
                        return 0, f"高位滞涨:阶段涨幅{stage_gain:.0f}%,换手{turnover:.1f}%,长上影"
    
    # 2.3 筹码高位发散：套牢盘>60%或集中度较5日前扩大>30%
    # 代理方案：BOLL带宽不能替代筹码集中度，但T+1无CYQ数据。
    # 优先尝试Tushare cyq_perf接口获取真实筹码数据。
    cyq_data = None
    try:
        resp = call_tushare("cyq_perf", token, {"ts_code": code}, "trade_date,cost_5pct,cost_95pct,winner_rate")
        cyq_items = resp.get("data", {}).get("items", [])
        if cyq_items:
            cyq_data = cyq_items[0]  # 最新日期
    except Exception:
        pass
    
    if cyq_data and len(cyq_data) >= 3:
        cost_5 = safe_float(cyq_data[1])
        cost_95 = safe_float(cyq_data[2])
        winner = safe_float(cyq_data[3])
        if cost_5 and cost_95 and cost_95 > cost_5:
            conc = (cost_95 - cost_5) / (cost_95 + cost_5) * 100  # 集中度指标
            # 套牢盘估算：winner_rate < 30% 视为高位套牢盘>70%
            if winner is not None and winner < 30:
                return 0, f"筹码高位发散:获利盘仅{winner:.1f}%"
            # 集中度较5日前扩大>30%（需历史数据对比）
            try:
                resp2 = call_tushare("cyq_perf", token, {"ts_code": code, "start_date": (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')}, "trade_date,cost_5pct,cost_95pct")
                hist_cyq = resp2.get("data", {}).get("items", [])
                if hist_cyq and len(hist_cyq) >= 5:
                    old = hist_cyq[-5]  # 5日前
                    old_5 = safe_float(old[1])
                    old_95 = safe_float(old[2])
                    if old_5 and old_95 and old_95 > old_5:
                        old_conc = (old_95 - old_5) / (old_95 + old_5) * 100
                        if old_conc > 0 and conc > old_conc * 1.3:
                            return 0, f"筹码发散:集中度扩大{(conc/old_conc-1)*100:.0f}%"
            except Exception:
                pass
    else:
        # 降级：BOLL带宽代理（标注为代理方案）
        if len(factors) >= 5:
            boll_widths = []
            for i in range(5):
                bu = safe_float(factors[i].get('boll_upper_bfq'))
                bl = safe_float(factors[i].get('boll_lower_bfq'))
                bm = safe_float(factors[i].get('boll_mid_bfq'))
                if bu and bl and bm:
                    boll_widths.append((bu - bl) / bm * 100)
            if len(boll_widths) >= 5:
                # 带宽扩大>30% = 筹码发散（代理方案）
                if boll_widths[0] > boll_widths[-1] * 1.3:
                    return 0, f"筹码高位发散:带宽扩大{(boll_widths[0]/boll_widths[-1]-1)*100:.0f}%[BOLL代理]"
    
    # 2.4 持续缩量阴跌：连续3日量比<0.5且下跌
    if len(factors) >= 3:
        vr_list = [safe_float(factors[i].get('vol_ratio')) for i in range(3)]
        pc_list = [safe_float(factors[i].get('pct_change')) for i in range(3)]
        if all(vr and vr < 0.5 for vr in vr_list if vr):
            if all(pc and pc < 0 for pc in pc_list if pc):
                return 0, f"持续缩量阴跌:连续3日缩量下跌"
    
    # 2.5 资金持续出逃：近2日主力净流出且分时承接<0.4
    if mf_data and len(mf_data) >= 2:
        net_mf_2d = sum(safe_float(mf_data[i][1]) if len(mf_data[i]) > 1 else 0 for i in range(2))
        if net_mf_2d < 0:
            # 分时承接：收盘/BOLL中轨(VWAP代理) < 0.98 视为无承接
            # 注：设计文档"承接强度<0.4"是0-1复合指标，此处用价格比率代理
            if close and boll_mid and close / boll_mid < 0.98:
                return 0, f"资金持续出逃:近2日主力净流出,分时承接弱"
    
    # ===== 3. 五维度评分 =====
    score = 0
    reasons = []
    
    # --- 3.1 量能结构维度 (40分) ---
    vol_score = 0
    vol_reasons = []
    
    # 量比启动
    if vol_ratio:
        if 1.8 <= vol_ratio <= 4.0:
            vol_score += 15
            vol_reasons.append(f"量比={vol_ratio:.2f}∈[1.8,4.0]+15")
        elif vol_ratio < 1.5:
            vol_reasons.append(f"量比={vol_ratio:.2f}<1.5")
        elif vol_ratio > 6.0:
            vol_score -= 10
            vol_reasons.append(f"量比={vol_ratio:.2f}>6.0异常-10")
    
    # 换手率
    turnover = safe_float(today.get('turnover_rate'))
    if turnover:
        if 3 <= turnover <= 12:
            vol_score += 10
            vol_reasons.append(f"换手={turnover:.1f}%+10")
        elif turnover < 1.5:
            vol_score -= 10
            vol_reasons.append(f"换手={turnover:.1f}%无量-10")
        elif turnover > 20:
            vol_score -= 15
            vol_reasons.append(f"换手={turnover:.1f}%暴量-15")
    
    # 洗盘-起爆节奏
    if len(factors) >= 3:
        vr_yest = safe_float(factors[1].get('vol_ratio'))
        vr_before = safe_float(factors[2].get('vol_ratio'))
        if vr_yest and vr_before and vol_ratio:
            if vr_yest < 0.8 and vr_before < 0.8 and vol_ratio >= 1.5:
                vol_score += 10
                vol_reasons.append(f"洗盘起爆+10")
    
    # 温和放量：当日成交量 > 近3日均量1.3倍 且 < 近20日均量2.5倍
    if len(factors) >= 21:
        today_vol = safe_float(today.get('vol'))
        vol_3d = sum(safe_float(factors[i].get('vol', 0)) for i in range(1, 4)) / 3
        vol_20d = sum(safe_float(factors[i].get('vol', 0)) for i in range(1, 21)) / 20
        if today_vol and vol_3d > 0 and vol_20d > 0:
            if today_vol > vol_3d * 1.3 and today_vol < vol_20d * 2.5:
                vol_score += 15
                vol_reasons.append(f"温和放量(vol/3d={today_vol/vol_3d:.1f})+15")
    elif len(factors) >= 4:
        # 数据不足20日，用3日均量判断
        today_vol = safe_float(today.get('vol'))
        vol_3d = sum(safe_float(factors[i].get('vol', 0)) for i in range(1, 4)) / 3
        if today_vol and vol_3d > 0 and today_vol > vol_3d * 1.3:
            vol_score += 10  # 数据不足，给部分分
            vol_reasons.append(f"放量(vol/3d={today_vol/vol_3d:.1f})+10")
    
    score += max(0, min(40, vol_score))
    reasons.extend(vol_reasons)
    
    # --- 3.2 趋势与均线维度 (25分) ---
    trend_score = 0
    trend_reasons = []
    
    ma5 = safe_float(today.get('ma_bfq_5'))
    ma10 = safe_float(today.get('ma_bfq_10'))
    ma60 = safe_float(today.get('ma_bfq_60'))
    
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            trend_score += 15
            trend_reasons.append(f"均线多头+15")
        elif ma5 < ma10 < ma20:
            trend_score -= 15
            trend_reasons.append(f"均线空头-15")
    
    # MA60方向
    if ma60 and len(factors) >= 5:
        ma60_5d = safe_float(factors[4].get('ma_bfq_60'))
        if ma60_5d and ma60 < ma60_5d:
            trend_score -= 10
            trend_reasons.append(f"MA60下倾-10")
    
    # 回踩企稳
    if close and ma10:
        low_5d = min(safe_float(factors[i].get('low')) or float('inf') for i in range(min(5, len(factors))))
        if low_5d <= ma10 * 1.01 and close > ma10:
            trend_score += 10
            trend_reasons.append(f"回踩MA10企稳+10")
    
    # 硬标准：收盘>MA20
    if close and ma20 and close <= ma20:
        trend_score -= 5
        trend_reasons.append(f"收盘<=MA20弱势")
    
    score += max(0, min(25, trend_score))
    reasons.extend(trend_reasons)
    
    # --- 3.3 关键位置形态维度 (12分) ---
    pos_score = 0
    pos_reasons = []
    
    high = safe_float(today.get('high'))
    low = safe_float(today.get('low'))
    open_price = safe_float(today.get('open'))
    
    # 振幅与突破
    if close and open_price and high and low:
        amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
        if amplitude > 4 and vol_ratio and vol_ratio > 1.5:
            pos_score += 8
            pos_reasons.append(f"振幅{amplitude:.1f}%突破+8")
    
    # 下影线（下影线长=支撑强=企稳信号）
    if close and open_price and low:
        lower_shadow = min(close, open_price) - low
        body = abs(close - open_price)
        if body > 0 and lower_shadow / body > 0.3:
            pos_score += 4
            pos_reasons.append(f"下影线支撑+4")
    
    score += max(0, min(12, pos_score))
    reasons.extend(pos_reasons)
    
    # --- 3.4 筹码结构维度 (15分) ---
    chip_score = 0
    chip_reasons = []
    
    # 优先使用真实筹码数据（cyq_perf）
    cyq_score_data = None
    try:
        resp = call_tushare("cyq_perf", token, {"ts_code": code}, "trade_date,cost_5pct,cost_95pct,winner_rate")
        cyq_items = resp.get("data", {}).get("items", [])
        if cyq_items:
            cyq_score_data = cyq_items[0]
    except Exception:
        pass
    
    if cyq_score_data and len(cyq_score_data) >= 4:
        cost_5 = safe_float(cyq_score_data[1])
        cost_95 = safe_float(cyq_score_data[2])
        winner = safe_float(cyq_score_data[3])
        if cost_5 and cost_95 and cost_95 > cost_5:
            conc = (cost_95 - cost_5) / (cost_95 + cost_5) * 100
            # 低位密集：集中度<12%且获利盘>70%
            if conc < 12 and winner is not None and winner > 70:
                chip_score += 10
                chip_reasons.append(f"低位密集(集中度{conc:.1f}%)+10")
            elif conc > 25:
                chip_score -= 10
                chip_reasons.append(f"筹码发散(集中度{conc:.1f}%)-10")
            # 锁定良好：获利盘>50%
            if winner is not None and winner > 50:
                chip_score += 5
                chip_reasons.append(f"获利盘{winner:.1f}%锁定+5")
    else:
        # 降级：BOLL带宽代理（标注为代理方案）
        boll_upper = safe_float(today.get('boll_upper_bfq'))
        boll_lower = safe_float(today.get('boll_lower_bfq'))
        boll_mid = safe_float(today.get('boll_mid_bfq'))
        
        if boll_upper and boll_lower and boll_mid:
            boll_width = (boll_upper - boll_lower) / boll_mid * 100
            if boll_width < 12:
                chip_score += 10
                chip_reasons.append(f"筹码集中(带宽{boll_width:.1f}%)[BOLL代理]+10")
            elif boll_width > 25:
                chip_score -= 10
                chip_reasons.append(f"筹码发散(带宽{boll_width:.1f}%)[BOLL代理]-10")
        
        # 筹码锁定检查（带宽持续收窄 = 锁仓度高）
        if len(factors) >= 5:
            widths = []
            for i in range(5):
                bu = safe_float(factors[i].get('boll_upper_bfq'))
                bl = safe_float(factors[i].get('boll_lower_bfq'))
                bm = safe_float(factors[i].get('boll_mid_bfq'))
                if bu and bl and bm:
                    widths.append((bu - bl) / bm * 100)
            if widths and len(widths) >= 5:
                # 带宽5日持续收窄（从远到近越来越窄）
                narrowing = all(widths[i] >= widths[i+1] for i in range(len(widths)-1))
                if narrowing and widths[0] < widths[-1] * 0.9:
                    chip_score += 5
                    chip_reasons.append(f"筹码锁定(带宽5日收窄)[BOLL代理]+5")
    
    score += max(0, min(15, chip_score))
    reasons.extend(chip_reasons)
    
    # --- 3.5 资金与盘口维度 (8分) ---
    capital_score = 0
    capital_reasons = []
    
    # 分时承接（收盘/VWAP）
    # 代理方案：T+1无盘中VWAP数据，用收盘价/BOLL中轨代理。
    # 盘中场景应使用CDP实时VWAP数据。
    if close and boll_mid:
        vw_ratio = close / boll_mid
        if vw_ratio > 1.01:
            capital_score += 3
            capital_reasons.append(f"收盘/BOLL中轨{vw_ratio:.3f}>1.01+3[VWAP代理]")
        elif vw_ratio < 0.98:
            capital_score -= 3
            capital_reasons.append(f"收盘/BOLL中轨{vw_ratio:.3f}<0.98-3[VWAP代理]")
    
    # 资金流向（字段顺序：trade_date, net_mf_amount, buy_lg_amount, sell_lg_amount）
    if mf_data:
        mf = mf_data[0]
        net_mf = safe_float(mf[1]) if len(mf) > 1 else None
        buy_lg = safe_float(mf[2]) if len(mf) > 2 else None
        sell_lg = safe_float(mf[3]) if len(mf) > 3 else None
        
        if net_mf and net_mf > 0:
            total = (buy_lg or 0) + (sell_lg or 0)
            if total > 0:
                net_pct = net_mf / total * 100
                if net_pct > 5:
                    capital_score += 5
                    capital_reasons.append(f"主力净流入{net_pct:.1f}%+5")
                elif net_pct > 2:
                    capital_score += 3
                    capital_reasons.append(f"主力净流入{net_pct:.1f}%+3")
        elif net_mf and net_mf < 0:
            total = (buy_lg or 0) + (sell_lg or 0)
            if total > 0:
                net_pct = abs(net_mf) / total * 100
                if net_pct > 5:
                    capital_score -= 8
                    capital_reasons.append(f"主力净流出{net_pct:.1f}%-8")
    
    score += max(0, min(8, capital_score))
    reasons.extend(capital_reasons)
    
    # ===== 4. 综合评定 =====
    final_score = max(0, min(100, score))
    
    if final_score >= 75:
        level = "高"
    elif final_score >= 55:
        level = "中"
    elif final_score >= 35:
        level = "低"
    else:
        level = "无"
    
    reason_str = f"[{level}] " + "; ".join(reasons[:5]) if reasons else f"[{level}] 无明显信号"
    
    return final_score, reason_str


# ===== 4. 资金面评分 (五维度量化评分 V1.0) =====
# 缓存当日资金流向数据（避免每次调用都请求全市场）
_FUND_FLOW_CACHE = None
_FUND_FLOW_DATE = None

def score_fundflow(code):
    """
    资金面涨停潜力预判 V2.0
    五维度量化评分：超大单主力35分 + 龙虎榜机构游资25分 + 分时盘口20分 + 融资聪明资金7分 + 筹码抛压13分
    含一票否决规则（含V2.0市场状态调节器+一字板豁免）
    
    V2.0变更：
    - 维4权重12→7(降共线性)，维5权重8→13(强锁仓)
    - 维2盘中从大单代理→封板质量因子(limit_list)
    - 维4盘中从大单代理→融资余额增速(margin_detail)
    - 否决3加市场状态调节器(低迷市放宽至-0.75)
    - 否决4加一字板豁免
    
    注意：分时盘口为实时数据，T+1场景下用资金流向结构替代评估
    """
    from datetime import datetime, timedelta
    
    token = CONFIG["TUSHARE_TOKEN"]
    today = datetime.now().strftime("%Y%m%d")
    
    score = 0
    reason = []
    veto_flags = []
    
    # ===== 1. 获取资金流向数据 =====
    # 1.1 个股资金流向（moneyflow）
    moneyflow_data = []
    try:
        resp = call_tushare("moneyflow", token, {"ts_code": code}, "trade_date,buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,net_mf_vol,net_mf_amount")
        items = resp.get("data", {}).get("items", [])
        fields = resp.get("data", {}).get("fields", [])
        moneyflow_data = list_to_dict(items, fields)
    except:
        pass
    
    # 1.2 龙虎榜交易明细（top_list）
    top_list_data = []
    try:
        resp = call_tushare("top_list", token, {"ts_code": code, "trade_date": today}, "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate")
        items = resp.get("data", {}).get("items", [])
        fields = resp.get("data", {}).get("fields", [])
        top_list_data = list_to_dict(items, fields)
    except:
        pass
    
    # 1.3 龙虎榜机构交易（top_inst）
    top_inst_data = []
    try:
        resp = call_tushare("top_inst", token, {"ts_code": code, "trade_date": today}, "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason")
        items = resp.get("data", {}).get("items", [])
        fields = resp.get("data", {}).get("fields", [])
        top_inst_data = list_to_dict(items, fields)
    except:
        pass
    
    # 1.4 北向持股（hk_hold）
    hk_hold_data = []
    try:
        # hk_hold接口参数：ts_code必填，exchange为SH/SZ（港股通市场类型，非股票交易所）
        # 北向资金看的是沪股通/深股通，对应exchange=SH/SZ
        exchange = "SH" if code.endswith(".SH") else "SZ" if code.endswith(".SZ") else ""
        resp = call_tushare("hk_hold", token, {"ts_code": code, "exchange": exchange}, "trade_date,ts_code,name,vol,ratio,exchange")
        items = resp.get("data", {}).get("items", [])
        fields = resp.get("data", {}).get("fields", [])
        hk_hold_data = list_to_dict(items, fields)
    except Exception:
        pass
    
    # 注：hk_hold的exchange参数是港股通市场类型（SH=沪股通，SZ=深股通），
    # 与股票后缀一致，无需额外转换。
    
    # 1.5 每日基本面数据（获取流通市值）
    daily_basic_data = []
    try:
        resp = call_tushare("daily_basic", token, {"ts_code": code}, "trade_date,ts_code,close,pct_change,turnover_rate,turnover_rate_f,volume_ratio,total_mv,circ_mv")
        items = resp.get("data", {}).get("items", [])
        fields = resp.get("data", {}).get("fields", [])
        daily_basic_data = list_to_dict(items, fields)
    except:
        pass
    
    # ===== 2. 一票否决检查 =====
    yiziban_exempt = False  # V2.0一字板豁免标志
    # 2.1 主力持续流出：近3日累计净流出 > 0.5%流通市值
    if moneyflow_data:
        recent_3d = moneyflow_data[:3] if len(moneyflow_data) >= 3 else moneyflow_data
        net_3d = sum([safe_float(x.get("net_mf_amount", 0)) for x in recent_3d])
        if daily_basic_data:
            circ_mv = safe_float(daily_basic_data[0].get("circ_mv", 0)) * 10000  # 万转元
            if circ_mv > 0 and net_3d < -circ_mv * 0.005:  # 流出超0.5%流通市值
                veto_flags.append(f"主力3日净流出{net_3d/10000:.2f}万")
    
    # 2.2 纯散户博弈：主力净占比 < 10%（无大资金控盘）
    # V2.0一字板豁免：一字板(pct_chg≈10%且开板次数=0)无大单成交属正常，主力已高度控盘
    is_yiziban = False  # 一字板标志
    if daily_basic_data:
        pct_chg = safe_float(daily_basic_data[0].get("pct_change", 0))
        # 用涨跌停数据判断一字板（开板次数=0且涨停）
        try:
            resp_ll = call_tushare("limit_list", token, {"ts_code": code, "trade_date": today}, "trade_date,ts_code,close,pct_chg,open_times,limit")
            ll_items = resp_ll.get("data", {}).get("items", [])
            if ll_items:
                ll_fields = resp_ll.get("data", {}).get("fields", [])
                ll_data = list_to_dict(ll_items, ll_fields)
                if ll_data:
                    open_times = safe_float(ll_data[0].get("open_times", 1))
                    limit_type = str(ll_data[0].get("limit", "")).upper()
                    if limit_type == "U" and open_times == 0:
                        is_yiziban = True
        except:
            pass
        # 简化判断：涨幅>=9.9%也视为一字板候选（limit_list可能无数据）
        if not is_yiziban and pct_chg >= 9.9:
            is_yiziban = True
    
    if moneyflow_data and not is_yiziban:
        latest = moneyflow_data[0]
        buy_elg = safe_float(latest.get("buy_elg_amount", 0))
        sell_elg = safe_float(latest.get("sell_elg_amount", 0))
        buy_lg = safe_float(latest.get("buy_lg_amount", 0))
        sell_lg = safe_float(latest.get("sell_lg_amount", 0))
        net_elg = buy_elg - sell_elg
        net_lg = buy_lg - sell_lg
        total_buy = buy_elg + buy_lg
        total_sell = sell_elg + sell_lg
        total_vol = total_buy + total_sell
        if total_vol > 0:
            main_ratio = (net_elg + net_lg) / total_vol * 100
            if main_ratio < 10:
                veto_flags.append(f"纯散户博弈:主力净占比{main_ratio:.1f}%<10%")
    elif is_yiziban:
        # 一字板豁免：不触发否决，但记录豁免信息到reason
        yiziban_exempt = True
    
    # 2.3 龙虎榜大额撤离：机构/游资净卖出 > 净买入2倍
    if top_inst_data:
        total_net_buy = 0
        total_net_sell = 0
        for inst in top_inst_data:
            nb = safe_float(inst.get("net_buy", 0))
            if nb > 0:
                total_net_buy += nb
            else:
                total_net_sell += abs(nb)
        if total_net_sell > total_net_buy * 2 and total_net_sell > 1000:  # 万元
            veto_flags.append(f"龙虎榜净卖出{total_net_sell:.0f}万")
    
    # 2.4 分时资金背离：股价拉升>3%但资金净流入为负
    # T+1场景简化：当日涨幅>3%但主力净流出
    # V2.0市场状态调节器：低迷市(成交额<8000亿或跌停>20家)阈值放宽
    corr_threshold = -0.6  # 默认相关系数阈值
    if daily_basic_data:
        try:
            # 获取全市场成交额和跌停家数判断市场状态
            resp_info = call_tushare("daily_info", token, {"trade_date": today, "ts_code": "SSE"}, "trade_date,ts_code,amount")
            info_items = resp_info.get("data", {}).get("items", [])
            market_amount = 0
            if info_items:
                info_fields = resp_info.get("data", {}).get("fields", [])
                info_data = list_to_dict(info_items, info_fields)
                if info_data:
                    market_amount = safe_float(info_data[0].get("amount", 0))  # 万元
            # 获取跌停家数
            limit_down_cnt = 0
            try:
                resp_ld = call_tushare("limit_list_d", token, {"trade_date": today, "limit_type": "D"}, "trade_date,ts_code")
                ld_items = resp_ld.get("data", {}).get("items", [])
                limit_down_cnt = len(ld_items) if ld_items else 0
            except:
                pass
            # 低迷市判定：全市场成交额<8000亿(80000000万) 或 跌停>20家
            if market_amount < 80000000 or limit_down_cnt > 20:
                corr_threshold = -0.75
        except:
            pass
    
    if moneyflow_data and daily_basic_data:
        latest_basic = daily_basic_data[0]
        pct_change = safe_float(latest_basic.get("pct_change", 0))
        if pct_change > 3:
            latest_mf = moneyflow_data[0]
            net_mf = safe_float(latest_mf.get("net_mf_amount", 0))
            if net_mf < 0:
                # V2.0: 低迷市用-0.75阈值（此处简化为：低迷市不触发此否决）
                # 完整实现需算滑动相关系数，T+1场景用简化逻辑
                if corr_threshold < -0.6:
                    # 低迷市放宽，不触发背离否决
                    pass
                else:
                    veto_flags.append(f"资金背离:涨{pct_change:.1f}%但净流出{abs(net_mf)/10000:.0f}万")
    
    # 否决5(尾盘集中兑现)：14:45后资金净流出占全天流出比例>60%
    # T+1替代：主力净流出>0.3%流通市值（与设计文档维度1规模阈值对齐）
    if moneyflow_data and daily_basic_data:
        latest_mf = moneyflow_data[0]
        net_mf = safe_float(latest_mf.get("net_mf_amount", 0))
        circ_mv = safe_float(daily_basic_data[0].get("circ_mv", 0)) * 10000
        if circ_mv > 0 and net_mf < -circ_mv * 0.003:
            veto_flags.append(f"大额流出:净流出{abs(net_mf)/10000:.0f}万")
    
    # 触发否决直接返回
    if veto_flags:
        return 0, f"否决: {'; '.join(veto_flags)}"
    
    # ===== 3. 维度1：超大单主力净流入（35分）=====
    dim1_score = 0
    dim1_reason = []
    
    if moneyflow_data:
        latest = moneyflow_data[0]
        buy_elg = safe_float(latest.get("buy_elg_amount", 0))
        sell_elg = safe_float(latest.get("sell_elg_amount", 0))
        buy_lg = safe_float(latest.get("buy_lg_amount", 0))
        sell_lg = safe_float(latest.get("sell_lg_amount", 0))
        net_mf = safe_float(latest.get("net_mf_amount", 0))
        
        # 主力净额（超大单+大单）
        main_net = (buy_elg - sell_elg) + (buy_lg - sell_lg)
        
        # 规模阈值：主力净流入 >= 流通市值0.3%
        if daily_basic_data:
            circ_mv = safe_float(daily_basic_data[0].get("circ_mv", 0)) * 10000  # 万转元
            if circ_mv > 0:
                main_net_ratio = main_net / circ_mv * 100
                if main_net_ratio >= 0.3:
                    dim1_score += 15
                    dim1_reason.append(f"主力净流入{main_net_ratio:.2f}%+15")
                elif main_net_ratio < 0.1:
                    dim1_score -= 5
                    dim1_reason.append(f"主力净流入{main_net_ratio:.2f}%-5")
        
        # 占比健康：主力净占比 > 30%
        total_vol = buy_elg + sell_elg + buy_lg + sell_lg
        if total_vol > 0:
            main_ratio = main_net / total_vol * 100
            if main_ratio > 30:
                dim1_score += 10
                dim1_reason.append(f"主力占比{main_ratio:.1f}%+10")
        
        # 持续抢筹：近3日连续净流入
        if len(moneyflow_data) >= 3:
            net_3d = [safe_float(x.get("net_mf_amount", 0)) for x in moneyflow_data[:3]]
            if all(n > 0 for n in net_3d):
                dim1_score += 10
                dim1_reason.append(f"连续3日净流入+10")
        
        # 负向：散户接盘（中小单流入、主力流出）
        if main_net < 0 and net_mf > 0:  # 主力流出但总净流入为正
            dim1_score -= 10
            dim1_reason.append(f"散户接盘-10")
    
    dim1_score = max(0, min(35, dim1_score))
    score += dim1_score
    if dim1_reason:
        reason.append(f"[主力{dim1_score}分] {' '.join(dim1_reason)}")
    
    # ===== 4. 维度2：龙虎榜机构游资（25分）=====
    dim2_score = 0
    dim2_reason = []
    
    if is_trading_time():
        # V2.0盘中方案：从大单代理改为封板质量因子(T-1日limit_list)
        # 消除与维度1(大单流入)的共线性，封板质量反映游资/机构合力
        limit_list_data = []
        try:
            resp = call_tushare("limit_list", token, {"ts_code": code}, "trade_date,ts_code,close,pct_chg,open_times,fd_amount,first_time,last_time,up_stat,limit")
            items = resp.get("data", {}).get("items", [])
            fields = resp.get("data", {}).get("fields", [])
            limit_list_data = list_to_dict(items, fields)
        except:
            pass
        
        if limit_list_data:
            # 取T-1日数据(最新一条)
            latest_ll = limit_list_data[0]
            fd_amount = safe_float(latest_ll.get("fd_amount", 0))  # 封单金额(万)
            first_time = latest_ll.get("first_time", "")  # 首次涨停时间
            open_times = safe_float(latest_ll.get("open_times", 1))  # 开板次数
            limit_type = str(latest_ll.get("limit", "")).upper()
            
            # 封板强度：封单金额 > 流通市值1%
            if daily_basic_data and fd_amount > 0:
                circ_mv = safe_float(daily_basic_data[0].get("circ_mv", 0))  # 万
                if circ_mv > 0:
                    fd_ratio = fd_amount / circ_mv * 100
                    if fd_ratio >= 1:
                        dim2_score += 10
                        dim2_reason.append(f"[盘中]封单{fd_ratio:.1f}%流通市值+10")
                    elif fd_ratio < 0.3:
                        dim2_score -= 10
                        dim2_reason.append(f"[盘中]封单弱{fd_ratio:.1f}%-10")
            
            # 首封时间：<10:30(早封板=游资合力强)
            if first_time and limit_type == "U":
                try:
                    hhmm = first_time.replace(":", "")
                    if hhmm < "103000":
                        dim2_score += 8
                        dim2_reason.append(f"[盘中]早封板{first_time}+8")
                    elif hhmm > "140000":
                        dim2_score -= 8
                        dim2_reason.append(f"[盘中]尾板{first_time}-8")
                except:
                    pass
            
            # 开板次数：0次(一字板/秒封)+7分，1次+3分，>=3次扣7分
            if limit_type == "U":
                if open_times == 0:
                    dim2_score += 7
                    dim2_reason.append(f"[盘中]秒封/一字板+7")
                elif open_times == 1:
                    dim2_score += 3
                    dim2_reason.append(f"[盘中]开板1次+3")
                elif open_times >= 3:
                    dim2_score -= 7
                    dim2_reason.append(f"[盘中]开板{int(open_times)}次-7")
            
            # 负向：T-1日未涨停或炸板
            if limit_type != "U":
                dim2_score -= 15
                dim2_reason.append(f"[盘中]T-1未涨停-15")
        else:
            # 无limit_list数据（非涨停股），给基础分0
            dim2_reason.append(f"[盘中]无封板数据")
    else:
        # 盘后方案：Tushare龙虎榜
        inst_net_buy = 0
        hot_money_net_buy = 0
        
        if top_inst_data:
            for inst in top_inst_data:
                nb = safe_float(inst.get("net_buy", 0))
                exalter = inst.get("exalter", "")
                # 机构席位
                if "机构" in exalter or "专用" in exalter:
                    inst_net_buy += nb
                else:
                    hot_money_net_buy += nb
            
            # 资金合力：机构+游资净买入 > 3000万
            total_net = inst_net_buy + hot_money_net_buy
            if total_net > 3000:
                dim2_score += 12
                dim2_reason.append(f"机构游资净买{total_net/10000:.2f}亿+12")
            
            # 席位主导：单一席位净买入占比 > 40%
            if total_net > 0:
                max_seat = max(abs(inst_net_buy), abs(hot_money_net_buy))
                if max_seat / total_net > 0.4:
                    dim2_score += 8
                    dim2_reason.append(f"席位主导+8")
        
        # 龙虎榜上榜且净流入
        if top_list_data:
            latest_top = top_list_data[0]
            net_rate = safe_float(latest_top.get("net_rate", 0))
            if net_rate > 0:
                dim2_score += 5
                dim2_reason.append(f"龙虎榜净买率{net_rate:.1f}%+5")
    
    dim2_score = max(0, min(25, dim2_score))
    score += dim2_score
    if dim2_reason:
        reason.append(f"[龙虎{dim2_score}分] {' '.join(dim2_reason)}")
    
    # ===== 5. 维度3：分时盘口资金抢筹（20分）=====
    # 注意：T+1数据无法获取实时分时，用资金流向结构替代评估
    dim3_score = 0
    dim3_reason = []
    
    if moneyflow_data and daily_basic_data:
        latest = moneyflow_data[0]
        net_mf = safe_float(latest.get("net_mf_amount", 0))
        turnover_rate = safe_float(daily_basic_data[0].get("turnover_rate", 0))
        
        # 用净流入强度和换手率评估
        if net_mf > 0:
            # 净流入 > 0，得分
            dim3_score += 10
            dim3_reason.append(f"净流入{net_mf/10000:.2f}亿+10")
            
            # 换手率健康区间
            if 3 <= turnover_rate <= 10:
                dim3_score += 6
                dim3_reason.append(f"换手{turnover_rate:.1f}%+6")
            elif turnover_rate > 10:
                dim3_score += 4
                dim3_reason.append(f"换手{turnover_rate:.1f}%活跃+4")
        else:
            # 净流出，不给基础分
            dim3_score = 0
            dim3_reason.append(f"净流出{abs(net_mf)/10000:.2f}亿")
    
    dim3_score = max(0, min(20, dim3_score))
    score += dim3_score
    if dim3_reason:
        reason.append(f"[盘口{dim3_score}分] {' '.join(dim3_reason)}")
    
    # ===== 6. 维度4：融资与聪明资金（7分）V2.0: 权重12→7 =====
    dim4_score = 0
    dim4_reason = []
    
    if is_trading_time():
        # V2.0盘中方案：从大单代理改为融资余额增速(T-1日margin_detail)
        # 消除与维度1(大单流入)的共线性，融资增速反映杠杆聪明钱
        margin_data = []
        try:
            resp = call_tushare("margin_detail", token, {"ts_code": code}, "trade_date,ts_code,rzye,rqye,rzmre,rqmcl,rzrqye")
            items = resp.get("data", {}).get("items", [])
            fields = resp.get("data", {}).get("fields", [])
            margin_data = list_to_dict(items, fields)
        except:
            pass
        
        if margin_data and len(margin_data) >= 5:
            # 融资持续增长：近5日融资余额连续增长(无单日下降)
            rzye_list = [safe_float(x.get("rzye", 0)) for x in margin_data[:5]]
            if all(rzye_list[i] <= rzye_list[i+1] for i in range(len(rzye_list)-1)) and rzye_list[0] > rzye_list[1]:
                # 按时间降序：[0]最新，连续增长意味着[0]>[1]>[2]>[3]>[4]
                dim4_score += 3
                dim4_reason.append(f"[盘中]融资5日连增+3")
            
            # 融资活跃度：当日融资买入额占成交额比例>8%
            rzmre = safe_float(margin_data[0].get("rzmre", 0))  # 融资买入额(元)
            if daily_basic_data and rzmre > 0:
                # 成交额从moneyflow获取
                if moneyflow_data:
                    total_amount = sum([
                        safe_float(margin_data[0].get("rzmre", 0)),
                        abs(safe_float(moneyflow_data[0].get("net_mf_amount", 0)))
                    ])
                else:
                    total_amount = rzmre * 10  # 粗估
                if total_amount > 0:
                    rz_ratio = rzmre / total_amount * 100
                    if rz_ratio > 8:
                        dim4_score += 2
                        dim4_reason.append(f"[盘中]融资买入占比{rz_ratio:.1f}%+2")
            
            # 融资共振：融资余额增速与超大单净流入同向
            rz_chg = safe_float(margin_data[0].get("rzye", 0)) - safe_float(margin_data[1].get("rzye", 0)) if len(margin_data) > 1 else 0
            if moneyflow_data:
                main_net = safe_float(moneyflow_data[0].get("net_mf_amount", 0))
                if (rz_chg > 0 and main_net > 0) or (rz_chg < 0 and main_net < 0):
                    dim4_score += 2
                    dim4_reason.append(f"[盘中]融资主力同向+2")
            
            # 负向：融资余额连续3日下降
            if len(margin_data) >= 3:
                rz_3d = [safe_float(x.get("rzye", 0)) for x in margin_data[:3]]
                if rz_3d[0] < rz_3d[1] < rz_3d[2]:  # 按时间降序，连续下降
                    dim4_score -= 5
                    dim4_reason.append(f"[盘中]融资3日连降-5")
        elif margin_data:
            # 数据不足5日
            dim4_reason.append(f"[盘中]融资数据不足5日")
        else:
            dim4_reason.append(f"[盘中]无融资数据")
    else:
        # 盘后方案：Tushare hk_hold
        if hk_hold_data:
            # 当日北向持股变动
            latest_hold = hk_hold_data[0]
            latest_vol = safe_float(latest_hold.get("vol", 0))
            latest_ratio = safe_float(latest_hold.get("ratio", 0))
            
            # 近5日持仓变动
            if len(hk_hold_data) >= 5:
                vol_5d_ago = safe_float(hk_hold_data[4].get("vol", 0))
                if vol_5d_ago > 0:
                    vol_chg = (latest_vol - vol_5d_ago) / vol_5d_ago * 100
                    # 持续增持
                    if latest_vol > vol_5d_ago:
                        dim4_score += 6
                        dim4_reason.append(f"北向5日增持{vol_chg:.1f}%+6")
                    # 筹码锁定
                    if len(hk_hold_data) >= 2:
                        ratio_prev = safe_float(hk_hold_data[1].get("ratio", 0))
                        ratio_delta = latest_ratio - ratio_prev
                        if ratio_delta > 0.05:
                            dim4_score += 4
                            dim4_reason.append(f"持股占比+{ratio_delta:.2f}%+4")
            else:
                # 数据不足，当日北向持股 > 0 即可
                if latest_vol > 0:
                    dim4_score += 4
                    dim4_reason.append(f"北向持股{latest_vol/10000:.2f}万股+4")
    
    dim4_score = max(0, min(7, dim4_score))
    score += dim4_score
    if dim4_reason:
        reason.append(f"[融资{dim4_score}分] {' '.join(dim4_reason)}")
    
    # ===== 7. 维度5：筹码抛压与锁仓（13分）V2.0: 权重8→13 =====
    dim5_score = 0
    dim5_reason = []
    
    if moneyflow_data and len(moneyflow_data) >= 3:
        # 近3日净流入数据（按时间降序：[0]今天、[1]昨天、[2]前天）
        net_flows = [safe_float(x.get("net_mf_amount", 0)) for x in moneyflow_data[:3]]
        # 净流入递增 = 锁仓度高（前天<=昨天<=今天）
        if net_flows[2] <= net_flows[1] <= net_flows[0] and net_flows[0] > 0:
            dim5_score += 7
            dim5_reason.append(f"流入递增锁仓+7")
        
        # 无大幅流出 = 抛压可控
        if all(n >= 0 for n in net_flows):
            dim5_score += 3
            dim5_reason.append(f"无抛压+3")
        
        # V2.0新增：净流入加速（今日>前2日均值1.5倍）
        if net_flows[0] > 0 and len(net_flows) >= 3:
            avg_2d = (abs(net_flows[1]) + abs(net_flows[2])) / 2
            if avg_2d > 0 and net_flows[0] > avg_2d * 1.5:
                dim5_score += 3
                dim5_reason.append(f"流入加速+3")
    
    dim5_score = max(0, min(13, dim5_score))
    score += dim5_score
    if dim5_reason:
        reason.append(f"[锁仓{dim5_score}分] {' '.join(dim5_reason)}")
    
    # ===== 8. 返回结果 =====
    if yiziban_exempt:
        reason.append("[豁免]一字板跳过散户博弈否决")
    if not reason:
        reason.append("[无] 无明显资金信号")
    
    final_score = min(100, score)
    
    if final_score >= 75:
        level = "高"
    elif final_score >= 55:
        level = "中"
    elif final_score >= 35:
        level = "低"
    else:
        level = "无"
    
    return final_score, f"[{level}] " + "; ".join(reason)

def score_sentiment(code):
    """
    情绪面涨停潜力预判 V1.2
    五维度量化评分：大盘情绪30分 + 主线题材30分 + 板块梯队20分 + 个股人气10分 + 集合竞价15分
    含一票否决规则
    V1.2变更：CallVolRatio量纲修正(vol/yesterday_vol替代vol/float_share) + OpenGap市场状态乘数
    """
    from datetime import datetime, timedelta
    
    token = CONFIG["TUSHARE_TOKEN"]
    
    # 使用模块级工具函数（区分None和0）
    safe_float = safe_float_none
    safe_int = safe_int_none
    # list_to_dict 使用模块级定义
    
    # ===== 0. 获取交易日期 =====
    today_str = datetime.now().strftime('%Y%m%d')
    
    # ===== 1. 数据获取 =====
    # 1.1 获取个股所属概念板块（离线数据）
    concept_names = []
    try:
        resp = call_tushare("concept_detail", token, {"ts_code": code}, "id,concept_name")
        data = resp.get("data", {})
        items = data.get("items", [])
        concept_names = [c[1] for c in items if len(c) > 1] if items else []
    except:
        pass
    
    # 1.2 获取全市场涨停数据（T+1）
    limit_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "limit", "limit_times", "up_stat"]
    limit_data = []
    try:
        resp = call_tushare("limit_list_d", token, {"trade_date": today_str}, ",".join(limit_fields))
        data = resp.get("data", {})
        limit_data = list_to_dict(data.get("items", []), limit_fields)
    except:
        pass
    
    # 1.3 获取连板天梯数据
    step_fields = ["trade_date", "ts_code", "name", "nums"]
    step_data = []
    try:
        resp = call_tushare("limit_step", token, {"trade_date": today_str}, ",".join(step_fields))
        data = resp.get("data", {})
        step_data = list_to_dict(data.get("items", []), step_fields)
    except:
        pass
    
    # 1.4 获取龙虎榜数据
    top_list_fields = ["trade_date", "ts_code", "name", "close", "pct_change", "turnover_rate", "amount", "l_sell", "l_buy", "l_amount", "net_amount", "net_rate"]
    top_list_data = []
    try:
        resp = call_tushare("top_list", token, {"ts_code": code}, ",".join(top_list_fields))
        data = resp.get("data", {})
        top_list_data = list_to_dict(data.get("items", []), top_list_fields)
    except:
        pass
    
    # 1.5 获取机构买卖明细
    inst_data = []
    try:
        resp = call_tushare("top_inst", token, {"trade_date": today_str}, "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason")
        inst_data = resp.get("data", {}).get("items", [])
    except:
        pass
    
    # 1.6 获取涨停最强板块统计（概念涨停家数）
    cpt_fields = ["ts_code", "name", "trade_date", "days", "up_stat", "cons_nums", "up_nums", "pct_chg", "rank"]
    cpt_data = []
    try:
        resp = call_tushare("limit_cpt_list", token, {"trade_date": today_str}, ",".join(cpt_fields))
        data = resp.get("data", {})
        cpt_data = list_to_dict(data.get("items", []), cpt_fields)
    except:
        pass
    
    # 构建概念→涨停家数映射
    concept_ul_cnt = {}
    if cpt_data:
        for cpt in cpt_data:
            cpt_name = cpt.get('name', '')
            up_nums = safe_int(cpt.get('up_nums', 0)) or 0
            if cpt_name and up_nums > 0:
                concept_ul_cnt[cpt_name] = up_nums
    # 补充：用涨停数据按行业统计（备选）
    if limit_data:
        for item in limit_data:
            item_name = item.get('name', '')
            # 用涨停股所属概念名统计
            for cpt_name in concept_names:
                if cpt_name not in concept_ul_cnt:
                    concept_ul_cnt[cpt_name] = 0
    
    # 1.7 获取个股昨日成交量（CallVolRatio量纲修正，V1.2）
    yesterday_vol = 0
    try:
        end_dt = datetime.now() - timedelta(days=5)  # 往前多取几天确保覆盖周末
        resp = call_tushare("daily", token, {
            "ts_code": code,
            "start_date": end_dt.strftime('%Y%m%d'),
            "end_date": today_str
        }, "trade_date,vol")
        daily_items = resp.get("data", {}).get("items", [])
        if daily_items and len(daily_items) >= 2:
            # 取最近一个交易日的成交量作为yesterday_vol（排除当日）
            # daily接口按日期倒序返回，items[0]是最近的
            # 如果items[0]日期=today，取items[1]；否则取items[0]
            d_fields = resp.get("data", {}).get("fields", [])
            d_dict_list = [dict(zip(d_fields, x)) for x in daily_items if d_fields]
            for d in d_dict_list:
                if d.get('trade_date', '') != today_str:
                    yesterday_vol = safe_float(d.get('vol', 0)) or 0
                    break
            # 如果没找到非今日数据，取items[1]（第二近的日期）
            if yesterday_vol == 0 and len(daily_items) >= 2:
                vol_val = daily_items[1][1] if len(daily_items[1]) > 1 else 0
                yesterday_vol = safe_float(vol_val) or 0
    except Exception:
        pass
    
    # 1.8 市场状态判定（V1.2新增，用于OpenGap乘数）
    # 基于全市场涨跌家数+成交额判定牛市/震荡/熊市态
    market_state = "震荡"  # 默认震荡态
    market_state_multiplier = 1.0  # 默认乘数
    mkt_advance_decline_ratio = 0
    try:
        # 涨跌比：用limit_data中的涨停+跌停数估算（精确值需全市场数据）
        # 更精确方案：获取上证+深证每日交易统计
        resp_sh = call_tushare("daily_info", token, {"trade_date": today_str, "ts_code": "SSE"}, "trade_date,ts_code,com_count,amount")
        sh_data = resp_sh.get("data", {}).get("items", [])
        resp_sz = call_tushare("daily_info", token, {"trade_date": today_str, "ts_code": "SZSE"}, "trade_date,ts_code,com_count,amount")
        sz_data = resp_sz.get("data", {}).get("items", [])
        
        # 获取20日均成交额（取近20个交易日）
        mkt_amount_20d_avg = 0
        resp_info = call_tushare("daily_info", token, {
            "start_date": (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'),
            "end_date": today_str
        }, "trade_date,amount")
        info_items = resp_info.get("data", {}).get("items", [])
        if info_items:
            amounts = []
            info_fields = resp_info.get("data", {}).get("fields", [])
            for item in info_items:
                d = dict(zip(info_fields, item)) if info_fields else {}
                amt = safe_float(d.get('amount', 0))
                if amt and amt > 0:
                    amounts.append(amt)
            if len(amounts) >= 5:
                mkt_amount_20d_avg = sum(amounts[-20:]) / len(amounts[-20:])
        
        # 计算涨跌比（用涨停跌停家数简化估算）
        if limit_data:
            limit_up_cnt_est = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'U'])
            limit_down_cnt_est = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'D'])
            # 精确涨跌比需要全市场数据，此处用涨停/跌停比率粗估
            # 更精确：用daily_info的com_count推算
            total_com = 0
            today_amount = 0
            if sh_data:
                sh_dict = dict(zip(resp_sh.get("data", {}).get("fields", []), sh_data[0])) if sh_data else {}
                total_com += safe_int(sh_dict.get('com_count', 0)) or 0
                today_amount += safe_float(sh_dict.get('amount', 0)) or 0
            if sz_data:
                sz_dict = dict(zip(resp_sz.get("data", {}).get("fields", []), sz_data[0])) if sz_data else {}
                total_com += safe_int(sz_dict.get('com_count', 0)) or 0
                today_amount += safe_float(sz_dict.get('amount', 0)) or 0
            
            # 用涨停跌停数近似涨跌比（涨停数/跌停数，无法获取全市场涨跌家数）
            # 如果有daily_info数据，可更精确估算（假设涨跌比 ≈ 涨停家数占比高的市场偏暖）
            if limit_up_cnt_est > 0 and limit_down_cnt_est > 0:
                mkt_advance_decline_ratio = limit_up_cnt_est / limit_down_cnt_est
            elif limit_up_cnt_est > 0:
                mkt_advance_decline_ratio = 3.0  # 无跌停数据时默认偏暖
            
            # 判定市场状态
            amount_ratio = today_amount / mkt_amount_20d_avg if mkt_amount_20d_avg > 0 else 1.0
            
            if mkt_advance_decline_ratio > 2.5 and amount_ratio > 1.2:
                market_state = "牛市"
                market_state_multiplier = 1.3
            elif mkt_advance_decline_ratio < 0.8 or amount_ratio < 0.7:
                market_state = "熊市"
                market_state_multiplier = 0.6
            else:
                market_state = "震荡"
                market_state_multiplier = 1.0
            
            # 限定乘数范围[0.5, 1.5]
            market_state_multiplier = max(0.5, min(1.5, market_state_multiplier))
    except Exception:
        pass
    
    # ===== 2. 一票否决检查 =====
    # 2.1 市场退潮：炸板率>45% 或 涨停数极少
    if limit_data:
        limit_up_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'U'])
        limit_z_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'Z'])  # 炸板
        total_board = limit_up_cnt + limit_z_cnt
        if total_board > 0:
            break_rate = limit_z_cnt / total_board * 100
            if break_rate > 45:
                return 0, f"市场退潮:炸板率{break_rate:.1f}%>45%"
            if limit_up_cnt < 15:
                return 0, f"市场退潮:涨停仅{limit_up_cnt}家"
    
    # 否决2(主线崩塌)：核心龙头断板 或 所属题材无涨停
    # T+1场景简化：概念涨停数=0视为主线崩塌（=1留给否决5纯跟风）
    if concept_names and cpt_data:
        max_ul = max([concept_ul_cnt.get(n, 0) for n in concept_names], default=0)
        if max_ul == 0 and len(concept_names) > 0:
            return 0, f"主线崩塌:所属概念无涨停"
    
    # 2.3 高位杀跌：最高连板高度连续2日下降（需多日数据，T+1简化为高度<2）
    if step_data:
        max_height = max([safe_int(x.get('nums', 0)) or 0 for x in step_data], default=0)
        if max_height < 2 and len(step_data) > 0:
            return 0, f"高位杀跌:最高仅{max_height}板"
    
    # 2.4 个股情绪溃散：近5日核按钮 或 龙虎榜知名游资单日净卖出>3000万
    # 核按钮：近5日出现收盘跌幅<=-7%且放量（成交量>5日均量1.5倍）
    try:
        from datetime import datetime, timedelta
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=10)  # 多取几天覆盖周末
        resp = call_tushare("daily", token, {
                    "ts_code": code,
                    "start_date": start_dt.strftime('%Y%m%d'),
                    "end_date": end_dt.strftime('%Y%m%d')
                }, "trade_date,close,pct_chg,vol")
        daily_items = resp.get("data", {}).get("items", [])
        if daily_items and len(daily_items) >= 2:
            # 计算5日均量
            vols = [safe_float(x[3]) for x in daily_items if x[3] is not None]
            avg_vol_5 = sum(vols[-5:]) / len(vols[-5:]) if len(vols) >= 5 else sum(vols) / len(vols)
            # 检查近5日（不含今日）是否有核按钮
            for item in daily_items[-6:-1]:  # 近5个交易日（不含当日）
                pct_chg = safe_float(item[2])
                vol = safe_float(item[3])
                if pct_chg is not None and vol is not None:
                    if pct_chg <= -7 and avg_vol_5 > 0 and vol > avg_vol_5 * 1.5:
                        return 0, f"核按钮:{item[0]}跌幅{pct_chg:.1f}%且放量"
    except Exception:
        pass
    
    if top_list_data:
        for item in top_list_data[:3]:
            net_amount = safe_float(item.get('net_amount', 0))
            if net_amount and net_amount < -3000:
                return 0, f"游资出逃:净卖{abs(net_amount):.0f}万"
    
    # 2.5 纯跟风弱势：所属板块仅该股独涨，无梯队扩散
    # 需要板块成分数据判断，T+1简化：概念涨停数=1且人气排名无数据
    if concept_names and cpt_data:
        max_ul = max([concept_ul_cnt.get(n, 0) for n in concept_names], default=0)
        if max_ul == 1 and len(concept_names) > 0:
            return 0, f"纯跟风:所属板块仅1只涨停,无梯队"
    
    # ===== 3. 五维度评分 =====
    score = 0
    reasons = []
    
    # --- 3.1 大盘整体情绪维度 (30分) ---
    market_score = 0
    market_reasons = []
    
    if limit_data:
        limit_up_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'U'])
        limit_down_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'D'])
        limit_z_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'Z'])
        
        # 赚钱效应：昨日涨停股今日平均溢价（T+1用当日涨停股平均涨幅代理）
        avg_premium = 0
        up_items = [x for x in limit_data if str(x.get('limit', '')).upper() == 'U']
        if up_items:
            premiums = [safe_float(x.get('pct_change', 0)) for x in up_items]
            avg_premium = sum(premiums) / len(premiums) if premiums else 0
        
        if avg_premium >= 1.5:
            market_score += 10
            market_reasons.append(f"涨停溢价{avg_premium:.1f}%+10")
        elif avg_premium < 0:
            market_score -= 10
            market_reasons.append(f"涨停溢价{avg_premium:.1f}%-10")
        
        # 涨跌结构：涨停>35家且跌停<5家，涨跌比>1.5
        if limit_up_cnt >= 35 and limit_down_cnt < 5:
            market_score += 8
            market_reasons.append(f"结构健康+8")
        elif limit_up_cnt > 0 and limit_down_cnt > 0:
            ratio = limit_up_cnt / max(limit_down_cnt, 1)
            if ratio < 0.8:
                market_score -= 8
                market_reasons.append(f"涨跌比{ratio:.1f}-8")
        
        # 炸板控制：炸板率<30% +7分；>45%已在否决区处理
        total_board = limit_up_cnt + limit_z_cnt
        if total_board > 0:
            break_rate = limit_z_cnt / total_board * 100
            if break_rate < 30:
                market_score += 7
                market_reasons.append(f"炸板率{break_rate:.1f}%+7")
            elif break_rate > 40:
                market_score -= 7
                market_reasons.append(f"炸板率{break_rate:.1f}%-7")
    
    # 连板高度
    if step_data:
        max_height = max([safe_int(x.get('nums', 0)) or 0 for x in step_data], default=0)
        if max_height >= 4:
            market_score += 5
            market_reasons.append(f"最高{max_height}板+5")
        elif max_height >= 3:
            market_score += 3
            market_reasons.append(f"最高{max_height}板+3")
    
    score += max(0, min(30, market_score))
    reasons.extend(market_reasons)
    
    # --- 3.2 主线题材情绪维度 (30分) ---
    theme_score = 0
    theme_reasons = []
    
    if concept_names:
        # 概念数量
        if len(concept_names) >= 8:
            theme_score += 8
            theme_reasons.append(f"{len(concept_names)}概念+8")
        elif len(concept_names) >= 4:
            theme_score += 5
            theme_reasons.append(f"{len(concept_names)}概念+5")
        
        # 热门关键词匹配
        hot_keywords = ["机器人", "AI", "人工智能", "新能源", "芯片", "半导体", "算力", 
                        "低空", "光伏", "储能", "鸿蒙", "华为", "军工", "医药"]
        matched_hot = []
        for name in concept_names:
            for kw in hot_keywords:
                if kw in str(name):
                    matched_hot.append(name)
                    break
        
        if len(matched_hot) >= 3:
            theme_score += 10
            theme_reasons.append(f"热门题材+10")
        elif len(matched_hot) >= 1:
            theme_score += 5
            theme_reasons.append(f"题材{matched_hot[0]}+5")
        
        # 检查概念板块涨停数（使用limit_cpt_list统计数据）
        for name in concept_names[:5]:
            cnt = concept_ul_cnt.get(name, 0)
            if cnt >= 3:
                theme_score += 7
                theme_reasons.append(f"{name}涨停{cnt}只+7")
                break
    
    score += max(0, min(30, theme_score))
    reasons.extend(theme_reasons)
    
    # --- 3.3 板块梯队情绪维度 (20分) ---
    sector_score = 0
    sector_reasons = []
    
    # 检查同板块涨停数（使用limit_cpt_list统计数据）
    if concept_names and concept_ul_cnt:
        max_sector_ul = max([concept_ul_cnt.get(n, 0) for n in concept_names], default=0)
        if max_sector_ul >= 5:
            sector_score += 10
            sector_reasons.append(f"板块涨停{max_sector_ul}只+10")
        elif max_sector_ul >= 3:
            sector_score += 6
            sector_reasons.append(f"板块涨停{max_sector_ul}只+6")
    
    # 连板梯队
    if step_data:
        high_boards = [x for x in step_data if safe_int(x.get('nums', 0)) >= 3]
        if len(high_boards) >= 2:
            sector_score += 4
            sector_reasons.append(f"梯队完整+4")
    
    score += max(0, min(20, sector_score))
    reasons.extend(sector_reasons)
    
    # --- 3.4 个股人气资金情绪维度 (10分) ---
    popular_score = 0
    popular_reasons = []

    # 人气排名：东财/同花顺个股人气榜前50（T+1无实时排名接口，用换手率代理情绪资金博弈热度）
    # 注：换手率是情绪资金活跃度的代理指标，非技术指标。游资活跃标的通常高换手。
    try:
        resp = call_tushare("daily_basic", token, {"ts_code": code}, "turnover_rate")
        daily_basic = resp.get("data", {}).get("items", [])
        if daily_basic:
            turnover = safe_float(daily_basic[0][0]) if daily_basic[0] else None
            if turnover:
                if 10 <= turnover <= 25:
                    popular_score += 2
                    popular_reasons.append(f"换手{turnover:.1f}%情绪活跃+2")
                elif turnover > 25:
                    popular_score -= 2
                    popular_reasons.append(f"换手{turnover:.1f}%过热-2")
    except:
        pass

    # 资金记忆：近20日出现>=2次涨停
    try:
        from datetime import datetime, timedelta
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=25)
        resp = call_tushare("limit_list_d", token, {
                    "ts_code": code,
                    "start_date": start_dt.strftime('%Y%m%d'),
                    "end_date": end_dt.strftime('%Y%m%d')
                }, "trade_date,ts_code,limit")
        hist_ul = resp.get("data", {}).get("items", [])
        ul_cnt_20d = len([x for x in hist_ul if str(x[2]).upper() == 'U']) if hist_ul else 0
        if ul_cnt_20d >= 2:
            popular_score += 3
            popular_reasons.append(f"20日涨停{ul_cnt_20d}次+3")
        elif ul_cnt_20d >= 1:
            popular_score += 1
            popular_reasons.append(f"20日涨停+1")
    except Exception:
        pass

    # 龙虎榜游资买入
    if top_list_data:
        for item in top_list_data[:3]:
            net_rate = safe_float(item.get('net_rate'))
            if net_rate and net_rate > 0:
                popular_score += 2
                popular_reasons.append(f"龙虎榜净买{net_rate:.1f}%+2")
                break

    score += max(0, min(10, popular_score))
    reasons.extend(popular_reasons)

    # --- 3.5 集合竞价情绪动能维度 (15分) ---
    # 基于 stk_auction 接口的开盘竞价数据，衡量开盘前情绪强度
    auction_score = 0
    auction_reasons = []

    try:
        resp = call_tushare("stk_auction", token, {"trade_date": today_str, "ts_code": code}, "ts_code,trade_date,vol,price,amount,pre_close,turnover_rate,volume_ratio,float_share")
        auction_data = resp.get("data", {})
        auction_items = auction_data.get("items", [])
        if auction_items and len(auction_items) > 0:
            item = auction_items[0]
            a_fields = auction_data.get("fields", [])
            a_dict = dict(zip(a_fields, item)) if a_fields else {}

            pre_close = safe_float(a_dict.get('pre_close')) or 0
            price = safe_float(a_dict.get('price')) or 0
            vol = safe_float(a_dict.get('vol')) or 0
            amount = safe_float(a_dict.get('amount')) or 0
            float_share = safe_float(a_dict.get('float_share')) or 0
            volume_ratio = safe_float(a_dict.get('volume_ratio')) or 0

            open_gap = (price - pre_close) / pre_close * 100 if pre_close > 0 else 0
            # CallVolRatio量纲修正(V1.2)：竞价量/昨日成交量（旧版vol/float_share*100已废弃）
            call_vol_ratio = vol / yesterday_vol if yesterday_vol > 0 else 0

            # 1. OpenGap 评分 (5分) × 市场状态乘数(V1.2)
            # 基础跳空评分（震荡态参考值）
            open_gap_base = 0
            if 5 <= open_gap < 8:
                open_gap_base = 5
            elif 3 <= open_gap < 5:
                open_gap_base = 3
            elif 1 <= open_gap < 3:
                open_gap_base = 1
            elif -1 <= open_gap < 1:
                open_gap_base = 0  # 平开
            elif -3 <= open_gap < -1:
                open_gap_base = -2
            elif open_gap < -3:
                open_gap_base = -4
            elif open_gap >= 8:
                open_gap_base = 2  # 大幅高开有冲高回落风险
            
            # 牛市态：加分放大，扣分不变；熊市态：加分缩小，扣分放大×1.5
            if open_gap_base > 0:
                open_gap_score = round(open_gap_base * market_state_multiplier)
            elif open_gap_base < 0:
                # 扣分：牛市不变(×1.0)，熊市放大(×1/multiplier，即÷0.6≈×1.67)
                bear_penalty_factor = 1.0 / market_state_multiplier if market_state_multiplier < 1.0 else 1.0
                bear_penalty_factor = min(bear_penalty_factor, 1.5)  # 最大放大1.5倍
                open_gap_score = round(open_gap_base * bear_penalty_factor)
            else:
                open_gap_score = 0
            
            # 截断规则
            open_gap_score = max(0, min(5, open_gap_score))
            if open_gap_base != 0:
                gap_state_tag = f"[{market_state}态×{market_state_multiplier}]"
                auction_reasons.append(f"竞价跳空{open_gap:.1f}%{gap_state_tag}→{open_gap_score}分")
            auction_score += open_gap_score

            # 2. CallVolRatio 评分 (5分) - 竞价关注度(V1.2量纲修正)
            # 新量纲：竞价量/昨日成交量，实际值范围0.3~5.0
            if call_vol_ratio >= 3.0:  # 竞价量达昨日全天3倍以上
                auction_score += 5
                auction_reasons.append(f"竞价关注度极高(量比{call_vol_ratio:.1f})+5")
            elif call_vol_ratio >= 1.5:  # 竞价量达昨日全天1.5倍
                auction_score += 3
                auction_reasons.append(f"竞价关注度高(量比{call_vol_ratio:.1f})+3")
            elif call_vol_ratio >= 0.5:  # 竞价量达昨日全天半量
                auction_score += 1
                auction_reasons.append(f"竞价关注度较高(量比{call_vol_ratio:.1f})+1")

            # 3. 量比验证 (3分)
            if volume_ratio > 5:
                auction_score += 3
                auction_reasons.append(f"竞价量比{volume_ratio:.1f}+3")
            elif volume_ratio > 3:
                auction_score += 1
                auction_reasons.append(f"竞价量比{volume_ratio:.1f}+1")

            # 4. 竞价成交额 (2分)
            if amount >= 5000000:  # 500万
                auction_score += 2
                auction_reasons.append(f"竞价成交{amount/10000:.0f}万+2")
            elif amount >= 1000000:  # 100万
                auction_score += 1
                auction_reasons.append(f"竞价成交{amount/10000:.0f}万+1")
    except Exception:
        pass

    score += max(0, min(15, auction_score))
    reasons.extend(auction_reasons[:3])  # V1.2：竞价reason只取前3条，避免reason列表过长
    
    # ===== 4. 综合评定 =====
    final_score = max(0, min(100, score))
    
    if final_score >= 75:
        level = "高"
    elif final_score >= 55:
        level = "中"
    elif final_score >= 35:
        level = "低"
    else:
        level = "无"
    
    # V1.2：截断从[:5]改为[:8]，确保5个维度都能展示关键reason
    # 市场状态标签（牛市态/熊市态）在竞价维度reason中，[:5]截断会隐藏竞价维度
    reason_str = f"[{level}] " + "; ".join(reasons[:8]) if reasons else f"[{level}] 无明显信号"
    
    return final_score, reason_str

# ===== 6. 飞书推送 =====
def push_feishu(results):
    """发送飞书卡片"""
    import requests
    
    # 获取token
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": CONFIG["FEISHU_APP_ID"],
            "app_secret": CONFIG["FEISHU_APP_SECRET"]
        }
    )
    _feishu_resp = resp.json()
    token = _feishu_resp.get("tenant_access_token")
    
    if not token:
        print("飞书token获取失败")
        return False
    
    # 构建卡片
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🎯 涨停预测信号 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"},
            "template": "blue"
        },
        "elements": []
    }
    
    for r in results[:10]:  # 只推送前10
        element = {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{r['code']} {r['name']}** | 综合: **{r['total']:.1f}**\n基本面:{r['scores']['fundamental']} | 技术面:{r['scores']['technical']} | 资金面:{r['scores']['fundflow']} | 情绪面:{r['scores']['sentiment']}"
            }
        }
        card["elements"].append(element)
    
    # 发送
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "receive_id": CONFIG["FEISHU_CHAT_ID_SIGNAL"],
            "msg_type": "interactive",
            "content": json.dumps(card)
        }
    )
    
    result = resp.json()
    if result.get("code") == 0:
        print(f"飞书推送成功: {result['data']['message_id']}")
        return True
    else:
        print(f"飞书推送失败: {result}")
        return False

# ===== 主流程 =====
def main():
    parser = argparse.ArgumentParser(description="涨停预测流程")
    parser.add_argument("--from-file", help="从已有信号文件加载", default=None)
    parser.add_argument("--top", type=int, default=50, help="分析前N只股票（默认50，覆盖全部候选股）")
    args = parser.parse_args()
    
    clear_tushare_cache()  # 每次流水线启动清空API缓存
    
    print("=" * 50)
    print(f"涨停预测流程启动: {datetime.now()}")
    print("=" * 50)
    
    # 1. 获取候选股
    if args.from_file:
        candidates = load_from_file(args.from_file)
    else:
        print("\n[1/5] 扫描涨速数据...")
        candidates = scan_surge()
    
    if not candidates:
        print("无候选股，退出")
        return
    
    # 取前N只做分析
    candidates = candidates[:args.top]
    print(f"分析候选股: {[c['code'] for c in candidates]}")
    
    # 1.5 全系统过滤
    print("\n[1.5/5] 全系统过滤...")
    candidates = filter_candidates(candidates)
    if not candidates:
        print("过滤后无候选股，退出")
        return
    
    # 2-5. 四维度评分
    results = []
    for stock in candidates:
        code = stock["code"]
        name = stock["name"]
        print(f"\n[分析] {code} {name}")
        
        print("  四维度并行评分...", flush=True)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        scoring_funcs = {
            "fundamental": score_fundamental,
            "technical": score_technical,
            "fundflow": score_fundflow,
            "sentiment": score_sentiment,
        }
        scores = {}
        reasons = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fn, code): dim for dim, fn in scoring_funcs.items()}
            for future in as_completed(futures):
                dim = futures[future]
                try:
                    s, r = future.result()
                    scores[dim] = s
                    reasons[dim] = r
                    print(f"    {dim}: {s}")
                except Exception as e:
                    scores[dim] = 0
                    reasons[dim] = f"评分异常: {e}"
                    print(f"    {dim}: 异常 {e}")
        
        f_score = scores.get("fundamental", 0)
        t_score = scores.get("technical", 0)
        m_score = scores.get("fundflow", 0)
        s_score = scores.get("sentiment", 0)
        f_reason = reasons.get("fundamental", "")
        t_reason = reasons.get("technical", "")
        m_reason = reasons.get("fundflow", "")
        s_reason = reasons.get("sentiment", "")
        
        # 加权综合评分
        weights = AGENT_WEIGHTS
        total = (f_score * weights["fundamental"] + 
                 t_score * weights["technical"] + 
                 m_score * weights["fundflow"] + 
                 s_score * weights["sentiment"]) / sum(weights.values())
        
        # 多维度共振判定（≥3个维度得分≥权重70%）
        # 维度满分映射：基本面100→70, 技术面100→70, 资金面100→70, 情绪面100→70
        resonance_threshold = 75  # 全系统统一评级阈值：75/55/35
        resonance_count = sum([
            f_score >= resonance_threshold,
            t_score >= resonance_threshold,
            m_score >= resonance_threshold,
            s_score >= resonance_threshold
        ])
        resonance_flag = resonance_count >= 3
        
        # 记录权重信息（用于调试和复盘）
        weight_info = {k: f"{v:.1f}" for k, v in weights.items()}
        
        results.append({
            "code": code,
            "name": name,
            "scores": {
                "fundamental": f_score,
                "technical": t_score,
                "fundflow": m_score,
                "sentiment": s_score
            },
            "reasons": {
                "fundamental": f_reason,
                "technical": t_reason,
                "fundflow": m_reason,
                "sentiment": s_reason
            },
            "weights": weight_info,
            "total": total,
            "resonance": {
                "count": resonance_count,
                "threshold": resonance_threshold,
                "is_resonance": resonance_flag
            }
        })
    
    # 排序
    results.sort(key=lambda x: x["total"], reverse=True)
    
    print("\n[排序结果]")
    for i, r in enumerate(results, 1):
        resonance_tag = " [共振]" if r.get("resonance", {}).get("is_resonance") else ""
        print(f"  {i}. {r['code']} {r['name']} - 综合:{r['total']:.1f}{resonance_tag}")
    
    # 保存结果
    output_dir = PROJECT_DIR / "data" / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_file}")
    
    # 6. 飞书推送
    print("\n[飞书推送]...")
    push_feishu(results)
    
    print("\n" + "=" * 50)
    print("流程完成!")
    print("=" * 50)

if __name__ == "__main__":
    main()
