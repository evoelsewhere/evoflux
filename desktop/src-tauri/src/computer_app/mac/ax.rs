//! The Accessibility API: its C functions, and [`Ax`], the element wrapper
//! every other module reads and operates apps through.

use super::*;

/// How long one accessibility call may wait for the app. A hung app must not
/// hang the worker (and every action queued behind it).
pub(super) const AX_TIMEOUT_SECONDS: f32 = 2.0;

// ── Accessibility and system FFI ────────────────────────────────────────

pub(super) type AXUIElementRef = CFTypeRef;
pub(super) type AXError = i32;
pub(super) const AX_SUCCESS: AXError = 0;
const AX_VALUE_CGPOINT: u32 = 1;
const AX_VALUE_CGSIZE: u32 = 2;
pub(super) const AX_VALUE_CFRANGE: u32 = 4;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    pub(super) static kAXTrustedCheckOptionPrompt: CFStringRef;
    pub(super) fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> u8;
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCreateSystemWide() -> AXUIElementRef;
    fn AXUIElementGetTypeID() -> CFTypeID;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> AXError;
    fn AXUIElementCopyParameterizedAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        parameter: CFTypeRef,
        value: *mut CFTypeRef,
    ) -> AXError;
    fn AXUIElementCopyMultipleAttributeValues(
        element: AXUIElementRef,
        attributes: CFArrayRef,
        options: u32,
        values: *mut CFArrayRef,
    ) -> AXError;
    fn AXUIElementSetAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: CFTypeRef,
    ) -> AXError;
    fn AXUIElementIsAttributeSettable(
        element: AXUIElementRef,
        attribute: CFStringRef,
        settable: *mut u8,
    ) -> AXError;
    fn AXUIElementCopyActionNames(element: AXUIElementRef, names: *mut CFArrayRef) -> AXError;
    fn AXUIElementPerformAction(element: AXUIElementRef, action: CFStringRef) -> AXError;
    fn AXUIElementGetPid(element: AXUIElementRef, pid: *mut i32) -> AXError;
    fn AXUIElementSetMessagingTimeout(element: AXUIElementRef, seconds: f32) -> AXError;
    fn AXValueCreate(kind: u32, value: *const c_void) -> CFTypeRef;
    fn AXValueGetTypeID() -> CFTypeID;
    fn AXValueGetValue(value: CFTypeRef, kind: u32, out: *mut c_void) -> u8;
    /// Private but long-stable (window managers such as yabai and Rectangle
    /// rely on it): the window server id of an accessibility window, which
    /// is how an `AXUIElement` window is matched to a captured window.
    fn _AXUIElementGetWindow(element: AXUIElementRef, window: *mut u32) -> AXError;
}

/// An accessibility element: an app, a window or a control in one.
#[derive(Clone)]
pub(super) struct Ax(CFType);

pub(super) fn cf_string(text: &str) -> CFString {
    CFString::new(text)
}

impl Ax {
    fn wrap(raw: AXUIElementRef) -> Option<Self> {
        (!raw.is_null()).then(|| Self(unsafe { CFType::wrap_under_create_rule(raw) }))
    }

    pub(super) fn application(pid: i32) -> Option<Self> {
        static GLOBAL_TIMEOUT: std::sync::Once = std::sync::Once::new();
        GLOBAL_TIMEOUT.call_once(|| {
            // Set on the system-wide element, the timeout covers every
            // element this process asks about, not just the app itself.
            if let Some(system) = Self::system_wide() {
                unsafe { AXUIElementSetMessagingTimeout(system.raw(), AX_TIMEOUT_SECONDS) };
            }
        });
        Self::wrap(unsafe { AXUIElementCreateApplication(pid) })
    }

    pub(super) fn system_wide() -> Option<Self> {
        Self::wrap(unsafe { AXUIElementCreateSystemWide() })
    }

    pub(super) fn from_value(value: &CFType) -> Option<Self> {
        (value.type_of() == unsafe { AXUIElementGetTypeID() }).then(|| Self(value.clone()))
    }

    pub(super) fn raw(&self) -> AXUIElementRef {
        self.0.as_CFTypeRef()
    }

    pub(super) fn same(&self, other: &Ax) -> bool {
        self.0 == other.0
    }

    pub(super) fn attribute(&self, name: &str) -> Option<CFType> {
        let key = cf_string(name);
        let mut value: CFTypeRef = std::ptr::null();
        let error =
            unsafe { AXUIElementCopyAttributeValue(self.raw(), key.as_concrete_TypeRef(), &mut value) };
        (error == AX_SUCCESS && !value.is_null()).then(|| unsafe { CFType::wrap_under_create_rule(value) })
    }

