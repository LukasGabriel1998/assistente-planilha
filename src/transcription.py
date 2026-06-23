from __future__ import annotations

import builtins
import os
import re
import sys
import tempfile
import threading
import wave
from pathlib import Path
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


_MODEL_INSTANCE_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()

_FINANCIAL_INITIAL_PROMPT = (
    "Transcricao em portugues do Brasil de comandos financeiros falados no Telegram. "
    "Preserve nomes proprios, valores monetarios, datas, numeros e a palavra chat com precisao. "
    "Exemplos: chat, aproveitando, adiciona mil reais de material para essa venda; "
    "ID venda zero zero dois; acabei de fazer uma venda aqui para o Adriel; "
    "eles compraram uma fachada, pagaram cinco mil e o restante amanha; "
    "vendi um banner para a Maria por dois mil e quinhentos; "
    "fechei um servico para a empresa Joao Joao; entrou metade hoje; "
    "saldo dia trinta; gastei oitocentos de material; orcamento de material."
)

_COMMON_TRANSCRIPTION_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbochat(?:e|ing)?\b", re.I), "chat"),
    (re.compile(r"\bpuxat(?:e|ing)?\b", re.I), "chat"),
    (re.compile(r"\bpoxat(?:e|ing)?\b", re.I), "chat"),
    (re.compile(r"\bte\s+apag(?:a|ar)\b", re.I), "apaga"),
    (re.compile(r"\bpucha\b", re.I), "chat"),
    (re.compile(r"\bxat\b", re.I), "chat"),
    (re.compile(r"\bchate\b", re.I), "chat"),
    (re.compile(r"\bchato\b", re.I), "chat"),
    (re.compile(r"\bchats\b", re.I), "chat"),
    (re.compile(r"\borcamento\b", re.I), "orçamento"),
    (re.compile(r"\bmateria\s+prima\b", re.I), "matéria-prima"),
    (re.compile(r"\bbander\b", re.I), "banner"),
)


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


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _resolve_initial_prompt() -> str:
    custom = os.getenv("WHISPER_INITIAL_PROMPT", "").strip()
    return custom or _FINANCIAL_INITIAL_PROMPT


def _resolve_beam_size() -> int:
    raw = os.getenv("WHISPER_BEAM_SIZE", "7").strip()
    try:
        value = int(raw)
    except ValueError:
        return 7
    return max(1, min(value, 10))


def _normalize_audio_samples(samples):
    import numpy as np

    if samples.size == 0:
        return samples
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-6:
        return samples
    target_peak = 0.92
    return (samples * (target_peak / peak)).astype(np.float32)


def _write_mono_wav(path: Path, samples, sample_rate: int = 16000) -> None:
    import numpy as np

    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def _prepare_audio_for_whisper(audio_path: Path) -> tuple[Path, Path | None]:
    """Converte o audio para mono 16 kHz com volume normalizado (melhor para voz)."""
    if not _env_flag("WHISPER_PREPARE_AUDIO", default=True):
        return audio_path, None

    try:
        import av
        import numpy as np
    except Exception:
        return audio_path, None

    samples_chunks: list = []
    container = None
    try:
        container = av.open(str(audio_path))
        if not container.streams.audio:
            return audio_path, None

        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            resampled = resampler.resample(frame)
            if resampled is None:
                continue
            frames = resampled if isinstance(resampled, list) else [resampled]
            for item in frames:
                arr = item.to_ndarray()
                if arr.ndim > 1:
                    arr = arr.mean(axis=0)
                samples_chunks.append(arr.astype(np.float32) / 32768.0)

        flush = resampler.resample(None)
        if flush is not None:
            frames = flush if isinstance(flush, list) else [flush]
            for item in frames:
                arr = item.to_ndarray()
                if arr.ndim > 1:
                    arr = arr.mean(axis=0)
                samples_chunks.append(arr.astype(np.float32) / 32768.0)
    except Exception:
        return audio_path, None
    finally:
        if container is not None:
            try:
                container.close()
            except Exception:
                pass

    if not samples_chunks:
        return audio_path, None

    samples = _normalize_audio_samples(np.concatenate(samples_chunks))
    if samples.size < 1600:
        return audio_path, None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        _write_mono_wav(tmp_path, samples)
        return tmp_path, tmp_path
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return audio_path, None


def _cleanup_transcription_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    cleaned = re.sub(
        r"\blegendas?\s+pel[ao]\s+comunidade\s+de\s+amara(?:\.org)?\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def _fix_common_transcription_errors(text: str) -> str:
    from src.parser import normalize_spoken_ids_in_text

    fixed = normalize_spoken_ids_in_text(text)
    for pattern, replacement in _COMMON_TRANSCRIPTION_REPLACEMENTS:
        fixed = pattern.sub(replacement, fixed)
    return normalize_spoken_ids_in_text(fixed)


def _get_whisper_model(WhisperModel: type, model_source: str, cache_root: Path):
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_INSTANCE_CACHE.get(model_source)
        if cached is not None:
            return cached

        model = WhisperModel(
            model_source,
            device="cpu",
            compute_type="int8",
            download_root=str(cache_root),
        )
        _MODEL_INSTANCE_CACHE[model_source] = model
        return model


def _build_transcribe_kwargs() -> dict:
    beam_size = _resolve_beam_size()
    kwargs = {
        "language": "pt",
        "task": "transcribe",
        "beam_size": beam_size,
        "best_of": beam_size,
        "temperature": 0.0,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "initial_prompt": _resolve_initial_prompt(),
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -1.0,
        "no_speech_threshold": 0.5,
    }
    if _env_flag("WHISPER_VAD_PARAMETERS", default=True):
        kwargs["vad_parameters"] = {
            "min_silence_duration_ms": 400,
            "speech_pad_ms": 300,
            "threshold": 0.45,
        }
    return kwargs


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

    prepared_path, temp_path = _prepare_audio_for_whisper(audio_path)
    transcribe_path = prepared_path

    try:
        model = _get_whisper_model(WhisperModel, model_source, cache_root)
        transcribe_kwargs = _build_transcribe_kwargs()
        try:
            segments, _ = model.transcribe(str(transcribe_path), **transcribe_kwargs)
        except TypeError:
            # Compatibilidade com versoes antigas de faster-whisper.
            segments, _ = model.transcribe(str(transcribe_path), language="pt")
        text = _fix_common_transcription_errors(
            _cleanup_transcription_text(" ".join(seg.text.strip() for seg in segments))
        )
    except Exception as exc:  # pragma: no cover - runtime branch
        raise TranscriptionError(f"Erro ao transcrever audio: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    if not text:
        raise TranscriptionError("Nao foi possivel reconhecer fala no audio.")
    return text
