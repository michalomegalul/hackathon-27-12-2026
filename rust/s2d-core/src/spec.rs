//! The story DSL (port of `s2d/spec.py`).
//!
//! Unknown keys are an error. Field bounds and the cross-field checks run in
//! [`StorySpec::validate`]; its messages are plain sentences that are sent back to
//! the LLM verbatim, so their wording must match the Python original.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use chrono::{Duration, NaiveDate};
use serde::{Deserialize, Deserializer, Serialize};

// ---------------------------------------------------------------- enums

macro_rules! string_enum {
    ($(#[$m:meta])* $name:ident { $($variant:ident = $text:literal),+ $(,)? }) => {
        $(#[$m])*
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
        pub enum $name {
            $(#[serde(rename = $text)] $variant),+
        }
        impl $name {
            /// The wire value, e.g. `"s.r.o."`.
            pub fn value(&self) -> &'static str {
                match self { $(Self::$variant => $text),+ }
            }
        }
    };
}

string_enum!(Currency { Czk = "CZK", Eur = "EUR" });
string_enum!(Difficulty { Easy = "easy", Medium = "medium", Hard = "hard" });
string_enum!(LegalForm { Sro = "s.r.o.", As = "a.s.", Other = "other" });
string_enum!(Industry {
    Retail = "retail", Eshop = "eshop", CafeChain = "cafe_chain",
    Subscription = "subscription", Services = "services",
});
string_enum!(Channel { Eshop = "eshop", Store = "store", App = "app", Phone = "phone" });
string_enum!(SeasonProfile {
    RetailCz = "retail_cz", Flat = "flat", SummerPeak = "summer_peak", WinterPeak = "winter_peak",
});
string_enum!(EventType {
    PriceChange = "price_change", ChurnShock = "churn_shock", CompetitorEntry = "competitor_entry",
    Campaign = "campaign", SupplierDelay = "supplier_delay", Stockout = "stockout",
    CourierChange = "courier_change", ServiceOutage = "service_outage",
    QualityIssue = "quality_issue", StaffShortage = "staff_shortage", ViralSpike = "viral_spike",
});
string_enum!(Metric {
    PurchaseRate = "purchase_rate", ChurnHazard = "churn_hazard", AcquisitionRate = "acquisition_rate",
    BasketSize = "basket_size", TicketRate = "ticket_rate", RatingMean = "rating_mean",
    ReturnRate = "return_rate", PaymentFailureRate = "payment_failure_rate",
    DeliveryDays = "delivery_days",
});
string_enum!(DecoyType {
    ViralSpike = "viral_spike", SeasonalPeak = "seasonal_peak", DataOutage = "data_outage",
});
string_enum!(Messiness { None = "none", Light = "light", Medium = "medium", Heavy = "heavy" });

// ---------------------------------------------------------------- defaults

fn d_currency() -> Currency { Currency::Czk }
fn d_locale() -> String { "cs_CZ".to_string() }
fn d_difficulty() -> Difficulty { Difficulty::Medium }
fn d_legal_form() -> LegalForm { LegalForm::Sro }
fn d_one() -> f64 { 1.0 }
fn d_weekly() -> Vec<f64> { vec![1.0; 7] }
fn d_profile() -> SeasonProfile { SeasonProfile::Flat }
fn d_stores_per_city() -> i64 { 1 }
fn d_agents() -> i64 { 2 }
fn d_tickets_per_agent() -> f64 { 25.0 }
fn d_zipf() -> f64 { 1.1 }
fn d_reliability() -> f64 { 0.97 }
fn d_pay_fail() -> f64 { 0.02 }
fn d_return() -> f64 { 0.02 }
fn d_review() -> f64 { 0.1 }
fn d_ticket() -> f64 { 0.02 }
fn d_version() -> i64 { 1 }
fn d_messiness() -> Messiness { Messiness::None }

// ---------------------------------------------------------------- meta + company

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Meta {
    pub seed: i64,
    pub start: NaiveDate,
    pub days: i64,
    #[serde(default = "d_currency")]
    pub currency: Currency,
    #[serde(default = "d_locale")]
    pub locale: String,
    #[serde(default = "d_difficulty")]
    pub difficulty: Difficulty,
}

impl Meta {
    /// Last simulated day (inclusive).
    pub fn end(&self) -> NaiveDate {
        Duration::try_days(self.days - 1)
            .and_then(|d| self.start.checked_add_signed(d))
            .unwrap_or(NaiveDate::MAX)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ChannelWeight {
    pub channel: Channel,
    pub weight: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct City {
    pub name: String,
    pub weight: f64,
    #[serde(default)]
    pub has_store: bool,
}

/// Either `{channel: eshop, weight: 0.55}` or the report's short form `{eshop: 0.55}`.
#[derive(Deserialize)]
#[serde(untagged)]
enum ChannelEntry {
    Full(ChannelWeight),
    Short(BTreeMap<Channel, f64>),
}

fn channels_short_form<'de, D: Deserializer<'de>>(de: D) -> Result<Vec<ChannelWeight>, D::Error> {
    let mut out = Vec::new();
    for entry in Vec::<ChannelEntry>::deserialize(de)? {
        match entry {
            ChannelEntry::Full(full) => out.push(full),
            ChannelEntry::Short(map) if map.len() == 1 => {
                let (channel, weight) = map.into_iter().next().expect("len is 1");
                out.push(ChannelWeight { channel, weight });
            }
            ChannelEntry::Short(_) => {
                return Err(serde::de::Error::custom(
                    "a channel entry needs 'channel' and 'weight', or a single {channel: weight} pair",
                ))
            }
        }
    }
    Ok(out)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Company {
    pub name: String,
    #[serde(default = "d_legal_form")]
    pub legal_form: LegalForm,
    pub industry: Industry,
    #[serde(deserialize_with = "channels_short_form")]
    pub channels: Vec<ChannelWeight>,
    pub cities: Vec<City>,
    #[serde(default)]
    pub description: String,
}

// ---------------------------------------------------------------- entities

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Segment {
    pub id: String,
    pub share: f64,
    pub base_orders_per_month: f64,
    #[serde(default = "d_one")]
    pub price_sensitivity: f64,
    pub base_churn_per_month: f64,
    /// `None` = guess from the id (predplatitel, subscriber, ...).
    #[serde(default)]
    pub subscription: Option<bool>,
}

impl Segment {
    /// True when customers of this segment hold a subscription.
    pub fn has_subscription(&self) -> bool {
        if let Some(flag) = self.subscription {
            return flag;
        }
        let low = self.id.to_lowercase();
        ["predplat", "předplat", "subscri", "abonent"].iter().any(|k| low.contains(k))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Customers {
    pub n: i64,
    #[serde(default)]
    pub growth_per_year: f64,
    pub segments: Vec<Segment>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Category {
    pub id: String,
    pub n_skus: i64,
    pub price_min: f64,
    pub price_max: f64,
    pub supplier: String,
    #[serde(default = "d_zipf")]
    pub zipf_s: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Products {
    pub categories: Vec<Category>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Supplier {
    pub id: String,
    pub name: String,
    pub lead_time_days: i64,
    #[serde(default = "d_reliability")]
    pub reliability: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Stores {
    #[serde(default = "d_stores_per_city")]
    pub per_city_with_store: i64,
}

impl Default for Stores {
    fn default() -> Self {
        Self { per_city_with_store: d_stores_per_city() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Employees {
    #[serde(default = "d_agents")]
    pub support_agents: i64,
    #[serde(default = "d_tickets_per_agent")]
    pub tickets_per_agent_day: f64,
}

impl Default for Employees {
    fn default() -> Self {
        Self { support_agents: d_agents(), tickets_per_agent_day: d_tickets_per_agent() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Entities {
    pub customers: Customers,
    pub products: Products,
    pub suppliers: Vec<Supplier>,
    #[serde(default)]
    pub stores: Stores,
    #[serde(default)]
    pub employees: Employees,
}

// ---------------------------------------------------------------- baseline

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Seasonality {
    /// Monday first.
    #[serde(default = "d_weekly")]
    pub weekly: Vec<f64>,
    #[serde(default = "d_profile")]
    pub profile: SeasonProfile,
    #[serde(default)]
    pub black_friday: bool,
    #[serde(default)]
    pub christmas: bool,
    #[serde(default)]
    pub cz_holidays_closed: bool,
}

impl Default for Seasonality {
    fn default() -> Self {
        Self {
            weekly: d_weekly(),
            profile: d_profile(),
            black_friday: false,
            christmas: false,
            cz_holidays_closed: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Baseline {
    #[serde(default)]
    pub seasonality: Seasonality,
    #[serde(default = "d_pay_fail")]
    pub payment_failure_rate: f64,
    #[serde(default = "d_return")]
    pub return_rate: f64,
    #[serde(default = "d_review")]
    pub review_rate: f64,
    #[serde(default = "d_ticket")]
    pub ticket_rate_per_order: f64,
}

impl Default for Baseline {
    fn default() -> Self {
        Self {
            seasonality: Seasonality::default(),
            payment_failure_rate: d_pay_fail(),
            return_rate: d_return(),
            review_rate: d_review(),
            ticket_rate_per_order: d_ticket(),
        }
    }
}

// ---------------------------------------------------------------- events

/// Who/what an event hits. An empty list or missing key means "everyone".
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Target {
    #[serde(default)]
    pub city: Option<Vec<String>>,
    #[serde(default)]
    pub segment: Option<Vec<String>>,
    #[serde(default)]
    pub category: Option<Vec<String>>,
    #[serde(default)]
    pub channel: Option<Vec<Channel>>,
    #[serde(default)]
    pub supplier: Option<Vec<String>>,
}

fn non_empty<T>(v: &Option<Vec<T>>) -> bool {
    v.as_ref().is_some_and(|x| !x.is_empty())
}

impl Target {
    /// Stable text form, e.g. `city=Brno;segment=predplatitel`. Empty = everyone.
    pub fn describe(&self) -> String {
        let join = |v: &Option<Vec<String>>| v.as_ref().map(|x| x.join(","));
        let channels = self
            .channel
            .as_ref()
            .map(|x| x.iter().map(|c| c.value()).collect::<Vec<_>>().join(","));
        [
            ("city", join(&self.city), non_empty(&self.city)),
            ("segment", join(&self.segment), non_empty(&self.segment)),
            ("category", join(&self.category), non_empty(&self.category)),
            ("channel", channels, non_empty(&self.channel)),
            ("supplier", join(&self.supplier), non_empty(&self.supplier)),
        ]
        .into_iter()
        .filter(|(_, _, present)| *present)
        .map(|(key, text, _)| format!("{key}={}", text.unwrap_or_default()))
        .collect::<Vec<_>>()
        .join(";")
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Params {
    #[serde(default)]
    pub price_change_pct: Option<f64>,
    #[serde(default)]
    pub lead_time_multiplier: Option<f64>,
    #[serde(default)]
    pub delivery_delay_days: Option<f64>,
    #[serde(default)]
    pub budget_czk: Option<f64>,
    /// churn_shock only: "churn_pct % of the target leaves within churn_window_days".
    #[serde(default)]
    pub churn_pct: Option<f64>,
    #[serde(default)]
    pub churn_window_days: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Effect {
    pub metric: Metric,
    /// Relative: +0.15 = +15 %.
    pub size: f64,
    /// True when the story text states this number; neither difficulty nor calibration may change it.
    #[serde(default)]
    pub size_stated: bool,
    #[serde(default)]
    pub lag_days: i64,
    #[serde(default)]
    pub ramp_days: i64,
    /// `None` = permanent.
    #[serde(default)]
    pub duration_days: Option<i64>,
    #[serde(default)]
    pub decay_halflife_days: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub id: String,
    #[serde(rename = "type")]
    pub type_: EventType,
    pub start: NaiveDate,
    #[serde(default)]
    pub target: Target,
    #[serde(default)]
    pub params: Params,
    pub effects: Vec<Effect>,
    #[serde(default)]
    pub caused_by: Option<String>,
    /// Long text last; ignored by the simulator.
    #[serde(default)]
    pub narrative_cs: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Decoy {
    #[serde(rename = "type")]
    pub type_: DecoyType,
    pub date: NaiveDate,
    #[serde(default)]
    pub target: Target,
    pub size: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Noise {
    #[serde(default = "d_messiness")]
    pub messiness: Messiness,
}

impl Default for Noise {
    fn default() -> Self {
        Self { messiness: d_messiness() }
    }
}

// ---------------------------------------------------------------- the whole spec

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct StorySpec {
    #[serde(default = "d_version")]
    pub version: i64,
    pub meta: Meta,
    pub company: Company,
    pub entities: Entities,
    #[serde(default)]
    pub baseline: Baseline,
    #[serde(default)]
    pub events: Vec<Event>,
    #[serde(default)]
    pub decoys: Vec<Decoy>,
    #[serde(default)]
    pub noise: Noise,
}

/// Why a spec was rejected. `Display` is the text that goes back to the LLM.
#[derive(Debug, thiserror::Error)]
pub enum SpecError {
    #[error("cannot read {0}: {1}")]
    Io(String, std::io::Error),
    #[error("invalid YAML or structure: {0}")]
    Parse(String),
    #[error("{0}")]
    Invalid(String),
}

/// Python `repr()` of a string, as used in the original error messages.
fn py_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::from(quote);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Field-bound checks (pydantic's `Field(ge=..., le=...)`), collecting one message each.
struct Bounds {
    errors: Vec<String>,
}

impl Bounds {
    fn push(&mut self, path: &str, value: f64, range: &str, ok: bool) {
        // NaN fails every comparison, so it is reported like any other out-of-range value.
        if !ok {
            self.errors.push(format!("{path}: {value} is outside {range}"));
        }
    }
    fn ge_le(&mut self, path: &str, v: f64, lo: f64, hi: f64) {
        self.push(path, v, &format!("[{lo}, {hi}]"), v >= lo && v <= hi);
    }
    fn gt_le(&mut self, path: &str, v: f64, lo: f64, hi: f64) {
        self.push(path, v, &format!("({lo}, {hi}]"), v > lo && v <= hi);
    }
    fn ge_lt(&mut self, path: &str, v: f64, lo: f64, hi: f64) {
        self.push(path, v, &format!("[{lo}, {hi})"), v >= lo && v < hi);
    }
    fn gt_lt(&mut self, path: &str, v: f64, lo: f64, hi: f64) {
        self.push(path, v, &format!("({lo}, {hi})"), v > lo && v < hi);
    }
    fn gt(&mut self, path: &str, v: f64, lo: f64) {
        self.push(path, v, &format!("> {lo}"), v > lo);
    }
    fn min_len(&mut self, path: &str, len: usize, min: usize) {
        if len < min {
            self.errors.push(format!("{path}: needs at least {min} item(s), got {len}"));
        }
    }
}

impl StorySpec {
    /// Field bounds, then the cross-field checks. All problems come back as one
    /// `"; "`-joined sentence list, like the Python validator.
    pub fn validate(&self) -> Result<(), SpecError> {
        let mut b = Bounds { errors: vec![] };
        self.check_bounds(&mut b);
        // Python runs the semantic checks only after every field is valid.
        if !b.errors.is_empty() {
            return Err(SpecError::Invalid(b.errors.join("; ")));
        }
        let errors = self.semantic_errors();
        if errors.is_empty() {
            Ok(())
        } else {
            Err(SpecError::Invalid(errors.join("; ")))
        }
    }

    fn check_bounds(&self, b: &mut Bounds) {
        let m = &self.meta;
        b.ge_le("meta.days", m.days as f64, 90.0, 1095.0);

        b.min_len("company.channels", self.company.channels.len(), 1);
        for (i, c) in self.company.channels.iter().enumerate() {
            b.gt_le(&format!("company.channels[{i}].weight"), c.weight, 0.0, 1.0);
        }
        b.min_len("company.cities", self.company.cities.len(), 1);
        for (i, c) in self.company.cities.iter().enumerate() {
            b.gt_le(&format!("company.cities[{i}].weight"), c.weight, 0.0, 1.0);
        }

        let cu = &self.entities.customers;
        b.ge_le("entities.customers.n", cu.n as f64, 500.0, 200_000.0);
        b.ge_le("entities.customers.growth_per_year", cu.growth_per_year, -0.5, 3.0);
        b.min_len("entities.customers.segments", cu.segments.len(), 1);
        for (i, s) in cu.segments.iter().enumerate() {
            let p = format!("entities.customers.segments[{i}]");
            b.gt_le(&format!("{p}.share"), s.share, 0.0, 1.0);
            b.gt_le(&format!("{p}.base_orders_per_month"), s.base_orders_per_month, 0.0, 60.0);
            b.ge_le(&format!("{p}.price_sensitivity"), s.price_sensitivity, 0.0, 3.0);
            b.ge_lt(&format!("{p}.base_churn_per_month"), s.base_churn_per_month, 0.0, 1.0);
        }

        b.min_len("entities.products.categories", self.entities.products.categories.len(), 1);
        for (i, c) in self.entities.products.categories.iter().enumerate() {
            let p = format!("entities.products.categories[{i}]");
            b.ge_le(&format!("{p}.n_skus"), c.n_skus as f64, 1.0, 2000.0);
            b.gt(&format!("{p}.price_min"), c.price_min, 0.0);
            b.gt(&format!("{p}.price_max"), c.price_max, 0.0);
            b.ge_le(&format!("{p}.zipf_s"), c.zipf_s, 0.8, 1.4);
        }

        b.min_len("entities.suppliers", self.entities.suppliers.len(), 1);
        for (i, s) in self.entities.suppliers.iter().enumerate() {
            let p = format!("entities.suppliers[{i}]");
            b.ge_le(&format!("{p}.lead_time_days"), s.lead_time_days as f64, 0.0, 365.0);
            b.ge_le(&format!("{p}.reliability"), s.reliability, 0.0, 1.0);
        }
        b.ge_le(
            "entities.stores.per_city_with_store",
            self.entities.stores.per_city_with_store as f64,
            0.0,
            50.0,
        );
        let e = &self.entities.employees;
        b.ge_le("entities.employees.support_agents", e.support_agents as f64, 0.0, 1000.0);
        b.gt_le("entities.employees.tickets_per_agent_day", e.tickets_per_agent_day, 0.0, 500.0);

        let se = &self.baseline.seasonality;
        if se.weekly.len() != 7 {
            b.errors.push(format!("baseline.seasonality.weekly: needs exactly 7 items, got {}", se.weekly.len()));
        }
        for (i, w) in se.weekly.iter().enumerate() {
            b.ge_le(&format!("baseline.seasonality.weekly[{i}]"), *w, 0.0, 5.0);
        }
        b.ge_le("baseline.payment_failure_rate", self.baseline.payment_failure_rate, 0.0, 0.5);
        b.ge_le("baseline.return_rate", self.baseline.return_rate, 0.0, 0.5);
        b.ge_le("baseline.review_rate", self.baseline.review_rate, 0.0, 1.0);
        b.ge_le("baseline.ticket_rate_per_order", self.baseline.ticket_rate_per_order, 0.0, 1.0);

        for (i, ev) in self.events.iter().enumerate() {
            let p = format!("events[{i}]");
            let pr = &ev.params;
            if let Some(v) = pr.price_change_pct {
                b.ge_le(&format!("{p}.params.price_change_pct"), v, -90.0, 300.0);
            }
            if let Some(v) = pr.lead_time_multiplier {
                b.gt_le(&format!("{p}.params.lead_time_multiplier"), v, 0.0, 20.0);
            }
            if let Some(v) = pr.delivery_delay_days {
                b.ge_le(&format!("{p}.params.delivery_delay_days"), v, 0.0, 60.0);
            }
            if let Some(v) = pr.budget_czk {
                b.push(&format!("{p}.params.budget_czk"), v, ">= 0", v >= 0.0);
            }
            if let Some(v) = pr.churn_pct {
                b.gt_lt(&format!("{p}.params.churn_pct"), v, 0.0, 100.0);
            }
            if let Some(v) = pr.churn_window_days {
                b.ge_le(&format!("{p}.params.churn_window_days"), v as f64, 1.0, 365.0);
            }
            b.min_len(&format!("{p}.effects"), ev.effects.len(), 1);
            for (j, ef) in ev.effects.iter().enumerate() {
                let q = format!("{p}.effects[{j}]");
                b.ge_le(&format!("{q}.size"), ef.size, -1.0, 10.0);
                b.ge_le(&format!("{q}.lag_days"), ef.lag_days as f64, 0.0, 120.0);
                b.ge_le(&format!("{q}.ramp_days"), ef.ramp_days as f64, 0.0, 60.0);
                if let Some(v) = ef.duration_days {
                    b.ge_le(&format!("{q}.duration_days"), v as f64, 0.0, 1095.0);
                }
                if let Some(v) = ef.decay_halflife_days {
                    b.ge_le(&format!("{q}.decay_halflife_days"), v as f64, 1.0, 365.0);
                }
            }
        }
        for (i, d) in self.decoys.iter().enumerate() {
            b.ge_le(&format!("decoys[{i}].size"), d.size, -1.0, 10.0);
        }
    }

    /// Checks that field bounds cannot express. Plain sentences, same order as Python.
    fn semantic_errors(&self) -> Vec<String> {
        let mut errors: Vec<String> = Vec::new();
        let (start, end) = (self.meta.start, self.meta.end());

        let shares: f64 = self.entities.customers.segments.iter().map(|s| s.share).sum();
        if (shares - 1.0).abs() > 0.01 {
            errors.push(format!("segment shares sum to {shares:.3}, must be 1 (±0.01)"));
        }
        let city_w: f64 = self.company.cities.iter().map(|c| c.weight).sum();
        if (city_w - 1.0).abs() > 0.01 {
            errors.push(format!("city weights sum to {city_w:.3}, must be 1 (±0.01)"));
        }
        let distinct: HashSet<Channel> = self.company.channels.iter().map(|c| c.channel).collect();
        if distinct.len() != self.company.channels.len() {
            errors.push("a channel is listed twice".to_string());
        }
        let has_store = self.company.cities.iter().any(|c| c.has_store);
        if distinct.contains(&Channel::Store) && !has_store {
            errors.push("channel 'store' is used but no city has_store".to_string());
        }

        let segment_ids: HashSet<&str> =
            self.entities.customers.segments.iter().map(|s| s.id.as_str()).collect();
        let city_names: HashSet<&str> = self.company.cities.iter().map(|c| c.name.as_str()).collect();
        let category_ids: HashSet<&str> =
            self.entities.products.categories.iter().map(|c| c.id.as_str()).collect();
        let supplier_ids: HashSet<&str> =
            self.entities.suppliers.iter().map(|s| s.id.as_str()).collect();

        for cat in &self.entities.products.categories {
            if cat.price_min > cat.price_max {
                errors.push(format!("category {}: price_min > price_max", cat.id));
            }
            if !supplier_ids.contains(cat.supplier.as_str()) {
                errors.push(format!("category {}: unknown supplier {}", cat.id, py_repr(&cat.supplier)));
            }
        }

        let check_target = |errors: &mut Vec<String>, where_: &str, t: &Target| {
            let strings: [(&str, &Option<Vec<String>>, &HashSet<&str>); 4] = [
                ("city", &t.city, &city_names),
                ("segment", &t.segment, &segment_ids),
                ("category", &t.category, &category_ids),
                ("supplier", &t.supplier, &supplier_ids),
            ];
            for (key, values, known) in strings {
                for value in values.iter().flatten() {
                    if !known.contains(value.as_str()) {
                        errors.push(format!("{where_}: unknown {key} {}", py_repr(value)));
                    }
                }
            }
            for value in t.channel.iter().flatten() {
                if !distinct.contains(value) {
                    errors.push(format!("{where_}: unknown channel {}", py_repr(value.value())));
                }
            }
        };

        let mut seen: Vec<&str> = Vec::new();
        for ev in &self.events {
            let where_ = format!("event {}", ev.id);
            if seen.contains(&ev.id.as_str()) {
                errors.push(format!("{where_}: duplicate id"));
            }
            if !(start <= ev.start && ev.start <= end) {
                errors.push(format!("{where_}: start {} is outside {start}..{end}", ev.start));
            }
            if let Some(cause) = &ev.caused_by {
                if !seen.contains(&cause.as_str()) {
                    errors.push(format!("{where_}: caused_by {} is not an earlier event", py_repr(cause)));
                }
            }
            check_target(&mut errors, &where_, &ev.target);
            if ev.type_ == EventType::SupplierDelay
                && ev.params.lead_time_multiplier.map_or(true, |v| v == 0.0)
            {
                errors.push(format!(
                    "{where_}: supplier_delay needs params.lead_time_multiplier \
                     (how many times longer the supplier's lead time gets, e.g. 3)"
                ));
            }
            if matches!(ev.type_, EventType::SupplierDelay | EventType::Stockout)
                && !(non_empty(&ev.target.supplier) || non_empty(&ev.target.category))
            {
                errors.push(format!(
                    "{where_}: {} needs a target supplier or category",
                    ev.type_.value()
                ));
            }
            if ev.type_ == EventType::ChurnShock {
                if ev.params.churn_pct.is_none() || ev.params.churn_window_days.is_none() {
                    errors.push(format!("{where_}: churn_shock needs params.churn_pct and churn_window_days"));
                }
                if ev.effects.iter().any(|e| e.metric != Metric::ChurnHazard) {
                    errors.push(format!("{where_}: churn_shock effects must use metric churn_hazard"));
                }
            }
            seen.push(&ev.id);
        }

        for (i, d) in self.decoys.iter().enumerate() {
            if !(start <= d.date && d.date <= end) {
                errors.push(format!("decoy {i}: date {} is outside {start}..{end}", d.date));
            }
            check_target(&mut errors, &format!("decoy {i}"), &d.target);
        }
        errors
    }

    /// Parse and validate YAML (JSON is valid YAML, so it works for both).
    pub fn from_yaml(text: &str) -> Result<Self, SpecError> {
        let spec: StorySpec =
            serde_yaml::from_str(text).map_err(|e| SpecError::Parse(e.to_string()))?;
        spec.validate()?;
        Ok(spec)
    }

    /// Parse and validate an already decoded JSON value.
    pub fn from_value(value: serde_json::Value) -> Result<Self, SpecError> {
        let spec: StorySpec =
            serde_json::from_value(value).map_err(|e| SpecError::Parse(e.to_string()))?;
        spec.validate()?;
        Ok(spec)
    }
}

/// Load and validate a spec file.
pub fn load_spec(path: impl AsRef<Path>) -> Result<StorySpec, SpecError> {
    let path = path.as_ref();
    let text = std::fs::read_to_string(path)
        .map_err(|e| SpecError::Io(path.display().to_string(), e))?;
    StorySpec::from_yaml(&text)
}
