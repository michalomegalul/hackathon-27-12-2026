"""The narrator: one LLM call that looks at the scan's suspicious findings, accepts,
rejects or merges them, and for each one states what is odd (observation_cs) and a
hypothesis of what happened in the company (hypothesis_cs): one Czech sentence in the
style of a spec's `narrative_cs`, so the web can show it next to the sentence the
story planted. It never invents events, dates or numbers: the output only refers to
candidate ids, and every id is checked. The hypothesis may lean only on the
candidates, their evidence and the anchors (price-list and courier changes read from
treatment tables), so the detective stays blind. If the LLM fails, every candidate
with confidence >= FALLBACK_CONFIDENCE is accepted and rule-based hypotheses and a
template narrative are written, so the demo never stops.
"""

from __future__ import annotations

import datetime as dt
import json

from s2d import llm

FALLBACK_CONFIDENCE = 0.5

SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "accept": {"type": "boolean"},
                    "merged_into": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "label_cs": {"type": "string"},
                    "observation_cs": {"type": "string"},
                    "hypothesis_cs": {"type": "string"},
                },
                "required": ["candidate_id", "accept", "merged_into", "label_cs",
                             "observation_cs", "hypothesis_cs"],
            },
        },
        "narrative_cs": {"type": "string"},
    },
    "required": ["events", "narrative_cs"],
}

METRIC_CS = {
    "purchase_rate": "objednávky", "churn_hazard": "odchod zákazníků",
    "acquisition_rate": "noví zákazníci", "rating_mean": "hodnocení",
    "ticket_rate": "tikety", "delivery_days": "doba doručení",
}
SINGULAR = {"churn_hazard", "rating_mean", "delivery_days"}  # "odchod roste", not "rostou"
KIND_CS = {"shift": "trvalejší změna", "spike": "krátký výkyv", "stockout": "výpadek zásob"}


def _table(events: list[dict]) -> str:
    keys = ["id", "metric", "segment", "start_date", "end_date", "direction", "magnitude_pct",
            "lag_days", "caused_by", "kind", "confidence", "evidence"]
    return "\n".join(json.dumps({k: e.get(k) for k in keys}, ensure_ascii=False) for e in events)


def _anchors(result: dict) -> str:
    rows = []
    for a in result.get("anchors") or []:
        if a.get("kind") == "price":
            rows.append(f"- {a['date']}: změna ceníku {a.get('pct', 0):+.0f} % ({_seg_cs(a.get('segment', ''))})")
        elif a.get("kind") == "courier":
            rows.append(f"- {a['date']}: přechod na kurýra {a.get('courier')} ({_seg_cs(a.get('segment', ''))})")
    return "\n".join(rows) or "- žádné"


# The hypothesis examples in the prompt are shapes with <placeholders>, never a sentence from a
# spec in examples/: a real one would hand the blind detective that story's answer.
def build_prompt(result: dict) -> str:
    events = result["events"]
    counts = result.get("status_counts", {})
    return f"""Jsi detektiv a datový analytik e-shopu. Nevíš, co se ve firmě stalo; vidíš jen data.
Statistický sken prošel {result['n_series']} denních řad ({result['data_start']} až
{result['data_end']}) a našel tyto podezřelé jevy. Odfiltroval už
{counts.get('explained_by_calendar', 0)} změn vysvětlených kalendářem (svátky, Black Friday,
prosinec) a {counts.get('not_confirmed', 0)} nepotvrzených.

Podezřelé jevy (JSON na řádek; evidence popisuje statistický důkaz, caused_by = jev, na který
tento navazuje, lag_days = zpoždění):
{_table(events)}

Zásahy, které firma podle svých tabulek udělala (ceníky, kurýři):
{_anchors(result)}

Úkol:
- U každého jevu rozhodni accept true/false. Odmítni jen to, co je zjevně duplicitní nebo
  nedává smysl. Duplicitu sluč: accept false a merged_into = id jevu, který ji pokrývá.
- label_cs: krátký český popis (max 8 slov), např. "Pokles objednávek v Brně v prodejně".
- observation_cs: jedna věta, co je na datech podezřelé (co, kde, od kdy, jak moc).
- hypothesis_cs: jedna krátká věta, co se ve firmě nejspíš stalo, tedy příčina, ne opis čísel.
  Piš ji jako zadání příběhu, tvarem jako "Zdražení <kategorie> o <X> % od <datum>." nebo
  "<Segment> po zdražení odcházejí se zpožděním několika týdnů." nebo "Nový konkurent
  v <městě> odlákal zákazníky prodejny." (za <...> dosaď údaje z tabulky). Opři ji o zásahy výše, o caused_by a o evidence (vyprodáno, kurýr, zdražení).
  Bez opory navrhni nejpravděpodobnější obchodní vysvětlení (konkurence, kampaň, problém
  s kvalitou, výpadek dodávky, technický problém) a slovem "nejspíš" dej najevo nejistotu.
- narrative_cs: 3 až 6 vět česky, co se ve firmě podle dat stalo a v jakém pořadí.
Pravidla: používej jen id z tabulky. Nevymýšlej nová data ani čísla: každé datum a číslo
v textu musí pocházet z tabulky nebo ze seznamu zásahů."""


