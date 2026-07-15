"""扬州长江水务水费——多实体传感器。

由 coordinator 统一拉取接口、解析数据，本模块只负责创建展示实体。
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
# 单位用 m³ 以兼容 HA 的 WATER 设备类；显示时 1 m³ = 1 吨
ENTITIES: list[tuple[str, str, str, str, SensorDeviceClass | None]] = [
    ("arrears", "欠费金额", "元", "mdi:currency-cny", None),
    ("latest_usage", "最近用水量", "m³", "mdi:water", SensorDeviceClass.WATER),
    ("latest_cost", "最近水费", "元", "mdi:cash", None),
    ("year_usage", "本年用水量", "m³", "mdi:water", SensorDeviceClass.WATER),
    ("year_cost", "本年水费", "元", "mdi:cash-multiple", None),
    ("total_usage", "累计用水量", "m³", "mdi:water", SensorDeviceClass.WATER),
    ("total_cost", "累计水费", "元", "mdi:cash-multiple", None),
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
            YangzhouWaterSensor(coordinator, entry.entry_id, key, name, unit, icon, dc)
            for (key, name, unit, icon, dc) in ENTITIES
        ]
    )


class YangzhouWaterSensor(CoordinatorEntity, SensorEntity):
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
            return val

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data:
            return None
        # 公共属性
        attrs = {
            "用户号": data.get("yhh", ""),
            "户名": data.get("yhm", ""),
            "用户地址": data.get("yhdz", ""),
            "供水状态": data.get("supply_status", ""),
            "抄表标识": data.get("cbbs", ""),
        }

        if self._key == "latest_usage":
            attrs["抄表日期"] = data.get("latest_date", "")
            attrs["上月指数"] = data.get("latest_prev_reading", "")
            attrs["本月指数"] = data.get("latest_curr_reading", "")
            attrs["收费情况"] = data.get("latest_status", "")
            attrs["水费(元)"] = round(data.get("latest_cost", 0.0), 2)
        elif self._key == "latest_cost":
            attrs["抄表日期"] = data.get("latest_date", "")
            attrs["用水量(m³)"] = round(data.get("latest_usage", 0.0), 2)
            attrs["收费情况"] = data.get("latest_status", "")
        elif self._key == "year_usage":
            attrs["本年抄表次数"] = data.get("year_count", 0)
            attrs["本年水费(元)"] = round(data.get("year_cost", 0.0), 2)
        elif self._key == "year_cost":
            attrs["本年抄表次数"] = data.get("year_count", 0)
            attrs["本年用水量(m³)"] = round(data.get("year_usage", 0.0), 2)
        elif self._key == "total_usage":
            attrs["累计水费(元)"] = round(data.get("total_cost", 0.0), 2)
            attrs["历史记录"] = data.get("recent_records", [])
        elif self._key == "total_cost":
            attrs["累计用水量(m³)"] = round(data.get("total_usage", 0.0), 2)
            attrs["历史记录"] = data.get("recent_records", [])
        elif self._key == "arrears":
            attrs["历史记录"] = data.get("recent_records", [])

        return attrs
