"""Persistencia y versionado del modelo causal (RF-32).

Carpeta del modelo (``data/models/<nombre>``):

- ``graph.graphml`` y ``graph.json``: grafo de referencia consolidado (enlaces con retardo y
  justificación);
- ``scm.json``: tipo de modelo, ecuaciones y parámetros identificados;
- ``residual_stats.json``: media y desviación de los residuos a un paso en datos normales;
- ``thresholds.json``: umbrales iniciales de los residuos (la Fase 6 los calibra);
- ``manifest.json``: dataset de origen con sus SHA-256, configuración del ajuste, métricas de
  validación, versiones, commit y el SHA-256 de cada archivo del modelo.

Los números se guardan con la representación exacta de Python, así que un modelo recargado
produce predicciones idénticas a las del original.

Implementado en la Fase 5.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fdisim.causal.prior_graph import export_graph, load_graph
from fdisim.causal.scm import StructuralCausalModel, model_from_dict

MODEL_FILES = ("graph.graphml", "graph.json", "scm.json", "residual_stats.json", "thresholds.json")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_model(
    model: StructuralCausalModel,
    graph: object,
    thresholds: dict[str, float],
    out_dir: Path,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Guarda el modelo en ``out_dir`` y devuelve la ruta de su manifiesto."""
    from fdisim.data.storage import git_commit, package_versions, sha256_file

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_graph(graph, out_dir / "graph.graphml", "graphml")
    export_graph(graph, out_dir / "graph.json", "json")
    _write_json(out_dir / "scm.json", model.to_dict())
    _write_json(
        out_dir / "residual_stats.json",
        {tag: asdict(stats) for tag, stats in model.residual_stats.items()},
    )
    _write_json(out_dir / "thresholds.json", thresholds)
    manifest = {
        "model": out_dir.name,
        "kind": model.kind,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "package_versions": package_versions(),
        **dict(metadata or {}),
        "files_sha256": {name: sha256_file(out_dir / name) for name in MODEL_FILES},
    }
    path = out_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def load_model(model_dir: Path) -> tuple[StructuralCausalModel, object, dict[str, float]]:
    """Carga un modelo guardado y verifica los SHA-256 de sus archivos."""
    from fdisim.data.storage import sha256_file

    model_dir = Path(model_dir)
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No hay un modelo causal en {model_dir} (falta manifest.json)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest.get("files_sha256", {}).items():
        if sha256_file(model_dir / name) != expected:
            raise ValueError(f"El archivo {name} del modelo no coincide con su SHA-256")
    model = model_from_dict(json.loads((model_dir / "scm.json").read_text(encoding="utf-8")))
    graph = load_graph(model_dir / "graph.graphml")
    thresholds = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))
    return model, graph, thresholds