SEG_KEY_CS = {"category": "kategorie", "segment": "segment", "courier": "kurýr", "supplier": "dodavatel",
              "sku": "SKU", "topic": "téma tiketů"}
CHANNEL_CS = {"eshop": "e-shop", "store": "prodejna"}


def _seg_cs(seg: str | None) -> str:
    """'city=Brno;channel=store' -> 'Brno, prodejna'; empty -> 'všichni zákazníci'."""
    parts = []
    for part in filter(None, (seg or "").split(";")):
        k, _, v = part.partition("=")
        vals = ", ".join(CHANNEL_CS.get(x, x) for x in v.split(","))
        parts.append(vals if k in ("city", "channel") else f"{SEG_KEY_CS.get(k, k)} {vals}")
    return ", ".join(parts) or "všichni zákazníci"


PRICE_METRICS = {"purchase_rate", "churn_hazard", "acquisition_rate"}
COURIER_METRICS = {"delivery_days", "rating_mean", "ticket_rate", "churn_hazard"}
ANCHOR_LOOKBACK = 60  # an anchor explains a find that starts up to 60 days after it (churn lags weeks)


def _anchor_for(e: dict, anchors: list[dict]) -> dict | None:
    """The latest anchor that can explain the find: a price change for orders, churn and new
    customers (any segment: students leave after coffee gets dearer), a courier switch for
    delivery, rating, tickets and churn in one of its cities; dated from 3 days after the
    find's start back to ANCHOR_LOOKBACK days before it."""
    day = _date(e["start_date"])
    seg = e.get("segment") or ""
    best = None
    for a in anchors or []:
        if not -3 <= (day - _date(a["date"])).days <= ANCHOR_LOOKBACK:
            continue
        if a["kind"] == "price":
            ok = e["metric"] in PRICE_METRICS
        else:
            ok = e["metric"] in COURIER_METRICS and (not seg or any(f"city={c}" in seg for c in a.get("cities", [])))
        if ok and (best is None or _date(a["date"]) > _date(best["date"])):
            best = a
    return best


def _moves(metric: str, up: bool) -> str:
    if metric in SINGULAR:
        return "roste" if up else "klesá"
    return "rostou" if up else "klesají"


