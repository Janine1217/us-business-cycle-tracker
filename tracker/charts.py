"""儀表板圖表定義：每個指標（需求文件 #1–#29）要畫哪些線、怎麼轉換。

每張圖可以有多個「檢視」（例如原始數值／年增率），網頁上可切換。
trace 欄位：
  name  圖例名稱      data  [(日期, 數值)]   axis  "y"（左軸）或 "y2"（右軸）
  unit  單位          chg   變化幅度單位：pp 百分點、pct 百分比、pt 點數
  dash  虛線（代理指標或對照用）
"""
from __future__ import annotations

from . import store
from . import transform as tf

_cache: dict[str, list] = {}


def S(sid: str) -> list:
    if sid not in _cache:
        _cache[sid] = store.read_series(sid)
    return _cache[sid]


def M(sid: str, how: str = "mean") -> list:
    """月資料（日、週資料取月平均或月底值）。"""
    return tf.to_monthly(S(sid), how)


def T(name, data, unit, chg, axis="y", dash=False):
    return {"name": name, "data": data, "unit": unit, "chg": chg, "axis": axis, "dash": dash}


def V(name, traces, y_title="", y2_title="", hlines=None, log_ok=False, vlines=None):
    return {"name": name, "traces": traces, "y_title": y_title, "y2_title": y2_title,
            "hlines": hlines or [], "log_ok": log_ok, "vlines": vlines or []}


