//! Coordinate helpers shared by the backends.

/// Longest edge of the screenshot handed to the agent, in pixels. Larger
/// windows are scaled down and coordinates are mapped back, so the agent only
/// ever sees one coordinate system: the screenshot's.
pub(crate) const SCREENSHOT_MAX_EDGE: u32 = 1568;

/// Screenshot pixels per window pixel for a window of this size.
pub(crate) fn screenshot_scale(width: u32, height: u32) -> f64 {
    let edge = width.max(height);
    if edge <= SCREENSHOT_MAX_EDGE || edge == 0 {
        1.0
    } else {
        f64::from(SCREENSHOT_MAX_EDGE) / f64::from(edge)
    }
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
    fn packs_negative_points_as_signed_words() {
        assert_eq!(pack_point(10, 20), (20 << 16) | 10);
        let packed = pack_point(-5, 7) as u32;
        assert_eq!((packed & 0xffff) as u16 as i16, -5);
        assert_eq!((packed >> 16) as u16 as i16, 7);
    }
}
