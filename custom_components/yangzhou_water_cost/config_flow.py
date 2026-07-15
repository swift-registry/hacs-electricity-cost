"""配置与选项流（支持网页 UI 添加与管理）。"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import CONF_NAME, CONF_YHH, CONF_YHM, DEFAULT_NAME, DOMAIN


class YangzhouWaterConfigFlow(ConfigFlow, domain=DOMAIN):
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
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_YHH): str,
                vol.Required(CONF_YHM): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """返回选项流，用于后续管理。"""
        return YangzhouWaterOptionsFlow()


class YangzhouWaterOptionsFlow(OptionsFlow):
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
                    CONF_YHH,
                    default=current.get(CONF_YHH, ""),
                ): str,
                vol.Required(
                    CONF_YHM,
                    default=current.get(CONF_YHM, ""),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
