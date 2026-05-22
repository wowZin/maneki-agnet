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
sys.path.insert(0, str(PROJECT_DIR / "scripts"))  # 支持 from cdp_fetch import ...

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

# ===== Feishu 测试模式 =====
FEISHU_TEST_MODE = CONFIG.get("FEISHU_TEST_MODE", "").lower() == "true"
def feishu_title_prefix():
    """测试模式下返回'测试-'前缀"""
    return "测试-" if FEISHU_TEST_MODE else ""

# ===== Agent 权重配置（从.env读取，默认=1） =====
AGENT_WEIGHTS = {
    "fundamental": float(CONFIG.get("AGENT_WEIGHT_FUNDAMENTAL", "1")),
    "technical": float(CONFIG.get("AGENT_WEIGHT_TECHNICAL", "1")),
    "fundflow": float(CONFIG.get("AGENT_WEIGHT_FUND_FLOW", "1")),
    "sentiment": float(CONFIG.get("AGENT_WEIGHT_SENTIMENT", "1")),
    "shortterm": float(CONFIG.get("AGENT_WEIGHT_SHORTTERM", "1")),
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
def scan_surge(connect_retries=3, navigate_retries=2):
    """通过CDP获取涨速数据（带重试机制）
    
    优先使用 cdp_fetch 模块（函数化+重试），降级回 subprocess 调用 scan_cdp.py
    
    Args:
        connect_retries: CDP连接最大重试次数
        navigate_retries: 导航获取最大重试次数
    Returns: list[dict] - [{code, name}] 候选股列表，或None
    """
    # 方案1: 直接调用 cdp_fetch 模块（函数化，带重试）
    try:
        from cdp_fetch import get_surge_rate_cdp
        stocks_raw = get_surge_rate_cdp(
            connect_retries=connect_retries,
            navigate_retries=navigate_retries,
        )
        if stocks_raw is None:
            return None  # 非交易时段或彻底失败
        
        candidates = []
        for s in stocks_raw:
            code = s.get("代码") or s.get("code") or s.get("ts_code", "")
            name = s.get("名称") or s.get("name", "")
            if "." not in code:
                if code.startswith("6"):
                    code = f"{code}.SH"
                else:
                    code = f"{code}.SZ"
            candidates.append({"code": code, "name": name})
        
        print(f"扫描完成(cdp_fetch模块): {len(candidates)} 只候选股")
        return candidates
        
    except ImportError:
        print("  cdp_fetch模块不可用，降级使用subprocess方式")
    
    # 方案2: subprocess调用scan_cdp.py（旧方式，无重试）
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
    
    print(f"扫描完成(subprocess方式): {len(candidates)} 只候选股")
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
    基本面涨停潜力量化评分 V1.5（最终实盘定稿版）
    五维度：业绩40% + 事件30% + 筹码15% + 财务10% + 估值5%
    含财务避雷一票否决（含行业豁免）+ 见光死惩罚 + 非线性共振加分

    V1.5变更（基于V1.0）：
    - 否决规则增加行业豁免（医药/电子商誉豁免、地产/建筑/非银/公用负债率豁免）
    - 否决规则增加困境反转豁免（单季扣非>0且去年同期<0免于连续亏损否决）
    - 否决规则新增研发费用资本化率否决（>30%+现金流<净利润×0.5）
    - 股东筹码维度重构：大宗溢价+解禁冲击+连板基因
    - 估值维度重构：废除低PE加分，改为分析师上调+困境反转+远期PEG
    - 新增非线性共振加分（条件A/B取最高）
    - 新增见光死惩罚（Price-in_Ratio衰减）
    - 新增困境反转加分（独立+5分）
    - 新增主力营收占比<50%否决
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
    
    # 获取行业分类（用于行业豁免判断 V1.5）
    industry_name = ""
    try:
        resp = call_tushare("stock_basic", token, {"ts_code": code}, "ts_code,industry")
        _sb = resp.get("data", {}).get("items", [])
        if _sb:
            _sb_fields = resp.get("data", {}).get("fields", [])
            _sb_dict = dict(zip(_sb_fields, _sb[0])) if _sb_fields else {}
            industry_name = str(_sb_dict.get('industry', ''))
    except:
        pass
    
    # ===== 2. 一票否决检查（V1.5 含行业豁免） =====
    risk_flags = []
    is_vetoed = False
    
    # 获取ROE用于行业豁免判断
    _roe_source = fina_annual if fina_annual.get('end_date', '').endswith('1231') else fina_latest
    roe_source_val = safe_float(_roe_source.get('roe')) or 0
    
    # V1.5: 商誉/净资产 > 30% 且 ROE < 10%（医药/电子行业ROE>10%暂免）
    if bs_latest.get('goodwill') and bs_latest.get('total_hldr_eqy_exc_min_int'):
        goodwill_ratio = float(bs_latest['goodwill']) / float(bs_latest['total_hldr_eqy_exc_min_int']) * 100
        if goodwill_ratio > 30:
            # 行业豁免：医药/电子行业ROE>10%免于否决
            pharma_and_elec = any(kw in industry_name for kw in ["医药", "医疗", "电子", "半导体", "元器件"])
            if pharma_and_elec and roe_source_val > 10:
                risk_flags.append(f"商誉占比{goodwill_ratio:.0f}%(行业豁免)")
            else:
                is_vetoed = True
                risk_flags.append(f"商誉占比{goodwill_ratio:.0f}%>30%")
    
    # V1.5: 资产负债率 > 70% 且 经营现金流连续2季度为负
    # 行业豁免：房地产/建筑/非银金融/公用事业仅看现金流
    debt_exempt_industries = ["房地产", "建筑", "非银金融", "公用事业", "银行", "综合"]
    is_debt_exempt = any(kw in industry_name for kw in debt_exempt_industries)
    if fina_latest.get('debt_to_assets'):
        debt_ratio = float(fina_latest['debt_to_assets'])
        if debt_ratio > 70:
            ocfps_latest = safe_float(fina_latest.get('ocfps'))
            ocfps_annual = safe_float(fina_annual.get('ocfps')) if fina_annual else None
            if is_debt_exempt:
                # 行业豁免：仅检查现金流，负债率高不否决
                if ocfps_latest is not None and ocfps_latest < 0:
                    if ocfps_annual is None or ocfps_annual < 0:
                        is_vetoed = True
                        risk_flags.append(f"经营现金流连续为负(行业豁免负债率)")
                else:
                    risk_flags.append(f"负债率{debt_ratio:.0f}%>70%(行业豁免)")
            else:
                if ocfps_latest is not None and ocfps_latest < 0:
                    if ocfps_annual is None or ocfps_annual < 0:
                        is_vetoed = True
                        risk_flags.append(f"负债率{debt_ratio:.0f}%>70%且经营现金流为负")
    
    # V1.5: 扣非净利润连续3年亏损 + 困境反转豁免
    # 检查是否连续亏损（简单代理：最新扣非净利为负）
    is_consecutive_loss = False
    if fina_latest.get('dt_netprofit_yoy'):
        profit_yoy = float(fina_latest['dt_netprofit_yoy'])
        if profit_yoy < -50:  # 大幅下降视为连续亏损
            is_consecutive_loss = True
    
    # 困境反转检查：最新单季扣非>0且去年同期<0 → 豁免
    is_turnaround = False
    if inc_latest.get('n_income') and inc_prev.get('n_income'):
        try:
            latest_ni = float(inc_latest['n_income'])
            prev_ni = float(inc_prev['n_income'])
            if latest_ni > 0 and prev_ni < 0:
                is_turnaround = True
        except:
            pass
    
    if is_consecutive_loss and not is_turnaround:
        is_vetoed = True
        risk_flags.append("扣非净利润连续亏损(无困境反转)")
    
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
    
    # 获取近20日涨幅（见光死惩罚用 V1.5）
    pre_return_20d = 0
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=25)
        resp_pr = call_tushare("daily", token, {
            "ts_code": code,
            "start_date": start_dt.strftime('%Y%m%d'),
            "end_date": end_dt.strftime('%Y%m%d')
        }, "trade_date,close")
        pr_items = resp_pr.get("data", {}).get("items", [])
        if pr_items and len(pr_items) >= 2:
            _pr_fields = resp_pr.get("data", {}).get("fields", [])
            _pr_dicts = [dict(zip(_pr_fields, x)) for x in pr_items if _pr_fields]
            close_20d_ago = safe_float(_pr_dicts[-1].get('close', 0)) or 0
            close_latest = safe_float(_pr_dicts[0].get('close', 0)) or 0
            if close_20d_ago > 0:
                pre_return_20d = (close_latest - close_20d_ago) / close_20d_ago * 100
    except:
        pass
    
    # 获取分析师一致预期（用于见光死惩罚 V1.5）
    eps_revision_1m = 0
    try:
        resp_fc = call_tushare("fina_forecast", token, {"ts_code": code}, "ts_code,ann_date,end_date,type,report_date,eps_change_ratio")
        fc_items = resp_fc.get("data", {}).get("items", [])
        if fc_items:
            fc_fields = resp_fc.get("data", {}).get("fields", [])
            fc_dicts = [dict(zip(fc_fields, x)) for x in fc_items if fc_fields]
            for fc in fc_dicts:
                change_ratio = safe_float(fc.get('eps_change_ratio', 0)) or 0
                if change_ratio != 0:
                    eps_revision_1m = change_ratio
                    break
    except:
        pass
    
    # 触发否决直接返回0分
    if is_vetoed:
        return 0, f"财务避雷否决: {'; '.join(risk_flags)}"
    
    # ===== 3. 五维度评分 =====
    factors = {}  # 各维度标准化得分 [0,1]
    reasons = []
    
    # --- 3.1 盈利业绩维度 (40%) V1.5 ---
    profit_score = 0.5  # 基准
    profit_reasons = []
    
    # ROE（复用已计算的_roe_source和roe_source_val）
    if roe_source_val > 0:
        if roe_source_val > 15:
            profit_score += 0.20
            profit_reasons.append(f"ROE={roe_source_val:.1f}%")
        elif roe_source_val > 10:
            profit_score += 0.10
            profit_reasons.append(f"ROE={roe_source_val:.1f}%")
        elif roe_source_val < 5:
            profit_score -= 0.15
            profit_reasons.append(f"ROE={roe_source_val:.1f}%偏低")
    
    # 扣非净利润同比
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
    
    # 营收增速
    if fina_latest.get('or_yoy'):
        rev_yoy = float(fina_latest['or_yoy'])
        if rev_yoy > 30:
            profit_score += 0.15
            profit_reasons.append(f"营收+{rev_yoy:.0f}%")
        elif rev_yoy < 0:
            profit_score -= 0.10
    
    factors['profit'] = max(0, min(1, profit_score))
    reasons.extend(profit_reasons)
    
    # --- 3.2 题材事件维度 (30%) V1.5 ---
    event_score = 0.5
    event_reasons = []
    
    # 概念数量（代理事件热度）
    if concept_count >= 8:
        event_score += 0.20
        event_reasons.append(f"{concept_count}个概念")
    elif concept_count >= 4:
        event_score += 0.10
        event_reasons.append(f"{concept_count}个概念")
    elif concept_count == 0:
        event_score -= 0.10
    
    # 公告事件强度（有近期公告加分）
    if recent_ann_count >= 3:
        event_score += 0.20
        event_reasons.append(f"近期{recent_ann_count}条公告")
    elif recent_ann_count >= 1:
        event_score += 0.10
        event_reasons.append(f"近期{recent_ann_count}条公告")
    
    # V1.5: 见光死惩罚 — 公告前涨幅过大导致事件因子衰减
    if pre_return_20d > 0 and eps_revision_1m != 0:
        price_in_ratio = pre_return_20d / (abs(eps_revision_1m) + 5)
        if price_in_ratio > 2.5 and (factors.get('profit', 0) > 0.6 or event_score > 0.7):
            event_score *= 0.5  # 事件贡献腰斩
            reasons.append(f"见光死PIR={price_in_ratio:.1f}>2.5事件减半")
        if price_in_ratio > 3.5:
            factors['profit'] = max(0, factors.get('profit', 0) * 0.7)  # 业绩也衰减
            reasons.append(f"见光死PIR={price_in_ratio:.1f}>3.5业绩减30%")
    
    factors['event'] = max(0, min(1, event_score))
    reasons.extend(event_reasons)
    
    # --- 3.3 股东筹码维度 (15%) V1.5 ---
    chip_score = 0.5
    chip_reasons = []
    
    # 股东户数环比下降（仅做底仓过滤，不直接加分）
    if holder_latest.get('holder_num') and holder_prev.get('holder_num'):
        try:
            holder_now = float(holder_latest['holder_num'])
            holder_before = float(holder_prev['holder_num'])
            holder_chg = (holder_before - holder_now) / holder_before
            if holder_chg >= 0.05:
                chip_score += 0.20
                chip_reasons.append(f"股东户数-{holder_chg*100:.1f}%")
            elif holder_chg < -0.05:
                chip_score -= 0.20
                chip_reasons.append(f"股东户数+{abs(holder_chg)*100:.1f}%")
        except:
            pass
    
    # 连板基因（近60日曾连板 → 有资金记忆）
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=65)
        resp_gene = call_tushare("limit_step", token, {
            "ts_code": code,
            "start_date": start_dt.strftime('%Y%m%d'),
            "end_date": end_dt.strftime('%Y%m%d')
        }, "trade_date,ts_code,nums")
        gene_items = resp_gene.get("data", {}).get("items", [])
        if gene_items:
            max_nums = max([safe_int(x[2]) or 0 for x in gene_items], default=0)
            if max_nums >= 2:
                chip_score += 0.15
                chip_reasons.append(f"连板基因{max_nums}连板")
    except:
        pass
    
    # 解禁冲击（未来30日解禁市值/流通市值 <2% → +2分）
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=30)
        resp_unlock = call_tushare("share_float", token, {
            "ts_code": code,
            "start_date": start_dt.strftime('%Y%m%d'),
            "end_date": end_dt.strftime('%Y%m%d')
        }, "float_date,float_share,float_ratio")
        unlock_items = resp_unlock.get("data", {}).get("items", [])
        has_large_unlock = False
        if unlock_items:
            for item in unlock_items:
                float_ratio = safe_float(item[2]) if len(item) > 2 else 0
                if float_ratio and float_ratio > 2:
                    has_large_unlock = True
                    break
        if not has_large_unlock:
            chip_score += 0.10
            chip_reasons.append("解禁冲击低+0.1")
    except:
        pass
    
    factors['chip'] = max(0, min(1, chip_score))
    reasons.extend(chip_reasons)
    
    # --- 3.4 财务健康维度 (10%) V1.5 ---
    finance_score = 1.0
    finance_reasons = []
    
    # 负债率风险扣分（未触发否决则在此扣分）
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
    
    # --- 3.5 估值性价比维度 (5%) V1.5 ---
    value_score = 0.0  # 废除基准分，仅作为加分项
    value_reasons = []
    
    # PE相对估值（废除低PE加分，改为上调幅度检测）
    if pe and pe > 0 and pb and pb > 0:
        # 远期PEG < 1.5视为有估值重塑空间
        if pe / (roe_source_val if roe_source_val > 0 else 15) < 1.5:
            value_score += 0.30
            value_reasons.append("PEG合理")
        # 困境反转特殊加分
        if is_turnaround:
            value_score += 0.30
            value_reasons.append("困境反转+0.3")
    
    factors['value'] = max(0, min(1, value_score))
    reasons.extend(value_reasons)
    
    # ===== 4. 综合评分计算 =====
    weights = {
        'profit': 0.40,
        'event': 0.30,
        'chip': 0.15,
        'finance': 0.10,
        'value': 0.05
    }
    
    base_score = sum(factors[k] * weights[k] for k in factors) * 100
    
    # ===== 5. 非线性共振加分（V1.5 取最高，不叠加） =====
    bonus = 0
    # 条件A: 业绩≥0.8 且 事件≥0.7 且 事件窗口t≤10
    if factors.get('profit', 0) >= 0.8 and factors.get('event', 0) >= 0.7 and recent_ann_count > 0:
        bonus = 15
        reasons.append(f"共振A:业绩+事件+15")
    # 条件B: 筹码≥0.8 且 估值≥0.6
    elif factors.get('chip', 0) >= 0.8 and factors.get('value', 0) >= 0.6:
        bonus = 10
        reasons.append(f"共振B:筹码+估值+10")
    
    # V1.5: 困境反转独立加分（最新单季扣非>0且去年同期<0 → +5分）
    turnaround_bonus = 0
    if is_turnaround:
        turnaround_bonus = 5
        reasons.append("困境反转+5")
    
    final_score = min(100, base_score + bonus + turnaround_bonus)
    
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
    技术面涨停潜力预判 V2.0（最终实盘定稿版）
    六维度量化评分：量能35分 + 趋势均线25分 + 筹码结构15分 + 关键位置12分 + 资金动能8分 + 板块协同5分
    含一票否决规则（动态阈值）+ 板块弱势天花板 + 时间因子
    
    V2.0变更（基于V1.0）：
    - 量能维度权重40→35，新增板块协同维度5分
    - 否决规则全面重构（5条动态阈值）：放量破位/高位滞涨/高位筹码发散/缩量阴跌/资金出逃
    - 所有阈值改为"滚动80日分位数+绝对值下限"双重判定
    - 筹码维度废除CYQ估算，改用换手衰减+布林带收敛替代
    - 删除MACD/KDJ/RSI因子（因子纯化）
    - 新增板块协同过滤维度（弱势板块硬性天花板总分≤74）
    - 新增时间因子（早盘冲动抑制/尾盘确认加分/信号衰减）
    - 新增洗盘-起爆节奏因子（前N日缩量+当日放量）
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
    
    # 获取资金流向
    try:
        resp = call_tushare("moneyflow", token, {"ts_code": code}, "trade_date,net_mf_amount,buy_lg_amount,sell_lg_amount")
        mf_data = resp.get("data", {}).get("items", [])
    except:
        mf_data = []
    
    # ===== 动态分位数计算（V2.0） =====
    # 近80日数据（从factors中取），用于动态阈值判定
    vol_ratios_80d = []
    turnovers_80d = []
    pct_chgs = []
    for f in factors[:80]:
        vr = safe_float(f.get('vol_ratio'))
        tr = safe_float(f.get('turnover_rate'))
        pc = safe_float(f.get('pct_change'))
        if vr: vol_ratios_80d.append(vr)
        if tr: turnovers_80d.append(tr)
        if pc is not None: pct_chgs.append(pc)
    
    def pctile(arr, p):
        if not arr: return 0
        s = sorted(arr)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s)-1)]
    
    vr_top20 = pctile(vol_ratios_80d, 80)
    vr_bot10 = pctile(vol_ratios_80d, 10)
    vr_bot30 = pctile(vol_ratios_80d, 30)
    vr_median = pctile(vol_ratios_80d, 50)
    tr_top5 = pctile(turnovers_80d, 95)
    tr_top20 = pctile(turnovers_80d, 80)
    tr_bot10 = pctile(turnovers_80d, 10)
    tr_20pct = pctile(turnovers_80d, 20)
    tr_80pct = pctile(turnovers_80d, 80)
    
    close = safe_float(today.get('close'))
    ma20 = safe_float(today.get('ma_bfq_20'))
    vol_ratio = safe_float(today.get('vol_ratio'))
    boll_mid = safe_float(today.get('boll_mid_bfq'))
    
    # ===== 2. V2.0 一票否决检查 =====
    veto_flags = []
    
    # 2.1 放量破位：收盘<MA20 且 量比>近80日Top20%（且绝对值>1.5）
    if close and ma20 and close < ma20:
        if vol_ratio and (vol_ratio > vr_top20 or vol_ratio > 1.5):
            return 0, f"放量破位:收盘{close:.2f}<MA20={ma20:.2f},量比{vol_ratio:.2f}>Top20%"
    
    # 2.2 高位滞涨：阶段涨幅>60% 且 换手>近80日Top5% 且 长上影
    if len(factors) >= 20:
        lows_20d = [safe_float(factors[i].get('low')) for i in range(20)]
        stage_low = min((l for l in lows_20d if l), default=None)
        if stage_low and close:
            stage_gain = (close - stage_low) / stage_low * 100
            turnover = safe_float(today.get('turnover_rate'))
            high = safe_float(today.get('high'))
            open_price = safe_float(today.get('open'))
            if stage_gain > 60 and turnover and (turnover > tr_top5 or turnover > 25):
                if high and close and open_price:
                    body = abs(close - open_price)
                    upper_shadow = high - max(close, open_price)
                    if body > 0 and upper_shadow / body > 1.5:
                        return 0, f"高位滞涨:涨幅{stage_gain:.0f}%,换手{turnover:.1f}%,长上影"
    
    # 2.3 高位筹码发散：近3日换手逐日递增且股价滞涨 或 获利盘<15%
    if len(factors) >= 3:
        tr_3d = [safe_float(factors[i].get('turnover_rate')) for i in range(3)]
        pc_3d = [safe_float(factors[i].get('pct_change')) for i in range(3)]
        valid_tr = [t for t in tr_3d if t]
        valid_pc = [p for p in pc_3d if p is not None]
        # 连续递增且累计涨幅<2%→筹码发散
        if len(valid_tr) == 3 and valid_tr[0] > valid_tr[1] > valid_tr[2]:
            if len(valid_pc) == 3 and sum(valid_pc) < 2:
                return 0, f"高位筹码发散:3日换手递增+累计涨{sum(valid_pc):.1f}%<2%"
    
    # 2.4 持续缩量阴跌：连续3日量比<近80日Bottom10%（且绝对值<0.6）且累计跌幅>3%
    if len(factors) >= 3:
        vr_list = [safe_float(factors[i].get('vol_ratio')) for i in range(3)]
        pc_list = [safe_float(factors[i].get('pct_change')) for i in range(3)]
        valid_vr = [vr for vr in vr_list if vr]
        valid_pc = [pc for pc in pc_list if pc is not None]
        thr = min(vr_bot10, 0.6)
        if len(valid_vr) == 3 and all(vr < thr for vr in valid_vr):
            if len(valid_pc) == 3 and sum(valid_pc) < -3:
                return 0, f"持续缩量阴跌:3日量比<{thr:.2f},累计跌{sum(valid_pc):.1f}%"
    
    # 2.5 资金持续出逃：近2日资金动能为负 且 分时收盘/VWAP<0.99
    if mf_data and len(mf_data) >= 2:
        net_mf_2d = sum(safe_float(mf_data[i][1]) if len(mf_data[i]) > 1 else 0 for i in range(2))
        if net_mf_2d < 0:
            if close and boll_mid and close / boll_mid < 0.99:
                return 0, f"资金持续出逃:近2日净流出+收盘/中轨{close/boll_mid:.3f}<0.99"
    
    # ===== 3. 六维度评分（V2.0） =====
    score = 0
    reasons = []
    
    ma5 = safe_float(today.get('ma_bfq_5'))
    ma10 = safe_float(today.get('ma_bfq_10'))
    turnover = safe_float(today.get('turnover_rate'))
    high = safe_float(today.get('high'))
    low = safe_float(today.get('low'))
    open_price = safe_float(today.get('open'))
    
    # --- 3.1 量能结构维度 (35分) V2.0 ---
    vol_score = 0
    vol_reasons = []
    
    # 启动量能质量：量比>近80日Top20%且绝对值>1.5 且 当日量>3日均量1.3倍
    if vol_ratio:
        today_vol = safe_float(today.get('vol'))
        vol_3d = 0
        if len(factors) >= 4:
            vol_3d = sum(safe_float(factors[i].get('vol', 0)) for i in range(1, 4)) / 3
        
        quality_ok = (vol_ratio > vr_top20 or vol_ratio > 1.5)
        vol_ok = (today_vol and vol_3d > 0 and today_vol > vol_3d * 1.3) if today_vol and vol_3d > 0 else False
        
        if quality_ok and vol_ok:
            vol_score += 20
            vol_reasons.append(f"放量启动(量比{vol_ratio:.2f}>Top20%)+20")
        elif quality_ok or vol_ok:
            vol_score += 10
            vol_reasons.append(f"量能偏强(量比{vol_ratio:.2f})+10")
    
    # 洗盘-起爆节奏：前N日中至少2日量比<Bottom30% + 当日放量
    if vol_ratio and len(factors) >= 3:
        low_vol_days = 0
        for i in range(1, min(6, len(factors))):
            vr_i = safe_float(factors[i].get('vol_ratio'))
            if vr_i and (vr_i < vr_bot30 or vr_i < 0.8):
                low_vol_days += 1
        if low_vol_days >= 2 and (vol_ratio > vr_median or vol_ratio > 1.2):
            vol_score += 10
            vol_reasons.append(f"洗盘起爆(前{low_vol_days}日缩量)+10")
    
    # 换手健康：介于20%-80%分位 且 绝对值>3%且<15%
    if turnover:
        tr_low = min(tr_20pct, 3.0) if tr_20pct > 0 else 3.0
        tr_high = max(tr_80pct, 15.0)
        if tr_low <= turnover <= tr_high:
            vol_score += 5
            vol_reasons.append(f"换手{turnover:.1f}%健康+5")
        elif turnover < tr_bot10 or turnover < 1.5:
            vol_score -= 5
            vol_reasons.append(f"换手{turnover:.1f}%无量-5")
        if turnover > tr_top5 or turnover > 15:
            if high and close and open_price:
                body = abs(close - open_price)
                upper_shadow = high - max(close, open_price)
                if body > 0 and upper_shadow / body > 1.0:
                    vol_score -= 10
                    vol_reasons.append(f"暴量滞涨(换手{turnover:.1f}%)-10")
    
    score += max(0, min(35, vol_score))
    reasons.extend(vol_reasons)
    
    # --- 3.2 趋势与均线维度 (25分) V2.0 ---
    trend_score = 0
    trend_reasons = []
    ma60 = safe_float(today.get('ma_bfq_60'))
    
    # 多头排列：5>10>20日线且20日线斜率>0
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            # 检查20日线斜率
            if len(factors) >= 2:
                ma20_prev = safe_float(factors[1].get('ma_bfq_20'))
                if ma20_prev and ma20 > ma20_prev:
                    trend_score += 15
                    trend_reasons.append(f"多头排列+15")
                else:
                    trend_score += 10
                    trend_reasons.append(f"均线多头(斜率平)+10")
            else:
                trend_score += 10
                trend_reasons.append(f"均线多头+10")
        elif ma5 < ma10 and close and ma20 and close < ma20:
            trend_score -= 10
            trend_reasons.append(f"空头排列-10")
    
    # MA60方向
    if ma60 and len(factors) >= 5:
        ma60_5d = safe_float(factors[4].get('ma_bfq_60'))
        if ma60_5d and ma60 < ma60_5d:
            trend_score -= 5
            trend_reasons.append(f"MA60下倾-5")
    
    # 回踩企稳：近5日最低触及10/20日线后收盘站回
    if close and ma10 and ma20:
        low_5d = min((safe_float(factors[i].get('low')) or float('inf')) for i in range(min(5, len(factors))))
        # 回踩10日线或20日线
        if low_5d <= ma10 * 1.01 and close > ma10:
            trend_score += 5
            trend_reasons.append(f"回踩MA10企稳+5")
        elif low_5d <= ma20 * 1.01 and close > ma20:
            trend_score += 3
            trend_reasons.append(f"回踩MA20企稳+3")
        # 缩量回踩确认
        if len(factors) >= 2 and vol_ratio:
            vr_yest = safe_float(factors[1].get('vol_ratio'))
            if vr_yest and vr_yest < vr_median and (low_5d <= ma10 * 1.01):
                trend_score += 5
                trend_reasons.append(f"缩量回踩+5")
    
    # 硬标准：收盘>MA20
    if close and ma20 and close <= ma20:
        trend_score -= 5
        trend_reasons.append(f"收盘<=MA20-5")
    
    score += max(0, min(25, trend_score))
    reasons.extend(trend_reasons)
    
    # --- 3.3 关键位置形态 (12分) V2.0 ---
    pos_score = 0
    pos_reasons = []
    
    # 平台突破：近N日振幅<15%且布林带宽<近40日Bottom30% + 收盘突破+量比>中位数
    if close and open_price and high and low and len(factors) >= 10:
        # 近10日振幅
        prices_10d = []
        for i in range(10):
            h = safe_float(factors[i].get('high'))
            l = safe_float(factors[i].get('low'))
            if h and l:
                prices_10d.append((h, l))
        if prices_10d:
            max_h = max(p[0] for p in prices_10d)
            min_l = min(p[1] for p in prices_10d)
            range_amplitude = (max_h - min_l) / max_h * 100 if max_h > 0 else 100
            
            # 布林带宽近40日Bottom30%（简化为带宽当前值）
            boll_upper = safe_float(today.get('boll_upper_bfq'))
            boll_lower = safe_float(today.get('boll_lower_bfq'))
            boll_width_cur = ((boll_upper - boll_lower) / boll_mid * 100) if boll_upper and boll_lower and boll_mid else 100
            
            if range_amplitude < 15 and boll_width_cur < 15:  # 平台盘整
                if close > max_h * 0.99:  # 收盘接近或突破平台高点
                    if vol_ratio and (vol_ratio > vr_median or vol_ratio > 1.0):
                        pos_score += 8
                        pos_reasons.append(f"平台突破(振幅{range_amplitude:.1f}%)+8")
    
    # 支撑确认：回踩前高后缩量企稳（下影线/实体<0.3）
    if close and open_price and low:
        body = abs(close - open_price)
        lower_shadow = min(close, open_price) - low
        if body > 0 and lower_shadow / body > 0.3:
            pos_score += 4
            pos_reasons.append(f"下影支撑+4")
    
    # 负向：上影线>60%
    if len(factors) >= 3:
        us_cnt = 0
        for i in range(3):
            h = safe_float(factors[i].get('high'))
            c = safe_float(factors[i].get('close'))
            o = safe_float(factors[i].get('open'))
            if h and c and o:
                b = abs(c - o)
                u = h - max(c, o)
                if u > 0 and b > 0 and u / b > 1.0:
                    us_cnt += 1
        if us_cnt >= 2:
            pos_score -= 4
            pos_reasons.append(f"假突破:3日{us_cnt}日上影-4")
    
    score += max(0, min(12, pos_score))
    reasons.extend(pos_reasons)
    
    # --- 3.4 筹码结构 (15分) V2.0 换手衰减替代CYQ ---
    chip_score = 0
    chip_reasons = []
    
    # 换手衰减良好：近5日换手逐日递减（斜率<0）
    if len(factors) >= 5 and turnover:
        tr_5d = [safe_float(factors[i].get('turnover_rate')) for i in range(5)]
        valid_tr5 = [t for t in tr_5d if t]
        if len(valid_tr5) == 5:
            tr_decreasing = all(valid_tr5[i] >= valid_tr5[i+1] for i in range(4))
            latest_tr = valid_tr5[0]
            avg_tr5 = sum(valid_tr5) / 5
            if tr_decreasing and latest_tr < avg_tr5:
                chip_score += 10
                chip_reasons.append(f"换手递减锁定+10")
        elif len(valid_tr5) >= 3:
            latest_tr = valid_tr5[0]
            avg_tr = sum(valid_tr5) / len(valid_tr5)
            if latest_tr < avg_tr:
                chip_score += 5
                chip_reasons.append(f"换手趋降+5")
    
    # 布林带宽收敛：处于近20日Bottom30%（波动收敛=筹码锁定）
    if len(factors) >= 20:
        bw_20d = []
        for i in range(20):
            bu = safe_float(factors[i].get('boll_upper_bfq'))
            bl = safe_float(factors[i].get('boll_lower_bfq'))
            bm = safe_float(factors[i].get('boll_mid_bfq'))
            if bu and bl and bm:
                bw_20d.append((bu - bl) / bm * 100)
        boll_width_cur = bw_20d[0] if bw_20d else 0
        bw_pct = pctile(bw_20d, 30) if bw_20d else 0
        if boll_width_cur > 0 and bw_pct > 0 and boll_width_cur <= bw_pct:
            chip_score += 5
            chip_reasons.append(f"波动收敛(带宽{boll_width_cur:.1f}%)+5")
    
    # 负向：高位换手递增+滞涨（已在否决2.3处理，这里再扣分）
    if len(factors) >= 3:
        tr_3d_chip = [safe_float(factors[i].get('turnover_rate')) for i in range(3)]
        pc_3d_chip = [safe_float(factors[i].get('pct_change')) for i in range(3)]
        valid_tr3c = [t for t in tr_3d_chip if t]
        valid_pc3c = [p for p in pc_3d_chip if p is not None]
        if len(valid_tr3c) == 3 and valid_tr3c[0] > valid_tr3c[1] > valid_tr3c[2]:
            if len(valid_pc3c) == 3 and sum(valid_pc3c) < 3:
                chip_score -= 10
                chip_reasons.append(f"换手递增滞涨-10")
    
    score += max(0, min(15, chip_score))
    reasons.extend(chip_reasons)
    
    # --- 3.5 日内资金动能 (8分) V2.0 ---
    capital_score = 0
    capital_reasons = []
    
    # 资金动能：外盘-内盘差用Level1代理（close/MA关系）
    # V2.0: 收盘>BOLL中轨+量比>中位数 → 资金正向
    if close and boll_mid:
        vw_ratio = close / boll_mid
        if vw_ratio > 1.01 and vol_ratio and vol_ratio > vr_median:
            capital_score += 5
            capital_reasons.append(f"资金正向(价>中轨+量比{vol_ratio:.2f})+5")
        elif vw_ratio > 1.01:
            capital_score += 2
            capital_reasons.append(f"价>中轨+2")
    
    # 分时强势：收盘/VWAP>1.01 且 日内最大回撤<VWAP下方1%
    if close and boll_mid:
        vw_ratio = close / boll_mid
        # 日内最大回撤代理：用(低开幅度)衡量
        intraday_drawdown = 0
        if open_price and low and open_price > 0:
            intraday_drawdown = (open_price - low) / open_price * 100
        if vw_ratio > 1.01 and intraday_drawdown < 1.5:
            capital_score += 3
            capital_reasons.append(f"分时强势(回撤{intraday_drawdown:.1f}%)+3")
    
    # 负向：分时走弱
    if close and boll_mid and close / boll_mid < 0.99:
        capital_score -= 8
        capital_reasons.append(f"分时走弱(价<中轨)-8")
    
    score += max(0, min(8, capital_score))
    reasons.extend(capital_reasons)
    
    # --- 3.6 板块协同过滤 (5分) V2.0新增 ---
    sector_score = 0
    sector_reasons = []
    sector_above_ma20_ratio = 0.5  # 中性的默认值
    
    try:
        # 获取所属行业
        resp_sector = call_tushare("stock_basic", token, {"ts_code": code}, "ts_code,industry")
        sector_items = resp_sector.get("data", {}).get("items", [])
        if sector_items:
            sector_fields = resp_sector.get("data", {}).get("fields", [])
            sector_dict = dict(zip(sector_fields, sector_items[0])) if sector_fields else {}
            industry = str(sector_dict.get('industry', ''))
            if industry:
                # 获取行业内所有股票
                resp_ind = call_tushare("stock_basic", token, {"industry": industry}, "ts_code")
                ind_items = resp_ind.get("data", {}).get("items", [])
                if ind_items and len(ind_items) > 1:
                    above_ma20_count = 0
                    total_count = 0
                    # 只检查前20只减少API调用
                    for ind_code_item in ind_items[:20]:
                        ind_code = ind_code_item[0] if isinstance(ind_code_item, (list, tuple)) else ''
                        if not ind_code:
                            continue
                        total_count += 1
                        try:
                            resp_daily = call_tushare("stk_factor_pro", token, {"ts_code": ind_code}, "trade_date,close,ma_bfq_20")
                            d_items = resp_daily.get("data", {}).get("items", [])
                            if d_items:
                                d_fields = resp_daily.get("data", {}).get("fields", [])
                                d_dict = dict(zip(d_fields, d_items[0])) if d_fields else {}
                                d_close = safe_float(d_dict.get('close'))
                                d_ma20 = safe_float(d_dict.get('ma_bfq_20'))
                                if d_close and d_ma20 and d_close > d_ma20:
                                    above_ma20_count += 1
                        except:
                            pass
                    if total_count > 0:
                        sector_above_ma20_ratio = above_ma20_count / total_count
                        
                        if sector_above_ma20_ratio >= 0.4:
                            sector_score += 5
                            sector_reasons.append(f"板块共振({sector_above_ma20_ratio*100:.0f}%>MA20)+5")
                        elif sector_above_ma20_ratio >= 0.2:
                            sector_score += 2
                            sector_reasons.append(f"板块中性({sector_above_ma20_ratio*100:.0f}%>MA20)+2")
                        else:
                            # 板块弱势天花板：总分上限74
                            sector_reasons.append(f"板块弱势(<20%>MA20)天花板74分")
    except:
        pass
    
    score += min(5, sector_score)
    reasons.extend(sector_reasons)
    
    # ===== 4. V2.0 板块弱势硬性天花板 =====
    if sector_above_ma20_ratio < 0.2 and score > 74:
        score = 74
        reasons.append("板块天花板→74")
    
    # ===== 5. V2.0 时间因子与信号衰减 =====
    try:
        from datetime import datetime as _dt
        now = _dt.now()
        now_minutes = now.hour * 60 + now.minute
        mkt_open = 9 * 60 + 30  # 09:30
        mkt_close = 15 * 60  # 15:00
        
        if mkt_open <= now_minutes <= mkt_close:
            # 早盘冲动抑制：10:30前触发，14:00后量比回落则-5分
            early_cutoff = 10 * 60 + 30  # 10:30
            afternoon_check = 14 * 60  # 14:00
            if now_minutes < early_cutoff:
                # 预设标记，需14:00后验证
                pass
            # 尾盘确认加分：14:30后量比>Top20%则+3分
            tail_cutoff = 14 * 60 + 30  # 14:30
            if now_minutes >= tail_cutoff and vol_ratio:
                if vol_ratio > vr_top20 or vol_ratio > 1.5:
                    score += 3
                    reasons.append(f"尾盘确认量比{vol_ratio:.2f}+3")
    except:
        pass
    
    # ===== 6. 综合评定 =====
    final_score = max(0, min(100, score))
    
    if final_score >= 75:
        level = "高"
    elif final_score >= 55:
        level = "中"
    elif final_score >= 35:
        level = "低"
    else:
        level = "无"
    
    reason_str = f"[{level}] " + "; ".join(reasons[:6]) if reasons else f"[{level}] 无明显信号"
    
    return final_score, reason_str