    /// A parameterized attribute, such as `AXStringForRange`.
    pub(super) fn parameterized(&self, name: &str, parameter: &CFType) -> Option<CFType> {
        let key = cf_string(name);
        let mut value: CFTypeRef = std::ptr::null();
        let error = unsafe {
            AXUIElementCopyParameterizedAttributeValue(
                self.raw(),
                key.as_concrete_TypeRef(),
                parameter.as_CFTypeRef(),
                &mut value,
            )
        };
        (error == AX_SUCCESS && !value.is_null()).then(|| unsafe { CFType::wrap_under_create_rule(value) })
    }

    /// Several attributes in one round trip to the app. A missing attribute
    /// comes back as an AXValue holding the error, which none of the
    /// `cf_*` conversions accept.
    pub(super) fn attributes<const N: usize>(&self, names: &CFArray<CFString>) -> [Option<CFType>; N] {
        let mut out: CFArrayRef = std::ptr::null();
        let error = unsafe {
            AXUIElementCopyMultipleAttributeValues(self.raw(), names.as_concrete_TypeRef(), 0, &mut out)
        };
        if error != AX_SUCCESS || out.is_null() {
            return std::array::from_fn(|_| None);
        }
        let array: CFArray = unsafe { CFArray::wrap_under_create_rule(out) };
        std::array::from_fn(|index| {
            array
                .get(index as CFIndex)
                .map(|value| unsafe { CFType::wrap_under_get_rule(*value as CFTypeRef) })
        })
    }

    pub(super) fn string(&self, name: &str) -> Option<String> {
        self.attribute(name).and_then(|value| cf_text(&value))
    }

    pub(super) fn flag(&self, name: &str) -> Option<bool> {
        self.attribute(name).and_then(|value| cf_bool(&value))
    }

    pub(super) fn element(&self, name: &str) -> Option<Ax> {
        self.attribute(name).and_then(|value| Ax::from_value(&value))
    }

    pub(super) fn elements(&self, name: &str) -> Vec<Ax> {
        self.attribute(name)
            .map(|value| cf_elements(&value))
            .unwrap_or_default()
    }

    pub(super) fn position(&self) -> Option<CGPoint> {
        self.attribute("AXPosition").and_then(|value| ax_point(&value))
    }

    pub(super) fn frame(&self) -> Option<Rect> {
        let origin = self.position()?;
        let size = self.attribute("AXSize").and_then(|value| ax_size(&value))?;
        Some(Rect { x: origin.x, y: origin.y, w: size.width, h: size.height })
    }

    pub(super) fn set(&self, name: &str, value: &CFType) -> Result<(), AXError> {
        let key = cf_string(name);
        let error = unsafe {
            AXUIElementSetAttributeValue(self.raw(), key.as_concrete_TypeRef(), value.as_CFTypeRef())
        };
        if error == AX_SUCCESS {
            Ok(())
        } else {
            Err(error)
        }
    }

    pub(super) fn set_flag(&self, name: &str, on: bool) -> Result<(), AXError> {
        let value = if on { CFBoolean::true_value() } else { CFBoolean::false_value() };
        self.set(name, &value.as_CFType())
    }

    pub(super) fn settable(&self, name: &str) -> bool {
        let key = cf_string(name);
        let mut settable = 0u8;
        let error = unsafe {
            AXUIElementIsAttributeSettable(self.raw(), key.as_concrete_TypeRef(), &mut settable)
        };
        error == AX_SUCCESS && settable != 0
    }

    pub(super) fn actions(&self) -> Vec<String> {
        let mut names: CFArrayRef = std::ptr::null();
        let error = unsafe { AXUIElementCopyActionNames(self.raw(), &mut names) };
        if error != AX_SUCCESS || names.is_null() {
            return Vec::new();
        }
        let names: CFArray<CFType> = unsafe { CFArray::wrap_under_create_rule(names) };
        names.iter().filter_map(|name| cf_text(&name)).collect()
    }

    /// How long calls through this element wait for the app.
    pub(super) fn set_timeout(&self, seconds: f32) {
        unsafe { AXUIElementSetMessagingTimeout(self.raw(), seconds) };
    }

