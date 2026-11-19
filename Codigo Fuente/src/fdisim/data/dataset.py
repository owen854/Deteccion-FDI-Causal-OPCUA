"""Construcción de datasets de entrenamiento, validación y prueba (RF-27).

- Entrenamiento y validación: solo operación normal (con perturbaciones legítimas).
- Prueba: operación normal y escenarios con ataque, con etiquetas por muestra.
- Alineación: las muestras asíncronas se llevan a una rejilla uniforme de periodo
  ``detection.period_s`` (retención de orden cero), igual que en el monitor en línea.
- Sin solapamiento temporal: cada corrida es una serie independiente (semilla propia) y se
  asigna completa a una sola partición; la columna ``run_id`` las separa.

Generación por lotes (Monte Carlo, ``generate_datasets``): corridas offline con semillas
controladas y consecutivas desde ``base_seed``. Como el modo offline no usa el reloj de pared,
la misma semilla produce archivos idénticos (criterio de RF-27, RNF-08); el manifiesto del
dataset guarda las semillas, la asignación de corridas y el SHA-256 de cada archivo.

Implementado en la Fase 4.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from fdisim.common.types import PROCESS_TAGS

SPLITS = ("train", "val", "test")


def align_samples(samples: Any, period_s: float, tags: Sequence[str] = PROCESS_TAGS) -> Any:
    """Convierte la tabla de muestras en una tabla ancha (una columna por etiqueta) en rejilla.

    Usa ``sim_time`` y retención de orden cero: en cada instante de la rejilla, el último valor
    recibido de cada variable. La rejilla empieza cuando todas las variables tienen valor y
    nunca antes de t = 0 (en red, los valores iniciales llegan antes del arranque del reloj).
    """
    import pandas as pd

    if period_s <= 0:
        raise ValueError("period_s debe ser positivo")
    data = samples[samples["tag"].isin(tags) & (samples["status"] == "Good")]
    firsts = [data.loc[data["tag"] == tag, "sim_time"].min() for tag in tags]
    if any(pd.isna(f) for f in firsts):
        missing = [tag for tag, f in zip(tags, firsts, strict=True) if pd.isna(f)]
        raise ValueError(f"Sin muestras de {missing}")
    start = max(0.0, np.ceil(max(firsts) / period_s - 1e-9) * period_s)
    end = float(data["sim_time"].max())
    grid = pd.DataFrame({"sim_time": np.round(np.arange(start, end + 1e-9, period_s), 6)})
    for tag in tags:
        series = data.loc[data["tag"] == tag, ["sim_time", "value"]].sort_values("sim_time")
        series = series.rename(columns={"value": tag})
        series["sim_time"] = series["sim_time"].astype(float)
        grid = pd.merge_asof(grid, series, on="sim_time", direction="backward")
    return grid


def label_grid(grid: Any, events: Iterable[Any], tags: Sequence[str] = PROCESS_TAGS) -> Any:
    """Agrega ``label``, ``attack_id`` y ``atk_<tag>`` (variable atacada) a una rejilla."""
    from fdisim.data.labels import label_times

    events = list(events)
    label, attack_id, _ = label_times(grid["sim_time"], events)
    out = grid.assign(label=label, attack_id=attack_id)
    for tag in tags:
        _, _, attacked = label_times(grid["sim_time"], events, np.full(len(grid), tag))
        out[f"atk_{tag}"] = attacked
    return out


def run_table(run_dir: Path, period_s: float) -> Any:
    """Rejilla etiquetada de una corrida guardada (verifica antes sus hashes)."""
    from fdisim.data.labels import events_from_frame
    from fdisim.data.storage import read_run

    tables, manifest = read_run(Path(run_dir))
    grid = align_samples(tables["samples"], period_s)
    events = events_from_frame(tables["attacks"]) if "attacks" in tables else []
    grid = label_grid(grid, events)
    grid.insert(0, "seed", manifest.seed)
    grid.insert(0, "scenario", manifest.scenario)
    grid.insert(0, "run_id", manifest.run_id)
    return grid


def build_splits(
    run_dirs: list[Path], seed: int, period_s: float = 0.5, fractions: Sequence[float] = (0.6, 0.2)
) -> dict[str, Any]:
    """Devuelve ``{"train": df, "val": df, "test": df}`` sin solapamiento temporal.

    Las corridas sin ataques se reparten (barajadas con ``seed``) entre entrenamiento,
    validación y prueba según ``fractions``; todas las corridas con ataques van a prueba.
    """
    import pandas as pd

    tables = [run_table(d, period_s) for d in run_dirs]
    normal = [t for t in tables if t["label"].sum() == 0]
    attacked = [t for t in tables if t["label"].sum() > 0]
    order = np.random.default_rng(seed).permutation(len(normal))
    n_train = int(round(fractions[0] * len(normal)))
    n_val = int(round(fractions[1] * len(normal)))
    groups = {
        "train": [normal[i] for i in order[:n_train]],
        "val": [normal[i] for i in order[n_train : n_train + n_val]],
        "test": [normal[i] for i in order[n_train + n_val :]] + attacked,
    }
    return {
        name: pd.concat(items, ignore_index=True) if items else pd.DataFrame()
        for name, items in groups.items()
    }


def generate_datasets(
    out_dir: Path,
    *,
    config_path: Path | None = None,
    normal_scenario: Path,
    attack_scenarios: Sequence[Path] = (),
    n_train: int = 10,
    n_val: int = 3,
    n_test_normal: int = 3,
    n_per_attack: int = 2,
    base_seed: int = 1000,
    duration_s: float | None = None,
    integrator: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Genera por lotes (Monte Carlo) las corridas offline y los datasets v1 (RF-27).

    Semillas: normales ``base_seed + i`` (entrenamiento, luego validación, luego prueba) y,
    para cada escenario de ataque ``j``, ``base_seed + 1000·(j+1) + i``. Devuelve la ruta del
    manifiesto del dataset.
    """
    import pandas as pd

    from fdisim.common.config import load_config, load_scenario
    from fdisim.data.storage import git_commit, package_versions, sha256_file
    from fdisim.orchestration.offline import run_scenario_offline

    say = progress or (lambda _msg: None)
    out_dir = Path(out_dir)
    runs_dir = out_dir / "runs"
    config = load_config(config_path).to_dict()
    period = float(config["detection"]["period_s"])
    fmt = "parquet"

    plan: list[tuple[str, Path, int]] = []
    seeds = iter(range(base_seed, base_seed + n_train + n_val + n_test_normal))
    for split, count in (("train", n_train), ("val", n_val), ("test", n_test_normal)):
        plan += [(split, Path(normal_scenario), next(seeds)) for _ in range(count)]
    for j, scenario in enumerate(attack_scenarios):
        plan += [
            ("test", Path(scenario), base_seed + 1000 * (j + 1) + i) for i in range(n_per_attack)
        ]

    frames: dict[str, list[Any]] = {name: [] for name in SPLITS}
    runs: list[dict[str, Any]] = []
    for n, (split, scenario_path, seed) in enumerate(plan, 1):
        scenario = load_scenario(scenario_path)
        run_id = f"{scenario.name}_s{seed}"
        say(f"[{n}/{len(plan)}] {split}: {run_id}")
        run_dir = run_scenario_offline(
            scenario_path,
            config_path,
            seed,
            duration_s=duration_s,
            integrator=integrator,
            raw_dir=runs_dir,
            run_id=run_id,
        )
        frames[split].append(run_table(run_dir, period))
        runs.append({"split": split, "run_id": run_id, "scenario": scenario.name, "seed": seed})

    files: dict[str, str] = {}
    sizes: dict[str, dict[str, int]] = {}
    for split in SPLITS:
        table = pd.concat(frames[split], ignore_index=True) if frames[split] else pd.DataFrame()
        path = out_dir / f"{split}.{fmt}"
        table.to_parquet(path, index=False)
        files[path.name] = sha256_file(path)
        sizes[split] = {
            "rows": int(len(table)),
            "runs": len(frames[split]),
            "attack_rows": int(table["label"].sum()) if len(table) else 0,
        }
    manifest = {
        "dataset": out_dir.name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "period_s": period,
        "base_seed": base_seed,
        "duration_s": duration_s,
        "integrator": integrator or config["simulation"].get("integrator"),
        "normal_scenario": str(normal_scenario),
        "attack_scenarios": [str(p) for p in attack_scenarios],
        "columns": list(frames["train"][0].columns) if frames["train"] else [],
        "splits": sizes,
        "runs": runs,
        "files_sha256": files,
        "git_commit": git_commit(),
        "package_versions": package_versions(),
    }
    path = out_dir / "dataset_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