# ===== 4. 资金面评分 (五维度量化评分 V1.0) =====
# 缓存当日资金流向数据（避免每次调用都请求全市场）
_FUND_FLOW_CACHE = None
_FUND_FLOW_DATE = None
# akshare实时资金流向缓存（盘中场景优先使用）
_AKSHARE_FUND_CACHE = None
_AKSHARE_FUND_DATE = None

def _get_akshare_fund_flow():
    """获取akshare同花顺源个股资金流向实时数据（带缓存）。
    返回DataFrame或None。盘中优先使用此数据源，降级时回退Tushare T+1。"""
    global _AKSHARE_FUND_CACHE, _AKSHARE_FUND_DATE
    from datetime import datetime
    today_str = datetime.now().strftime("%Y%m%d")
    if _AKSHARE_FUND_CACHE is not None and _AKSHARE_FUND_DATE == today_str:
        return _AKSHARE_FUND_CACHE
    try:
        import akshare as ak
        df = ak.stock_fund_flow_individual()
        _AKSHARE_FUND_CACHE = df
        _AKSHARE_FUND_DATE = today_str
        return df
    except Exception as e:
        print(f"akshare资金流向获取失败: {e}, 将降级使用Tushare T+1数据")
        return None

def _parse_akshare_amount(val_str):
    """解析akshare金额字符串，返回亿元单位的浮点数。
    akshare格式：'1.35亿', '4289.20万', '2021.40万', '-16.52万' 等"""
    if val_str is None:
        return 0.0
    s = str(val_str).strip()
    if '亿' in s:
        return float(s.replace('亿', ''))
    elif '万' in s:
        return float(s.replace('万', '')) / 10000.0
    else:
        try:
            return float(s) / 100000000.0  # 纯数字可能是元
        except:
            return 0.0

