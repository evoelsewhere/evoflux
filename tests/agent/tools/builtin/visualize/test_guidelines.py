"""Tests for visualize guidelines module."""

from app.agent.tools.builtin.visualize.guidelines import (
    AVAILABLE_MODULES,
    CORE_GUIDELINES,
    WIDGET_GALLERY,
    get_guidelines,
)


class TestAvailableModules:
    """Test AVAILABLE_MODULES constant."""

    def test_modules_list(self):
        assert "interactive" in AVAILABLE_MODULES
        assert "chart" in AVAILABLE_MODULES
        assert "mockup" in AVAILABLE_MODULES
        assert "art" in AVAILABLE_MODULES
        assert "diagram" in AVAILABLE_MODULES
        assert "gallery" in AVAILABLE_MODULES

    def test_modules_count(self):
        assert len(AVAILABLE_MODULES) == 6


class TestGetGuidelines:
    """Test get_guidelines function."""

    def test_single_module(self):
        result = get_guidelines(["interactive"])
        assert CORE_GUIDELINES in result
        assert "Interactive Components" in result

    def test_multiple_modules(self):
        result = get_guidelines(["interactive", "chart"])
        assert CORE_GUIDELINES in result
        assert "Interactive Components" in result
        assert "Chart.js Integration" in result

    def test_all_modules(self):
        result = get_guidelines(AVAILABLE_MODULES)
        assert CORE_GUIDELINES in result
        assert "Interactive Components" in result
        assert "Chart.js Integration" in result
        assert "UI Mockup Components" in result
        assert "SVG Illustration Guide" in result
        assert "Diagram Creation Guide" in result
        assert "Widget Gallery" in result

    def test_invalid_module_ignored(self):
        result = get_guidelines(["invalid_module"])
        assert CORE_GUIDELINES in result
        assert "invalid_module" not in result

    def test_empty_modules(self):
        result = get_guidelines([])
        assert CORE_GUIDELINES in result

    def test_deduplication(self):
        # Request same module twice
        result = get_guidelines(["interactive", "interactive"])
        # Should only contain one copy of interactive guidelines
        assert result.count("Interactive Components") == 1


class TestCoreGuidelines:
    """Test CORE_GUIDELINES content."""

    def test_has_streaming_architecture(self):
        assert "Streaming-First Architecture" in CORE_GUIDELINES

    def test_has_critical_rules(self):
        assert "Critical Rules" in CORE_GUIDELINES
        assert "NO gradients" in CORE_GUIDELINES

    def test_has_color_system(self):
        assert "Color System" in CORE_GUIDELINES
        assert "--color-text-primary" in CORE_GUIDELINES

    def test_has_dark_mode(self):
        assert "dark" in CORE_GUIDELINES.lower()

    def test_has_cdn_allowlist(self):
        assert "CDN Allowlist" in CORE_GUIDELINES
        assert "cdnjs.cloudflare.com" in CORE_GUIDELINES
        assert "cdn.jsdelivr.net" in CORE_GUIDELINES


class TestWidgetGallery:
    """Test WIDGET_GALLERY content."""

    def test_has_metric_dashboard(self):
        assert "Metric Dashboard" in WIDGET_GALLERY

    def test_has_interactive_slider(self):
        assert "Interactive Slider" in WIDGET_GALLERY

    def test_has_status_timeline(self):
        assert "Status Timeline" in WIDGET_GALLERY

    def test_has_code_diff_viewer(self):
        assert "Code Diff Viewer" in WIDGET_GALLERY

    def test_has_interactive_form(self):
        assert "Interactive Form" in WIDGET_GALLERY

    def test_has_progress_indicator(self):
        assert "Progress Indicator" in WIDGET_GALLERY

    def test_has_html_examples(self):
        assert "<style>" in WIDGET_GALLERY
        assert "<div" in WIDGET_GALLERY