def build_charts(cfg: dict) -> list[dict]:
    p = cfg.get("params", {})
    core_lo, core_hi = p.get("core_cpi_band", [1.8, 3.0])
    stim = [{"x": s["date"], "label": s["name"]} for s in cfg.get("stimulus", [])]
    yoy = tf.yoy
    ma3 = lambda r: tf.ma(r, 3)  # noqa: E731

    fed_target = tf.splice(M("DFEDTAR", "last"), M("DFEDTARU", "last"), "2008-12-01")
    wti = tf.splice(S("WTISPLC"), M("DCOILWTICO"), "1986-01-01")
    sp500 = tf.extend(S("SHILLER_SP500"), M("SP500"))
    retail_yoy = yoy(S("RRSFS"))
    retail_proxy_yoy = tf.before(yoy(S("DGDSRA3M086SBEA")), retail_yoy[0][0] if retail_yoy else "9999")
    imp_m = ma3(yoy(S("BOPTIMP")))
    imp_q = tf.before(yoy(S("IMPGS")), imp_m[0][0] if imp_m else "9999")
    cape = S("SHILLER_CAPE")
    cape_p80 = tf.percentile([v for d, v in tf.since(cape, cfg["settings"]["backtest_start"])], 80)

    charts = [
        {"id": "1", "title": "聯邦基金利率", "sources": ["DFEDTARU", "DFEDTAR", "DFF"],
         "notes": ["目標利率：2008-12-15 以前為單一目標 DFEDTAR，之後為目標區間上限 DFEDTARU"],
         "views": [V("利率", [T("目標利率（上限）", fed_target, "%", "pp"),
                              T("有效利率", M("DFF"), "%", "pp", dash=True)], "%")]},
        {"id": "2", "title": "10 年期公債殖利率", "sources": ["DGS10"],
         "views": [V("殖利率", [T("10 年期公債殖利率（月平均）", M("DGS10"), "%", "pp")], "%")]},
        {"id": "3", "title": "30 年房貸平均利率", "sources": ["MORTGAGE30US"],
         "views": [V("利率", [T("30 年房貸利率（月平均）", M("MORTGAGE30US"), "%", "pp")], "%")]},
        {"id": "4a", "title": "油價（WTI）", "sources": ["DCOILWTICO", "WTISPLC"],
         "notes": ["1985 年使用月資料 WTISPLC，1986 年起為日資料 DCOILWTICO 的月平均"],
         "views": [V("價格", [T("WTI 原油", wti, "美元/桶", "pct")], "美元/桶"),
                   V("年增率", [T("WTI 原油年增率", yoy(wti), "%", "pp")], "%", hlines=[{"y": 0}])]},
        {"id": "4b", "title": "原物料價格", "sources": ["PPIACO", "PALLFNFINDEXM"],
         "views": [V("指數", [T("PPI 全部商品", S("PPIACO"), "1982=100", "pct"),
                              T("IMF 全球原物料價格", S("PALLFNFINDEXM"), "2016=100", "pct", axis="y2", dash=True)],
                     "PPI（1982=100）", "IMF（2016=100）"),
                   V("年增率", [T("PPI 全部商品年增率", yoy(S("PPIACO")), "%", "pp"),
                                T("IMF 原物料年增率", yoy(S("PALLFNFINDEXM")), "%", "pp", dash=True)],
                     "%", hlines=[{"y": 0}])]},
        {"id": "5", "title": "初領失業救濟金人數 vs 新開職缺", "sources": ["IC4WSA", "ICSA", "JTSJOL"],
         "notes": ["2020 年疫情期間數值極端，可切換對數刻度", "新開職缺（JOLTS）自 2000-12 起提供"],
         "views": [V("人數", [T("初領失業救濟金（4 週平均）", S("IC4WSA"), "人", "pct"),
                              T("新開職缺", S("JTSJOL"), "千人", "pct", axis="y2")],
                     "初領人數（人）", "新開職缺（千人）", log_ok=True),
                   V("年增率", [T("初領失業救濟金年增率", yoy(S("IC4WSA"), weekly=True), "%", "pp")],
                     "%", hlines=[{"y": 0}])]},
        {"id": "6", "title": "短期失業人數（失業 < 5 週）", "sources": ["UEMPLT5"],
         "views": [V("人數", [T("3 個月移動平均", ma3(S("UEMPLT5")), "千人", "pct"),
                              T("原始值", S("UEMPLT5"), "千人", "pct", dash=True)], "千人")]},
        {"id": "7", "title": "實質零售銷售年增率", "sources": ["RRSFS", "DGDSRA3M086SBEA"],
         "notes": ["1993 年以前（虛線）以實質個人消費支出－商品（DGDSRA3M086SBEA）年增率代理"],
         "views": [V("年增率", [T("實質零售銷售年增率", retail_yoy, "%", "pp"),
                                T("代理：實質商品消費年增率", retail_proxy_yoy, "%", "pp", dash=True)],
                     "%", hlines=[{"y": 0}]),
                   V("原始值", [T("實質零售及餐飲銷售", S("RRSFS"), "百萬美元", "pct")], "百萬美元（1982-84 幣值）")]},
        {"id": "8", "title": "私人非住宅固定投資年增率", "sources": ["PNFI", "PNFIC1"],
         "views": [V("年增率", [T("名目年增率", yoy(S("PNFI")), "%", "pp"),
                                T("實質年增率（對照）", yoy(S("PNFIC1")), "%", "pp", dash=True)],
                     "%", hlines=[{"y": 0}]),
                   V("原始值", [T("名目", S("PNFI"), "十億美元", "pct"),
                                T("實質（2017 連鎖）", S("PNFIC1"), "十億美元", "pct", dash=True)], "十億美元")]},
        {"id": "9", "title": "耐久財新訂單年增率", "sources": ["DGORDER"],
         "views": [V("年增率", [T("年增率（3 個月移動平均）", ma3(yoy(S("DGORDER"))), "%", "pp")],
                     "%", hlines=[{"y": 0}]),
                   V("原始值", [T("耐久財新訂單", S("DGORDER"), "百萬美元", "pct")], "百萬美元")]},
        {"id": "10", "title": "進口金額年增率", "sources": ["BOPTIMP", "IMPGS"],
         "notes": ["1993 年以前（虛線）以季資料 IMPGS 年增率補畫"],
         "views": [V("年增率", [T("月資料年增率（3 個月移動平均）", imp_m, "%", "pp"),
                                T("季資料年增率", imp_q, "%", "pp", dash=True)], "%", hlines=[{"y": 0}]),
                   V("原始值", [T("進口金額（月）", S("BOPTIMP"), "百萬美元", "pct"),
                                T("進口金額（季，年率）", S("IMPGS"), "十億美元", "pct", axis="y2", dash=True)],
                     "月（百萬美元）", "季（十億美元）")]},
        {"id": "11", "title": "個人消費支出 vs 可支配所得年增率", "sources": ["PCE", "DSPI"],
         "notes": ["成長期依據 1：可支配所得年增率 > 消費支出年增率，且連續 ≥ 3 個月"],
         "views": [V("年增率", [T("可支配所得年增率", ma3(yoy(S("DSPI"))), "%", "pp"),
                                T("消費支出年增率", ma3(yoy(S("PCE"))), "%", "pp")],
                     "%（3 個月移動平均）", hlines=[{"y": 0}])]},
        {"id": "12", "title": "非住宅 vs 住宅固定投資年增率", "sources": ["PNFI", "PRFI"],
         "views": [V("年增率", [T("非住宅固定投資", yoy(S("PNFI")), "%", "pp"),
                                T("住宅固定投資", yoy(S("PRFI")), "%", "pp")],
                     "%", hlines=[{"y": 0}, {"y": p.get("investment_growth_min", 5), "label": "5% 門檻"}])]},
        {"id": "13", "title": "核心 CPI 年增率", "sources": ["CPILFESL"],
         "views": [V("年增率", [T("核心 CPI 年增率", yoy(S("CPILFESL")), "%", "pp")], "%",
                     hlines=[{"y": core_lo, "label": f"{core_lo}%"}, {"y": core_hi, "label": f"{core_hi}%"}])]},
        {"id": "14", "title": "實質消費、實質可支配所得、實質零售銷售年增率",
         "sources": ["DPCERA3M086SBEA", "DSPIC96", "RRSFS", "PCECC96"],
         "views": [V("月資料", [T("實質個人消費支出", ma3(yoy(S("DPCERA3M086SBEA"))), "%", "pp"),
                                T("實質可支配所得", ma3(yoy(S("DSPIC96"))), "%", "pp"),
                                T("實質零售銷售", ma3(retail_yoy), "%", "pp", dash=True)],
                     "%（3 個月移動平均）", hlines=[{"y": 0}]),
                   V("季資料", [T("實質個人消費支出（季）年增率", yoy(S("PCECC96")), "%", "pp")],
                     "%", hlines=[{"y": 0}])]},
        {"id": "15", "title": "密西根大學消費者信心指數", "sources": ["UMCSENT"],
         "notes": ["經濟諮商局指數需付費；OECD 代理指數已停更或與密西根指數重複，目前只用密西根指數"],
         "views": [V("指數", [T("3 個月移動平均", ma3(S("UMCSENT")), "點", "pt"),
                              T("原始值", S("UMCSENT"), "點", "pt", dash=True)], "1966Q1=100")]},
        {"id": "16", "title": "耐久財訂單（不含運輸設備）", "sources": ["ADXTNO"],
         "notes": ["「二度衝高」型態標註將於階段 3 加入"],
         "views": [V("金額", [T("3 個月移動平均", ma3(S("ADXTNO")), "百萬美元", "pct"),
                              T("原始值", S("ADXTNO"), "百萬美元", "pct", dash=True)], "百萬美元"),
                   V("年增率", [T("年增率（3 個月移動平均）", ma3(yoy(S("ADXTNO"))), "%", "pp")],
                     "%", hlines=[{"y": 0}])]},
        {"id": "17", "title": "州和地方政府支出年增率", "sources": ["SLEXPND"],
         "views": [V("年增率", [T("州和地方政府當期支出年增率", yoy(S("SLEXPND")), "%", "pp")], "%", hlines=[{"y": 0}])]},
        {"id": "18", "title": "聯邦與州地方政府收入年增率", "sources": ["FGRECPT", "W023RC1Q027SBEA"],
         "views": [V("年增率", [T("聯邦政府收入", yoy(S("FGRECPT")), "%", "pp"),
                                T("州和地方政府收入", yoy(S("W023RC1Q027SBEA")), "%", "pp")], "%", hlines=[{"y": 0}])]},
        {"id": "19", "title": "消費性與企業貸款違約率", "sources": ["DRCLACBS", "DRBLACBS"],
         "views": [V("違約率", [T("消費性貸款", S("DRCLACBS"), "%", "pp"),
                                T("企業貸款", S("DRBLACBS"), "%", "pp")], "%")]},
        {"id": "20", "title": "實質民間投資", "sources": ["GPDIC1", "A007RA3Q086SBEA"],
         "views": [V("季增率", [T("實質國內私人投資毛額季增率", tf.pct_change(S("GPDIC1")), "%", "pp")],
                     "%（未年化）", hlines=[{"y": 0}]),
                   V("年增率", [T("實質國內私人投資毛額", yoy(S("GPDIC1")), "%", "pp"),
                                T("實質固定投資（不含存貨，對照）", yoy(S("A007RA3Q086SBEA")), "%", "pp", dash=True)],
                     "%", hlines=[{"y": 0}, {"y": -10, "label": "−10%"}])]},
        {"id": "21", "title": "製造業景氣（PMI 代理：費城聯準銀行製造業調查）", "sources": ["GACDFSA066MSFRBPHI"],
         "notes": ["ISM PMI 不在 FRED；本指數為擴散指數，0 為榮枯線（不是 50）"],
         "views": [V("指數", [T("3 個月移動平均", ma3(S("GACDFSA066MSFRBPHI")), "點", "pt"),
                              T("原始值", S("GACDFSA066MSFRBPHI"), "點", "pt", dash=True)], "擴散指數", hlines=[{"y": 0}])]},
        {"id": "23", "title": "刺激措施輔助數據", "sources": ["WALCL", "FGEXPND"],
         "notes": ["垂直線為 config.yaml 登記的政府刺激措施"],
         "views": [V("數值", [T("聯準會總資產", M("WALCL", "last"), "百萬美元", "pct"),
                              T("聯邦政府支出年增率", yoy(S("FGEXPND")), "%", "pp", axis="y2")],
                     "聯準會總資產（百萬美元）", "聯邦支出年增率（%）", vlines=stim)]},
        {"id": "24", "title": "實質 GDP 年增率與 CFNAI", "sources": ["GDPC1", "CFNAIMA3"],
         "notes": ["CFNAI > 0 代表成長高於長期趨勢"],
         "views": [V("數值", [T("實質 GDP 年增率", yoy(S("GDPC1")), "%", "pp"),
                              T("CFNAI（3 個月平均）", S("CFNAIMA3"), "點", "pt", axis="y2")],
                     "GDP 年增率（%）", "CFNAI", hlines=[{"y": 3, "label": "3%"}])]},
        {"id": "25", "title": "S&P 500 指數", "sources": ["SHILLER_SP500", "SP500", "NASDAQCOM"],
         "notes": ["席勒月資料（月平均收盤）；席勒資料尚未更新的月份以 FRED SP500 月平均補上"],
         "views": [V("指數", [T("S&P 500", sp500, "點", "pct"),
                              T("那斯達克（對照）", M("NASDAQCOM"), "點", "pct", axis="y2", dash=True)],
                     "S&P 500", "那斯達克", log_ok=True),
                   V("年增率", [T("S&P 500 年增率", yoy(sp500), "%", "pp")], "%",
                     hlines=[{"y": 0}, {"y": 15, "label": "15%"}]),
                   V("距高點", [T("距歷史高點", tf.drawdown(sp500), "%", "pp")], "%", hlines=[{"y": -5, "label": "−5%"}])]},
        {"id": "26", "title": "席勒本益比（CAPE）", "sources": ["SHILLER_CAPE"],
         "notes": [f"水平線為 1985 年以來第 80 百分位（{cape_p80:.1f} 倍）；回測時改用「當時以前」的資料計算"],
         "views": [V("倍數", [T("CAPE", cape, "倍", "pt")], "倍", hlines=[{"y": round(cape_p80, 2), "label": "第 80 百分位"}])]},
        {"id": "27", "title": "VIX 恐慌指數", "sources": ["VIXCLS"],
         "views": [V("指數", [T("VIX（月平均）", M("VIXCLS"), "點", "pt")], "點")]},
        {"id": "28", "title": "信用利差", "sources": ["BAA10Y", "BAMLH0A0HYM2"],
         "notes": ["ICE BofA 高收益債利差在 FRED 只提供最近 3 年，僅作近期對照"],
         "views": [V("利差", [T("Baa 公司債 − 10 年期公債", M("BAA10Y"), "百分點", "pp"),
                              T("ICE BofA 高收益債利差", M("BAMLH0A0HYM2"), "百分點", "pp", dash=True)], "百分點")]},
        {"id": "29", "title": "芝加哥聯準銀行金融情勢指數", "sources": ["NFCIRISK", "NFCI"],
         "notes": ["數值愈低代表金融情勢愈寬鬆、風險意識愈低"],
         "views": [V("指數", [T("風險分項", M("NFCIRISK"), "點", "pt"),
                              T("總指數", M("NFCI"), "點", "pt", dash=True)], "指數", hlines=[{"y": 0}])]},
    ]
    return charts
