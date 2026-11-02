//! Tagged-JSON values written by `fixtures/gen_fixtures.py`.

use evoflux_shared_yaml::{python_float_repr, Mapping, Time, Timestamp, Value};
use serde_json::Value as J;

pub fn decode(json: &J) -> Value {
    let tag = json["t"].as_str().unwrap();
    let v = &json["v"];
    match tag {
        "null" => Value::Null,
        "bool" => Value::Bool(v.as_bool().unwrap()),
        "int" => Value::Int(v.as_str().unwrap().parse().unwrap()),
        "float" => Value::Float(match v.as_str().unwrap() {
            "nan" => f64::NAN,
            "inf" => f64::INFINITY,
            "-inf" => f64::NEG_INFINITY,
            other => other.parse().unwrap(),
        }),
        "str" => Value::Str(v.as_str().unwrap().to_owned()),
        "timestamp" => Value::Timestamp(parse_timestamp(v.as_str().unwrap())),
        "seq" => Value::Seq(v.as_array().unwrap().iter().map(decode).collect()),
        "map" => {
            let mut map = Mapping::new();
            for pair in v.as_array().unwrap() {
                map.insert(decode(&pair[0]), decode(&pair[1]));
            }
            Value::Map(map)
        }
        other => panic!("unknown tag {other}"),
    }
}

/// `date.isoformat()` or `datetime.isoformat(' ')`.
fn parse_timestamp(text: &str) -> Timestamp {
    let num = |s: &str| s.parse::<u32>().unwrap();
    let (date, time) = match text.split_once(' ') {
        Some((d, t)) => (d, Some(t)),
        None => (text, None),
    };
    let parts: Vec<_> = date.split('-').collect();
    let time = time.map(|t| {
        let (clock, offset) = match t.find(['+', '-']) {
            Some(at) => (&t[..at], Some(&t[at..])),
            None => (t, None),
        };
        let (hms, micro) = clock.split_once('.').unwrap_or((clock, "0"));
        let hms: Vec<_> = hms.split(':').collect();
        Time {
            hour: num(hms[0]) as u8,
            minute: num(hms[1]) as u8,
            second: num(hms[2]) as u8,
            microsecond: num(micro),
            offset_minutes: offset.map(|o| {
                let sign = if o.starts_with('-') { -1 } else { 1 };
                let (h, m) = o[1..].split_once(':').unwrap();
                sign * (num(h) * 60 + num(m)) as i16
            }),
        }
    });
    Timestamp {
        year: num(parts[0]) as u16,
        month: num(parts[1]) as u8,
        day: num(parts[2]) as u8,
        time,
    }
}

/// Structural equality where floats compare by Python repr (so NaN equals NaN
/// and -0.0 differs from 0.0) and mapping order matters.
pub fn same(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Float(x), Value::Float(y)) => python_float_repr(*x) == python_float_repr(*y),
        (Value::Seq(x), Value::Seq(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| same(p, q))
        }
        (Value::Map(x), Value::Map(y)) => {
            x.len() == y.len()
                && x.iter()
                    .zip(y.iter())
                    .all(|((k1, v1), (k2, v2))| same(k1, k2) && same(v1, v2))
        }
        _ => a == b,
    }
}
