"""数据协调器：拉取电表历史、计算各周期峰谷电量与电费，并增量更新。

周期说明：
- 全年/当月/当日电量 = 当前读数 - 对应起点读数
- 当月/当日/昨日 峰谷电量 = 各时段历史读数差按峰(8-21点)/谷(其余)累加
- 电费 = 峰电量×峰价 + 谷电量×谷价 + 阶梯加价(按年累计)
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PEAK_RATIO,
    CONF_PRICE_PEAK,
    CONF_PRICE_VALLEY,
    CONF_SOURCE_SENSOR,
    CONF_TIER1_LIMIT,
    CONF_TIER2_ADD,
    CONF_TIER2_LIMIT,
    CONF_TIER3_ADD,
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

PEAK_START_HOUR = 8  # 峰段开始（含）
PEAK_END_HOUR = 21  # 峰段结束（不含）


def tier_surcharge(annual_kwh, t1, t2, a2, a3):
    """年累计用电量对应的阶梯加价总额。"""
    if annual_kwh <= t1:
        return 0.0
    if annual_kwh <= t2:
        return (annual_kwh - t1) * a2
    return (t2 - t1) * a2 + (annual_kwh - t2) * a3


def _is_peak(utc_time) -> bool:
    h = dt_util.as_local(utc_time).hour
    return PEAK_START_HOUR <= h < PEAK_END_HOUR


def split_peak_valley(t0, t1, delta):
    """将 [t0,t1] 区间的电量 delta 按峰谷时段拆分，返回 (峰, 谷)。"""
    if delta <= 0 or t1 <= t0:
        return 0.0, 0.0
    total = (t1 - t0).total_seconds()
    if total <= 0:
        return 0.0, 0.0

    cuts = {t0, t1}
    day = dt_util.as_local(t0).replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(3):
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
        if _is_peak(s + (e - s) / 2):
            peak += frac
        else:
            valley += frac
    return peak, valley


class YangzhouCostCoordinator(DataUpdateCoordinator):
    """统一计算各周期电量与电费。"""

    def __init__(self, hass: HomeAssistant, cfg: dict, entry_id: str):
        super().__init__(hass, _LOGGER, name="yangzhou_electricity_cost")
        self.entry_id = entry_id
        self.source_sensor = cfg.get(CONF_SOURCE_SENSOR, DEFAULT_SOURCE_SENSOR)
        self.price_peak = cfg.get(CONF_PRICE_PEAK, DEFAULT_PRICE_PEAK)
        self.price_valley = cfg.get(CONF_PRICE_VALLEY, DEFAULT_PRICE_VALLEY)
        self.tier1_limit = cfg.get(CONF_TIER1_LIMIT, DEFAULT_TIER1_LIMIT)
        self.tier2_limit = cfg.get(CONF_TIER2_LIMIT, DEFAULT_TIER2_LIMIT)
        self.tier2_add = cfg.get(CONF_TIER2_ADD, DEFAULT_TIER2_ADD)
        self.tier3_add = cfg.get(CONF_TIER3_ADD, DEFAULT_TIER3_ADD)
        self.peak_ratio = cfg.get(CONF_PEAK_RATIO, DEFAULT_PEAK_RATIO)

        # 增量更新状态
        self._last_reading: float | None = None
        self._last_time = None
        # 累加器
        self.month_peak = 0.0
        self.month_valley = 0.0
        self.today_peak = 0.0
        self.today_valley = 0.0
        self.yesterday_peak = 0.0
        self.yesterday_valley = 0.0
        # 基线读数
        self.year_start_reading: float | None = None
        self.month_start_reading: float | None = None
        self.today_start_reading: float | None = None
        self.yesterday_start_reading: float | None = None
        self.yesterday_end_reading: float | None = None
        self.current_reading = 0.0

        self._unsub_state = None
        self._unsub_midnight = None

    async def async_init(self) -> None:
        """初始化：全量计算并注册监听。"""
        await self._compute_all()
        self._unsub_state = async_track_state_change_event(
            self.hass, [self.source_sensor], self._on_state_change
        )
        self._unsub_midnight = async_track_time_change(
            self.hass, self._on_midnight, hour=0, minute=0, second=5
        )

    async def async_close(self) -> None:
        """卸载时移除监听。"""
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None

    async def async_update_data(self):
        """DataUpdateCoordinator 占位（实际由事件驱动）。"""
        if self.data is None:
            await self._compute_all()
        return self.data

    @callback
    def _on_state_change(self, event) -> None:
        """电表变化：增量累加新一段并重算。"""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in ("unknown", "unavailable"):
            return
        try:
            new_reading = float(new_state.state)
        except (ValueError, TypeError):
            return

        if (
            self._last_reading is not None
            and self._last_time is not None
            and new_state.last_changed is not None
        ):
            delta = new_reading - self._last_reading
            if delta > 0:
                p, v = split_peak_valley(
                    self._last_time, new_state.last_changed, delta
                )
                self.month_peak += p
                self.month_valley += v
                self.today_peak += p
                self.today_valley += v

        self._last_reading = new_reading
        self._last_time = new_state.last_changed
        self.current_reading = new_reading
        self._publish()

    @callback
    def _on_midnight(self, now) -> None:
        """跨日：重新计算昨日/今日。"""
        self.hass.async_create_task(self._compute_all())

    async def _compute_all(self) -> None:
        """全量计算：拉取本月与昨日历史，逐段累加峰谷。"""
        now = dt_util.now()
        now_local = dt_util.as_local(now)
        today_start = dt_util.as_utc(
            now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        )
        month_start = dt_util.as_utc(
            now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        )
        year_start = dt_util.as_utc(
            now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        )
        yesterday_start = today_start - timedelta(days=1)

        self.year_start_reading = await self._get_reading_at(year_start)
        self.month_start_reading = await self._get_reading_at(month_start)
        self.today_start_reading = await self._get_reading_at(today_start)

        # 本月历史（含今日）
        month_states = await self._get_history(month_start, now)
        self.month_peak = 0.0
        self.month_valley = 0.0
        self.today_peak = 0.0
        self.today_valley = 0.0
        if month_states:
            prev = None
            prev_t = None
            for st in month_states:
                try:
                    cur = float(st.state)
                except (ValueError, TypeError):
                    continue
                if prev is not None and prev_t is not None and st.last_changed:
                    d = cur - prev
                    if d > 0:
                        p, v = split_peak_valley(prev_t, st.last_changed, d)
                        self.month_peak += p
                        self.month_valley += v
                        if st.last_changed >= today_start:
                            self.today_peak += p
                            self.today_valley += v
                prev = cur
                prev_t = st.last_changed
            self._last_reading = prev
            self._last_time = prev_t

        # 昨日历史
        yest_states = await self._get_history(yesterday_start, today_start)
        self.yesterday_peak = 0.0
        self.yesterday_valley = 0.0
        self.yesterday_start_reading = None
        self.yesterday_end_reading = None
        if yest_states:
            try:
                self.yesterday_start_reading = float(yest_states[0].state)
            except (ValueError, TypeError):
                pass
            prev = None
            prev_t = None
            for st in yest_states:
                try:
                    cur = float(st.state)
                except (ValueError, TypeError):
                    continue
                if prev is not None and prev_t is not None and st.last_changed:
                    d = cur - prev
                    if d > 0:
                        p, v = split_peak_valley(prev_t, st.last_changed, d)
                        self.yesterday_peak += p
                        self.yesterday_valley += v
                prev = cur
                prev_t = st.last_changed
            if prev is not None:
                self.yesterday_end_reading = prev

        # 当前实时读数
        live = self.hass.states.get(self.source_sensor)
        if live is not None and live.state not in ("unknown", "unavailable"):
            try:
                self.current_reading = float(live.state)
                if self._last_reading is None:
                    self._last_reading = self.current_reading
                    self._last_time = now
            except (ValueError, TypeError):
                pass

        self._publish()

    def _publish(self) -> None:
        """重算派生值并通知实体。"""
        self.data = self._build_data()
        self.last_update_success = True
        self.async_update_listeners()

    def _build_data(self) -> dict:
        cur = self.current_reading
        yb = self.year_start_reading if self.year_start_reading is not None else cur
        mb = self.month_start_reading if self.month_start_reading is not None else cur
        tb = self.today_start_reading if self.today_start_reading is not None else cur

        annual_usage = max(0.0, cur - yb)
        monthly_usage = max(0.0, cur - mb)
        daily_usage = max(0.0, cur - tb)

        # 全年峰谷：用本月真实峰谷比例估算（无历史则用配置比例）
        month_total = self.month_peak + self.month_valley
        if month_total > 0:
            ratio = self.month_peak / month_total
        else:
            ratio = self.peak_ratio / 100.0
        annual_peak = annual_usage * ratio
        annual_valley = annual_usage * (1 - ratio)

        # 阶梯加价（按年累计）
        sur_now = tier_surcharge(
            annual_usage, self.tier1_limit, self.tier2_limit, self.tier2_add, self.tier3_add
        )
        sur_month_start = tier_surcharge(
            max(0.0, mb - yb),
            self.tier1_limit,
            self.tier2_limit,
            self.tier2_add,
            self.tier3_add,
        )
        sur_today_start = tier_surcharge(
            max(0.0, tb - yb),
            self.tier1_limit,
            self.tier2_limit,
            self.tier2_add,
            self.tier3_add,
        )
        yest_end = (
            self.yesterday_end_reading
            if self.yesterday_end_reading is not None
            else tb
        )
        yest_start = (
            self.yesterday_start_reading
            if self.yesterday_start_reading is not None
            else tb
        )
        sur_yest_end = tier_surcharge(
            max(0.0, yest_end - yb),
            self.tier1_limit,
            self.tier2_limit,
            self.tier2_add,
            self.tier3_add,
        )
        sur_yest_start = tier_surcharge(
            max(0.0, yest_start - yb),
            self.tier1_limit,
            self.tier2_limit,
            self.tier2_add,
            self.tier3_add,
        )

        monthly_cost = (
            self.month_peak * self.price_peak
            + self.month_valley * self.price_valley
            + max(0.0, sur_now - sur_month_start)
        )
        daily_cost = (
            self.today_peak * self.price_peak
            + self.today_valley * self.price_valley
            + max(0.0, sur_now - sur_today_start)
        )
        yesterday_cost = (
            self.yesterday_peak * self.price_peak
            + self.yesterday_valley * self.price_valley
            + max(0.0, sur_yest_end - sur_yest_start)
        )
        annual_cost = (
            annual_peak * self.price_peak
            + annual_valley * self.price_valley
            + sur_now
        )

        if annual_usage > self.tier2_limit:
            tier = "第三档"
        elif annual_usage > self.tier1_limit:
            tier = "第二档"
        else:
            tier = "第一档"

        return {
            "annual_usage": annual_usage,
            "monthly_usage": monthly_usage,
            "daily_usage": daily_usage,
            "monthly_peak": self.month_peak,
            "monthly_valley": self.month_valley,
            "daily_peak": self.today_peak,
            "daily_valley": self.today_valley,
            "yesterday_peak": self.yesterday_peak,
            "yesterday_valley": self.yesterday_valley,
            "monthly_cost": monthly_cost,
            "daily_cost": daily_cost,
            "yesterday_cost": yesterday_cost,
            "annual_cost": annual_cost,
            "current_reading": cur,
            "annual_usage_kwh": annual_usage,
            "current_tier": tier,
        }

    async def _get_history(self, start_utc, end_utc):
        """获取源传感器在区间内的全部历史状态（含起始时刻状态）。"""
        try:
            from homeassistant.components.recorder import history

            result = await self.hass.async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start_utc,
                end_utc,
                [self.source_sensor],
                None,
                True,
                False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("查询历史区间失败(%s~%s)：%s", start_utc, end_utc, err)
            return []
        if not result:
            return []
        return result.get(self.source_sensor, [])

    async def _get_reading_at(self, utc_time) -> float | None:
        """获取指定时间点电表的累计读数。"""
        try:
            from homeassistant.components.recorder import history

            result = await self.hass.async_add_executor_job(
                history.get_state, self.hass, utc_time, [self.source_sensor]
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("查询历史读数失败(%s)：%s", utc_time, err)
            return None
        if not result:
            return None
        states = result.get(self.source_sensor)
        if not states:
            return None
        try:
            value = float(states[0].state)
        except (ValueError, TypeError):
            return None
        if states[0].last_changed > utc_time:
            _LOGGER.warning("在 %s 之前没有 %s 的历史数据", utc_time, self.source_sensor)
            return None
        return value
