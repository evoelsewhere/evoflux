//! Points, rectangles and the displays they fall on, in points with a
//! top-left origin.

use super::*;

// ── Geometry ────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(super) struct Rect {
    pub(super) x: f64,
    pub(super) y: f64,
    pub(super) w: f64,
    pub(super) h: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct Point {
    pub(super) x: f64,
    pub(super) y: f64,
}

impl Rect {
    pub(super) fn from_cg(rect: &CGRect) -> Self {
        Self { x: rect.origin.x, y: rect.origin.y, w: rect.size.width, h: rect.size.height }
    }

    pub(super) fn to_cg(self) -> CGRect {
        CGRect::new(&CGPoint::new(self.x, self.y), &CGSize::new(self.w, self.h))
    }

    pub(super) fn right(&self) -> f64 {
        self.x + self.w
    }

    pub(super) fn bottom(&self) -> f64 {
        self.y + self.h
    }

    pub(super) fn is_empty(&self) -> bool {
        self.w <= 0.0 || self.h <= 0.0
    }

    pub(super) fn contains(&self, point: Point) -> bool {
        !self.is_empty()
            && point.x >= self.x
            && point.x < self.right()
            && point.y >= self.y
            && point.y < self.bottom()
    }

    pub(super) fn intersects(&self, other: &Rect) -> bool {
        self.x < other.right() && other.x < self.right() && self.y < other.bottom() && other.y < self.bottom()
    }

    pub(super) fn overlap_area(&self, other: &Rect) -> f64 {
        let w = self.right().min(other.right()) - self.x.max(other.x);
        let h = self.bottom().min(other.bottom()) - self.y.max(other.y);
        if w > 0.0 && h > 0.0 {
            w * h
        } else {
            0.0
        }
    }

    pub(super) fn center(&self) -> Point {
        Point { x: self.x + self.w / 2.0, y: self.y + self.h / 2.0 }
    }
}

pub(super) fn displays() -> Vec<Rect> {
    CGDisplay::active_displays()
        .unwrap_or_default()
        .into_iter()
        .map(|id| Rect::from_cg(&CGDisplay::new(id).bounds()))
        .collect()
}

/// Whether next to nothing of `frame` shows on any display.
pub(super) fn mostly_off_screen(frame: &Rect) -> bool {
    let area = frame.w * frame.h;
    if area <= 0.0 {
        return true;
    }
    let visible: f64 = displays().iter().map(|display| display.overlap_area(frame)).sum();
    visible / area < 0.02
}
