from app.remote.severity import derive_severity


def test_destructive_command_is_high_severity():
    assert derive_severity(tool="shell", command="rm -rf build/") == "high"


def test_force_push_is_high_severity():
    assert (
        derive_severity(tool="shell", command="git push --force origin main")
        == "high"
    )


def test_shell_tool_without_destructive_pattern_is_elevated():
    assert derive_severity(tool="shell", command="pytest -q") == "elevated"


def test_python_tool_is_elevated():
    assert derive_severity(tool="python", command="print(1)") == "elevated"


def test_read_only_tool_is_normal():
    assert derive_severity(tool="read", command="tests/test_auth.py") == "normal"


def test_detection_is_case_insensitive():
    assert derive_severity(tool="shell", command="RM -RF /tmp/x") == "high"
