"""扬州电费预估传感器。

计费规则（江苏扬州居民，先峰谷后阶梯）：
- 峰段(8:00-21:00) 0.5583 元/度，谷段(21:00-次日8:00) 0.3583 元/度
- 阶梯按自然年累计：第一档<=2760度；第二档2761-4800度加价0.05；第三档>4800度加价0.30
- 本月电费 = 本月用电量×峰谷价 + 本月新增阶梯加价
- 本月用电量 = 当前累计读数 - 本月1日0点读数
- 本年累计   = 当前累计读数 - 今年1月1日0点读数
"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NAME,
    CONF_PEAK_RATIO,
    CONF_PRICE_PEAK,
    CONF_PRICE_VALLEY,
    CONF_SOURCE_SENSOR,
    CONF_TIER1_LIMIT,
    CONF_TIER2_ADD,
    CONF_TIER2_LIMIT,
    CONF_TIER3_ADD,
    DEFAULT_NAME,
    DEFAULT_PEAK_RATIO,
    DEFAULT_PRICE_PEAK,
    DEFAULT_PRICE_VALLEY,
    DEFAULT_SOURCE_SENSOR,
    DEFAULT_TIER1_LIMIT,
    DEFAULT_TIER2_ADD,
    DEFAULT_TIER2_LIMIT,
    DEFAULT_TIER3_ADD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _tier_surcharge(
    annual_kwh: float,
    tier1_limit: float,
    tier2_limit: float,
    tier2_add: float,
    tier3_add: float,
) -> float:
    """给定年累计用电量，返回对应的阶梯加价总额。"""
    if annual_kwh <= tier1_limit:
        return 0.0
    if annual_kwh <= tier2_limit:
        return (annual_kwh - tier1_limit) * tier2_add
    return (tier2_limit - tier1_limit) * tier2_add + (annual_kwh - tier2_limit) * tier3_add


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """根据 UI 配置创建传感器实体。"""
    cfg = dict(entry.data) | dict(entry.options)
    async_add_entities(
        [
            YangzhouCostSensor(
                name=cfg.get(CONF_NAME, DEFAULT_NAME),
                source_sensor=cfg.get(CONF_SOURCE_SENSOR, DEFAULT_SOURCE_SENSOR),
                peak_ratio=cfg.get(CONF_PEAK_RATIO, DEFAULT_PEAK_RATIO),
                price_peak=cfg.get(CONF_PRICE_PEAK, DEFAULT_PRICE_PEAK),
                price_valley=cfg.get(CONF_PRICE_VALLEY, DEFAULT_PRICE_VALLEY),
                tier2_add=cfg.get(CONF_TIER2_ADD, DEFAULT_TIER2_ADD),
                tier3_add=cfg.get(CONF_TIER3_ADD, DEFAULT_TIER3_ADD),
                tier1_limit=cfg.get(CONF_TIER1_LIMIT, DEFAULT_TIER1_LIMIT),
                tier2_limit=cfg.get(CONF_TIER2_LIMIT, DEFAULT_TIER2_LIMIT),
                entry_id=entry.entry_id,
            )
        ]
    )


class YangzhouCostSensor(SensorEntity):
    """扬州电费预估传感器（本月电费）。"""

    _attr_should_poll = False
    _attr_icon = "mdi:cash-multiple"
    _attr_unit_of_measurement = "元"
    _attr_has_entity_name = True

    def __init__(
        self,
        name: str,
        source_sensor: str,
        peak_ratio: float,
        price_peak: float,
        price_valley: float,
        tier2_add: float,
        tier3_add: float,
        tier1_limit: float,
        tier2_limit: float,
        entry_id: str,
    ) -> None:
        self._name = name
        self._source_sensor = source_sensor
        self._peak_ratio = peak_ratio
        self._price_peak = price_peak
        self._price_valley = price_valley
        self._tier2_add = tier2_add
        self._tier3_add = tier3_add
        self._tier1_limit = tier1_limit
        self._tier2_limit = tier2_limit

        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_cost"

        # 基线读数（从历史获取）
        self._month_start_reading: float | None = None
        self._year_start_reading: float | None = None
        self._cached_year: int | None = None
        self._cached_month: int | None = None

        # 计算结果
        self._current_reading = 0.0
        self._monthly_usage = 0.0
        self._annual_usage = 0.0
        self._current_tier = "未知"

    @property
    def extra_state_attributes(self):
        """返回细节属性。"""
        return {
            "源传感器": self._source_sensor,
            "本月用电量(kWh)": round(self._monthly_usage, 2),
            "本年累计用电量(kWh)": round(self._annual_usage, 2),
            "当前总读数(kWh)": round(self._current_reading, 2),
            "预估峰段占比": f"{self._peak_ratio:.0f}% (估算)",
            "当前阶梯": self._current_tier,
            "当前月份": f"{datetime.now().month}月",
            "说明": "本月电费=峰谷基础电费+阶梯加价(按年累计)；峰谷为按比例估算",
        }

    async def async_added_to_hass(self) -> None:
        """添加到 HA 后：先取基线，再监听源传感器变化。"""
        await self._refresh_baselines()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source_sensor], self._async_update_callback
            )
        )
        self._update_cost()

    @callback
    def _async_update_callback(self, event) -> None:
        """源传感器变化时重新计算；跨月/跨年时刷新基线。"""
        now = dt_util.as_local(dt_util.now())
        if now.year != self._cached_year or now.month != self._cached_month:
            self.hass.async_create_task(self._refresh_baselines())
        self._update_cost()
        self.async_write_ha_state()

    async def _refresh_baselines(self) -> None:
        """从 recorder 获取本月1日0点、今年1月1日0点的电表累计读数。"""
        now_local = dt_util.as_local(dt_util.now())
        self._cached_year = now_local.year
        self._cached_month = now_local.month

        month_start = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        year_start = now_local.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        self._month_start_reading = await self._get_reading_at(
            dt_util.as_utc(month_start)
        )
        self._year_start_reading = await self._get_reading_at(
            dt_util.as_utc(year_start)
        )
        _LOGGER.info(
            "电费基线已刷新：本月1日读数=%s，今年1月1日读数=%s",
            self._month_start_reading,
            self._year_start_reading,
        )
        self._update_cost()
        self.async_write_ha_state()

    async def _get_reading_at(self, utc_time) -> float | None:
        """获取指定时间点电表的累计读数（取该时刻最近一次历史状态）。"""
        try:
            from homeassistant.components.recorder import history

            result = await self.hass.async_add_executor_job(
                history.get_state, self.hass, utc_time, [self._source_sensor]
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("查询历史读数失败(%s)：%s", utc_time, err)
            return None

        if not result:
            return None
        states = result.get(self._source_sensor)
        if not states:
            return None
        try:
            value = float(states[0].state)
        except (ValueError, TypeError):
            _LOGGER.warning("历史读数无法转换：%s", states[0].state)
            return None
        # states[0] 应为该时刻的状态；若其发生时间晚于查询点，说明该点之前无数据
        if states[0].last_changed > utc_time:
            _LOGGER.warning("在 %s 之前没有 %s 的历史数据", utc_time, self._source_sensor)
            return None
        return value

    def _update_cost(self) -> None:
        """核心计算：本月电费。"""
        state = self.hass.states.get(self._source_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            return

        try:
            self._current_reading = float(state.state)
        except (ValueError, TypeError):
            _LOGGER.error("电表读数转换错误: %s", state.state)
            return

        # 基线：若历史取不到，则用当前读数（本月/本年用量从 0 起算）
        month_base = (
            self._month_start_reading
            if self._month_start_reading is not None
            else self._current_reading
        )
        year_base = (
            self._year_start_reading
            if self._year_start_reading is not None
            else self._current_reading
        )

        monthly_usage = max(0.0, self._current_reading - month_base)
        annual_usage = max(0.0, self._current_reading - year_base)

        # 1. 峰谷基础电费（按比例估算峰谷）
        peak_kwh = monthly_usage * (self._peak_ratio / 100.0)
        valley_kwh = monthly_usage * (1 - self._peak_ratio / 100.0)
        base_cost = peak_kwh * self._price_peak + valley_kwh * self._price_valley

        # 2. 阶梯加价：本月增量 = 年累计加价(现在) - 月初时年累计加价
        annual_at_month_start = max(0.0, month_base - year_base)
        surcharge_now = _tier_surcharge(
            annual_usage,
            self._tier1_limit,
            self._tier2_limit,
            self._tier2_add,
            self._tier3_add,
        )
        surcharge_at_month_start = _tier_surcharge(
            annual_at_month_start,
            self._tier1_limit,
            self._tier2_limit,
            self._tier2_add,
            self._tier3_add,
        )
        incremental_surcharge = max(0.0, surcharge_now - surcharge_at_month_start)

        self._monthly_usage = monthly_usage
        self._annual_usage = annual_usage
        if annual_usage > self._tier2_limit:
            self._current_tier = "第三档"
        elif annual_usage > self._tier1_limit:
            self._current_tier = "第二档"
        else:
            self._current_tier = "第一档"

        self._attr_native_value = round(base_cost + incremental_surcharge, 2)
