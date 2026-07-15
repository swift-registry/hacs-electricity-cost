"""扬州电费预估传感器。"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
                source_sensor=cfg.get(
                    CONF_SOURCE_SENSOR, DEFAULT_SOURCE_SENSOR
                ),
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
    """扬州电费预估传感器。"""

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
        self._current_total_kwh = 0.0

    @property
    def extra_state_attributes(self):
        """返回细节属性，便于在仪表盘查看。"""
        return {
            "源传感器": self._source_sensor,
            "当前总电量(kWh)": round(self._current_total_kwh, 2),
            "预估峰段占比": f"{self._peak_ratio:.0f}% (估算)",
            "当前月份": f"{datetime.now().month}月",
            "说明": "基于总电量估算，未区分实际峰谷读数",
        }

    async def async_added_to_hass(self) -> None:
        """添加到 HA 后监听源传感器变化。"""
        self.async_on_remove(
            self.hass.states.async_track_state_change_event(
                [self._source_sensor], self._async_update_callback
            )
        )
        self._update_cost()

    @callback
    def _async_update_callback(self, event) -> None:
        self._update_cost()
        self.async_write_ha_state()

    def _update_cost(self) -> None:
        """核心计算逻辑。"""
        state = self.hass.states.get(self._source_sensor)
        if state is None or state.state in ("unknown", "unavailable"):
            _LOGGER.warning("无法获取传感器 %s 的状态", self._source_sensor)
            return

        try:
            total_kwh = float(state.state)
            self._current_total_kwh = total_kwh

            peak_kwh = total_kwh * (self._peak_ratio / 100.0)
            valley_kwh = total_kwh * (1 - self._peak_ratio / 100.0)
            base_cost = (
                peak_kwh * self._price_peak
                + valley_kwh * self._price_valley
            )

            current_month = datetime.now().month
            monthly_tier1 = self._tier1_limit / 12
            monthly_tier2 = self._tier2_limit / 12
            cap_tier1 = monthly_tier1 * current_month
            cap_tier2 = monthly_tier2 * current_month

            surcharge = 0.0
            if total_kwh > cap_tier2:
                surcharge += (total_kwh - cap_tier2) * self._tier3_add
                surcharge += (cap_tier2 - cap_tier1) * self._tier2_add
            elif total_kwh > cap_tier1:
                surcharge += (total_kwh - cap_tier1) * self._tier2_add

            final_cost = base_cost + surcharge
            self._attr_native_value = round(final_cost, 2)
        except (ValueError, TypeError):
            _LOGGER.error("传感器数值转换错误: %s", state.state)
