//! Coordinate helpers shared by the backends.

/// Longest edge of the screenshot handed to the agent, in pixels. Larger
/// windows are scaled down and coordinates are mapped back, so the agent only
/// ever sees one coordinate system: the screenshot's.
pub(crate) const SCREENSHOT_MAX_EDGE: u32 = 1568;

/// Most pixels a screenshot may have. The model's API scales a larger image
/// down again before the model sees it — 1568×882, a 16:9 window within the
/// edge limit, is one — and the model then answers in the smaller image's
/// pixels, which were mapped back as if they were this one's: clicks landed
/// short, by more the further right and down they were.
pub(crate) const SCREENSHOT_MAX_PIXELS: u32 = 1_150_000;

/// Screenshot pixels per window pixel for a window of this size.
pub(crate) fn screenshot_scale(width: u32, height: u32) -> f64 {
    let edge = width.max(height);
    let pixels = f64::from(width) * f64::from(height);
    if edge == 0 {
        return 1.0;
    }
    let by_edge = f64::from(SCREENSHOT_MAX_EDGE) / f64::from(edge);
    let by_pixels = (f64::from(SCREENSHOT_MAX_PIXELS) / pixels).sqrt();
    by_edge.min(by_pixels).min(1.0)
}

/// Pack a point into the `LPARAM` layout mouse messages use: x in the low
/// word, y in the high word, each a signed 16-bit value.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub(crate) fn pack_point(x: i32, y: i32) -> isize {
    let low = (x as i16 as u16) as u32;
    let high = (y as i16 as u16) as u32;
    ((high << 16) | low) as i32 as isize
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_only_large_windows() {
        assert_eq!(screenshot_scale(1280, 800), 1.0);
        let scale = screenshot_scale(3136, 1000);
        assert!((scale - 0.5).abs() < 1e-9);
    }

    #[test]
    fn keeps_screenshots_within_the_pixel_budget() {
        for (width, height) in [(1920, 1080), (2560, 1440), (1600, 1600), (1568, 882)] {
            let scale = screenshot_scale(width, height);
            let scaled = (f64::from(width) * scale).round() * (f64::from(height) * scale).round();
            assert!(scaled <= f64::from(SCREENSHOT_MAX_PIXELS) + 2.0 * f64::from(width.max(height)));
            assert!(scale < 1.0, "{width}x{height} was not scaled");
        }
        // Within both limits: left as it is.
        assert_eq!(screenshot_scale(1280, 800), 1.0);
        assert_eq!(screenshot_scale(1024, 1024), 1.0);
    }

    #[test]
    fn packs_negative_points_as_signed_words() {
        assert_eq!(pack_point(10, 20), (20 << 16) | 10);
        let packed = pack_point(-5, 7) as u32;
        assert_eq!((packed & 0xffff) as u16 as i16, -5);
        assert_eq!((packed >> 16) as u16 as i16, 7);
    }
}
