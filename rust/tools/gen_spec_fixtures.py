"""Golden fixtures for the Rust port of s2d/spec.py.

Run from the repo root:  uv run python rust/tools/gen_spec_fixtures.py

Writes rust/fixtures/spec/:
  valid_<name>.json  - the normalized spec (what the Python model dumps) for each valid YAML
  invalid.json       - [{name, input, error}] cases; `error` is the exact Python message
  schema.json        - the flat JSON schema (same as schema/story.schema.json)
"""

import copy
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from s2d.spec import StorySpec, story_json_schema

OUT = Path("rust/fixtures/spec")
VALID = {"a": "examples/a.yaml", "b": "examples/b.yaml"}


def raw(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n"


def mutations(d):
    """name -> mutated copy. Each hits one rule of StorySpec or a field bound."""
    def m(name, fn):
        c = copy.deepcopy(d)
        fn(c)
        return name, c
    ev = lambda c, i=0: c["events"][i]
    seg = lambda c: c["entities"]["customers"]["segments"]
    yield m("unknown_segment", lambda c: ev(c, 1)["target"].update(segment=["nobody"]))
    yield m("unknown_city", lambda c: ev(c)["target"].update(city=["Atlantis"]))
    yield m("unknown_channel", lambda c: ev(c)["target"].update(channel=["phone"]))
    yield m("start_outside", lambda c: ev(c).update(start="2030-01-01"))
    yield m("caused_by_unknown", lambda c: ev(c, 1).update(caused_by="E9"))
    yield m("caused_by_later", lambda c: ev(c).update(caused_by=ev(c, 1)["id"]))
    yield m("duplicate_id", lambda c: ev(c, 1).update(id=ev(c)["id"]))
    yield m("shares_sum", lambda c: seg(c)[0].update(share=0.9))
    yield m("city_weights", lambda c: c["company"]["cities"][0].update(weight=0.01))
    yield m("channel_twice", lambda c: c["company"]["channels"].append(copy.deepcopy(c["company"]["channels"][0])))
    yield m("price_min_gt_max", lambda c: c["entities"]["products"]["categories"][0].update(price_min=1e6))
    yield m("unknown_supplier", lambda c: c["entities"]["products"]["categories"][0].update(supplier="zzz"))
    yield m("decoy_outside", lambda c: c["decoys"][0].update(date="2031-01-01"))
    yield m("extra_key", lambda c: c.update(typo=1))
    yield m("days_too_small", lambda c: c["meta"].update(days=10))
    yield m("missing_meta", lambda c: c.pop("meta"))
    yield m("bad_enum", lambda c: ev(c).update(type="nope"))
    yield m("bad_date", lambda c: c["meta"].update(start="2025-02-30"))
    yield m("effects_empty", lambda c: ev(c).update(effects=[]))
    yield m("size_too_big", lambda c: ev(c)["effects"][0].update(size=99))
    yield m("supplier_delay_no_mult", lambda c: ev(c).update(
        type="supplier_delay", params={}, target={"supplier": [c["entities"]["suppliers"][0]["id"]]}))
    yield m("churn_shock_missing", lambda c: ev(c).update(type="churn_shock", params={}))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, path in VALID.items():
        data = raw(path)
        spec = StorySpec.model_validate(data)
        (OUT / f"valid_{name}.json").write_text(dump(spec.model_dump(mode="json")), encoding="utf-8")
        (OUT / f"valid_{name}.input.json").write_text(dump(data), encoding="utf-8")
        if name == "a":
            for cname, bad in mutations(data):
                try:
                    StorySpec.model_validate(bad)
                except ValidationError as exc:
                    cases.append({"name": cname, "input": bad, "error": str(exc)})
                else:
                    raise SystemExit(f"mutation {cname} unexpectedly valid")
    (OUT / "invalid.json").write_text(dump(cases), encoding="utf-8")
    (OUT / "schema.json").write_text(dump(story_json_schema()), encoding="utf-8")
    print(f"{len(cases)} invalid cases")


main()
