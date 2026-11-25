"""The messiness layer: a dirty copy of the analyst tables for export.

The clean tables stay as they are (the verifier, the detective and the scorer read
them). The copy gets what real exports have: typos and missing diacritics in names and
cities, odd phone formats, empty fields, duplicated customers and payments. Keys stay
valid: a duplicate gets a new id, a NULL is only ever put into a nullable non-key
column, so the Postgres export keeps its PK/FK constraints.

    tables, log = dirty_copy(world.tables, "medium", rng)
"""

from __future__ import annotations

import unicodedata

import numpy as np
import pandas as pd

LEVELS = ("none", "low", "medium", "high")
# messiness in the spec -> level (the spec says light / heavy, the CLI low / high)
FROM_SPEC = {"none": "none", "light": "low", "medium": "medium", "heavy": "high"}
# share of rows touched, per kind of dirt
RATES = {
    "low":    {"typo": 0.005, "ascii": 0.01, "null": 0.005, "dup": 0.002, "format": 0.05},
    "medium": {"typo": 0.02, "ascii": 0.05, "null": 0.02, "dup": 0.01, "format": 0.15},
    "high":   {"typo": 0.05, "ascii": 0.15, "null": 0.05, "dup": 0.03, "format": 0.35},
}
QWERTZ_NEAR = {"a": "sq", "e": "wr", "i": "uo", "o": "ip", "n": "bm", "r": "et", "s": "ad", "t": "rz",
               "l": "kp", "k": "jl", "v": "cb", "c": "xv", "m": "n", "u": "zi", "z": "tu", "y": "x"}


def strip_diacritics(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def typo(text: str, rng: np.random.Generator) -> str:
    """One keyboard slip: swap two letters, drop one, double one or hit a neighbour key."""
    if len(text) < 3:
        return text
    i = int(rng.integers(1, len(text) - 1))
    kind = int(rng.integers(4))
    if kind == 0:
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if kind == 1:
        return text[:i] + text[i + 1:]
    if kind == 2:
        return text[:i] + text[i] + text[i:]
    near = QWERTZ_NEAR.get(text[i].lower())
    return text[:i] + (near[int(rng.integers(len(near)))] if near else text[i]) + text[i + 1:]


class _Log:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, table: str, column: str, kind: str, n: int) -> None:
        if n:
            self.rows.append({"table": table, "column": column, "kind": kind, "rows": int(n)})


def _pick(n: int, rate: float, rng: np.random.Generator) -> np.ndarray:
    return rng.random(n) < rate


def _text(df: pd.DataFrame, col: str, table: str, r: dict, rng, log: _Log, ascii_=True, typos=True) -> None:
    if col not in df or df.empty:
        return
    v = df[col].astype(object).to_numpy().copy()
    ok = pd.notna(v)
    if ascii_:
        hit = _pick(len(v), r["ascii"], rng) & ok
        v[hit] = [strip_diacritics(x) for x in v[hit]]
        log.add(table, col, "bez diakritiky", hit.sum())
    if typos:
        hit = _pick(len(v), r["typo"], rng) & ok
        v[hit] = [typo(x, rng) for x in v[hit]]
        log.add(table, col, "překlep", hit.sum())
    df[col] = v


def _nulls(df: pd.DataFrame, col: str, table: str, rate: float, rng, log: _Log) -> None:
    if col not in df or df.empty:
        return
    hit = _pick(len(df), rate, rng)
    df[col] = df[col].astype(object).where(~hit, None)
    log.add(table, col, "NULL", hit.sum())


def _city(df: pd.DataFrame, col: str, table: str, r: dict, rng, log: _Log) -> None:
    """Cities as people type them: 'Plzen', 'praha', 'Brno ' (plus the usual typos)."""
    if col not in df or df.empty:
        return
    _text(df, col, table, r, rng, log)
    v = df[col].astype(object).to_numpy().copy()
    hit = _pick(len(v), r["format"] / 3, rng) & pd.notna(v)
    style = rng.integers(3, size=hit.sum())
    v[hit] = [x.lower() if s == 0 else x.upper() if s == 1 else x + " " for x, s in zip(v[hit], style)]
    log.add(table, col, "velikost písmen / mezera", hit.sum())
    df[col] = v


def _phones(df: pd.DataFrame, r: dict, rng, log: _Log) -> None:
    """+420 777 123 456 -> 777123456 / 00420777123456 / +420777123456 / 777 123 456."""
    if "phone" not in df:
        return
    v = df["phone"].astype(object).to_numpy().copy()
    hit = _pick(len(v), r["format"], rng) & pd.notna(v)
    style = rng.integers(4, size=hit.sum())
    out = []
    for x, s in zip(v[hit], style):
        digits = x.replace("+420", "").replace(" ", "")
        out.append([digits, "00420" + digits, "+420" + digits, f"{digits[:3]} {digits[3:6]} {digits[6:]}"][s])
    v[hit] = out
    df["phone"] = v
    log.add("customers", "phone", "jiný formát", hit.sum())


def _duplicates(df: pd.DataFrame, key: str, table: str, rate: float, rng, log: _Log, tweak=None) -> pd.DataFrame:
    """Copies of some rows with new ids at the end (double submits, a customer signing up twice)."""
    hit = np.flatnonzero(_pick(len(df), rate, rng))
    if not len(hit):
        return df
    dup = df.iloc[hit].copy()
    dup[key] = np.arange(int(df[key].max()) + 1, int(df[key].max()) + 1 + len(dup))
    if tweak is not None:
        tweak(dup)
    log.add(table, key, "duplikát", len(dup))
    return pd.concat([df, dup], ignore_index=True)


def dirty_copy(tables: dict[str, pd.DataFrame], level: str, rng: np.random.Generator
               ) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """A messy copy of the tables, plus a log of what was done (table, column, kind, rows)."""
    log = _Log()
    out = {k: v.copy() for k, v in tables.items()}
    if level == "none":
        return out, pd.DataFrame(columns=["table", "column", "kind", "rows"])
    r = RATES[level]

    c = out["customers"]
    _text(c, "first_name", "customers", r, rng, log)
    _text(c, "last_name", "customers", r, rng, log)
    _city(c, "city", "customers", r, rng, log)
    _phones(c, r, rng, log)
    _nulls(c, "phone", "customers", r["null"] * 3, rng, log)
    _nulls(c, "email", "customers", r["null"], rng, log)
    _nulls(c, "gender", "customers", r["null"], rng, log)

    def other_email(dup: pd.DataFrame) -> None:
        dup["email"] = [None if e is None else e.upper() if i % 2 else e.replace("@", "+1@")
                        for i, e in enumerate(dup["email"])]
    out["customers"] = _duplicates(c, "customer_id", "customers", r["dup"], rng, log, other_email)

    o = out["orders"]
    _city(o, "city", "orders", r, rng, log)
    out["payments"] = _duplicates(out["payments"], "payment_id", "payments", r["dup"], rng, log)
    if "deliveries" in out:
        _text(out["deliveries"], "courier", "deliveries", r, rng, log, typos=False)
    for name in ("reviews", "tickets"):
        if name in out:
            _text(out[name], "topic", name, r, rng, log, typos=False)
    if "reviews" in out:
        _nulls(out["reviews"], "text", "reviews", r["null"] * 2, rng, log)
    if "subscriptions" in out:
        _text(out["subscriptions"], "cancel_reason", "subscriptions", r, rng, log, typos=False)
    return out, pd.DataFrame(log.rows, columns=["table", "column", "kind", "rows"])
