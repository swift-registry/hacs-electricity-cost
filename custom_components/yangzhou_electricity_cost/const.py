"""常量定义。"""

DOMAIN = "yangzhou_electricity_cost"
DEFAULT_NAME = "扬州预估电费"

# 配置键
CONF_SOURCE_SENSOR = "source_sensor"
CONF_NAME = "name"
CONF_PEAK_RATIO = "peak_ratio"
CONF_PRICE_PEAK = "price_peak"
CONF_PRICE_VALLEY = "price_valley"
CONF_TIER2_ADD = "tier2_add"
CONF_TIER3_ADD = "tier3_add"
CONF_TIER1_LIMIT = "tier1_limit"
CONF_TIER2_LIMIT = "tier2_limit"

# 默认值
DEFAULT_SOURCE_SENSOR = "sensor.zhi_neng_dian_biao_dian_li"
DEFAULT_PEAK_RATIO = 65.0       # 峰段占比 (%)
DEFAULT_PRICE_PEAK = 0.5583      # 峰段电价 (元/kWh)
DEFAULT_PRICE_VALLEY = 0.3583    # 谷段电价 (元/kWh)
DEFAULT_TIER2_ADD = 0.05         # 第二档加价 (元/kWh)
DEFAULT_TIER3_ADD = 0.30         # 第三档加价 (元/kWh)
DEFAULT_TIER1_LIMIT = 2760.0     # 第一档年累计上限 (kWh)
DEFAULT_TIER2_LIMIT = 4800.0     # 第二档年累计上限 (kWh)
