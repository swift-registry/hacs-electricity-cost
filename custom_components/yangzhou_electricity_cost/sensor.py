"""扬州电费预估传感器。

计费规则（江苏扬州居民，先峰谷后阶梯）：
- 峰段(8:00-21:00) 0.5583 元/度，谷段(21:00-次日8:00) 0.3583 元/度
- 阶梯按自然年累计：第一档<=2760度；第二档2761-4800度加价0.05；第三档>4800度加价0.30
- 本月电费 = 峰电量×峰价 + 谷电量×谷价 + 本月新增阶梯加价

峰/谷电量由电表历史读数逐段计算：
  相邻两次读数差 = 该时段消耗电量，按其时间落在峰段/谷段分别累加。
"""

from __future__ import annotations

import logging
from datetime import timedelta

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
)

_LOGGER = logging.getLogger(__name__)

PEAK_START_HOUR = 8   # 峰段开始（含）
PEAK_END_HOUR = 21    # 峰段结束（不含）


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
        self._peak_ratio = peak_ratio  # 仅在无历史时作为回退估算
        self._price_peak = price_peak
        self._price_valley = price_valley
        self._tier2_add = tier2_add
        self._tier3_add = tier3_add
        self._tier1_limit = tier1_limit
        self._tier2_limit = tier2_limit

        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_cost"

        # 基线读数
        self._month_start_reading: float | None = None
        self._year_start_reading: float | None = None
        self._cached_year: int | None = None
        self._cached_month: int | None = None

        # 峰谷累加（本月）
        self._peak_kwh = 0.0
        self._valley_kwh = 0.0
        self._peak_kwh_display = 0.0
        self._valley_kwh_display = 0.0
        self._has_real_peak_valley = False

        # 增量更新用的上一次读数与时间
        self._last_reading: float | None = None
        self._last_time = None

        # 结果
        self._current_reading = 0.0
        self._monthly_usage = 0.0
        self._annual_usage = 0.0
        self._current_tier = "未知"

    @property
    def extra_state_attributes(self):
        """返回细节属性。"""
        return {
            "源传感器": self._source_sensor,
            "本月峰电量(kWh)": round(self._peak_kwh_display, 2),
            "本月谷电量(kWh)": round(self._valley_kwh_display, 2),
            "本月用电量(kWh)": round(self._monthly_usage, 2),
            "本年累计用电量(kWh)": round(self._annual_usage, 2),
            "当前总读数(kWh)": round(self._current_reading, 2),
            "当前阶梯": self._current_tier,
            "峰谷来源": "历史读数逐段计算" if self._has_real_peak_valley else "按比例估算(无历史)",
            "说明": "本月电费=峰谷电费+阶梯加价(按年累计)",
        }

    async def async_added_to_hass(self) -> None:
        """添加到 HA 后：刷新本月历史，再监听源传感器。"""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source_sensor], self._async_update_callback
            )
        )
        await self._refresh_month_history()

    @callback
    def _async_update_callback(self, event) -> None:
        """源传感器变化：增量累加新的一段电量并重算；跨月/跨年则刷新历史。"""
        now = dt_util.as_local(dt_util.now())
        if now.year != self._cached_year or now.month != self._cached_month:
            self.hass.async_create_task(self._refresh_month_history())
            return

        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            new_reading = float(new_state.state)
        except (ValueError, TypeError):
            return

        if (
            self._has_real_peak_valley
            and self._last_reading is not None
            and self._last_time is not None
        ):
            delta = new_reading - self._last_reading
            if delta > 0:
                peak, valley = self._split_peak_valley(
                    self._last_time, new_state.last_changed, delta
                )
                self._peak_kwh += peak
                self._valley_kwh += valley

        self._last_reading = new_reading
        self._last_time = new_state.last_changed
        self._current_reading = new_reading
        self._recompute_cost()
        self.async_write_ha_state()

    async def _refresh_month_history(self) -> None:
        """从 recorder 获取本月历史，逐段计算峰谷电量。"""
        now_local = dt_util.as_local(dt_util.now())
        self._cached_year = now_local.year
        self._cached_month = now_local.month

        month_start_local = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        year_start_local = now_local.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        self._year_start_reading = await self._get_reading_at(
            dt_util.as_utc(year_start_local)
        )

        states = await self._get_history(
            dt_util.as_utc(month_start_local), dt_util.now()
        )

        self._peak_kwh = 0.0
        self._valley_kwh = 0.0
        self._has_real_peak_valley = False
        self._month_start_reading = None
        self._last_reading = None
        self._last_time = None

        if states:
            try:
                self._month_start_reading = float(states[0].state)
            except (ValueError, TypeError):
                self._month_start_reading = None

            prev_reading = self._month_start_reading
            prev_time = states[0].last_changed
            for st in states[1:]:
                try:
                    cur = float(st.state)
                except (ValueError, TypeError):
                    continue
                if prev_reading is not None and prev_time is not None:
                    delta = cur - prev_reading
                    if delta > 0:
                        peak, valley = self._split_peak_valley(
                            prev_time, st.last_changed, delta
                        )
                        self._peak_kwh += peak
                        self._valley_kwh += valley
                prev_reading = cur
                prev_time = st.last_changed

            self._last_reading = prev_reading
            self._last_time = prev_time
            self._has_real_peak_valley = True
            _LOGGER.info(
                "本月历史已加载：峰%.2f 谷%.2f 度，月初读数=%s",
                self._peak_kwh,
                self._valley_kwh,
                self._month_start_reading,
            )
        else:
            _LOGGER.warning("未取到 %s 的本月历史，峰谷将按比例估算", self._source_sensor)

        # 取当前实时读数
        live = self.hass.states.get(self._source_sensor)
        if live is not None and live.state not in ("unknown", "unavailable"):
            try:
                self._current_reading = float(live.state)
                self._last_reading = self._current_reading
                self._last_time = dt_util.now()
            except (ValueError, TypeError):
                pass

        self._recompute_cost()
        self.async_write_ha_state()

    async def _get_history(self, start_utc, end_utc):
        """获取源传感器在 [start,end] 内的全部历史状态（含起始时刻状态）。"""
        try:
            from homeassistant.components.recorder import history

            result = await self.hass.async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start_utc,
                end_utc,
                [self._source_sensor],
                None,  # filters
                True,  # include_start_time_state
                False,  # significant_changes_only=False 取全部
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("查询历史区间失败(%s~%s)：%s", start_utc, end_utc, err)
            return []
        if not result:
            return []
        return result.get(self._source_sensor, [])

    async def _get_reading_at(self, utc_time) -> float | None:
        """获取指定时间点电表的累计读数。"""
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
            return None
        if states[0].last_changed > utc_time:
            _LOGGER.warning("在 %s 之前没有 %s 的历史数据", utc_time, self._source_sensor)
            return None
        return value

    def _split_peak_valley(self, t0, t1, delta):
        """将 [t0,t1] 区间的电量 delta 按峰谷时段拆分，返回 (峰, 谷)。"""
        if delta <= 0 or t1 <= t0:
            return 0.0, 0.0
        total = (t1 - t0).total_seconds()
        if total <= 0:
            return 0.0, 0.0

        # 区间内的峰谷分界点（8:00、21:00 本地时间）
        cuts = {t0, t1}
        day = dt_util.as_local(t0).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for _ in range(3):  # 区间很短，最多跨 1~2 天
            for hour in (PEAK_START_HOUR, PEAK_END_HOUR):
                b = dt_util.as_utc(day.replace(hour=hour))
                if t0 < b < t1:
                    cuts.add(b)
            day = day + timedelta(days=1)
            if dt_util.as_utc(day) > t1:
                break

        points = sorted(cuts)
        peak = valley = 0.0
        for i in range(len(points) - 1):
            s, e = points[i], points[i + 1]
            dur = (e - s).total_seconds()
            if dur <= 0:
                continue
            frac = delta * dur / total
            mid = s + (e - s) / 2
            if self._is_peak(mid):
                peak += frac
            else:
                valley += frac
        return peak, valley

    @staticmethod
    def _is_peak(utc_time) -> bool:
        local = dt_util.as_local(utc_time)
        return PEAK_START_HOUR <= local.hour < PEAK_END_HOUR

    def _recompute_cost(self) -> None:
        """根据峰谷电量与年累计阶梯计算本月电费。"""
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

        # 峰谷电量：有真实值就用真实值，否则按比例回退
        if self._has_real_peak_valley:
            peak_kwh = self._peak_kwh
            valley_kwh = self._valley_kwh
            # 以读数差为准做轻微校正（防止历史缺点导致偏差）
            real_total = peak_kwh + valley_kwh
            if real_total > 0 and abs(real_total - monthly_usage) > 0.01:
                scale = monthly_usage / real_total
                peak_kwh *= scale
                valley_kwh *= scale
        else:
            peak_kwh = monthly_usage * (self._peak_ratio / 100.0)
            valley_kwh = monthly_usage * (1 - self._peak_ratio / 100.0)

        base_cost = peak_kwh * self._price_peak + valley_kwh * self._price_valley

        # 阶梯加价：本月增量 = 年累计加价(现在) - 月初时年累计加价
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

        self._peak_kwh_display = peak_kwh
        self._valley_kwh_display = valley_kwh
        self._monthly_usage = monthly_usage
        self._annual_usage = annual_usage
        if annual_usage > self._tier2_limit:
            self._current_tier = "第三档"
        elif annual_usage > self._tier1_limit:
            self._current_tier = "第二档"
        else:
            self._current_tier = "第一档"

        self._attr_native_value = round(base_cost + incremental_surcharge, 2)
