from datetime import date, timedelta
from itertools import product
from random import Random

from backend.catalog import DEMO_END, DEMO_START

DATA_VERSION = "demo-202506-v1"
CHANNELS = {"ecommerce": ("信息流", "搜索", "会员"), "fmcg": ("商超", "经销", "直营")}
CATEGORIES = {"ecommerce": ("美妆", "家居", "数码"), "fmcg": ("饮品", "粮油", "休闲食品")}
REGIONS = ("华东", "华北", "华南")
SEGMENTS = ("新客", "复购")


def generate(domain):
    rng = Random(202506 if domain == "ecommerce" else 202507)
    starts = (DEMO_END - timedelta(days=100), date(2024, 6, 1))
    for start, days, variant in [(starts[0], 101, "actual"), (starts[1], 30, "actual"),
                                 (DEMO_START, 4, "target")]:
        for offset in range(days):
            day = start + timedelta(days=offset)
            incident = variant == "actual" and DEMO_START <= day <= DEMO_END
            for channel, region, category, segment in product(
                CHANNELS[domain], REGIONS, CATEGORIES[domain], SEGMENTS,
            ):
                row = dict(day=day.isoformat(), variant=variant, channel=channel,
                           region=region, category=category, segment=segment)
                weekday = 1.08 if day.weekday() >= 5 else 1
                if domain == "ecommerce":
                    channel_index = CHANNELS[domain].index(channel)
                    visits = int((610, 680, 520)[channel_index] * weekday * rng.uniform(.77, 1.23))
                    conversion = (.034, .059, .084)[channel_index] * (1.10 if segment == "复购" else 1)
                    promoted = variant == "actual" and date(2025, 6, 15) <= day < DEMO_START
                    if promoted:
                        visits = int(visits * 1.18)
                    if incident:
                        visits = int(visits * (1.06, .64, .53)[channel_index])
                        conversion *= .96
                    orders = max(1, round(visits * conversion * rng.uniform(.86, 1.14)))
                    aov = (218, 168, 393)[CATEGORIES[domain].index(category)] * rng.uniform(.86, 1.14)
                    stockout = incident and category == "美妆"
                    if stockout:
                        aov *= .66
                    row.update(visits=visits, orders=orders, gmv=round(orders * aov, 2),
                               stockouts=round(visits * (.22 if stockout else .013)),
                               promo_orders=round(orders * (.34 if promoted else .06)))
                else:
                    units = int(295 * weekday * rng.uniform(.75, 1.25))
                    price = (19, 16, 23)[CATEGORIES[domain].index(category)] * rng.uniform(.88, 1.12)
                    revenue = round(units * price, 2)
                    materials = units * (9.0, 8.0, 9.8)[CATEGORIES[domain].index(category)]
                    materials *= rng.uniform(.86, 1.14) * (1.40 if incident and category == "饮品" else 1)
                    commission = revenue * (.12, .074, .051)[CHANNELS[domain].index(channel)]
                    commission *= rng.uniform(.88, 1.12) * (1.41 if incident and channel == "商超" else 1)
                    row.update(units=units, revenue=revenue, materials=round(materials, 2),
                               logistics=round(units * rng.uniform(1.0, 1.6), 2),
                               commission=round(commission, 2))
                yield row
