import os
import sys
import zipfile
import urllib.request
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_DIR_NAME = "vosk-model-small-ru-0.22"


def ensure_vosk_model(target_base_dir: Path) -> Path:
    """Ensure Vosk Russian model exists locally, download and unpack if needed."""
    target_base_dir = Path(target_base_dir)
    target_base_dir.mkdir(parents=True, exist_ok=True)
    model_path = target_base_dir / MODEL_DIR_NAME

    # Check if directory already has model files
    if model_path.exists() and (model_path / "am").exists() or (model_path / "conf").exists():
        return model_path

    zip_path = target_base_dir / f"{MODEL_DIR_NAME}.zip"

    # Ensure utf-8 friendly console or log
    logger.info("Checking/downloading Vosk Russian model (~45 MB)...")
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print("[SPUTNIK STT] Загрузка русской языковой модели Vosk (~45 МБ)...")
    except Exception:
        print("[SPUTNIK STT] Downloading Vosk Russian model (~45 MB)...")

    def _progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100, int(downloaded * 100 / total_size))
            try:
                print(f"\rЗагрузка модели: {percent}% ({downloaded // (1024*1024)}/{total_size // (1024*1024)} МБ)", end="", flush=True)
            except Exception:
                pass

    try:
        urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path, reporthook=_progress)
        print("\n[SPUTNIK STT] Распаковка модели...")
        target_resolved = target_base_dir.resolve()
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Prevent Zip Slip / Directory Traversal attacks
            for member in zip_ref.infolist():
                member_path = (target_base_dir / member.filename).resolve()
                if not member_path.is_relative_to(target_resolved):
                    raise RuntimeError(f"Попытка выхода за пределы каталога (Zip Slip) в архиве: {member.filename}")
            try:
                zip_ref.extractall(target_base_dir, filter="data")
            except TypeError:
                zip_ref.extractall(target_base_dir)
        logger.info("Vosk model successfully downloaded and unpacked.")
    except Exception as e:
        logger.error(f"Failed to download or unpack Vosk model: {e}", exc_info=True)
        raise RuntimeError(f"Не удалось загрузить модель Vosk: {e}")
    finally:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass

    return model_path
