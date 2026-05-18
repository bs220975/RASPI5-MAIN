"""
Scheduled on/off timers for the three relay-controlled lights.

Schedules are stored in Firebase RTDB at:
    schedules/living_room/       { on_time, off_time, enabled }
    schedules/lobby/             { on_time, off_time, enabled }
    schedules/lower_porch_light/ { on_time, off_time, enabled }

The app writes to these paths; the Pi picks them up via SSE stream and
calls apply_schedules() which arms cron jobs in APScheduler.  At fire
time the existing mqtt_bridge relay functions are called directly.
"""
import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APS_AVAILABLE = True
except ImportError:
    _APS_AVAILABLE = False
    logger.warning(
        'APScheduler not installed — light scheduling disabled. '
        'Run: pip install apscheduler'
    )

_LIGHT_IDS = ('living_room', 'lobby', 'lower_porch_light')


class LightScheduler:
    """
    Cron-based on/off scheduler for lobby, porch, and L-Porch lights.

    Times are HH:MM strings (24-hour, local Pi clock).  Schedules are
    applied atomically — calling apply_schedule() replaces the previous
    on/off pair for that light without touching other lights.
    """

    def __init__(
        self,
        send_lobby:  Callable[[bool], None],
        send_porch:  Callable[[bool], None],
        send_lp_rly: Callable[[bool], None],
    ) -> None:
        self._relay_fns: Dict[str, Callable[[bool], None]] = {
            'living_room':       send_lobby,
            'lobby':             send_porch,
            'lower_porch_light': send_lp_rly,
        }
        self._scheduler = BackgroundScheduler(daemon=True) if _APS_AVAILABLE else None

    def start(self) -> None:
        if self._scheduler:
            self._scheduler.start()
            logger.info('LightScheduler started')

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info('LightScheduler stopped')

    def apply_schedules(self, schedules: dict) -> None:
        """Apply all light schedules from a Firebase schedules dict."""
        for light_id in _LIGHT_IDS:
            data = schedules.get(light_id) if schedules else None
            if isinstance(data, dict):
                self.apply_schedule(
                    light_id,
                    data.get('on_time', ''),
                    data.get('off_time', ''),
                    bool(data.get('enabled', False)),
                )
            else:
                self._remove_jobs(light_id)

    def apply_schedule(
        self, light_id: str, on_time: str, off_time: str, enabled: bool
    ) -> None:
        """Add or replace the on/off cron pair for a single light."""
        if not self._scheduler:
            return
        self._remove_jobs(light_id)
        if not enabled or not on_time or not off_time:
            logger.info(f'Schedule {light_id}: disabled/cleared')
            return
        try:
            on_h, on_m   = map(int, on_time.split(':'))
            off_h, off_m = map(int, off_time.split(':'))
        except (ValueError, AttributeError):
            logger.warning(
                f'Invalid schedule times for {light_id}: '
                f'on={on_time!r} off={off_time!r}'
            )
            return
        fn = self._relay_fns.get(light_id)
        if fn is None:
            logger.warning(f'LightScheduler: unknown light_id "{light_id}"')
            return
        self._scheduler.add_job(
            fn, CronTrigger(hour=on_h, minute=on_m),
            id=f'{light_id}_on', args=[True], replace_existing=True,
        )
        self._scheduler.add_job(
            fn, CronTrigger(hour=off_h, minute=off_m),
            id=f'{light_id}_off', args=[False], replace_existing=True,
        )
        logger.info(f'Schedule set: {light_id}  ON={on_time}  OFF={off_time}')

    def _remove_jobs(self, light_id: str) -> None:
        if not self._scheduler:
            return
        for suffix in ('on', 'off'):
            job_id = f'{light_id}_{suffix}'
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
