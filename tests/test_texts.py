import pandas as pd

from s2d import texts
from s2d.spec import load_spec


def test_plan_covers_ratings_topics_categories():
    spec = load_spec("examples/a.yaml")
    keys = texts.plan_keys(spec)
    assert len(keys) == 2 * 5 * 5 * len(spec.entities.products.categories)
    assert texts.plan_keys(None)[0][3] == texts.ANY


def test_generate_batches_one_call_per_key(tmp_path, monkeypatch):
    calls = []

    def fake(step, prompt, schema=None, **kw):
        calls.append(prompt)
        n = schema["properties"]["texts"]["maxItems"]
        return {"texts": [f"Text cislo {len(calls)}-{i} o {{produkt}}" for i in range(n)]}
    monkeypatch.setattr(texts.llm, "complete", fake)
    out = tmp_path / "pool.json"
    pools = texts.generate_pool(None, out, per_key=40, kinds=("review",), limit=3, workers=1)
    assert len(calls) == 3 and all(len(v) == 40 for v in pools.values())
    # resumable: a second run skips the 3 full keys and fills the next 3
    pools = texts.generate_pool(None, out, per_key=40, kinds=("review",), limit=3, workers=1)
    assert len(calls) == 6 and len(pools) == 6 and all(len(v) == 40 for v in pools.values())


def test_clean_drops_bad_texts():
    got = texts.clean(["Dobrá káva {produkt}", "dobrá káva {produkt}", "Neznámá {jmeno} značka",
                       "Rozbitá { závorka", "záपदा mix písma", "krátké"])
    assert got == ["Dobrá káva {produkt}"]


def test_fill_is_seeded_and_falls_back():
    pools = {texts.key("review", 1, "zpoždění", texts.ANY): [f"Čekal jsem {{dny}} na {{produkt}} #{i}" for i in range(40)]}
    rows = pd.DataFrame({"kind": ["review"] * 3, "rating": [1, 2, 1], "topic": ["zpoždění"] * 3,
                         "category": ["etiopie"] * 3, "dny": [1, 3, 7], "produkt": ["Etiopie Sidamo"] * 3})
    a, b = texts.fill_texts(rows, pools, seed=5), texts.fill_texts(rows, pools, seed=5)
    assert a.tolist() == b.tolist()
    assert a[0].startswith("Čekal jsem 1 den na Etiopie Sidamo")
    assert "3 dny" in a[1] and "7 dní" in a[2]  # rating 2 falls back to the nearest rating
