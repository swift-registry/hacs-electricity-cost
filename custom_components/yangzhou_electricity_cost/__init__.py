"""扬州电费计算集成入口。"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import YangzhouCostCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """通过 UI 添加 / 恢复配置项时调用。"""
    cfg = dict(entry.data) | dict(entry.options)
    coordinator = YangzhouCostCoordinator(hass, cfg, entry.entry_id)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await coordinator.async_init()
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载集成。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    coordinator: YangzhouCostCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_close()
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """配置项更新后重新加载。"""
    await hass.config_entries.async_reload(entry.entry_id)
