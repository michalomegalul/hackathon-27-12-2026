"""Daily orders chart, optionally against the no-story twin, with event markers.

    uv run python scripts/plot_daily_orders.py data/a --twin data/a_nostory --out data/a/daily_orders.png
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import yaml

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
STORY = "#2a78d6"   # categorical slot 1
TWIN = "#8f8e88"    # neutral: the twin is a reference, not a peer series


def daily_orders(folder: Path) -> pd.Series:
    orders = pd.read_parquet(folder / "orders.parquet", columns=["order_date"])
    return orders.groupby("order_date").size().rename("orders")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data")
    p.add_argument("--twin", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    data = Path(args.data)
    out = Path(args.out or data / "daily_orders.png")

    story = daily_orders(data)
    fig, ax = plt.subplots(figsize=(12, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ax.plot(story.index, story.values, color=STORY, alpha=0.25, linewidth=0.8, label="Daily orders (story)")
    smooth = story.rolling(7, center=True).mean()
    ax.plot(smooth.index, smooth.values, color=STORY, linewidth=2, label="7-day average (story)")
    if args.twin:
        twin = daily_orders(Path(args.twin)).rolling(7, center=True).mean()
        ax.plot(twin.index, twin.values, color=TWIN, linewidth=2, linestyle=(0, (4, 2)),
                label="7-day average (no-story twin)")
        ax.annotate("no story", (twin.index[-4], twin.iloc[-4]), xytext=(6, 0),
                    textcoords="offset points", color=INK_2, fontsize=9, va="center")
    ax.annotate("story", (smooth.index[-4], smooth.iloc[-4]), xytext=(6, 0),
                textcoords="offset points", color=INK_2, fontsize=9, va="center")

    # Event markers: where each simulated effect begins (start + lag).
    key = pd.read_parquet(data / "_truth" / "answer_key.parquet")
    top = story.max() * 1.02
    for r in key[key["simulated"]].itertuples():
        x = pd.Timestamp(r.start_date) + pd.Timedelta(days=int(r.lag_days))
        ax.axvline(x, color=INK_2, linewidth=0.8, linestyle=":")
        ax.text(x, top, f" {r.event_id} {r.metric.replace('_', ' ')}", color=INK_2, fontsize=8,
                rotation=90, va="top", ha="right")

    spec = yaml.safe_load(pd.read_parquet(data / "_truth" / "spec_yaml.parquet")["spec_yaml"][0])
    ax.set_title(f"Daily orders - {spec['company']['name']}", loc="left", color=INK, fontsize=13)
    ax.set_ylabel("Orders per day", color=INK_2)
    ax.set_ylim(0, story.max() * 1.05)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=INK_2, ncols=3)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