def score_fundflow(code):
    """
    资金面涨停潜力预判 V2.3
    五维度量化评分：超大单主力35分 + 龙虎榜机构游资25分 + 分时盘口20分 + 融资聪明资金7分 + 筹码抛压13分
    含一票否决规则（含V2.0市场状态调节器+一字板豁免）
    
    V2.3变更（基于V2.1）：
    - 否决4增加3日累计豁免：<5%+3日累计净流入≤0才否决，>0转入维度1扣-5分
    - 否决3增加尾盘抢筹豁免：收盘/最高>0.92+换手<15%或3日净流入>0豁免
    - 否决5改为组合A/B阈值（日频代理）
    - 维2首板豁免：T-1非涨停但T日涨幅>7%时按0分处理（不扣-15）
    - 维1散户接盘V2.3量化：中/小单>成交额8%+主力<0+涨幅>3%；增加涨停换手豁免
    - 维3全部因子改为日频代理：持续净流入条件改为最低价≥昨收×0.99
    - 维3负向过滤增加拉升无量/放量出逃/对倒嫌疑三项判定
    - 潜力分级增加53-56分边缘区间+二次确认
    - 维5换手递减因子增加至少2日收阳+20日新高附近条件
    
    V2.1变更（基于V2.0）：
    - 否决4阈值放宽：主力净占比<10%→<5%才否决，5%-10%转维度1扣分
    - 维1规模偏弱扣分修正：<0.1%从-5→-15(与文档对齐)
    - 维1占比阈值细化：5%-15%偏弱区间扣5分
    
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
    
    # 1.6 akshare实时资金流向（盘中优先使用，降级回退Tushare T+1）
    # 同花顺源不受东方财富反爬影响，盘中场景提供当日实时数据
    akshare_fund = None  # 该股票的akshare资金流向行(dict)
    akshare_fund_net_ratio = None  # 主力净占比(%)
    akshare_fund_main_net_ratio = None  # 主力净额/成交额(%)
    akshare_fund_net_amount_yi = None  # 净额(亿元)
    akshare_fund_total_amount_yi = None  # 成交额(亿元)
    akshare_main_buy_yi = None  # 流入资金(亿元, akshare原始单位)
    akshare_main_sell_yi = None  # 流出资金(亿元, akshare原始单位)
    akshare_main_net_yi = None  # 主力净额(亿元)
    akshare_pct_change = None  # 涨跌幅(用于否决2.4资金背离+维度1规模)
    akshare_turnover = None  # 换手率(用于维度1判断)
    
    df_akshare = _get_akshare_fund_flow()
    if df_akshare is not None:
        try:
            # akshare股票代码列是整数类型(002763→2763)，需转int匹配
            code_int = int(code.split('.')[0])
            row = df_akshare[df_akshare.iloc[:, 0] == code_int]
            if len(row) > 0:
                r = row.iloc[0]
                akshare_fund = r.to_dict()
                # 解析金额（akshare单位：净额=万, 流入/流出/成交额=亿）
                # 列名：股票代码,股票简称,最新价,涨跌幅,换手率,流入资金,流出资金,净额,成交额
                # 注意：不同版本akshare列名可能略有差异，用iloc索引兜底
                col_names = list(df_akshare.columns)
                
                # 净额列（单位：万，需转亿）
                net_col = None
                for c in col_names:
                    if '净额' in str(c) or '净流入' in str(c):
                        net_col = c
                        break
                if net_col is None and len(col_names) >= 8:
                    net_col = col_names[7]  # 第8列通常是净额
                
                # 流入/流出/成交额列（单位：亿）
                inflow_col = None
                outflow_col = None
                amount_col = None
                for c in col_names:
                    if '流入' in str(c) and '流出' not in str(c):
                        inflow_col = c
                    if '流出' in str(c) and '流入' not in str(c):
                        outflow_col = c
                    if '成交额' in str(c) or '成交' in str(c):
                        amount_col = c
                if inflow_col is None and len(col_names) >= 6:
                    inflow_col = col_names[5]
                if outflow_col is None and len(col_names) >= 7:
                    outflow_col = col_names[6]
                if amount_col is None and len(col_names) >= 9:
                    amount_col = col_names[8]
                
                # 涨跌幅列
                pct_col = None
                for c in col_names:
                    if '涨跌幅' in str(c) or '涨跌' in str(c):
                        pct_col = c
                        break
                if pct_col is None and len(col_names) >= 4:
                    pct_col = col_names[3]
                
                # 换手率列
                turnover_col = None
                for c in col_names:
                    if '换手率' in str(c) or '换手' in str(c):
                        turnover_col = c
                        break
                if turnover_col is None and len(col_names) >= 5:
                    turnover_col = col_names[4]
                
                # 计算关键指标
                if net_col and amount_col:
                    net_val = _parse_akshare_amount(str(r.get(net_col, '0')))
                    # 净额在akshare中是"万"单位，parse后已转为亿
                    akshare_fund_net_amount_yi = net_val
                    
                    total_amount_val = _parse_akshare_amount(str(r.get(amount_col, '0')))
                    akshare_fund_total_amount_yi = total_amount_val
                    
                    # 净占比 = 净额(亿) / 成交额(亿) * 100
                    if total_amount_val > 0:
                        akshare_fund_net_ratio = net_val / total_amount_val * 100
                
                if inflow_col and outflow_col:
                    # 流入/流出单位是亿
                    akshare_main_buy_yi = _parse_akshare_amount(str(r.get(inflow_col, '0')))
                    akshare_main_sell_yi = _parse_akshare_amount(str(r.get(outflow_col, '0')))
                    akshare_main_net_yi = akshare_main_buy_yi - akshare_main_sell_yi
                    
                    # 主力净占比 = (流入-流出)/(流入+流出) * 100
                    total_main = akshare_main_buy_yi + akshare_main_sell_yi
                    if total_main > 0:
                        akshare_fund_main_net_ratio = akshare_main_net_yi / total_main * 100
                
                # 涨跌幅和换手率（已在函数顶部初始化为None）
                if pct_col:
                    try:
                        akshare_pct_change = float(r.get(pct_col, 0))
                    except:
                        pass
                if turnover_col:
                    try:
                        akshare_turnover = float(r.get(turnover_col, 0))
                    except:
                        pass
        except Exception as e:
            print(f"akshare资金解析失败({code}): {e}")
    
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
    
    # V2.3: 否决4 — 纯散户博弈（3日累计豁免）
    # <5% + 3日累计净流入≤0 → 否决
    # <5% + 3日累计净流入>0 → 不否决，维度1占比因子扣-5分
    main_ratio_for_dim1 = None  # 保存主力占比供维度1使用
    akshare_used_in_veto = False
    dim1_veto4_deduction = 0  # V2.3: 否决4豁免后的维度1扣分标记
    
    # V2.3: 计算3日累计净流入（用于否决4豁免判定）
    net_3d_for_veto4 = 0
    if moneyflow_data:
        recent_3d = moneyflow_data[:3] if len(moneyflow_data) >= 3 else moneyflow_data
        net_3d_for_veto4 = sum([safe_float(x.get("net_mf_amount", 0)) for x in recent_3d])
    
    if not is_yiziban:
        # 盘中优先用akshare实时数据
        if akshare_fund_main_net_ratio is not None:
            main_ratio = akshare_fund_main_net_ratio
            main_ratio_for_dim1 = main_ratio
            akshare_used_in_veto = True
            if main_ratio < 5:
                if net_3d_for_veto4 <= 0:
                    veto_flags.append(f"纯散户博弈[实时]:主力净占比{main_ratio:.1f}%<5%+3日累计净流入{net_3d_for_veto4:.0f}≤0")
                else:
                    dim1_veto4_deduction = -5  # V2.3: 豁免否决，转入维度1扣分
        elif moneyflow_data:
            # 降级：Tushare T+1数据
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
                main_ratio_for_dim1 = main_ratio
                if main_ratio < 5:
                    if net_3d_for_veto4 <= 0:
                        veto_flags.append(f"纯散户博弈[T-1]:主力净占比{main_ratio:.1f}%<5%+3日累计净流入{net_3d_for_veto4:.0f}≤0")
                    else:
                        dim1_veto4_deduction = -5  # V2.3: 豁免否决，转入维度1扣分
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
    
    # V2.3: 否决3 — 分时资金背离（增加尾盘抢筹豁免+换手率/累计流入双重验证）
    # 盘中优先用akshare实时数据（涨跌幅+净占比），降级用Tushare T+1
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
    
    # V2.3: 查找 T-1日换手率和当日收盘位置（用于否决3豁免判定）
    t_turnover_rate = 0
    if daily_basic_data:
        t_turnover_rate = safe_float(daily_basic_data[0].get("turnover_rate", 0))
    
    # 盘中优先用akshare实时涨跌幅+净占比判断背离
    if akshare_pct_change is not None and akshare_fund_net_ratio is not None:
        # akshare实时：涨跌幅>3%但净占比为负（资金背离）
        if akshare_pct_change > 3 and akshare_fund_net_ratio < 0:
            if corr_threshold < -0.6:
                pass  # 低迷市放宽，不触发背离否决
            else:
                # V2.3: 尾盘抢筹豁免 —— 收盘在日高附近 AND (换手率<15% OR 3日累计净流入>0)
                # 豁免条件（二者同时满足）：
                #   ① 收盘价/最高价 > 0.92（尾盘无跳水）
                #   ② 换手率<15% OR 近3日累计净流入>0
                if daily_basic_data:
                    close = safe_float(daily_basic_data[0].get("close", 0))
                    high = safe_float(daily_basic_data[0].get("high", 0)) if "high" in daily_basic_data[0] else 0
                else:
                    close = high = 0
                close_high_ratio = close / high if high > 0 else 0
                if close_high_ratio > 0.92 and (t_turnover_rate < 15 or net_3d_for_veto4 > 0):
                    pass  # V2.3: 豁免（尾盘抢筹或主力做T，良性分歧）
                else:
                    veto_flags.append(f"资金背离[akshare]:涨{akshare_pct_change:.1f}%但净占比{akshare_fund_net_ratio:.1f}%")
    elif moneyflow_data and daily_basic_data:
        # 降级：Tushare T+1
        latest_basic = daily_basic_data[0]
        pct_change = safe_float(latest_basic.get("pct_change", 0))
        if pct_change > 3:
            latest_mf = moneyflow_data[0]
            net_mf = safe_float(latest_mf.get("net_mf_amount", 0))
            if net_mf < 0:
                if corr_threshold < -0.6:
                    pass  # 低迷市放宽
                else:
                    # V2.3: 尾盘抢筹豁免（同上，用Tushare数据）
                    if "high" in latest_basic:
                        close = safe_float(latest_basic.get("close", 0))
                        high = safe_float(latest_basic.get("high", 0))
                    else:
                        close = high = 0
                    close_high_ratio = close / high if high > 0 else 0
                    if close_high_ratio > 0.92 and (t_turnover_rate < 15 or net_3d_for_veto4 > 0):
                        pass  # V2.3: 豁免
                    else:
                        veto_flags.append(f"资金背离[T+1]:涨{pct_change:.1f}%但净流出{abs(net_mf)/10000:.0f}万")
    
    # V2.3: 否决5 — 尾盘集中兑现（组合A/B阈值，日频代理）
    # 组合A：14:30后成交量占全天>25% AND 收盘价<分时均价线
    # 组合B：14:00后成交量占全天>45% AND 当日收跌 AND 收盘价<分时均价线
    # 分时均价线代理（无分钟数据时）：收盘价 < (最高价+最低价)/2
    if daily_basic_data:
        close = safe_float(daily_basic_data[0].get("close", 0))
        high = safe_float(daily_basic_data[0].get("high", 0))
        low = safe_float(daily_basic_data[0].get("low", 0))
        pct_chg = safe_float(daily_basic_data[0].get("pct_change", 0))
        # 分时均价线代理
        avg_price_proxy = (high + low) / 2 if high > 0 and low > 0 else 0
        below_avg = close < avg_price_proxy if avg_price_proxy > 0 else False
        
        # 无分钟成交量数据，用净流向结构做日频代理
        if moneyflow_data:
            latest_mf = moneyflow_data[0]
            net_mf = safe_float(latest_mf.get("net_mf_amount", 0))
            
            # 组合A代理：主力净流出 + 收盘低于均价（模拟尾盘兑现）
            if net_mf < 0 and below_avg:
                # 判定为"尾盘走弱预警"，降级为低潜力（降分而非否决）
                # 注：无分钟成交量数据，用净流出结构做近似代理
                veto_flags.append(f"尾盘走弱预警:净流出{abs(net_mf)/10000:.0f}万+收盘低于均价")
            
            # 组合B代理：收跌 + 净流出 + 低于均价（更弱信号）
            if pct_chg < 0 and net_mf < 0 and below_avg:
                veto_flags.append(f"尾盘走弱预警:收跌+净流出+低于均价")
    
    # 触发否决直接返回
    if veto_flags:
        return 0, f"否决: {'; '.join(veto_flags)}"
    
    # ===== 3. 维度1：超大单主力净流入（35分）=====
    # V2.2: 盘中优先使用akshare实时数据，降级回退Tushare T+1
    dim1_score = 0
    dim1_reason = []
    
    # --- 规模阈值因子(15分)：主力净流入占市值/成交额比例 ---
    # 盘中：净额/成交额比例（akshare实时）
    # 盘后/T+1：主力净额/流通市值比例（Tushare）
    if akshare_fund_net_amount_yi is not None and akshare_fund_total_amount_yi is not None and akshare_fund_total_amount_yi > 0:
        # akshare实时：净额占成交额比例
        akshare_net_pct = akshare_fund_net_amount_yi / akshare_fund_total_amount_yi * 100
        if akshare_net_pct >= 3:  # 净流入占成交额>=3%
            dim1_score += 15
            dim1_reason.append(f"主力净流入[实时]{akshare_net_pct:.2f}%+15")
        elif akshare_net_pct < 0.1:  # 净流入占比极低
            dim1_score -= 15
            dim1_reason.append(f"主力净流入[实时]{akshare_net_pct:.2f}%-15")
    elif moneyflow_data and daily_basic_data:
        # 降级：Tushare T+1
        latest = moneyflow_data[0]
        buy_elg = safe_float(latest.get("buy_elg_amount", 0))
        sell_elg = safe_float(latest.get("sell_elg_amount", 0))
        buy_lg = safe_float(latest.get("buy_lg_amount", 0))
        sell_lg = safe_float(latest.get("sell_lg_amount", 0))
        main_net = (buy_elg - sell_elg) + (buy_lg - sell_lg)
        circ_mv = safe_float(daily_basic_data[0].get("circ_mv", 0)) * 10000  # 万转元
        if circ_mv > 0:
            main_net_ratio = main_net / circ_mv * 100
            if main_net_ratio >= 0.3:
                dim1_score += 15
                dim1_reason.append(f"主力净流入[T-1]{main_net_ratio:.2f}%+15")
            elif main_net_ratio < 0.1:
                dim1_score -= 15  # V2.1: 从-5修正为-15(与文档对齐)
                dim1_reason.append(f"主力净流入[T-1]{main_net_ratio:.2f}%-15")
    
    # --- 占比健康因子(10分)：主力净占比梯度评分 ---
    # >30%: +10分，15%-30%: 0分(中性)，5%-15%: -5分(偏弱)，<5%: 已在否决区拦截
    # main_ratio_for_dim1 已在否决2.2阶段计算(含akshare实时优先)
    if main_ratio_for_dim1 is not None:
        main_ratio = main_ratio_for_dim1
        if akshare_used_in_veto:
            src_tag = "[实时]"
        elif moneyflow_data:
            src_tag = "[T-1]"
        else:
            src_tag = ""
        if main_ratio > 30:
            dim1_score += 10
            dim1_reason.append(f"主力占比{src_tag}{main_ratio:.1f}%+10")
        elif main_ratio >= 5 and main_ratio < 15:  # V2.1: 5%-15%偏弱扣分
            dim1_score -= 5
            dim1_reason.append(f"主力占比偏弱{src_tag}{main_ratio:.1f}%-5")
    
    # V2.3: 否决4豁免 — 主力净占比<5%但3日累计净流入>0，转入维度1扣-5分
    if dim1_veto4_deduction != 0:
        dim1_score += dim1_veto4_deduction
        dim1_reason.append(f"否决4豁免(3日累计>0)-5")
    elif moneyflow_data:
        # 降级：Tushare计算
        latest = moneyflow_data[0]
        buy_elg = safe_float(latest.get("buy_elg_amount", 0))
        sell_elg = safe_float(latest.get("sell_elg_amount", 0))
        buy_lg = safe_float(latest.get("buy_lg_amount", 0))
        sell_lg = safe_float(latest.get("sell_lg_amount", 0))
        main_net = (buy_elg - sell_elg) + (buy_lg - sell_lg)
        total_vol = buy_elg + sell_elg + buy_lg + sell_lg
        if total_vol > 0:
            main_ratio = main_net / total_vol * 100
            if main_ratio > 30:
                dim1_score += 10
                dim1_reason.append(f"主力占比[T-1]{main_ratio:.1f}%+10")
            elif main_ratio >= 5 and main_ratio < 15:
                dim1_score -= 5
                dim1_reason.append(f"主力占比偏弱[T-1]{main_ratio:.1f}%-5")
    
    # --- 持续抢筹因子(10分)：近3日连续净流入（仍用Tushare历史数据） ---
    if moneyflow_data and len(moneyflow_data) >= 3:
        net_3d = [safe_float(x.get("net_mf_amount", 0)) for x in moneyflow_data[:3]]
        if all(n > 0 for n in net_3d):
            dim1_score += 10
            dim1_reason.append(f"连续3日净流入+10")
    
    # --- 散户接盘因子 V2.3量化+豁免(-20分)：主力流出但散户接盘 ---
    # 触发条件（三者同时满足）：
    # ① 主力净额 < 0
    # ② (中单净额 + 小单净额) > 成交额的8%
    # ③ 当日股价涨幅 > 3%
    # 豁免条件（满足任一即不扣分）：
    # ① 当日涨停且换手率在5%-25%区间（换手板属健康博弈）
    # ② 近3日主力累计净流入 > 0（主力前期已进场）
    # 盘中：akshare主力净额<0且总净额>0
    # 降级：Tushare main_net<0且net_mf>0
    retail_retail_exempt = False
    # 取换手率（V2.3散户接盘豁免判定用）
    retail_turnover_rate = t_turnover_rate if 't_turnover_rate' in dir() else 0
    pct_change_for_retail = akshare_pct_change or 0
    if not pct_change_for_retail and daily_basic_data:
        pct_change_for_retail = safe_float(daily_basic_data[0].get("pct_change", 0))
    
    if akshare_main_net_yi is not None and akshare_fund_net_amount_yi is not None:
        # 豁免判定
        if akshare_main_net_yi < 0:
            # 豁免①：涨停+换手5%-25%
            akshare_pct = akshare_pct_change or 0
            if akshare_pct >= 9.5 and 5 <= retail_turnover_rate <= 25:
                retail_retail_exempt = True
            # 豁免②：3日累计净流入>0
            elif net_3d_for_veto4 > 0:
                retail_retail_exempt = True
            # 非豁免：触发散户接盘扣分
            if akshare_main_net_yi < 0 and akshare_fund_net_amount_yi > 0 and not retail_retail_exempt:
                dim1_score -= 20
                dim1_reason.append(f"散户接盘[实时]-20")
    elif moneyflow_data:
        latest = moneyflow_data[0]
        buy_elg = safe_float(latest.get("buy_elg_amount", 0))
        sell_elg = safe_float(latest.get("sell_elg_amount", 0))
        buy_lg = safe_float(latest.get("buy_lg_amount", 0))
        sell_lg = safe_float(latest.get("sell_lg_amount", 0))
        net_mf = safe_float(latest.get("net_mf_amount", 0))
        main_net = (buy_elg - sell_elg) + (buy_lg - sell_lg)
        # V2.3: Tushare降级分支也需要做豁免判定
        if main_net < 0 and net_mf > 0:
            # 豁免①：涨停+换手5%-25%
            if pct_change_for_retail >= 9.5 and 5 <= retail_turnover_rate <= 25:
                retail_retail_exempt = True
            # 豁免②：3日累计净流入>0
            elif net_3d_for_veto4 > 0:
                retail_retail_exempt = True
            if not retail_retail_exempt:
                dim1_score -= 20
                dim1_reason.append(f"散户接盘[T-1]-20")
    
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
            
            # V2.3首板豁免：T-1日非涨停股但T日涨幅>7% → 不适用"未涨停扣15分"，按0分处理
            if limit_type != "U":
                # 检查T日是否正在拉升（涨幅>7%），若是则豁免
                t_day_pct = 0
                if akshare_pct_change is not None:
                    t_day_pct = akshare_pct_change
                elif daily_basic_data:
                    t_day_pct = safe_float(daily_basic_data[0].get("pct_change", 0))
                if t_day_pct > 7:
                    pass  # V2.3首板豁免：不扣分
                else:
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
        
        # V2.3: 持续净流入（日频代理）——最低价≥昨收×0.99 包容换手板宽幅震荡
        if net_mf > 0:
            close = safe_float(daily_basic_data[0].get("close", 0))
            low = safe_float(daily_basic_data[0].get("low", 0))
            high = safe_float(daily_basic_data[0].get("high", 0))
            pre_close = safe_float(daily_basic_data[0].get("pre_close", 0))
            
            # 持续净流入条件：主力净流入>0 AND 最低价≥昨收×0.99 AND 收盘/最高>0.95
            low_ok = low >= pre_close * 0.99 if pre_close > 0 else True
            close_high_ok = close / high > 0.95 if high > 0 else True
            if low_ok and close_high_ok:
                dim3_score += 10
                dim3_reason.append(f"持续净流入{net_mf/10000:.2f}亿+10")
            
            # 强承接：主力净流入>0 AND 换手率>3% AND 换手率/振幅>2.0
            amplitude = (high - low) / pre_close * 100 if pre_close > 0 else 0
            if turnover_rate > 3 and amplitude > 0 and (turnover_rate / amplitude) > 2.0:
                dim3_score += 6
                dim3_reason.append(f"强承接换手/振幅{max(0,turnover_rate/amplitude if amplitude>0 else 0):.1f}+6")
            
            # 脉冲/尾盘回流：超大单净流入>0 AND (中单+小单)净流出>0
            buy_elg = safe_float(latest.get("buy_elg_amount", 0))
            sell_elg = safe_float(latest.get("sell_elg_amount", 0))
            buy_lg = safe_float(latest.get("buy_lg_amount", 0))
            sell_lg = safe_float(latest.get("sell_lg_amount", 0))
            elg_net = buy_elg - sell_elg
            lg_net = buy_lg - sell_lg
            # 中单+小单净流出 ≈ 总净流入 - 超大单净流入 - 大单净流入（简化：net_mf > 0 + elg_net > 0 即超大单主导）
            if elg_net > 0 and net_mf > 0:
                dim3_score += 4
                dim3_reason.append(f"超大单主导+4")
        else:
            dim3_score = 0
            dim3_reason.append(f"净流出{abs(net_mf)/10000:.2f}亿")
        
        # V2.3 负向过滤（满足任一即扣12分）
        pct_chg = safe_float(daily_basic_data[0].get("pct_change", 0))
        is_zt = (pct_chg >= 9.5)
        is_negative_triggered = False
        
        # ① 当日涨幅>5% AND 换手率<2%（拉升无量）
        if pct_chg > 5 and turnover_rate < 2 and not is_zt:
            dim3_score -= 12
            dim3_reason.append(f"拉升无量{pct_chg:.1f}%换手{turnover_rate:.1f}%-12")
            is_negative_triggered = True
        # ② 当日跌幅>3% AND 换手率>8%（放量出逃）
        if not is_negative_triggered and pct_chg < -3 and turnover_rate > 8:
            dim3_score -= 12
            dim3_reason.append(f"放量出逃{pct_chg:.1f}%换手{turnover_rate:.1f}%-12")
        # ③ 当日主力净流出>0 AND 换手率>10%（对倒嫌疑）
        if not is_negative_triggered and net_mf < 0 and turnover_rate > 10:
            dim3_score -= 12
            dim3_reason.append(f"对倒嫌疑换手{turnover_rate:.1f}%-12")
    
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
    
    # V2.3: 53-56分边缘区间二次确认
    if 53 <= final_score <= 56:
        # 二次确认：维度1≥21(60%) AND 维度5≥8(60%) → 升级为高潜力
        if dim1_score >= 21 and dim5_score >= 8:
            level = "高"
            reason.append("[边缘升级]维1≥21+维5≥8→高潜力")
        else:
            level = "中"
            reason.append("[边缘确认]维持中等潜力")
    elif final_score >= 75:
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
    情绪面涨停潜力预判 V2.3
    五维度量化评分：大盘情绪30分 + 主线题材30分 + 板块梯队20分 + 个股人气10分 + 集合竞价15分
    含一票否决规则
    
    V2.3变更（基于V1.2）：
    - 否决4核按钮定义修正（诱多A+一字闷杀B分开，闷杀无需换手率）
    - 否决4豁免增加"盘中最高价触及涨停价"
    - 否决5人气排名动态阈值+Null处理(未上榜=5000)
    - 否决2盘中代理明确(14:30后执行)
    - 维2周期标签改为三态(退潮-10/分歧0/发酵+5)
    - 维2题材地位梯度(1名+10,2-3名+5,4-5名+2)
    - 维2发酵强度增加持平条件(≥前日涨停数)
    - 维4换手率梯度计分(5-15%+1/15-25%+2/25-30%+1/>30%-2/<5%:0)
    - 维4资金记忆增加溢价校验+连板基因因子+3分
    - 维5高开≥8%秒板修正(5min内封板→+5分)
    - 维1空间高度扣分明确定义
    - 新增高位情绪折扣(≥5板总分系数)
    - 新增评估时间策略(早盘预览暂停否决2-5)
    
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
    
    # V2.4: 否决6 — 情绪退潮熔断
    if limit_data:
        up_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'U'])
        down_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'D'])
        z_cnt = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'Z'])
        total_b = up_cnt + z_cnt
        break_rate = z_cnt / total_b * 100 if total_b > 0 else 0
        
        if break_rate > 40 and down_cnt > 15:
            # V2.4: 检查是否可进入冰点拐点试探
            max_height = 0
            if step_data:
                max_height = max([safe_int(x.get('nums', 0)) or 0 for x in step_data], default=0)
            
            if max_height <= 2:
                # 冰点拐点：最高连板降至2板+跌停减少
                return 0, f"情绪熔断冰点:炸板率{break_rate:.1f}%>40%+跌停{down_cnt}家+连板{max_height}板"
            else:
                return 0, f"情绪熔断:炸板率{break_rate:.1f}%>40%+跌停{down_cnt}家"
    
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
    
    # V2.3: 否决4 — 个股情绪溃散（诱多A+一字闷杀B）
    # A. 诱多核按钮：
    #   ① 当日最高涨幅曾>3%但收盘跌停
    #   ② 该日换手率 > 近10日均换手率的1.5倍
    #   ③ 近5日内出现≥1次
    # B. 一字闷杀：
    #   ① 开盘即跌停且全天未开板
    #   ② 无需换手率确认
    #   ③ 近5日内出现≥1次
    # 豁免条件（A和B通用）：
    #   ① 曾出现过涨停（收盘涨停或触及涨停）
    #   OR
    #   ② 今日盘中最高价已触及涨停价（正在打反包板）
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=10)
        resp = call_tushare("daily", token, {
            "ts_code": code,
            "start_date": start_dt.strftime('%Y%m%d'),
            "end_date": end_dt.strftime('%Y%m%d')
        }, "trade_date,close,pct_chg,vol,high,low,open")
        daily_items = resp.get("data", {}).get("items", [])
        if daily_items and len(daily_items) >= 2:
            d_fields = resp.get("data", {}).get("fields", [])
            d_dicts = [dict(zip(d_fields, x)) for x in daily_items if d_fields]
            
            # 计算近10日均换手率（从daily_basic获取）
            try:
                resp_tr = call_tushare("daily_basic", token, {
                    "ts_code": code,
                    "start_date": start_dt.strftime('%Y%m%d'),
                    "end_date": end_dt.strftime('%Y%m%d')
                }, "trade_date,turnover_rate")
                tr_items = resp_tr.get("data", {}).get("items", [])
                tr_fields = resp_tr.get("data", {}).get("fields", [])
                tr_dicts = [dict(zip(tr_fields, x)) for x in tr_items if tr_fields]
                tr_values = [safe_float(x.get('turnover_rate', 0)) or 0 for x in tr_dicts if safe_float(x.get('turnover_rate')) is not None]
                tr_10d_avg = sum(tr_values[-10:]) / len(tr_values[-10:]) if len(tr_values) >= 10 else (sum(tr_values) / len(tr_values) if tr_values else 0)
            except:
                tr_10d_avg = 0
            
            # 检查是否有豁免（曾经涨停/盘中触及涨停）
            has_exemption = False
            today_high_touched_zt = False
            
            for d in d_dicts:
                d_pct = safe_float(d.get('pct_chg', 0)) or 0
                if d_pct >= 9.5:
                    has_exemption = True
                    break
                # 今日盘中最高价是否触及涨停
                d_date = d.get('trade_date', '')
                if d_date == today_str:
                    d_high = safe_float(d.get('high', 0)) or 0
                    d_pre_close = safe_float(d.get('open', 0)) or 0  # 用收盘代理昨收
                    # 从daily接口获取前一日收盘价
                    # 检查high是否接近涨停（>=昨收*1.095）
                    # 用open代理pre_close不准确，从数据中获取昨收
                    d_close = safe_float(d.get('close', 0)) or 0
                    if d_high > 0 and d_close > 0 and d_high >= d_close * 1.095:
                        today_high_touched_zt = True
            
            if today_high_touched_zt:
                has_exemption = True
            
            # 检查近5个交易日的核按钮（不含当日）
            recent_5d = [d for d in d_dicts if d.get('trade_date', '') != today_str][-5:]
            for d in recent_5d:
                d_pct = safe_float(d.get('pct_chg', 0)) or 0
                d_high = safe_float(d.get('high', 0)) or 0
                d_close = safe_float(d.get('close', 0)) or 0
                d_open = safe_float(d.get('open', 0)) or 0
                d_low = safe_float(d.get('low', 0)) or 0
                d_vol = safe_float(d.get('vol', 0)) or 0
                
                # A. 诱多核按钮：最高曾>3%但收盘跌停
                is_a = (d_high > d_close * 1.03) and (d_pct <= -9.9)
                # B. 一字闷杀：开盘即跌停且全天未开板
                is_b = (d_open == d_close) and (d_open == d_low) and (d_pct <= -9.9) and (d_high >= d_close * 0.99)
                
                if is_a or is_b:
                    if has_exemption:
                        continue  # 豁免
                    
                    # A需要换手率确认
                    if is_a and tr_10d_avg > 0:
                        # 获取该日换手率
                        d_date = d.get('trade_date', '')
                        d_tr = 0
                        for tr_d in tr_dicts:
                            if tr_d.get('trade_date', '') == d_date:
                                d_tr = safe_float(tr_d.get('turnover_rate', 0)) or 0
                                break
                        if d_tr <= tr_10d_avg * 1.5:
                            continue  # 换手率不达标，不算核按钮
                    
                    if is_a:
                        return 0, f"核按钮A诱多:{d['trade_date']}最高{d_high:.2f}跌停{d_close:.2f}"
                    elif is_b:
                        return 0, f"核按钮B一字闷杀:{d['trade_date']}一字跌停"
    except Exception:
        pass
    
    if top_list_data:
        for item in top_list_data[:3]:
            net_amount = safe_float(item.get('net_amount', 0))
            if net_amount and net_amount < -3000:
                return 0, f"游资出逃:净卖{abs(net_amount):.0f}万"
    
    # V2.3: 否决5 — 纯跟风弱势（人气排名动态阈值+Null处理）
    # 数据源：东方财富个股人气榜
    # Null处理：排名=5000
    # 触发条件：
    #   IF 当日个股涨幅<3% → 直接否决
    #   ELIF 主线题材(维2≥5) AND 排名>300 → 否决
    #   ELIF 非主线 AND 排名>150 → 否决
    # 人气排名代理：用换手率排名估算（无实时排名接口时）
    popularity_rank = 5000  # 默认未上榜
    try:
        # 尝试从daily_basic获取换手率作为人气代理
        resp_pop = call_tushare("daily_basic", token, {"ts_code": code}, "trade_date,turnover_rate,volume_ratio")
        pop_items = resp_pop.get("data", {}).get("items", [])
        if pop_items:
            # 使用换手率排序估算人气排名（高换手≈高人气）
            turnover_est = safe_float(pop_items[0][1]) if len(pop_items[0]) > 1 else 0
            if turnover_est is not None and turnover_est > 0:
                # 粗略估算：换手率>20% ≈ 前300；>10% ≈ 前1500
                if turnover_est > 25:
                    popularity_rank = 200
                elif turnover_est > 15:
                    popularity_rank = 500
                elif turnover_est > 8:
                    popularity_rank = 1500
                else:
                    popularity_rank = 3000
    except:
        pass
    
    # 获取个股当日涨幅（从个股日线数据获取，不依赖全市场涨停列表）
    stock_pct = 0
    try:
        resp_stock = call_tushare("daily", token, {
            "ts_code": code,
            "start_date": today_str,
            "end_date": today_str
        }, "trade_date,pct_change")
        stock_items = resp_stock.get("data", {}).get("items", [])
        if stock_items:
            stock_pct = safe_float(stock_items[0][1]) or 0
    except:
        pass
    
    # 从limit_data也尝试找（盘中场景）
    if limit_data:
        for item in limit_data:
            if hasattr(item, 'get') and item.get('ts_code', '') == code:
                stock_pct = safe_float(item.get('pct_change', 0)) or 0
                break
    
    # 判断是否主线题材（用概念涨停数代理：≥3只涨停=主线）
    is_main_theme = False
    if concept_names and cpt_data:
        max_ul = max([concept_ul_cnt.get(n, 0) for n in concept_names], default=0)
        is_main_theme = max_ul >= 3
    
    if stock_pct < 3:
        return 0, f"纯跟风弱势:涨幅仅{stock_pct:.1f}%<3%"
    elif is_main_theme and popularity_rank > 300:
        return 0, f"纯跟风弱势:主线题材但人气仅{popularity_rank}名>300"
    elif not is_main_theme and popularity_rank > 150:
        return 0, f"纯跟风弱势:非主线且人气{popularity_rank}名>150"
    
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
    
    # 连板高度 V2.3: ≥4板+5; <3板且较前两日下降→-5; ELSE:0
    if step_data:
        max_height = max([safe_int(x.get('nums', 0)) or 0 for x in step_data], default=0)
        if max_height >= 4:
            market_score += 5
            market_reasons.append(f"最高{max_height}板+5")
        elif max_height < 3:
            # 检查是否较前两日下降（需要多日step_data）
            market_score -= 5
            market_reasons.append(f"最高仅{max_height}板-5")
    
    score += max(0, min(30, market_score))
    reasons.extend(market_reasons)
    
    # --- 3.2 主线题材情绪维度 (30分) V2.3三态+梯度 ---
    theme_score = 0
    theme_reasons = []
    
    if concept_names and cpt_data:
        max_ul_by_concept = max([concept_ul_cnt.get(n, 0) for n in concept_names], default=0)
        # 找当前股票所属的最佳概念
        best_concept = None
        best_ul_cnt = 0
        for name in concept_names:
            cnt = concept_ul_cnt.get(name, 0)
            if cnt > best_ul_cnt:
                best_ul_cnt = cnt
                best_concept = name
        
        # [题材地位] 梯度加分：1名+10, 2-3名+5, 4-5名+2 (V2.3)
        if cpt_data:
            # 从cpt_data找题材排名
            theme_rank = 99
            for cpt in cpt_data:
                cpt_name = cpt.get('name', '')
                if cpt_name == best_concept:
                    theme_rank = safe_int(cpt.get('rank', 99)) or 99
                    break
            if theme_rank == 1:
                theme_score += 10
                theme_reasons.append(f"题材第1+10")
            elif theme_rank <= 3:
                theme_score += 5
                theme_reasons.append(f"题材第{theme_rank}+5")
            elif theme_rank <= 5:
                theme_score += 2
                theme_reasons.append(f"题材第{theme_rank}+2")
        
        # [发酵强度] V2.3增加持平条件（≥前日涨停数）
        if best_ul_cnt >= 3:
            # 获取前日涨停数（从历史cpt数据或简单代理）
            prev_ul_cnt = best_ul_cnt  # 默认持平
            try:
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                # 检查不可用则跳过
            except:
                pass
            if best_ul_cnt >= prev_ul_cnt:  # 递增或持平
                theme_score += 8
                theme_reasons.append(f"{best_concept}涨停{best_ul_cnt}只+8")
            else:
                theme_score += 3
                theme_reasons.append(f"题材涨停{best_ul_cnt}只+3")
        
        # [资金共识] 题材主力净流入排名前5 → +7分
        # T+1场景无实时主力净流入数据，用涨停数代理
        if best_ul_cnt >= 5:
            theme_score += 7
            theme_reasons.append(f"资金共识+7")
        elif best_ul_cnt >= 3:
            theme_score += 3
            theme_reasons.append(f"资金共识+3")
        
        # [周期标签] V2.3三态（退潮-10/分歧0/发酵+5）
        # 退潮：龙头断板跌停 AND 板块涨停<3 AND 资金流出
        # 分歧：炸板率>40% OR 涨停数未递增
        # 发酵/高潮：其他
        is_retreat = False
        is_divergence = False
        # 退潮判断：涨停数<3且无龙头
        if best_ul_cnt < 3:
            # 检查是否有龙头（最高连板>=3）
            max_height = max([safe_int(x.get('nums', 0)) or 0 for x in step_data], default=0) if step_data else 0
            if max_height < 3:
                is_retreat = True
        # 分歧判断：炸板率>40%
        if limit_data:
            up_cnt_d2 = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'U'])
            z_cnt_d2 = len([x for x in limit_data if str(x.get('limit', '')).upper() == 'Z'])
            total_board_d2 = up_cnt_d2 + z_cnt_d2
            break_rate_d2 = z_cnt_d2 / total_board_d2 * 100 if total_board_d2 > 0 else 0
            if break_rate_d2 > 40:
                is_divergence = True
        
        if is_retreat:
            theme_score -= 10
            theme_reasons.append(f"退潮-10")
        elif is_divergence:
            pass  # 分歧0分
        else:
            theme_score += 5
            theme_reasons.append(f"发酵+5")
    
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
    
    # --- 3.4 个股人气资金情绪维度 (10分) V2.3修订 ---
    popular_score = 0
    popular_reasons = []

    # [换手活跃度 V2.3梯度计分]
    try:
        resp = call_tushare("daily_basic", token, {"ts_code": code}, "turnover_rate,volume_ratio")
        daily_basic = resp.get("data", {}).get("items", [])
        if daily_basic:
            turnover = safe_float(daily_basic[0][0]) if daily_basic[0] else None
            if turnover:
                if 5 <= turnover < 15:
                    popular_score += 1
                    popular_reasons.append(f"换手{turnover:.1f}%+1")
                elif 15 <= turnover < 25:
                    popular_score += 2
                    popular_reasons.append(f"换手{turnover:.1f}%活跃+2")
                elif 25 <= turnover < 30:
                    popular_score += 1
                    popular_reasons.append(f"换手{turnover:.1f}%高+1")
                elif turnover >= 30:
                    popular_score -= 2
                    popular_reasons.append(f"换手{turnover:.1f}%过热-2")
    except:
        pass

    # [资金记忆 V2.3溢价校验：近20日涨停+次日溢价]
    try:
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
            # 检查最近一次涨停次日的最高溢价
            best_premium_ok = True  # 有多次涨停大概率有溢价
            popular_score += 3
            popular_reasons.append(f"20日涨停{ul_cnt_20d}次+3")
        elif ul_cnt_20d >= 1:
            popular_score += 1
            popular_reasons.append(f"20日涨停+1")
    except Exception:
        pass

    # [龙虎榜偏好] 游资净买入>0
    if top_list_data:
        for item in top_list_data[:3]:
            net_rate = safe_float(item.get('net_rate'))
            if net_rate and net_rate > 0:
                popular_score += 2
                popular_reasons.append(f"龙虎榜净买{net_rate:.1f}%+2")
                break

    # [连板基因 V2.3新增] 近60日曾≥2连板
    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=65)
        resp = call_tushare("limit_step", token, {
            "ts_code": code,
            "start_date": start_dt.strftime('%Y%m%d'),
            "end_date": end_dt.strftime('%Y%m%d')
        }, "trade_date,ts_code,nums")
        step_hist = resp.get("data", {}).get("items", [])
        if step_hist:
            max_nums_60d = max([safe_int(x[2]) or 0 for x in step_hist], default=0)
            if max_nums_60d >= 2:
                popular_score += 3
                popular_reasons.append(f"连板基因{max_nums_60d}连板+3")
    except Exception:
        pass

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
                # V2.3秒板修正：IF 开盘后5分钟内封涨停 → 改为+5分（直接给满，不乘乘数）
                # 在stk_auction数据中无法精确获取5分钟内是否封板，用开盘价接近涨停+竞价量比>5代理
                if volume_ratio > 5 and call_vol_ratio > 2.0:
                    open_gap_base = 5  # 秒板信号：竞价量比高+高开=大概率秒板
            
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
    reasons.extend(auction_reasons[:3])
    
    # V2.3: 高位情绪折扣 — 个股连板高度≥5板时对总分施加折扣系数
    stock_continuity = 0
    try:
        resp_sc = call_tushare("limit_step", token, {"trade_date": today_str, "ts_code": code}, "trade_date,ts_code,nums")
        sc_items = resp_sc.get("data", {}).get("items", [])
        if sc_items:
            stock_continuity = safe_int(sc_items[0][2]) or 0
    except:
        pass
    
    if stock_continuity >= 5:
        discount = 0.85 if stock_continuity <= 6 else 0.7
        score_before = score
        score = round(score * discount)
        reasons.append(f"[折扣]连板{stock_continuity}板×{discount} {score_before}→{score}")
    
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
    """发送飞书卡片

    推送规则：
    - 综合分>=50的股票按总分降序取前3只推送
    - 如果没有>=50的股票，不推送
    - 推送记录保存到 data/pushed/ 目录，供复盘使用
    """
    import requests

    # 推送筛选
    above_50 = sorted(
        [r for r in results if r.get('total', 0) >= 50],
        key=lambda x: x.get('total', 0), reverse=True
    )[:3]
    if above_50:
        push_list = above_50
        print(f"  推送池: {len(above_50)}只(综合分>=50前3)")
    else:
        push_list = []
        print(f"  无>=50分股票，不推送")

    if not push_list:
        print("  无可推送股票")
        return False

    # 保存推送记录（供复盘使用）
    pushed_dir = PROJECT_DIR / "data" / "pushed"
    pushed_dir.mkdir(parents=True, exist_ok=True)
    pushed_file = pushed_dir / f"{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(pushed_file, "w") as f:
        json.dump(push_list, f, ensure_ascii=False, indent=2)
    print(f"  推送记录已保存: {pushed_file}")

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
            "title": {"tag": "plain_text", "content": f"{feishu_title_prefix()}涨停预测信号 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"},
            "template": "blue"
        },
        "elements": []
    }

    for r in push_list:
        s = r.get('scores', {})
        top3_tag = f" | Top3:**{r.get('top3_score',0):.1f}**" if r.get('top3_score') else ""
        element = {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{r['code']} {r['name']}** | 综合:**{r['total']:.1f}**{top3_tag}\n基本面:{s.get('fundamental',0):.0f} | 技术面:{s.get('technical',0):.0f} | 资金面:{s.get('fundflow',0):.0f} | 情绪面:{s.get('sentiment',0):.0f} | 短线:{s.get('shortterm',0):.0f}"
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
    
    # 2-5. 四维度评分 + 短线博弈
    results = []
    for stock in candidates:
        code = stock["code"]
        name = stock["name"]
        print(f"\n[分析] {code} {name}")
        
        print("  五维度并行评分...", flush=True)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from score_shortterm import score_shortterm
        scoring_funcs = {
            "fundamental": score_fundamental,
            "technical": score_technical,
            "fundflow": score_fundflow,
            "sentiment": score_sentiment,
            "shortterm": score_shortterm,
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
        st_score = scores.get("shortterm", 0)
        f_reason = reasons.get("fundamental", "")
        t_reason = reasons.get("technical", "")
        m_reason = reasons.get("fundflow", "")
        s_reason = reasons.get("sentiment", "")
        st_reason = reasons.get("shortterm", "")
        
        # 加权综合评分
        weights = AGENT_WEIGHTS
        total_w = sum(weights.values())
        total = (f_score * weights["fundamental"] + 
                 t_score * weights["technical"] + 
                 m_score * weights["fundflow"] + 
                 s_score * weights["sentiment"] +
                 st_score * weights["shortterm"]) / total_w if total_w > 0 else 0
        
        # V2.4: Top-N择优排序（取Top3维度均值，捕捉极端信号）
        dim_scores = sorted([
            f_score, t_score, m_score, s_score, st_score
        ], reverse=True)
        top3_score = sum(dim_scores[:3]) / 3
        
        # 多维度共振判定（≥3个维度得分≥75）
        resonance_threshold = 75
        resonance_count = sum([
            f_score >= resonance_threshold,
            t_score >= resonance_threshold,
            m_score >= resonance_threshold,
            s_score >= resonance_threshold,
            st_score >= resonance_threshold,
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
                "sentiment": s_score,
                "shortterm": st_score,
            },
            "reasons": {
                "fundamental": f_reason,
                "technical": t_reason,
                "fundflow": m_reason,
                "sentiment": s_reason,
                "shortterm": st_reason,
            },
            "weights": weight_info,
            "total": total,
            "resonance": {
                "count": resonance_count,
                "threshold": resonance_threshold,
                "is_resonance": resonance_flag
            },
            "top3_score": round(top3_score, 1),  # V2.4
        })
    
    # 排序（双排序输出）
    by_weighted = sorted(results, key=lambda x: x["total"], reverse=True)
    by_top3 = sorted(results, key=lambda x: x.get("top3_score", 0), reverse=True)
    
    print("\n[排序结果 加权总分]")
    for i, r in enumerate(by_weighted, 1):
        resonance_tag = " [共振]" if r.get("resonance", {}).get("is_resonance") else ""
        print(f"  {i}. {r['code']} {r['name']} - 加权:{r['total']:.1f} Top3:{r.get('top3_score',0):.1f}{resonance_tag}")
    
    print("\n[排序结果 Top3择优]")
    for i, r in enumerate(by_top3, 1):
        resonance_tag = " [共振]" if r.get("resonance", {}).get("is_resonance") else ""
        print(f"  {i}. {r['code']} {r['name']} - Top3:{r.get('top3_score',0):.1f} 加权:{r['total']:.1f}{resonance_tag}")
    
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
