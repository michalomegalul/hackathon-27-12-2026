"""Czech review and ticket text pools.

Texts are generated ahead of time in batches (one LLM call fills one pool key with
~40 texts) and stored as JSON. Rows are filled later by sampling from the pools
with the seed, so no row ever waits on the LLM.

A pool key is  kind | rating | topic | category,  e.g.  review|2|zpoždění|etiopie.
kind is review or ticket. For tickets the rating is the customer's mood (1 = furious).
Category "_any" is the generic pool used when a category has no texts.

Texts may contain placeholders that the sim fills: {produkt}, {dny} (delay with its
unit, "3 dny"), {objednavka} (order id). Unknown placeholders are dropped at generation time.

    python -m s2d.texts generate examples/a.yaml                 # pool for one spec
    python -m s2d.texts generate --generic                       # generic pool
    python -m s2d.texts generate examples/a.yaml --per-key 40 --kinds review
    python -m s2d.texts stats data/text_pools/prazirna_zrnko.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import string
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from s2d import llm
from s2d.spec import StorySpec, load_spec

KINDS = ("review", "ticket")
RATINGS = (1, 2, 3, 4, 5)
TOPICS = ("zpoždění", "kvalita", "cena", "obsluha", "vyprodáno")
ANY = "_any"
PER_KEY = 40
PLACEHOLDERS = {"produkt", "dny", "objednavka"}

TOPIC_HINTS = {
    "zpoždění": "doručení nebo vyřízení objednávky trvalo déle, než slibovali",
    "kvalita": "kvalita produktu (chuť, zpracování, funkčnost, čerstvost)",
    "cena": "cena a poměr cena/výkon, zdražení, slevy",
    "obsluha": "personál, zákaznická podpora, ochota, komunikace",
    "vyprodáno": "zboží nebylo skladem, vyprodané, nedostupná varianta",
}
MOOD = {1: "velmi nespokojený, naštvaný", 2: "nespokojený", 3: "smíšený, neutrální",
        4: "spokojený, drobné výhrady", 5: "nadšený"}


def pool_dir() -> Path:
    return Path(os.environ.get("TEXT_POOL_DIR", "data/text_pools"))


def key(kind: str, rating: int, topic: str, category: str) -> str:
    return f"{kind}|{rating}|{topic}|{category}"


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "pool"


# ---------------------------------------------------------------- generation


def _schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "texts": {"type": "array", "minItems": n, "maxItems": n,
                      "items": {"type": "string", "minLength": 15, "maxLength": 400}},
        },
        "required": ["texts"],
    }


def _company_context(spec: StorySpec | None) -> str:
    if spec is None:
        return "Obecná česká firma (e-shop nebo prodejna). Nezmiňuj konkrétní značku ani obor."
    c = spec.company
    return f"Firma: {c.name} ({c.legal_form.value}), obor {c.industry.value}. {c.description}".strip()


def _category_context(spec: StorySpec | None, category: str) -> str:
    if spec is None or category == ANY:
        return "Produkt: libovolný, piš obecně nebo použij {produkt}."
    cat = next(c for c in spec.entities.products.categories if c.id == category)
    return (f"Kategorie produktu: {category.replace('_', ' ')} "
            f"(ceny {cat.price_min:.0f}-{cat.price_max:.0f} {spec.meta.currency.value}).")


def build_prompt(spec: StorySpec | None, kind: str, rating: int, topic: str, category: str,
                 n: int, batch: int = 0) -> str:
    what = ("recenzí zákazníků (jako na Heurece nebo Google)" if kind == "review"
            else "zpráv zákazníků na zákaznickou podporu (e-mail nebo formulář)")
    lines = [
        f"Napiš {n} různých krátkých {what} v češtině.",
        _company_context(spec),
        _category_context(spec, category),
        f"Hodnocení {rating}/5, nálada pisatele: {MOOD[rating]}.",
        f"Hlavní téma: {topic} ({TOPIC_HINTS[topic]}).",
        "Pravidla:",
        "- Každý text 1-3 věty, různé délky, různý styl (někdo píše spisovně, někdo hovorově, "
        "občas bez diakritiky nebo s překlepem).",
        "- Neopakuj stejné začátky ani fráze. Nevymýšlej jména firem, osob ani přesná data.",
        "- Čísla nepiš natvrdo. Kde se hodí, použij zástupné značky {produkt} (název produktu), "
        "{dny} (zpoždění i s jednotkou, např. '5 dní') a {objednavka} (číslo objednávky). "
        "Jiné značky nepoužívej.",
    ]
    if kind == "ticket":
        lines.append("- Je to zpráva firmě, ne veřejná recenze: dotaz, stížnost nebo žádost o řešení.")
    if batch:
        lines.append(f"- Toto je dávka č. {batch + 1}, vymysli jiné formulace než obvykle.")
    lines.append('Vrať JSON {"texts": [...]}.')
    return "\n".join(lines)


_FIELD = string.Formatter()


def _latin_only(text: str) -> bool:
    # At temperature 1.0 gemma4 sometimes slips into another script mid-word.
    return all(not ch.isalpha() or unicodedata.name(ch, "").startswith("LATIN") for ch in text)


def clean(texts: Iterable) -> list[str]:
    """Strip, dedupe, and drop texts with broken or unknown placeholders or
    non-Latin letters."""
    out, seen = [], set()
    for t in texts:
        if not isinstance(t, str):
            continue
        t = " ".join(t.split())
        if len(t) < 10 or t.lower() in seen or not _latin_only(t):
            continue
        try:
            fields = {f for _, f, _, _ in _FIELD.parse(t) if f is not None}
        except ValueError:
            continue
        if not fields <= PLACEHOLDERS:
            continue
        seen.add(t.lower())
        out.append(t)
    return out


def plan_keys(spec: StorySpec | None, kinds=KINDS, ratings=RATINGS, topics=TOPICS) -> list[tuple]:
    cats = [c.id for c in spec.entities.products.categories] if spec else [ANY]
    return [(k, r, t, c) for k in kinds for c in cats for r in ratings for t in topics]


def load_pool(path: str | Path) -> dict[str, list[str]]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["pools"]


def save_pool(path: str | Path, pools: dict, meta: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"meta": meta, "pools": pools}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)


def generate_pool(spec: StorySpec | None, out: str | Path, *, per_key: int = PER_KEY,
                  per_call: int = PER_KEY, kinds=KINDS, limit: int | None = None,
                  workers: int | None = None,
                  progress: Callable[[int, int, str], None] | None = None) -> dict[str, list[str]]:
    """Fill every key up to `per_key` texts, `per_call` texts per LLM call.

    Resumable: keys already full in `out` are skipped, and the file is rewritten
    after every call, so an interrupted overnight run loses at most one batch.
    """
    pools = load_pool(out)
    todo = [k for k in plan_keys(spec, kinds) if len(pools.get(key(*k), [])) < per_key]
    if limit is not None:
        todo = todo[:limit]
    meta = {"company": spec.company.name if spec else "generic", "model": llm.current_model(),
            "backend": llm.backend_name()}
    lock = threading.Lock()
    done = 0
    if workers is None:
        workers = 2 if os.environ.get("OLLAMA_DESKTOP_URL") else 1

    def fill(k: tuple) -> tuple[str, int]:
        name = key(*k)
        batch = 0
        while True:
            with lock:
                have = len(pools.get(name, []))
            if have >= per_key or batch >= 2 * (per_key // per_call + 1):
                return name, have
            n = min(per_call, per_key - have)
            prompt = build_prompt(spec, *k, n=n, batch=batch)
            data = llm.complete("texts", prompt, _schema(n))
            with lock:
                merged = clean(pools.get(name, []) + list(data.get("texts", [])))
                pools[name] = merged[:per_key]
                save_pool(out, pools, meta)
            batch += 1

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = [ex.submit(fill, k) for k in todo]
        for f in as_completed(futures):
            name, have = f.result()
            done += 1
            if progress:
                progress(done, len(todo), f"{name}: {have}")
    return pools


# ---------------------------------------------------------------- filling rows


def _lookup(pools: dict, kind: str, rating: int, topic: str, category: str) -> list[str]:
    """Most specific non-empty pool: exact, then generic category, then nearest rating."""
    for cat in (category, ANY):
        for r in sorted(RATINGS, key=lambda x: abs(x - rating)):
            texts = pools.get(key(kind, r, topic, cat))
            if texts:
                return texts
    return []


def cz_days(n) -> str:
    n = int(round(float(n)))
    return f"{n} den" if n == 1 else f"{n} dny" if 2 <= n <= 4 else f"{n} dní"


def fill_texts(rows: pd.DataFrame, pools: dict, seed: int) -> pd.Series:
    """One text per row. `rows` needs kind, rating, topic, category, and may have
    produkt, dny, objednavka for the placeholders. Same seed, same texts."""
    rng = np.random.default_rng(seed)
    extras = {c: rows[c].astype(str).tolist() if c in rows else None for c in PLACEHOLDERS}
    if "dny" in rows:
        extras["dny"] = [cz_days(v) for v in rows["dny"]]
    out = []
    for i, (kind, rating, topic, cat) in enumerate(
            zip(rows["kind"], rows["rating"], rows["topic"], rows["category"])):
        texts = _lookup(pools, kind, int(rating), topic, cat)
        if not texts:
            out.append("")
            continue
        text = texts[rng.integers(len(texts))]
        values = {c: (v[i] if v is not None else "") for c, v in extras.items()}
        out.append(text.format(**values) if "{" in text else text)
    return pd.Series(out, index=rows.index, name="text")


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m s2d.texts")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate text pools (overnight batch)")
    g.add_argument("spec", nargs="?", help="spec YAML; pools per category of this company")
    g.add_argument("--generic", action="store_true", help="the generic _any pool instead")
    g.add_argument("--out", help="pool file (default data/text_pools/<company>.json)")
    g.add_argument("--per-key", type=int, default=PER_KEY)
    g.add_argument("--per-call", type=int, default=PER_KEY)
    g.add_argument("--kinds", default=",".join(KINDS))
    g.add_argument("--limit", type=int, help="only the first N unfinished keys")
    g.add_argument("--workers", type=int)
    s = sub.add_parser("stats", help="show how full a pool file is")
    s.add_argument("pool")
    args = p.parse_args(argv)

    if args.cmd == "stats":
        pools = load_pool(args.pool)
        sizes = [len(v) for v in pools.values()]
        print(f"{len(pools)} keys, {sum(sizes)} texts, min {min(sizes, default=0)} per key")
        for name in list(pools)[:5]:
            print(f"  {name}: {pools[name][:2]}")
        return 0

    if not args.generic and not args.spec:
        p.error("give a spec or --generic")
    spec = None if args.generic else load_spec(args.spec)
    out = Path(args.out) if args.out else pool_dir() / f"{slug(spec.company.name) if spec else 'generic'}.json"
    kinds = tuple(k for k in args.kinds.split(",") if k)
    n_keys = len(plan_keys(spec, kinds))
    print(f"{llm.describe()}: {n_keys} keys x {args.per_key} texts -> {out}")
    t0 = time.perf_counter()

    def progress(done, total, msg):
        el = time.perf_counter() - t0
        eta = el / done * (total - done)
        print(f"[{done}/{total}] {msg}  ({el:.0f}s, eta {eta / 60:.0f} min)", flush=True)

    generate_pool(spec, out, per_key=args.per_key, per_call=args.per_call, kinds=kinds,
                  limit=args.limit, workers=args.workers, progress=progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
