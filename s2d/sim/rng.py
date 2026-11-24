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
)


def make_streams(seed: int) -> dict[str, np.random.Generator]:
    children = np.random.SeedSequence(seed).spawn(len(STREAM_NAMES))
    return {name: np.random.default_rng(child) for name, child in zip(STREAM_NAMES, children)}
