from datetime import date, datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field

ET_TZ = ZoneInfo("America/New_York")


class MacroEvent(BaseModel):
    name: str = Field(description="Name of the high-impact macro event")
    release_time_et: datetime = Field(
        description="Official release timestamp in US/Eastern"
    )
    lockout_start_et: datetime = Field(
        description="Cutoff timestamp when new entries are blocked and existing positions must be closed"
    )
    lockout_end_et: datetime = Field(
        description="Timestamp when event data is digested and post-print IV verification can begin"
    )
    description: str = Field(description="Context and volatility expectation")

    @property
    def release_time_utc(self) -> datetime:
        return self.release_time_et.astimezone(timezone.utc)

    @property
    def lockout_start_utc(self) -> datetime:
        return self.lockout_start_et.astimezone(timezone.utc)

    @property
    def lockout_end_utc(self) -> datetime:
        return self.lockout_end_et.astimezone(timezone.utc)


# Hackathon Build Window Boundaries (Aug 28 – Sep 4, 2026)
BUILD_WINDOW_START = datetime(2026, 8, 28, 9, 30, tzinfo=ET_TZ)
BUILD_WINDOW_END = datetime(2026, 9, 4, 16, 0, tzinfo=ET_TZ)

# Official US Equity & Options Market Holidays 2026 (NYSE, Nasdaq, CBOE)
US_MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # Martin Luther King, Jr. Day
    date(2026, 2, 16),  # Washington's Birthday (Presidents' Day)
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth National Independence Day
    date(2026, 7, 3),   # Independence Day (Observed)
    date(2026, 9, 7),   # Labor Day (Markets & Options Exchanges Closed)
    date(2026, 11, 26), # Thanksgiving Day
    date(2026, 12, 25), # Christmas Day
}


def is_market_holiday(d: date) -> bool:
    """Checks if a given calendar date is an official US stock/options market holiday."""
    return d in US_MARKET_HOLIDAYS_2026


def is_market_trading_day(d: date) -> bool:
    """Checks if a date is a standard weekday market session (Mon-Fri and not a holiday)."""
    return d.weekday() < 5 and not is_market_holiday(d)


# Hard-coded Event Calendar per Build Contract §4 & §8
CALENDAR_EVENTS: List[MacroEvent] = [
    MacroEvent(
        name="JOLTS Job Openings",
        release_time_et=datetime(2026, 9, 1, 10, 0, tzinfo=ET_TZ),
        # Hard exclusion rule: never hold through market open on Sep 1
        # Close all positions by EOD Aug 31 (16:00 ET) and block new entries
        lockout_start_et=datetime(2026, 8, 31, 15, 45, tzinfo=ET_TZ),
        lockout_end_et=datetime(2026, 9, 1, 10, 15, tzinfo=ET_TZ),
        description="Labor market data release. Elevated volatility expected at 10:00 AM ET.",
    ),
    MacroEvent(
        name="Non-Farm Payrolls (NFP) & Unemployment",
        release_time_et=datetime(2026, 9, 4, 8, 30, tzinfo=ET_TZ),
        # Hard exclusion rule: never hold through market open on Sep 4
        # Close all positions by EOD Sep 3 (16:00 ET) and block new entries
        lockout_start_et=datetime(2026, 9, 3, 15, 45, tzinfo=ET_TZ),
        lockout_end_et=datetime(2026, 9, 4, 9, 45, tzinfo=ET_TZ),
        description="Monthly employment report. Major macro risk print at 8:30 AM ET.",
    ),
]


def _coerce_datetime(dt: Optional[object] = None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, 12, 0, tzinfo=ET_TZ).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def is_time_in_lockout(
    dt: Optional[object] = None,
) -> tuple[bool, Optional[MacroEvent], str]:
    """
    Checks if a given datetime (default: current UTC/ET) falls within any macro lockout window.
    Returns (in_lockout, matched_event, reason).
    """
    current_dt = _coerce_datetime(dt)
    current_et = current_dt.astimezone(ET_TZ)

    # Check build window closure (any position opened after Sep 4 8:30am must be closed before 16:00 ET)
    if current_et >= BUILD_WINDOW_END:
        return (
            True,
            None,
            "Build window has concluded. All trading halted for hackathon judging.",
        )

    for event in CALENDAR_EVENTS:
        if event.lockout_start_et <= current_et <= event.lockout_end_et:
            return (
                True,
                event,
                f"Active lockout for {event.name}. Window: {event.lockout_start_et.strftime('%Y-%m-%d %H:%M ET')} "
                f"to {event.lockout_end_et.strftime('%Y-%m-%d %H:%M ET')}.",
            )

    return False, None, "No active event lockouts. Trading window is clear."