    pub(super) fn perform(&self, action: &str) -> Result<(), AXError> {
        let name = cf_string(action);
        let error = unsafe { AXUIElementPerformAction(self.raw(), name.as_concrete_TypeRef()) };
        if error == AX_SUCCESS {
            Ok(())
        } else {
            Err(error)
        }
    }

    pub(super) fn pid(&self) -> Option<i32> {
        let mut pid = 0;
        (unsafe { AXUIElementGetPid(self.raw(), &mut pid) } == AX_SUCCESS).then_some(pid)
    }

    pub(super) fn window_id(&self) -> Option<u32> {
        let mut id = 0u32;
        (unsafe { _AXUIElementGetWindow(self.raw(), &mut id) } == AX_SUCCESS && id != 0).then_some(id)
    }

    pub(super) fn role(&self) -> String {
        self.string("AXRole").unwrap_or_default()
    }

    /// What a person would call the element: its title, description, or
    /// (for static text) the text itself.
    pub(super) fn label(&self) -> String {
        for attribute in ["AXTitle", "AXDescription"] {
            if let Some(text) = self.string(attribute).filter(|text| !text.trim().is_empty()) {
                return text;
            }
        }
        if self.role() == "AXStaticText" {
            return self.string("AXValue").unwrap_or_default();
        }
        String::new()
    }

    pub(super) fn value_text(&self) -> Option<String> {
        self.attribute("AXValue").and_then(|value| cf_text(&value))
    }
}

pub(super) fn cf_text(value: &CFType) -> Option<String> {
    if let Some(text) = value.downcast::<CFString>() {
        return Some(text.to_string());
    }
    value.downcast::<CFNumber>().and_then(|number| {
        number
            .to_i64()
            .map(|n| n.to_string())
            .or_else(|| number.to_f64().map(|n| n.to_string()))
    })
}

pub(super) fn cf_bool(value: &CFType) -> Option<bool> {
    if let Some(flag) = value.downcast::<CFBoolean>() {
        return Some(flag.into());
    }
    value.downcast::<CFNumber>().and_then(|number| number.to_i64()).map(|n| n != 0)
}

pub(super) fn cf_number(value: &CFType) -> Option<f64> {
    value.downcast::<CFNumber>().and_then(|number| number.to_f64())
}

pub(super) fn cf_elements(value: &CFType) -> Vec<Ax> {
    let Some(array) = value.downcast::<CFArray>() else {
        return Vec::new();
    };
    array
        .iter()
        .filter_map(|item| Ax::from_value(&unsafe { CFType::wrap_under_get_rule(*item as CFTypeRef) }))
        .collect()
}

pub(super) fn ax_value<T: Default>(value: &CFType, kind: u32) -> Option<T> {
    if value.type_of() != unsafe { AXValueGetTypeID() } {
        return None;
    }
    let mut out = T::default();
    let ok = unsafe { AXValueGetValue(value.as_CFTypeRef(), kind, &mut out as *mut T as *mut c_void) };
    (ok != 0).then_some(out)
}

#[derive(Default, Clone, Copy)]
#[repr(C)]
struct PointValue {
    x: f64,
    y: f64,
}

#[derive(Default, Clone, Copy)]
#[repr(C)]
struct SizeValue {
    width: f64,
    height: f64,
}

/// `CFRange`'s layout.
#[derive(Default, Clone, Copy)]
#[repr(C)]
pub(super) struct RangeValue {
    pub(super) location: CFIndex,
    pub(super) length: CFIndex,
}

pub(super) fn ax_point(value: &CFType) -> Option<CGPoint> {
    ax_value::<PointValue>(value, AX_VALUE_CGPOINT).map(|p| CGPoint::new(p.x, p.y))
}

pub(super) fn ax_size(value: &CFType) -> Option<CGSize> {
    ax_value::<SizeValue>(value, AX_VALUE_CGSIZE).map(|s| CGSize::new(s.width, s.height))
}

fn make_ax_value<T>(kind: u32, value: &T) -> Option<CFType> {
    let raw = unsafe { AXValueCreate(kind, value as *const T as *const c_void) };
    (!raw.is_null()).then(|| unsafe { CFType::wrap_under_create_rule(raw) })
}

pub(super) fn ax_point_value(x: f64, y: f64) -> Option<CFType> {
    make_ax_value(AX_VALUE_CGPOINT, &PointValue { x, y })
}

pub(super) fn ax_range_value(location: usize, length: usize) -> Option<CFType> {
    let range = CFRange { location: location as CFIndex, length: length as CFIndex };
    make_ax_value(AX_VALUE_CFRANGE, &range)
}
