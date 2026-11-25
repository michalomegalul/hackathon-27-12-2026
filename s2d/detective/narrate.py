"""The narrator: one LLM call that accepts, rejects or merges scan candidates and
writes the Czech story. It never invents events, dates or numbers: the output only
refers to candidate ids, and every id is checked. If the LLM fails, every
candidate with confidence >= FALLBACK_CONFIDENCE is accepted and a template
narrative is written, so the demo never stops.
"""

from __future__ import annotations

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
                },
                "required": ["candidate_id", "accept", "merged_into", "label_cs"],
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
KIND_CS = {"shift": "trvalejší změna", "spike": "krátký výkyv", "stockout": "výpadek zásob"}


def _table(events: list[dict]) -> str:
    keys = ["id", "metric", "segment", "start_date", "end_date", "direction", "magnitude_pct",
            "lag_days", "caused_by", "kind", "confidence", "evidence"]
    return "\n".join(json.dumps({k: e.get(k) for k in keys}, ensure_ascii=False) for e in events)


def build_prompt(result: dict) -> str:
    events = result["events"]
    counts = result.get("status_counts", {})
    return f"""Jsi datový analytik. Statistický sken prošel {result['n_series']} denních řad
({result['data_start']} až {result['data_end']}) a našel tyto kandidáty na události.
Odfiltroval už {counts.get('explained_by_calendar', 0)} změn vysvětlených kalendářem (svátky,
Black Friday, prosinec) a {counts.get('not_confirmed', 0)} nepotvrzených.

Kandidáti (JSON na řádek):
{_table(events)}

Úkol:
- U každého kandidáta rozhodni accept true/false. Odmítni jen to, co je zjevně duplicitní
  nebo nedává smysl. Duplicitu sluč: accept false a merged_into = id kandidáta, který ji pokrývá.
- label_cs: krátký český popis (max 8 slov), např. "Pokles objednávek v Brně v prodejně".
- narrative_cs: 3 až 6 vět česky, co se ve firmě podle dat stalo a v jakém pořadí.
  Uveď příčiny, pokud je naznačuje caused_by.
Pravidla: používej jen id z tabulky. Nevymýšlej nová data, čísla ani události.
Každé datum a číslo v textu musí pocházet z tabulky."""


def _template(result: dict) -> dict:
    accepted = [e for e in result["events"] if e["confidence"] >= FALLBACK_CONFIDENCE]
    lines = []
    for e in sorted(accepted, key=lambda e: e["start_date"]):
        seg = e["segment"].replace(";", ", ") or "všichni zákazníci"
        why = f", navazuje na {e['caused_by']} po {e['lag_days']} dnech" if e.get("caused_by") else ""
        lines.append(f"Od {e['start_date']} {METRIC_CS.get(e['metric'], e['metric'])} "
                     f"({seg}) {'rostou' if e['direction'] == 'up' else 'klesají'} "
                     f"o {abs(e['magnitude_pct']):.0f} %{why}.")
    narrative = " ".join(lines) if lines else "Sken nenašel žádnou změnu, kterou by nevysvětlil kalendář."
    return {
        "events": [{"candidate_id": e["id"], "accept": e["confidence"] >= FALLBACK_CONFIDENCE,
                    "merged_into": None,
                    "label_cs": f"{KIND_CS.get(e['kind'], e['kind'])}: {METRIC_CS.get(e['metric'], e['metric'])}"}
                   for e in result["events"]],
        "narrative_cs": narrative,
    }


def validate(out: dict, ids: set[str]) -> dict:
    """Every id must be a candidate; unknown ids are an error, missing ones are kept."""
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
        out = validate(raw, ids)
        info = llm.last_call()
        out["source"] = f"{info.backend} {info.model}" + (" (cache)" if info.cached else "")
        return out
    except (llm.LLMError, ValueError) as e:
        out = _template(result)
        out["source"] = f"template (LLM failed: {e})"
        return out