def get_next_blackout_cutoff(
    dt: Optional[object] = None,
) -> tuple[Optional[datetime], Optional[MacroEvent]]:
    """
    Returns the nearest upcoming blackout cutoff timestamp (lockout_start_et) and the corresponding MacroEvent.
    """
    current_dt = _coerce_datetime(dt)
    current_et = current_dt.astimezone(ET_TZ)

    upcoming_events = [
        e for e in CALENDAR_EVENTS if e.lockout_start_et > current_et
    ]
    if not upcoming_events:
        return BUILD_WINDOW_END, None

    upcoming_events.sort(key=lambda e: e.lockout_start_et)
    next_event = upcoming_events[0]
    return next_event.lockout_start_et, next_event


def is_expiry_safe_from_blackouts(
    exp_date: date, dt: Optional[object] = None
) -> tuple[bool, str]:
    """
    Proactively asserts whether an option expiration date matures safely BEFORE
    the next upcoming macro blackout window starts.
    Contract §4: Never hold through Sep 1 (JOLTS) or Sep 4 (NFP).
    """
    current_dt = _coerce_datetime(dt)
    current_et = current_dt.astimezone(ET_TZ)

    # Option expires at market close 16:00 ET on expiration date
    exp_et = datetime(exp_date.year, exp_date.month, exp_date.day, 16, 0, tzinfo=ET_TZ)

    # Must mature within the overall hackathon build window
    if exp_et > BUILD_WINDOW_END:
        return False, f"Expiry {exp_date} extends past hackathon build window conclusion ({BUILD_WINDOW_END.strftime('%Y-%m-%d %H:%M ET')})."

    for event in CALENDAR_EVENTS:
        # If the option expires during or after any event's blackout start,
        # but current time is before that event's end, holding this expiry risks event exposure!
        if current_et < event.lockout_end_et:
            if exp_et >= event.lockout_start_et:
                return (
                    False,
                    f"Expiry {exp_date} ({exp_et.strftime('%Y-%m-%d %H:%M ET')}) matures during or after "
                    f"{event.name} lockout start ({event.lockout_start_et.strftime('%Y-%m-%d %H:%M ET')}). "
                    f"Contract Section 4 requires proactive avoidance.",
                )

    return True, f"Expiry {exp_date} is safe and matures before all upcoming blackout cutoffs."


def get_active_or_upcoming_lockouts(
    dt: Optional[datetime] = None, hours_ahead: Optional[float] = 360.0
) -> List[dict]:
    """Returns a list of upcoming or active lockouts within the specified horizon (default 15 days)."""
    current_dt = dt or datetime.now(timezone.utc)
    if current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=timezone.utc)
    current_et = current_dt.astimezone(ET_TZ)

    events_info = []
    for event in CALENDAR_EVENTS:
        hours_until_start = (
            event.lockout_start_et - current_et
        ).total_seconds() / 3600.0
        hours_until_release = (
            event.release_time_et - current_et
        ).total_seconds() / 3600.0
        is_active = event.lockout_start_et <= current_et <= event.lockout_end_et

        if is_active or (hours_ahead is None) or (0 <= hours_until_start <= hours_ahead):
            events_info.append(
                {
                    "name": event.name,
                    "is_active": is_active,
                    "release_time": event.release_time_et.isoformat(),
                    "lockout_start": event.lockout_start_et.isoformat(),
                    "lockout_end": event.lockout_end_et.isoformat(),
                    "hours_until_start": round(hours_until_start, 2),
                    "hours_until_release": round(hours_until_release, 2),
                    "description": event.description,
                }
            )
    return events_info
