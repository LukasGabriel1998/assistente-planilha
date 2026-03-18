from __future__ import annotations

import builtins
import os
from pathlib import Path
import sys
from types import ModuleType


_RUNTIME_CACHE_KEY = "_ASSISTENTE_WHISPER_RUNTIME_CACHE"
_RUNTIME_MODULE_PREFIXES = (
    "faster_whisper",
    "ctranslate2",
    "av",
    "numpy",
    "onnxruntime",
    "tokenizers",
)


class TranscriptionError(RuntimeError):
    pass


def _is_runtime_module(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in _RUNTIME_MODULE_PREFIXES
    )


def _capture_runtime_modules() -> dict[str, ModuleType]:
    captured: dict[str, ModuleType] = {}
    for name, module in sys.modules.items():
        if module is None or not _is_runtime_module(name):
            continue
        captured[name] = module
    return captured


def _restore_runtime_modules(cached_modules: dict[str, ModuleType]) -> None:
    for name, module in cached_modules.items():
        if name not in sys.modules and module is not None:
            sys.modules[name] = module


def _merge_runtime_cache() -> dict[str, ModuleType]:
    cache = getattr(builtins, _RUNTIME_CACHE_KEY, None)
    cached_modules = cache if isinstance(cache, dict) else {}
    live_modules = _capture_runtime_modules()
    if live_modules:
        merged = dict(cached_modules)
        merged.update(live_modules)
        setattr(builtins, _RUNTIME_CACHE_KEY, merged)
        return merged
    return cached_modules


def _bootstrap_whisper_runtime() -> None:
    """Ajusta caminhos de import/DLL para execucao empacotada (PyInstaller)."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass))

    here = Path(__file__).resolve()
    candidates.extend([Path.cwd(), here.parent, here.parent.parent, here.parent.parent.parent])

    seen: set[str] = set()
    for base in candidates:
        key = str(base)
        if key in seen or not base.exists():
            continue
        seen.add(key)

        if (base / "faster_whisper").exists() and key not in sys.path:
            sys.path.insert(0, key)

        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            for dll_dir in [
                base,
                base / "ctranslate2",
                base / "av.libs",
                base / "numpy.libs",
                base / "onnxruntime" / "capi",
            ]:
                if dll_dir.exists():
                    try:
                        os.add_dll_directory(str(dll_dir))
                    except Exception:
                        pass


def _import_whisper_model() -> type:
    cached_modules = _merge_runtime_cache()
    if cached_modules:
        _restore_runtime_modules(cached_modules)

    try:
        from faster_whisper import WhisperModel
    except Exception:
        _bootstrap_whisper_runtime()
        cached_modules = _merge_runtime_cache()
        if cached_modules:
            _restore_runtime_modules(cached_modules)
        from faster_whisper import WhisperModel

    latest_snapshot = _merge_runtime_cache()
    if latest_snapshot:
        _restore_runtime_modules(latest_snapshot)
    return WhisperModel


def _resolve_model_source(model_size: str) -> str:
    explicit = os.getenv("WHISPER_LOCAL_MODEL_DIR", "").strip()
    if explicit:
        path = Path(explicit)
        if path.exists():
            return str(path)

    local_models_root = Path.cwd() / "models"
    named_candidates = [
        local_models_root / f"faster-whisper-{model_size}",
        local_models_root / model_size,
    ]
    for candidate in named_candidates:
        if (candidate / "model.bin").exists():
            return str(candidate)

    # Fallback for Hugging Face snapshot layout under models/
    if local_models_root.exists():
        for model_file in local_models_root.rglob("model.bin"):
            parent = model_file.parent
            if model_size in str(parent).lower():
                return str(parent)

    return model_size


def transcribe_audio(audio_path: str | Path, model_size: str = "small") -> str:
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise TranscriptionError(f"Arquivo de audio nao encontrado: {audio_path}")

    _bootstrap_whisper_runtime()

    try:
        WhisperModel = _import_whisper_model()
    except Exception as exc:  # pragma: no cover - dependency/runtime in client environment
        raise TranscriptionError(
            "Nao foi possivel carregar o motor de audio (faster-whisper). "
            f"Detalhe: {type(exc).__name__}: {exc}"
        ) from exc

    model_source = _resolve_model_source(model_size)
    cache_root = Path.cwd() / "models_cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    try:
        model = WhisperModel(
            model_source,
            device="cpu",
            compute_type="int8",
            download_root=str(cache_root),
        )
        transcribe_kwargs = {
            "language": "pt",
            "task": "transcribe",
            "beam_size": 5,
            "best_of": 5,
            "temperature": 0.0,
            "vad_filter": True,
            "condition_on_previous_text": False,
            "initial_prompt": (
                "Transcricao financeira em portugues do Brasil. "
                "Preserve valores monetarios e numeros com o maximo de precisao."
            ),
        }
        try:
            segments, _ = model.transcribe(str(audio_path), **transcribe_kwargs)
        except TypeError:
            # Compatibilidade com versoes antigas de faster-whisper.
            segments, _ = model.transcribe(str(audio_path), language="pt")
        text = " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as exc:  # pragma: no cover - runtime branch
        raise TranscriptionError(f"Erro ao transcrever audio: {exc}") from exc

    if not text:
        raise TranscriptionError("Nao foi possivel reconhecer fala no audio.")
    return text
