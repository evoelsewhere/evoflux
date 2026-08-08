"""Self-contained source and symbolic code-context index.

The package deliberately owns no rows in EvoFlux's application database.
Each repository has an isolated desired-state SQLite target in the regeneratable
EvoFlux cache directory. Cross-repository resolution happens over the authorized
repository set at query time. The runtime is implemented and packaged as the
application's primary code-index service.
"""

from app.services.code_index.models import (
    CodeContextResult,
    GraphOperation,
    RepositoryScope,
)
from app.services.code_index.service import query_code_context

__all__ = [
    "CodeContextResult",
    "GraphOperation",
    "RepositoryScope",
    "query_code_context",
]
