"""数据协调器：拉取扬州长江水务水费接口并解析。

接口返回用水记录列表（每次抄表一条），包含抄表日期、上月/本月指数、
用水量、实际金额、收费情况等。本协调器负责：
- 定时拉取接口
- 解析最新一条记录与本年/全部累计
- 对外暴露统一数据字典供传感器读取
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    API_TIMEOUT,
    API_URL,
    CONF_YHH,
    CONF_YHM,
    UPDATE_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _safe_float(value, default: float = 0.0) -> float:
    """安全转换为 float。"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class YangzhouWaterCoordinator(DataUpdateCoordinator):
    """扬州长江水务水费数据协调器。"""

    def __init__(self, hass: HomeAssistant, cfg: dict):
        super().__init__(
            hass,
            _LOGGER,
            name="yangzhou_water_cost",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.yhh = cfg.get(CONF_YHH, "")
        self.yhm = cfg.get(CONF_YHM, "")

    async def _async_update_data(self) -> dict:
        """拉取水费接口并解析。"""
        session = async_get_clientsession(self.hass)
        params = {"yhh": self.yhh, "yhm": self.yhm}
        try:
            async with session.get(
                API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"接口返回状态码 {resp.status}")
                result = await resp.json(content_type=None)
        except TimeoutError as err:
            raise UpdateFailed(f"请求水费接口超时: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"请求水费接口失败: {err}") from err

        if result.get("resultCode") != "00":
            raise UpdateFailed(
                f"接口返回错误: {result.get('errorMsg', '未知错误')}"
            )

        data = result.get("data") or {}
        return self._build_data(data)

    def _build_data(self, data: dict) -> dict:
        """解析原始数据为统一字典。"""
        # 用水记录按抄表日期升序排序
        records = list(data.get("ysjl") or [])
        records.sort(key=lambda r: r.get("cbrq", ""))

        latest = records[-1] if records else {}

        # 当前年份
        current_year = dt_util.as_local(dt_util.now()).year

        # 本年累计
        year_usage = 0.0
        year_cost = 0.0
        year_count = 0
        # 全部累计
        total_usage = 0.0
        total_cost = 0.0
        for r in records:
            usage = _safe_float(r.get("ysl"))
            cost = _safe_float(r.get("sjje"))
            total_usage += usage
            total_cost += cost
            cbrq = r.get("cbrq", "")
            if cbrq.startswith(str(current_year)):
                year_usage += usage
                year_cost += cost
                year_count += 1

        # 历史记录（用于属性展示，最近6条，降序）
        recent_records = []
        for r in reversed(records[-6:]):
            recent_records.append(
                {
                    "抄表日期": r.get("cbrq", ""),
                    "上月指数": r.get("syss", ""),
                    "本月指数": r.get("byss", ""),
                    "用水量(m³)": _safe_float(r.get("ysl")),
                    "水费(元)": _safe_float(r.get("sjje")),
                    "收费情况": r.get("sfqk", ""),
                }
            )

        return {
            "arrears": _safe_float(data.get("qfje")),
            "latest_usage": _safe_float(latest.get("ysl")),
            "latest_cost": _safe_float(latest.get("sjje")),
            "latest_date": latest.get("cbrq", ""),
            "latest_prev_reading": latest.get("syss", ""),
            "latest_curr_reading": latest.get("byss", ""),
            "latest_status": latest.get("sfqk", ""),
            "year_usage": year_usage,
            "year_cost": year_cost,
            "year_count": year_count,
            "total_usage": total_usage,
            "total_cost": total_cost,
            "supply_status": data.get("gsqk", ""),
            "yhh": data.get("yhh", self.yhh),
            "yhm": data.get("yhm", self.yhm),
            "yhdz": data.get("yhdz", ""),
            "cbbs": data.get("cbbs", ""),
            "current_year": current_year,
            "recent_records": recent_records,
        }
