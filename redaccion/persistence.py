"""Persistencia de la auditoría de Redacción en JSON, con escritura atómica.

Cada consulta tiene su subdirectorio `{audit_dir}/{consultation_id}/`; qué archivos lleva lo
fija R10. Aquí solo hay piezas genéricas: guardar y leer cualquier modelo pydantic sin pasar
nunca por un JSON a medias (temporal + `fsync` + `os.replace`, mismo código que fase 04).

`model_dump_json` convierte todo a tipos nativos de JSON (regla 5): nada de numpy ni
`SecretStr` llega crudo al disco.
"""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from expertos.persistence import _atomic_write_text

M = TypeVar("M", bound=BaseModel)


def consultation_dir(audit_dir: Path, consultation_id: str) -> Path:
    """`{audit_dir}/{consultation_id}`; rechaza un id que no sea un nombre de directorio plano."""
    if not consultation_id or consultation_id.startswith(".") or Path(consultation_id).name != consultation_id:
        raise ValueError(f"consultation_id no válido como nombre de directorio: {consultation_id!r}")
    return Path(audit_dir) / consultation_id


def save_record(model: BaseModel, path: Path, *, overwrite: bool = False) -> Path:
    """Guarda `model` en `path` de forma atómica y devuelve la ruta.

    Por defecto no pisa un archivo existente: la auditoría es de solo añadir (patrón de
    `save_consult`). `overwrite=True` es para archivos que se reescriben a propósito.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    _atomic_write_text(path, model.model_dump_json(indent=2) + "\n")
    return path


def load_record(model_cls: type[M], path: Path) -> M:
    """Lee y valida `path` como `model_cls`."""
    return model_cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
