//! Compares the Rust spec port with fixtures dumped from the Python original
//! (`uv run python rust/tools/gen_spec_fixtures.py`).

use std::fs;
use std::path::PathBuf;

use s2d_core::spec::{SpecError, StorySpec};
use serde_json::Value;

fn fixture(name: &str) -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../fixtures/spec").join(name);
    serde_json::from_str(&fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path:?}: {e}"))).unwrap()
}

/// Python writes 1.0 where JSON input had 1; compare numbers as f64.
fn normalize(v: Value) -> Value {
    match v {
        Value::Number(n) => serde_json::json!(n.as_f64().unwrap()),
        Value::Array(a) => Value::Array(a.into_iter().map(normalize).collect()),
        Value::Object(o) => Value::Object(o.into_iter().map(|(k, v)| (k, normalize(v))).collect()),
        other => other,
    }
}

#[test]
fn valid_specs_round_trip_to_the_python_dump() {
    for name in ["a", "b"] {
        let spec = StorySpec::from_value(fixture(&format!("valid_{name}.input.json")))
            .unwrap_or_else(|e| panic!("{name}: {e}"));
        let ours = normalize(serde_json::to_value(&spec).unwrap());
        let theirs = normalize(fixture(&format!("valid_{name}.json")));
        assert_eq!(ours, theirs, "spec {name} differs from the Python dump");
    }
}

/// The sentence list Python raised, without pydantic's wrapper text.
fn python_message(error: &str) -> Option<String> {
    let after = error.split("Value error, ").nth(1)?;
    Some(after.split(" [type=").next()?.to_string())
}

#[test]
fn invalid_specs_are_rejected_with_the_python_message() {
    let cases = fixture("invalid.json");
    let cases = cases.as_array().unwrap();
    assert!(cases.len() >= 20);
    let mut compared = 0;
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let result = StorySpec::from_value(case["input"].clone());
        let err = match result {
            Ok(_) => panic!("{name}: accepted an invalid spec"),
            Err(e) => e,
        };
        if let Some(expected) = python_message(case["error"].as_str().unwrap()) {
            match err {
                SpecError::Invalid(got) => assert_eq!(got, expected, "{name}"),
                other => panic!("{name}: expected a semantic error, got {other}"),
            }
            compared += 1;
        }
    }
    // Every semantic rule in the fixtures must have been compared, not just rejected.
    assert!(compared >= 15, "only {compared} messages compared");
}

#[test]
fn short_channel_form_is_normalized() {
    let spec = StorySpec::from_value(fixture("valid_a.input.json")).unwrap();
    let got: Vec<_> = spec.company.channels.iter().map(|c| (c.channel.value(), c.weight)).collect();
    assert_eq!(got, vec![("eshop", 0.55), ("store", 0.45)]);
}
