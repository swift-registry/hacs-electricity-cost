"""扬州长江水务水费常量定义。"""

DOMAIN = "yangzhou_water_cost"
DEFAULT_NAME = "扬州长江水务"

# 配置键
CONF_NAME = "name"
CONF_YHH = "yhh"  # 用户号
CONF_YHM = "yhm"  # 用户名

# API
API_URL = (
    "https://cjsw.yzckjt.com/_web/_customize/yzcjkg/waterCost/api/search.rst"
)
API_TIMEOUT = 15  # 请求超时（秒）
UPDATE_INTERVAL_MINUTES = 30  # 拉取间隔（分钟）
