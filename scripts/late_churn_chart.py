"""Chart of the JOIN + lag test: after which parcels did customers leave, and when?

    python scripts/late_churn_chart.py verify.json docs/late_churn_b.png

Reads the verifier's result (python -m s2d.verify RUN --twin TWIN --out verify.json).
Two panels, story and no-story twin: % of parcels (late vs on time) after which the
customer left, by days from the parcel to the estimated departure.
"""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

LATE, ON_TIME = "#eb6834", "#2a78d6"   # categorical slots 2 and 1 (validated on the light surface)
INK, MUTED, GRID, SURFACE, BAND = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb", "#f1efe8"


def panel(ax, r, title, top):
    off = r["offsets"]
    x = np.array(off["bin_start"]) + 5
    w = 4.2
    ax.axvspan(30, 60, color=BAND, zorder=0)
    ax.text(45, top * 0.97, "okno testu\n30–60 dní", ha="center", va="top", fontsize=8.5, color=MUTED)
    ax.bar(x - w / 2 - 0.3, off["late"], w, color=LATE, zorder=2,
           label=f"po pozdní zásilce ({off['late_parcels']:,} zásilek)")
    ax.bar(x + w / 2 + 0.3, off["on_time"], w, color=ON_TIME, zorder=2,
           label=f"po včasné zásilce ({off['on_time_parcels']:,} zásilek)")
    g = r["groups"]
    ax.set_title(f"{title}\nodešlo za 30–60 dní: po pozdní {g['late_left_pct']:.1f} %, po včasné "
                 f"{g['on_time_left_pct']:.1f} %  (z = {r['z']:.1f})", loc="left", fontsize=10, color=INK)
    ax.set_xlabel("dní od doručení do odchodu zákazníka", color=MUTED, fontsize=9)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, top)
    ax.set_xticks(np.arange(0, 151, 30))
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=1)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    ax.set_facecolor(SURFACE)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right", labelcolor=INK)


def main(path, out):
    res = json.load(open(path, encoding="utf-8"))
    r = next(t for t in res["tests"] if t["kpi"] == "late_churn")
    tw = r["twin"]
    top = 1.25 * max(max(d["offsets"][k]) for d in (r, tw) for k in ("late", "on_time"))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), sharey=True, facecolor=SURFACE)
    cities = r["segment"].split("=")[1].replace(",", " a ")
    panel(axes[0], r, f"Příběh: nový kurýr ({cities})", top)
    panel(axes[1], tw, "Dvojče bez příběhu (stejný seed)", top)
    axes[0].set_ylabel("% zásilek, po kterých zákazník odešel", color=MUTED, fontsize=9)
    fig.suptitle("Pozdní zásilka → odchod zákazníka za 30–60 dní  (zákazníci ⋈ objednávky ⋈ doručení)",
                 x=0.01, ha="left", fontsize=12, color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
