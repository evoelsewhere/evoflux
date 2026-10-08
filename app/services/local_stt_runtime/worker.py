"""Persistent, offline faster-whisper worker for the EvoFlux sidecar."""

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
from pathlib import Path
from typing import Any

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_RESULT_BYTES = 1024 * 1024


def _load_model(model_path: Path):
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_path),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        local_files_only=True,
    )


def _write_frame(payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_RESULT_BYTES:
        data = b'{"error":"result_too_large"}'
    sys.stdout.buffer.write(struct.pack(">I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_exactly(count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sys.stdin.buffer.read(count - len(chunks))
        if not chunk:
            raise EOFError
        chunks.extend(chunk)
    return bytes(chunks)


def _transcribe(model: Any, metadata: dict[str, Any], audio: bytes) -> dict[str, Any]:
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        return {"error": "invalid_audio"}
    try:
        from faster_whisper.audio import decode_audio

        decoded = decode_audio(io.BytesIO(audio), sampling_rate=16_000)
        language = metadata.get("language")
        if isinstance(language, str):
            language = language.split("-", 1)[0].lower()
            if language not in {"en", "vi", "ja"}:
                language = None
        segments, _info = model.transcribe(
            decoded,
            language=language,
            task="transcribe",
            beam_size=5,
        )
        text = "".join(segment.text for segment in segments).strip()
        if not text:
            return {"error": "empty_transcript"}
        return {"text": text[:100_000]}
    except Exception:  # noqa: BLE001 - do not disclose native/model/audio diagnostics
        return {"error": "transcription_failed"}


def serve(model_path: Path) -> int:
    model = None
    while True:
        try:
            header_size = struct.unpack(">I", _read_exactly(4))[0]
        except EOFError:
            return 0
        if not 1 <= header_size <= MAX_HEADER_BYTES:
            return 2
        try:
            metadata = json.loads(_read_exactly(header_size))
            if not isinstance(metadata, dict):
                return 2
            audio_size = metadata.get("audio_bytes")
            if not isinstance(audio_size, int) or not 0 < audio_size <= MAX_AUDIO_BYTES:
                _write_frame({"error": "invalid_audio"})
                continue
            audio = _read_exactly(audio_size)
        except (EOFError, ValueError, TypeError):
            return 2
        if model is None:
            try:
                model = _load_model(model_path)
            except Exception:  # noqa: BLE001 - safe error only
                _write_frame({"error": "model_load_failed"})
                return 3
        _write_frame(_transcribe(model, metadata, audio))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("model_path", type=Path)
    args = parser.parse_args()
    if not args.model_path.is_dir():
        return 2
    if args.health:
        try:
            _load_model(args.model_path)
        except Exception:  # noqa: BLE001 - do not reveal local paths or native errors
            return 3
        sys.stdout.write('{"ok":true}\n')
        return 0
    if args.serve:
        return serve(args.model_path)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
