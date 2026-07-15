"""配置与选项流（支持网页 UI 添加与管理）。"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
)

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


class YangzhouCostConfigFlow(ConfigFlow, domain=DOMAIN):
    """配置流。"""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """通过 UI 初次添加集成。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=user_input
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=DEFAULT_NAME
                ): str,
                vol.Required(
                    CONF_SOURCE_SENSOR,
                    default=DEFAULT_SOURCE_SENSOR,
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_PEAK_RATIO, default=DEFAULT_PEAK_RATIO
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_PRICE_PEAK, default=DEFAULT_PRICE_PEAK
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_PRICE_VALLEY, default=DEFAULT_PRICE_VALLEY
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """返回选项流，用于后续管理。"""
        return YangzhouCostOptionsFlow()


class YangzhouCostOptionsFlow(OptionsFlow):
    """选项流（集成配置好后可随时修改）。"""

    async def async_step_init(self, user_input=None):
        """管理界面主步骤。"""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options or self.config_entry.data
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME,
                    default=current.get(CONF_NAME, DEFAULT_NAME),
                ): str,
                vol.Required(
                    CONF_SOURCE_SENSOR,
                    default=current.get(
                        CONF_SOURCE_SENSOR, DEFAULT_SOURCE_SENSOR
                    ),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_PEAK_RATIO,
                    default=current.get(CONF_PEAK_RATIO, DEFAULT_PEAK_RATIO),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_PRICE_PEAK,
                    default=current.get(
                        CONF_PRICE_PEAK, DEFAULT_PRICE_PEAK
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_PRICE_VALLEY,
                    default=current.get(
                        CONF_PRICE_VALLEY, DEFAULT_PRICE_VALLEY
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_TIER2_ADD,
                    default=current.get(CONF_TIER2_ADD, DEFAULT_TIER2_ADD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_TIER3_ADD,
                    default=current.get(CONF_TIER3_ADD, DEFAULT_TIER3_ADD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_TIER1_LIMIT,
                    default=current.get(
                        CONF_TIER1_LIMIT, DEFAULT_TIER1_LIMIT
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_TIER2_LIMIT,
                    default=current.get(
                        CONF_TIER2_LIMIT, DEFAULT_TIER2_LIMIT
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