def _date(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def hypothesis(e: dict, anchors: list[dict] | None = None, by_id: dict | None = None) -> str:
    """A rule-based hypothesis, one Czech sentence: the fallback when the LLM is down."""
    seg = _seg_cs(e.get("segment"))
    up = e.get("direction") == "up"
    m = e.get("metric")
    ev = e.get("evidence") or ""
    a = _anchor_for(e, anchors or [])
    src = (by_id or {}).get(e.get("caused_by")) if e.get("caused_by") else None
    if e.get("kind") == "stockout":
        return f"Výpadek dodávky: zboží ({seg}) došlo a nebylo co prodávat."
    if "vyprodáno" in ev and m in ("purchase_rate", "ticket_rate", "rating_mean"):
        return f"Vyprodané zboží ({seg}) vede k {'stížnostem' if m == 'ticket_rate' else 'menším nákupům'}."
    if src:
        return (f"Navazuje na {src['id']} ({METRIC_CS.get(src['metric'], src['metric'])}, {_seg_cs(src.get('segment'))}): "
                f"zákazníci ({seg}) reagují se zpožděním {e.get('lag_days') or '?'} dní.")
    if a and a["kind"] == "price":
        pct = a.get("pct") or 0
        what = "Zdražení" if pct > 0 else "Zlevnění"
        if m == "churn_hazard":
            return f"Zákazníci ({seg}) po {what.lower()} od {a['date']} odcházejí."
        return f"{what} o {abs(pct):.0f} % od {a['date']} ({_seg_cs(a['segment'])}) změnilo nákupy."
    if a and a["kind"] == "courier":
        return f"Přechod na kurýra {a.get('courier')} od {a['date']} ({_seg_cs(a['segment'])}) zhoršil doručení."
    if e.get("kind") == "spike":
        if m in ("purchase_rate", "acquisition_rate") and up:
            return f"Nejspíš krátká akce nebo kampaň ({seg}) od {e['start_date']}."
        return f"Nejspíš krátký výpadek nebo technický problém ({seg}) od {e['start_date']}."
    table = {
        ("purchase_rate", False): f"Nejspíš konkurence nebo zhoršení služby: zákazníci ({seg}) nakupují méně.",
        ("purchase_rate", True): f"Nejspíš kampaň nebo nová nabídka: zákazníci ({seg}) nakupují víc.",
        ("churn_hazard", True): f"Zákazníci ({seg}) jsou nespokojení a odcházejí.",
        ("churn_hazard", False): f"Zákazníci ({seg}) jsou věrnější, nejspíš díky zlepšení služby.",
        ("acquisition_rate", True): f"Nejspíš marketingová kampaň přivedla nové zákazníky ({seg}).",
        ("acquisition_rate", False): f"Nejspíš konkurence nebo konec kampaně: méně nových zákazníků ({seg}).",
        ("rating_mean", False): f"Nejspíš problém s kvalitou zboží nebo služby ({seg}).",
        ("rating_mean", True): f"Nejspíš zlepšení kvality ({seg}).",
        ("ticket_rate", True): f"Nejspíš problém s dodávkami nebo kvalitou: víc stížností ({seg}).",
        ("ticket_rate", False): f"Méně stížností ({seg}), nejspíš vyřešený problém.",
        ("delivery_days", True): f"Nejspíš problém u dopravce: doručení trvá déle ({seg}).",
        ("delivery_days", False): f"Rychlejší doručení ({seg}), nejspíš nový dopravce.",
    }
    return table.get((m, up), f"Nejspíš změna ve firmě ({seg}) od {e['start_date']}.")


def observation(e: dict) -> str:
    seg = _seg_cs(e.get("segment"))
    if e.get("kind") == "stockout":
        return f"Od {e['start_date']} se neprodává {seg}."
    mag = e.get("magnitude_pct")
    how = f" o {abs(mag):.0f} %" if mag is not None and e.get("metric") not in ("delivery_days", "rating_mean") else ""
    return (f"Od {e['start_date']} {METRIC_CS.get(e['metric'], e['metric'])} ({seg}) "
            f"{_moves(e['metric'], e['direction'] == 'up')}{how} ({KIND_CS.get(e['kind'], e['kind'])}).")


def _template(result: dict) -> dict:
    accepted = [e for e in result["events"] if e["confidence"] >= FALLBACK_CONFIDENCE]
    anchors = result.get("anchors") or []
    by_id = {e["id"]: e for e in result["events"]}
    lines = []
    for e in sorted(accepted, key=lambda e: e["start_date"]):
        seg = e["segment"].replace(";", ", ") or "všichni zákazníci"
        why = f", navazuje na {e['caused_by']} po {e['lag_days']} dnech" if e.get("caused_by") else ""
        lines.append(f"Od {e['start_date']} {METRIC_CS.get(e['metric'], e['metric'])} "
                     f"({seg}) {_moves(e['metric'], e['direction'] == 'up')} "
                     f"o {abs(e['magnitude_pct']):.0f} %{why}.")
    narrative = " ".join(lines) if lines else "Sken nenašel žádnou změnu, kterou by nevysvětlil kalendář."
    return {
        "events": [{"candidate_id": e["id"], "accept": e["confidence"] >= FALLBACK_CONFIDENCE,
                    "merged_into": None,
                    "label_cs": f"{KIND_CS.get(e['kind'], e['kind'])}: {METRIC_CS.get(e['metric'], e['metric'])}",
                    "observation_cs": observation(e),
                    "hypothesis_cs": hypothesis(e, anchors, by_id)}
                   for e in result["events"]],
        "narrative_cs": narrative,
    }


def validate(out: dict, ids: set[str], result: dict | None = None) -> dict:
    """Every id must be a candidate; unknown ids are an error, missing ones are kept. An empty
    observation or hypothesis is filled with the rule-based one."""
    if not isinstance(out, dict) or not isinstance(out.get("events"), list):
        raise ValueError("output has no events list")
    seen = {}
    for e in out["events"]:
        cid = e.get("candidate_id")
        if cid not in ids:
            raise ValueError(f"unknown candidate id {cid!r}")
        m = e.get("merged_into")
        if m is not None and m not in ids:
            raise ValueError(f"merged_into {m!r} is not a candidate")
        if m is not None:
            e["accept"] = False
        seen[cid] = e
    for cid in ids - seen.keys():  # the model skipped one: keep the scan's decision
        seen[cid] = {"candidate_id": cid, "accept": True, "merged_into": None, "label_cs": ""}
    rules = {e["candidate_id"]: e for e in _template(result)["events"]} if result else {}
    for cid, e in seen.items():
        for k in ("observation_cs", "hypothesis_cs"):
            if not str(e.get(k) or "").strip():
                e[k] = rules.get(cid, {}).get(k, "")
    out["events"] = [seen[c] for c in sorted(seen)]
    if not str(out.get("narrative_cs", "")).strip():
        raise ValueError("empty narrative")
    return out


def narrate(result: dict, on_status=None) -> dict:
    ids = {e["id"] for e in result["events"]}
    if not ids:
        out = _template(result)
        out["source"] = "template (no events)"
        return out
    try:
        raw = llm.complete("detective", build_prompt(result), SCHEMA, on_status=on_status)
        out = validate(raw, ids, result)
        info = llm.last_call()
        out["source"] = f"{info.backend} {info.model}" + (" (cache)" if info.cached else "")
        return out
    except (llm.LLMError, ValueError) as e:
        out = _template(result)
        out["source"] = f"template (LLM failed: {e})"
        return out
