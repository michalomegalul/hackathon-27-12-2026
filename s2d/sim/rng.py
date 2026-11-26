"""One root seed -> one independent random stream per subsystem.

Each subsystem (acquisition, purchases, churn, ...) gets its own child of
`np.random.SeedSequence(seed)`. Changing how purchases are drawn therefore
does not shift the random numbers used for churn, and the reverse is also true.

IMPORTANT: only ever APPEND to STREAM_NAMES. Reordering it changes which
child each name gets, which changes every dataset for a given seed.
"""

import numpy as np

STREAM_NAMES = (
    "acquisition",  # how many new customers arrive each day, and where
    "customers",    # customer attributes: gender, base rate, signup dates
    "catalog",      # products, prices, popularity
    "purchases",    # order counts, baskets, timestamps
    "churn",        # who leaves and when
    "payments",     # payment methods and failures
    "faker",        # seed for Faker (names, e-mail domains)
    "deliveries",   # courier delays, satisfaction of each delivery
    "tickets",      # who writes to support, queue handling times
    "reviews",      # who reviews, ratings, topics
    "service",      # leaving at the next purchase occasion after a bad experience
    "subscriptions",  # subscription plans and schedules
    "inventory",    # stock levels, supplier shipments
    "dirt",         # the messiness layer of the export copy
    "timestamps",   # times of day for reviews and tickets
)


def make_streams(seed: int) -> dict[str, np.random.Generator]:
    children = np.random.SeedSequence(seed).spawn(len(STREAM_NAMES))
    return {name: np.random.default_rng(child) for name, child in zip(STREAM_NAMES, children)}


# The day loop's streams: a run with the story and its no-story twin should draw the
# same numbers wherever nothing differs. A stream consumed in variable amounts (baskets
# per order, one review draw per delivery) would otherwise shift every later day once
# the story adds a single order, and the twin comparison (calibration) stops being paired.
DAILY_STREAMS = ("purchases", "churn", "payments", "deliveries", "tickets", "reviews", "service", "inventory")


class DailyRng:
    """A Generator re-seeded every simulated day from (this stream's key, day). Use it like
    a Generator; call day(t) at the start of day t. Within a day, arrays run over customers
    in signup order, so the starting base draws the same numbers with and without the story."""

    def __init__(self, parent: np.random.Generator):
        self._key = int(parent.integers(0, 2**63 - 1))
        self._g = parent

    def day(self, t: int) -> None:
        self._g = np.random.default_rng([self._key, t])

    def __getattr__(self, name):
        return getattr(self._g, name)


def daily(streams: dict[str, np.random.Generator]) -> dict:
    """The same streams with DAILY_STREAMS wrapped in DailyRng."""
    return {k: DailyRng(v) if k in DAILY_STREAMS else v for k, v in streams.items()}
