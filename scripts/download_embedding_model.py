"""Download the embedding model into models/embedding/ for bundling in the repo."""
import sys
import os

# Must preload onnxruntime FIRST on Windows
if sys.platform == "win32":
    from app._onnx_preload import preload_onnxruntime
    preload_onnxruntime()

# Apply SSL patch for corporate proxies
os.environ.setdefault("SSL_VERIFY", "false")
from app.core.ssl_patch import apply_ssl_patch
apply_ssl_patch()

from fastembed import TextEmbedding

print("Downloading snowflake/snowflake-arctic-embed-s → models/embedding/ ...")
m = TextEmbedding(model_name="snowflake/snowflake-arctic-embed-s", cache_dir="models/embedding")
print("Done! Model cached in models/embedding/")
