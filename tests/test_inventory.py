import pandas as pd

from s2d.sim import simulate
from s2d.spec import load_spec


def test_a_zero_lead_time_still_refills_the_shelf():
    """Digital goods: lead_time_days 0 used to leave every shipment undelivered (due the day it
    was ordered, after that day's arrivals), so sales stopped after the starting stock
    (DECISIONS 132; Nahá pravda sold for 12 of 932 days)."""
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 1500
    spec.events, spec.decoys = [], []
    for s in spec.entities.suppliers:
        s.lead_time_days = 0
    last = pd.Timestamp(simulate(spec, seed=1).tables["orders"]["order_date"].max())
    assert last >= pd.Timestamp(spec.meta.start) + pd.Timedelta(days=spec.meta.days - 15)
