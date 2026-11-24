"""Day-level demand factors: day of week, time of year, Black Friday, Christmas
and Czech public holidays."""

from dataclasses import dataclass
from datetime import date, timedelta

import holidays
import numpy as np

from s2d.spec import SeasonProfile, StorySpec

# Yearly shape: 1 + amplitude * cos(2π (day_of_year/365 - peak)).
# peak is the fraction of the year where demand is highest.
YEARLY_PROFILES = {
    SeasonProfile.flat: (0.00, 0.0),
    SeasonProfile.winter_peak: (0.15, 0.0),   # peak around New Year, low in July
    SeasonProfile.summer_peak: (0.15, 0.5),   # peak in July
    SeasonProfile.retail_cz: (0.08, 0.95),    # mild peak in December
}

# How much of a normal day's demand still happens on a public holiday.
HOLIDAY_FACTOR_ONLINE = 0.8
HOLIDAY_FACTOR_STORE_OPEN = 0.5


@dataclass
class Calendar:
    dates: list[date]          # one entry per simulated day
    day_factor: np.ndarray     # weekly * yearly * Black Friday * Christmas
    is_holiday: np.ndarray     # bool, Czech public holiday
    holiday_name: list[str]    # '' on normal days
    store_holiday_factor: float  # multiplier for store orders on a holiday

    @property
    def n_days(self) -> int:
        return len(self.dates)

    def index_of(self, d: date) -> int:
        """Day index of a date (may be negative or >= n_days if outside the sim)."""
        return (d - self.dates[0]).days


def black_friday(year: int) -> date:
    """The Friday after the fourth Thursday of November."""
    nov1 = date(year, 11, 1)
    first_thursday = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    return first_thursday + timedelta(days=21 + 1)


def build_calendar(spec: StorySpec) -> Calendar:
    season = spec.baseline.seasonality
    dates = [spec.meta.start + timedelta(days=i) for i in range(spec.meta.days)]

    weekly = np.array(season.weekly, dtype=float)
    weekly = weekly / weekly.mean()  # so the weekly pattern does not change the monthly total
    amplitude, peak = YEARLY_PROFILES[season.profile]

    cz = holidays.CZ(years=range(dates[0].year, dates[-1].year + 1), language="cs")

    factor = np.ones(len(dates))
    is_holiday = np.zeros(len(dates), dtype=bool)
    names = [""] * len(dates)
    for i, d in enumerate(dates):
        f = weekly[d.weekday()]
        f *= 1 + amplitude * np.cos(2 * np.pi * (d.timetuple().tm_yday / 365 - peak))
        if season.black_friday:
            days_after_bf = (d - black_friday(d.year)).days
            if days_after_bf == 0:
                f *= 1.8
            elif 1 <= days_after_bf <= 3:      # weekend + Cyber Monday
                f *= 1.4
            elif -7 <= days_after_bf < 0:      # "Black week" warm-up
                f *= 1.15
        if season.christmas and d.month == 12:
            if d.day <= 20:
                f *= 1.25
            elif d.day <= 23:
                f *= 1.1
            elif d.day <= 26:
                f *= 0.4
            else:
                f *= 0.8
        factor[i] = f
        if d in cz:
            is_holiday[i] = True
            names[i] = cz.get(d)

    store_factor = 0.0 if season.cz_holidays_closed else HOLIDAY_FACTOR_STORE_OPEN
    return Calendar(dates, factor, is_holiday, names, store_factor)
