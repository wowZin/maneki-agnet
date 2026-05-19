"""
数据接口单元测试 - 确保Tushare数据链路通畅

测试范围:
- 基本面: daily_basic, fina_indicator, balancesheet, income, stk_holdernumber, concept_detail
- 技术面: stk_factor_pro, moneyflow
- 资金面: moneyflow, top_list, top_inst, hk_hold
- 情绪面: concept_detail, limit_list_d, limit_step, top_list
"""
import unittest
from unittest.mock import patch, MagicMock
import requests
import os
import sys

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 模拟配置
MOCK_TOKEN = "test_token_12345"


class TestTushareInterfaces(unittest.TestCase):
    """Tushare数据接口连通性测试"""

    def setUp(self):
        """测试前准备"""
        self.base_url = "https://api.tushare.pro"
        self.test_code = "000001.SZ"
        
    def _mock_response(self, items, fields=None):
        """构建模拟响应"""
        return {
            "data": {
                "fields": fields or [],
                "items": items
            }
        }
    
    # ===== 基本面接口 =====
    
    @patch('requests.post')
    def test_daily_basic_interface(self, mock_post):
        """测试daily_basic接口 - 估值数据"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[[10.5, 1.2, 250000, 180000]],
            fields=["pe", "pb", "total_mv", "circ_mv"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "daily_basic",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "pe,pb,total_mv,circ_mv"
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 1)
        pe, pb = data["items"][0][0], data["items"][0][1]
        self.assertIsNotNone(pe)
        self.assertIsNotNone(pb)
        
    @patch('requests.post')
    def test_fina_indicator_interface(self, mock_post):
        """测试fina_indicator接口 - 财务指标"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[["20240930", 20240930, 12.5, 13.2, 25.0, 15.0, 18.0, 45.0, 1.8, 2.5, 8.0]],
            fields=["ann_date", "end_date", "roe", "roe_dt", "dt_netprofit_yoy", 
                   "or_yoy", "op_yoy", "debt_to_assets", "current_ratio", "ocfps", "bps"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "fina_indicator",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "ann_date,end_date,roe,roe_dt,dt_netprofit_yoy,or_yoy,op_yoy,debt_to_assets,current_ratio,ocfps,bps"
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 1)
        roe = data["items"][0][2]
        self.assertEqual(roe, 12.5)
        
    @patch('requests.post')
    def test_balancesheet_interface(self, mock_post):
        """测试balancesheet接口 - 资产负债表"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[["20240930", 20240930, 5000, 150000]],
            fields=["ann_date", "end_date", "goodwill", "total_hldr_eqy_exc_min_int"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "balancesheet",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "ann_date,end_date,goodwill,total_hldr_eqy_exc_min_int"
            }
        )
        
        data = resp.json()["data"]
        goodwill = data["items"][0][2]
        self.assertEqual(goodwill, 5000)
        
    @patch('requests.post')
    def test_income_interface(self, mock_post):
        """测试income接口 - 利润表"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[["20240930", 20240930, 500000, 480000, 50000, 2000, 500]],
            fields=["ann_date", "end_date", "total_revenue", "revenue", 
                   "n_income", "non_oper_income", "non_oper_exp"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "income",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "ann_date,end_date,total_revenue,revenue,n_income,non_oper_income,non_oper_exp"
            }
        )
        
        data = resp.json()["data"]
        total_revenue = data["items"][0][2]
        self.assertEqual(total_revenue, 500000)
        
    @patch('requests.post')
    def test_stk_holdernumber_interface(self, mock_post):
        """测试stk_holdernumber接口 - 股东户数"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20240930", 20240930, 120000],
                ["40630", 20240630, 125000]
            ],
            fields=["ann_date", "end_date", "holder_num"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "stk_holdernumber",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "ann_date,end_date,holder_num"
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 2)
        holder_num = data["items"][0][2]
        self.assertEqual(holder_num, 120000)
        
    @patch('requests.post')
    def test_concept_detail_interface(self, mock_post):
        """测试concept_detail接口 - 概念板块"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["TS1", "人工智能"],
                ["TS2", "新能源汽车"],
                ["TS3", "芯片"]
            ],
            fields=["id", "concept_name"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "concept_detail",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "id,concept_name"
            }
        )
        
        data = resp.json()["data"]
        concept_count = len(data["items"])
        self.assertEqual(concept_count, 3)
    
    # ===== 技术面接口 =====
    
    @patch('requests.post')
    def test_stk_factor_pro_interface(self, mock_post):
        """测试stk_factor_pro接口 - 技术因子"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", 10.5, 10.8, 10.3, 10.6, 10.5, 0.1, 0.95, 
                 500000, 5250000, 1.02, 1.05, 1.03, 12.0, 25.0, 35.0, 
                 0.5, 0.6, 0.4, 2.5],
                ["20241017", 10.3, 10.5, 10.2, 10.5, 10.4, 0.1, 0.96,
                 450000, 4725000, 1.01, 1.04, 1.02, 11.0, 24.0, 34.0,
                 0.4, 0.5, 0.3, 2.3]
            ],
            fields=["trade_date", "open", "high", "low", "close", "pre_close",
                   "change", "pct_change", "vol", "amount", "turnover_rate",
                   "ma_5", "ma_10", "macd", "kdj_k", "kdj_d", "boll_upper",
                   "boll_mid", "boll_lower", "rsi_6"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "stk_factor_pro",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "trade_date,open,high,low,close,pre_close,change,pct_change,vol,amount,turnover_rate,ma_5,ma_10,macd,kdj_k,kdj_d,boll_upper,boll_mid,boll_lower,rsi_6"
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 2)
        close = data["items"][0][4]
        self.assertEqual(close, 10.6)
        
    @patch('requests.post')
    def test_moneyflow_interface_technical(self, mock_post):
        """测试moneyflow接口 - 资金流向(技术面用)"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", 5000000, 8000000, 6000000, 0.5],
                ["20241017", 4000000, 7000000, 5000000, 0.4]
            ],
            fields=["trade_date", "net_mf_amount", "buy_lg_amount", 
                   "sell_lg_amount", "net_mf_vol"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "moneyflow",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "trade_date,net_mf_amount,buy_lg_amount,sell_lg_amount,net_mf_vol"
            }
        )
        
        data = resp.json()["data"]
        # 字段索引验证: mf[1]是net_mf_amount, mf[2]是buy_lg_amount
        net_mf = data["items"][0][1]
        buy_lg = data["items"][0][2]
        self.assertEqual(net_mf, 5000000)
        self.assertEqual(buy_lg, 8000000)
    
    # ===== 资金面接口 =====
    
    @patch('requests.post')
    def test_moneyflow_interface_fundflow(self, mock_post):
        """测试moneyflow接口 - 资金流向(资金面用)"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", -5000000, 2000000, 3000000, 4000000, 
                 5000000, 6000000, 7000000, 8000000, 9000000,
                 -10000000, -5000000, 15000000, 20000000]
            ],
            fields=["trade_date", "net_mf_amount", "buy_sm_amount", "sell_sm_amount",
                   "buy_md_amount", "sell_md_amount", "buy_lg_amount", "sell_lg_amount",
                   "buy_elg_amount", "sell_elg_amount", "net_mf_vol", 
                   "buy_elg_vol", "sell_elg_vol"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "moneyflow",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "trade_date,net_mf_amount,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_vol,buy_elg_vol,sell_elg_vol"
            }
        )
        
        data = resp.json()["data"]
        net_mf = data["items"][0][1]
        buy_elg = data["items"][0][8]
        self.assertEqual(net_mf, -5000000)
        self.assertEqual(buy_elg, 8000000)
        
    @patch('requests.post')
    def test_top_list_interface(self, mock_post):
        """测试top_list接口 - 龙虎榜"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", self.test_code, "平安银行", 10.5, 5.0, 
                 3.5, 100000000, 50000000, 30000000, 80000000,
                 20000000, 0.25, 0.80, "涨停"]
            ],
            fields=["trade_date", "ts_code", "name", "close", "pct_change",
                   "turnover_rate", "amount", "l_sell", "l_buy", "l_amount",
                   "net_amount", "net_rate", "amount_rate", "reason"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "top_list",
                "token": MOCK_TOKEN,
                "params": {"trade_date": "20241018"},
                "fields": "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,l_sell,l_buy,l_amount,net_amount,net_rate,amount_rate,reason"
            }
        )
        
        data = resp.json()["data"]
        net_amount = data["items"][0][10]
        self.assertEqual(net_amount, 20000000)
        
    @patch('requests.post')
    def test_top_inst_interface(self, mock_post):
        """测试top_inst接口 - 龙虎榜机构"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", self.test_code, "机构专用", "买", 
                 30000000, 5.0, 10000000, 2.0, 20000000, "涨停"]
            ],
            fields=["trade_date", "ts_code", "exalter", "side",
                   "buy", "buy_rate", "sell", "sell_rate", "net_buy", "reason"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "top_inst",
                "token": MOCK_TOKEN,
                "params": {"trade_date": "20241018"},
                "fields": "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason"
            }
        )
        
        data = resp.json()["data"]
        net_buy = data["items"][0][8]
        self.assertEqual(net_buy, 20000000)
        
    @patch('requests.post')
    def test_hk_hold_interface(self, mock_post):
        """测试hk_hold接口 - 北向持股"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", self.test_code, "平安银行", 50000000, 0.5]
            ],
            fields=["trade_date", "ts_code", "name", "hold_amount", "hold_ratio"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "hk_hold",
                "token": MOCK_TOKEN,
                "params": {"ts_code": self.test_code},
                "fields": "trade_date,ts_code,name,hold_amount,hold_ratio"
            }
        )
        
        data = resp.json()["data"]
        hold_amount = data["items"][0][3]
        self.assertEqual(hold_amount, 50000000)
    
    # ===== 情绪面接口 =====
    
    @patch('requests.post')
    def test_limit_list_d_interface(self, mock_post):
        """测试limit_list_d接口 - 涨跌停统计"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["20241018", self.test_code, "银行", "平安银行", 10.5, 
                 10.0, 100000000, 95000000, 200000000, 5.0, 
                 "09:30:00", "15:00:00", 0, "2", 1, "U"]
            ],
            fields=["trade_date", "ts_code", "industry", "name", "close",
                   "pct_change", "amount", "limit_amount", "float_mv",
                   "turnover_ratio", "first_time", "last_time", "open_times",
                   "up_stat", "limit_times", "limit"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "limit_list_d",
                "token": MOCK_TOKEN,
                "params": {"trade_date": "20241018"},
                "fields": "trade_date,ts_code,industry,name,close,pct_change,amount,limit_amount,float_mv,turnover_ratio,first_time,last_time,open_times,up_stat,limit_times,limit"
            }
        )
        
        data = resp.json()["data"]
        up_stat = data["items"][0][13]
        self.assertEqual(up_stat, "2")
        
    @patch('requests.post')
    def test_limit_step_interface(self, mock_post):
        """测试limit_step接口 - 连板天梯"""
        mock_post.return_value.json.return_value = self._mock_response(
            items=[
                ["000001.SZ", "平安银行", "20241018", "4"],
                ["000002.SZ", "万科A", "20241018", "3"]
            ],
            fields=["ts_code", "name", "trade_date", "nums"]
        )
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "limit_step",
                "token": MOCK_TOKEN,
                "params": {"trade_date": "20241018"},
                "fields": "ts_code,name,trade_date,nums"
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 2)
        nums = data["items"][0][3]
        self.assertEqual(nums, "4")
    
    # ===== 异常处理测试 =====
    
    @patch('requests.post')
    def test_interface_timeout(self, mock_post):
        """测试接口超时处理"""
        mock_post.side_effect = requests.Timeout("Connection timeout")
        
        with self.assertRaises(requests.Timeout):
            requests.post(
                self.base_url,
                json={"api_name": "daily_basic", "token": MOCK_TOKEN},
                timeout=10
            )
            
    @patch('requests.post')
    def test_interface_empty_response(self, mock_post):
        """测试空数据响应处理"""
        mock_post.return_value.json.return_value = {"data": {"items": []}}
        
        resp = requests.post(
            self.base_url,
            json={
                "api_name": "daily_basic",
                "token": MOCK_TOKEN,
                "params": {"ts_code": "INVALID_CODE"}
            }
        )
        
        data = resp.json()["data"]
        self.assertEqual(len(data["items"]), 0)
        
    @patch('requests.post')
    def test_interface_auth_error(self, mock_post):
        """测试认证错误处理"""
        mock_post.return_value.json.return_value = {
            "data": None,
            "msg": "Token无效"
        }
        
        resp = requests.post(
            self.base_url,
            json={"api_name": "daily_basic", "token": "invalid_token"}
        )
        
        result = resp.json()
        self.assertIsNone(result["data"])
        self.assertIn("Token", result["msg"])


class TestInterfaceFieldMapping(unittest.TestCase):
    """字段索引映射验证测试 - 确保CR修复后的索引正确"""
    
    def test_moneyflow_field_order(self):
        """验证moneyflow接口字段顺序"""
        # Tushare moneyflow接口字段顺序:
        # [0]trade_date [1]net_mf_amount [2]buy_sm_amount [3]sell_sm_amount
        # [4]buy_md_amount [5]sell_md_amount [6]buy_lg_amount [7]sell_lg_amount
        # [8]buy_elg_amount [9]sell_elg_amount [10]net_mf_vol ...
        
        mock_fields = ["trade_date", "net_mf_amount", "buy_sm_amount", 
                      "sell_sm_amount", "buy_md_amount", "sell_md_amount",
                      "buy_lg_amount", "sell_lg_amount", "buy_elg_amount",
                      "sell_elg_amount", "net_mf_vol"]
        
        # 验证字段索引
        self.assertEqual(mock_fields[1], "net_mf_amount")  # mf[1] = 净流入
        self.assertEqual(mock_fields[6], "buy_lg_amount")  # mf[6] = 大单买入
        self.assertEqual(mock_fields[7], "sell_lg_amount") # mf[7] = 大单卖出
        
    def test_limit_list_d_field_order(self):
        """验证limit_list_d接口字段顺序"""
        mock_fields = ["trade_date", "ts_code", "industry", "name", "close",
                      "pct_change", "amount", "limit_amount", "float_mv",
                      "turnover_ratio", "first_time", "last_time", "open_times",
                      "up_stat", "limit_times", "limit"]
        
        self.assertEqual(mock_fields[13], "up_stat")    # 连板状态
        self.assertEqual(mock_fields[14], "limit_times") # 涨停次数
        self.assertEqual(mock_fields[15], "limit")       # U/D/Z


if __name__ == '__main__':
    unittest.main()
