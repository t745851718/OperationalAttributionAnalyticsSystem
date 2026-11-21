from datetime import date

DEMO_END = date(2025, 6, 22)
DEMO_START = date(2025, 6, 19)
DIMENSIONS = {
    "day": "日期",
    "channel": "渠道",
    "region": "区域",
    "category": "品类",
    "segment": "客群",
}
DOMAIN_LABELS = {"ecommerce": "电商", "fmcg": "快消品"}
FACT_FIELDS = {
    "ecommerce": ("visits", "orders", "gmv", "stockouts", "promo_orders"),
    "fmcg": ("revenue", "materials", "logistics", "commission", "units"),
}


def metric(metric_id, name, domain, unit, formula="", model="atomic", threshold=0.08):
    return {
        "metric_id": metric_id,
        "name": name,
        "domain_id": domain,
        "type": "atomic" if model == "atomic" else "composite" if model != "ratio" else "derived",
        "model": model,
        "unit": unit,
        "formula": formula,
        "threshold": threshold,
    }


METRICS = [
    metric("gmv", "成交总额 GMV", "ecommerce", "CNY", "visits * conversion * aov", "mul"),
    metric("visits", "访客数", "ecommerce", "visit"),
    metric("orders", "订单数", "ecommerce", "order"),
    metric("conversion", "转化率", "ecommerce", "order/visit", "orders / visits", "ratio"),
    metric("aov", "客单价", "ecommerce", "CNY/order", "sales / orders", "ratio"),
    metric("sales", "订单实付金额", "ecommerce", "CNY"),
    metric("stockouts", "断货访客数", "ecommerce", "visit"),
    metric("promo_orders", "促销订单数", "ecommerce", "order"),
    metric("net_margin", "净利率", "fmcg", "ratio", "profit / revenue", "ratio", 0.05),
    metric("gross_margin", "毛利率", "fmcg", "ratio", "gross_profit / revenue", "ratio"),
    metric("gross_profit", "毛利", "fmcg", "CNY", "revenue - materials", "add"),
    metric("profit", "净利润", "fmcg", "CNY", "revenue - materials - logistics - commission", "add"),
    metric("revenue", "营收", "fmcg", "CNY"),
    metric("materials", "原材料成本", "fmcg", "CNY"),
    metric("logistics", "物流履约费", "fmcg", "CNY"),
    metric("commission", "渠道佣金", "fmcg", "CNY"),
    metric("units", "销量", "fmcg", "unit"),
]

EVENTS = [
    ("promotion-618", "ecommerce", "promotion", "618 大促结束", "2025-06-16", "2025-06-18",
     {"channel": ["信息流", "搜索", "会员"]}, "大促结束后投放收缩，观察渠道结构与转化变化。"),
    ("stockout-beauty", "ecommerce", "outage", "美妆高价款断货", "2025-06-19", "2025-06-22",
     {"category": ["美妆"]}, "高价款库存不足，订单向低价款迁移。"),
    ("materials-price", "fmcg", "macro", "饮品原料采购价上涨", "2025-06-18", "2025-06-23",
     {"category": ["饮品"]}, "主要原料的新采购价格开始执行。"),
    ("commission-adjust", "fmcg", "policy", "商超渠道佣金调整", "2025-06-19", "2025-06-24",
     {"channel": ["商超"]}, "新佣金费率生效。"),
]
