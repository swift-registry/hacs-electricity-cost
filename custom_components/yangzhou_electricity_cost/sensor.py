"""扬州电费预估——多实体传感器。

由 coordinator 统一计算各周期电量与电费，本模块只负责创建展示实体。
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# (key, 名称, 单位, 图标, device_class)
ENTITIES: list[tuple[str, str, str, str, SensorDeviceClass | None]] = [
    ("annual_usage", "全年电量", "kWh", "mdi:counter", SensorDeviceClass.ENERGY),
    ("monthly_usage", "当月电量", "kWh", "mdi:counter", SensorDeviceClass.ENERGY),
    ("daily_usage", "当日电量", "kWh", "mdi:counter", SensorDeviceClass.ENERGY),
    ("monthly_peak", "当月峰电量", "kWh", "mdi:weather-sunny", SensorDeviceClass.ENERGY),
    ("monthly_valley", "当月谷电量", "kWh", "mdi:weather-night", SensorDeviceClass.ENERGY),
    ("daily_peak", "当日峰电量", "kWh", "mdi:weather-sunny", SensorDeviceClass.ENERGY),
    ("daily_valley", "当日谷电量", "kWh", "mdi:weather-night", SensorDeviceClass.ENERGY),
    ("yesterday_peak", "昨日峰电量", "kWh", "mdi:weather-sunny", SensorDeviceClass.ENERGY),
    ("yesterday_valley", "昨日谷电量", "kWh", "mdi:weather-night", SensorDeviceClass.ENERGY),
    ("monthly_cost", "当月电费", "元", "mdi:cash-multiple", None),
    ("daily_cost", "当日电费", "元", "mdi:cash", None),
    ("yesterday_cost", "昨日电费", "元", "mdi:cash", None),
    ("annual_cost", "全年电费", "元", "mdi:cash-multiple", None),
    ("seven_day_cost", "近7日电费", "元", "mdi:calendar-week", None),
    ("seven_day_usage", "近7日电量", "kWh", "mdi:calendar-week", SensorDeviceClass.ENERGY),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """创建全部展示实体。"""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            YangzhouSensor(coordinator, entry.entry_id, key, name, unit, icon, dc)
            for (key, name, unit, icon, dc) in ENTITIES
        ]
    )


class YangzhouSensor(CoordinatorEntity, SensorEntity):
    """单个展示实体，从 coordinator.data 读取对应字段。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry_id: str,
        key: str,
        name: str,
        unit: str,
        icon: str,
        device_class: SensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if device_class is not None:
            self._attr_device_class = device_class
        # 当月电费沿用旧 unique_id，避免产生重复实体
        if key == "monthly_cost":
            self._attr_unique_id = f"{entry_id}_cost"
        else:
            self._attr_unique_id = f"{entry_id}_{key}"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return None
        val = data.get(self._key)
        if val is None:
            return None
        try:
            return round(float(val), 2)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data:
            return None
        attrs = {
            "源传感器": self.coordinator.source_sensor,
            "当前总读数(kWh)": round(data.get("current_reading", 0.0), 2),
            "当前阶梯": data.get("current_tier", "未知"),
        }
        # 电费实体附带对应电量明细
        if self._key == "monthly_cost":
            attrs["峰电量(kWh)"] = round(data.get("monthly_peak", 0.0), 2)
            attrs["谷电量(kWh)"] = round(data.get("monthly_valley", 0.0), 2)
        elif self._key == "daily_cost":
            attrs["峰电量(kWh)"] = round(data.get("daily_peak", 0.0), 2)
            attrs["谷电量(kWh)"] = round(data.get("daily_valley", 0.0), 2)
        elif self._key == "yesterday_cost":
            attrs["峰电量(kWh)"] = round(data.get("yesterday_peak", 0.0), 2)
            attrs["谷电量(kWh)"] = round(data.get("yesterday_valley", 0.0), 2)
        elif self._key == "seven_day_cost":
            attrs["近7日总电量(kWh)"] = round(data.get("seven_day_usage", 0.0), 2)
            attrs["近7日峰电量(kWh)"] = round(data.get("seven_day_peak", 0.0), 2)
            attrs["近7日谷电量(kWh)"] = round(data.get("seven_day_valley", 0.0), 2)
            # 7天每日明细：第1天=今日，第7天=6天前
            daily_history = data.get("daily_history_7d", [])
            for i, day_data in enumerate(daily_history):
                label = f"第{i + 1}天({day_data['date']})"
                attrs[f"{label}电费(元)"] = day_data["cost"]
                attrs[f"{label}电量(kWh)"] = day_data["usage"]
                attrs[f"{label}峰电量(kWh)"] = day_data["peak"]
                attrs[f"{label}谷电量(kWh)"] = day_data["valley"]
        elif self._key == "seven_day_usage":
            attrs["近7日峰电量(kWh)"] = round(data.get("seven_day_peak", 0.0), 2)
            attrs["近7日谷电量(kWh)"] = round(data.get("seven_day_valley", 0.0), 2)
            attrs["近7日总电费(元)"] = round(data.get("seven_day_cost", 0.0), 2)
        return attrs
