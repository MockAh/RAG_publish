"""Persistencia de síntesis (C3) y del mapa (C4) en JSON (X5).

- `data/synthesis/{expert_id}.json`: una `Synthesis` por Experto.
- `data/synthesis_map.json`: el `SynthesisMap`.

Las rutas llegan como argumento (`Settings.synthesis_dir`, `Settings.synthesis_map_path`
las resuelve la CLI). Toda escritura es atómica —temporal en el mismo directorio,
`fsync` y `os.replace`—, así que una corrida de N9 interrumpida deja el archivo anterior
íntegro o el nuevo completo, nunca un JSON a medias.
"""

import os
import tempfile
from pathlib import Path

from expertos.models import Synthesis, SynthesisMap


def _atomic_write_text(path: Path, text: str) -> None:
    """Escribe `text` en `path` sin pasar nunca por un estado parcial visible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        with tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp.name, path)
    except BaseException:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _synthesis_path(synthesis_dir: Path, expert_id: str) -> Path:
    """`{synthesis_dir}/{expert_id}.json`; rechaza un `expert_id` que no sea un nombre de archivo plano."""
    if not expert_id or expert_id.startswith(".") or Path(expert_id).name != expert_id:
        raise ValueError(f"expert_id no válido como nombre de archivo: {expert_id!r}")
    return Path(synthesis_dir) / f"{expert_id}.json"


def save_synthesis(s: Synthesis, *, synthesis_dir: Path) -> Path:
    """Guarda `s` en `{synthesis_dir}/{s.expert_id}.json` (reemplaza la anterior) y devuelve la ruta."""
    path = _synthesis_path(synthesis_dir, s.expert_id)
    _atomic_write_text(path, s.model_dump_json(indent=2) + "\n")
    return path


def load_synthesis(expert_id: str, *, synthesis_dir: Path) -> Synthesis | None:
    """La síntesis de `expert_id`, o `None` si no se ha generado aún."""
    path = _synthesis_path(synthesis_dir, expert_id)
    if not path.exists():
        return None
    return Synthesis.model_validate_json(path.read_text(encoding="utf-8"))


def load_all_syntheses(*, synthesis_dir: Path) -> dict[str, Synthesis]:
    """Todas las síntesis de `synthesis_dir`, por `expert_id` (vacío si el directorio no existe).

    Un archivo cuyo nombre no coincide con su `expert_id` es un error: lo habría
    escrito alguien que no es `save_synthesis`.
    """
    synthesis_dir = Path(synthesis_dir)
    if not synthesis_dir.is_dir():
        return {}
    syntheses: dict[str, Synthesis] = {}
    for path in sorted(synthesis_dir.glob("*.json")):
        s = Synthesis.model_validate_json(path.read_text(encoding="utf-8"))
        if s.expert_id != path.stem:
            raise ValueError(f"{path} contiene la síntesis de {s.expert_id!r}, no de {path.stem!r}")
        syntheses[s.expert_id] = s
    return syntheses


def save_synthesis_map(m: SynthesisMap, *, path: Path) -> Path:
    """Guarda el mapa en `path` (reemplaza el anterior) y devuelve la ruta."""
    path = Path(path)
    _atomic_write_text(path, m.model_dump_json(indent=2) + "\n")
    return path


def load_synthesis_map(*, path: Path) -> SynthesisMap | None:
    """El mapa guardado en `path`, o `None` si no existe aún."""
    path = Path(path)
    if not path.exists():
        return None
    return SynthesisMap.model_validate_json(path.read_text(encoding="utf-8"))
