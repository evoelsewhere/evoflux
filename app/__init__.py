import sys

# uuid.uuid7() lands in the stdlib only in Python 3.14. Backport it onto the
# `uuid` module on older interpreters so `from uuid import uuid7` works
# everywhere else in the codebase unchanged.
if sys.version_info < (3, 14):
    import uuid

    if not hasattr(uuid, "uuid7"):
        from uuid_extensions import uuid7 as _uuid7_backport

        uuid.uuid7 = _uuid7_backport
