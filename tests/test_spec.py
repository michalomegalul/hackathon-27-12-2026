import json

import pytest
import yaml
from pydantic import ValidationError

from s2d.spec import StorySpec, load_spec, story_json_schema

EXAMPLES = ["examples/a.yaml", "examples/b.yaml"]


@pytest.mark.parametrize("path", EXAMPLES)
def test_examples_validate(path):
    spec = load_spec(path)
    assert spec.events


def test_short_channel_form_is_normalized():
    spec = load_spec("examples/a.yaml")
    assert [(c.channel.value, c.weight) for c in spec.company.channels] == [("eshop", 0.55), ("store", 0.45)]


def test_schema_is_flat():
    text = json.dumps(story_json_schema())
    assert "$ref" not in text and "oneOf" not in text


def _raw_a():
    with open("examples/a.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["events"][1]["target"].update(segment=["nobody"]), "unknown segment"),
    (lambda d: d["events"][0].update(start="2030-01-01"), "outside"),
    (lambda d: d["events"][1].update(caused_by="E9"), "not an earlier event"),
    (lambda d: d["entities"]["customers"]["segments"][0].update(share=0.9), "shares sum"),
])
def test_semantic_errors(mutate, message):
    data = _raw_a()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        StorySpec.model_validate(data)


def test_supply_events_need_their_params():
    data = yaml.safe_load(open("examples/a.yaml", encoding="utf-8"))
    ev = next(e for e in data["events"] if e["type"] == "supplier_delay")
    ev["params"] = {}
    with pytest.raises(ValidationError, match="needs params.lead_time_multiplier"):
        StorySpec.model_validate(data)
