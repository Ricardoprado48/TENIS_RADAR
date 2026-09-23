"""Congelamento de versao operacional (item 2). Cada previsao registrada
carrega a mesma identificacao explicita de fase/regras/calibrador, o commit
Git atual (quando disponivel) e a staleness calculada pela Fase 9
(`src.odds.pricing_compare.staleness_warning`, reaproveitada sem alteracao).

`historical_data_cutoff`/`data_staleness_days` sao recalculados aqui (nunca
inventados a partir do valor ja gravado pela Fase 10) porque representam o
estado "no momento deste registro" -- a base historica em si nunca muda
(Fase 8.1 confirmou 0 linhas novas), mas o numero de dias decorridos desde o
corte cresce a cada dia. Uma vez gravado em `forward_predictions.parquet`,
esse valor fica congelado como qualquer outro campo (item 1) -- so o
MOMENTO do calculo e "agora", nunca recalculado depois de registrado."""

from __future__ import annotations

import subprocess

from src.odds import pricing_compare as pc

from . import config as cfg


def current_git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cfg.PROJECT_ROOT, capture_output=True, text=True, timeout=5, check=True,
        )
        commit = out.stdout.strip()
        return commit or None
    except Exception:
        # item 2: "commit Git atual quando disponivel" -- repositorio sem
        # commits, git ausente do PATH, ou qualquer outra falha nunca
        # interrompe o registro, so grava None (nunca inventar um valor).
        return None


def current_version_stamp(tour: str) -> dict:
    stale = pc.staleness_warning(tour)
    return {
        "forward_version_id": cfg.FORWARD_VERSION_ID,
        "features_version": cfg.FEATURES_VERSION,
        "calibration_version": cfg.CALIBRATION_VERSION,
        "rules_version": cfg.RULES_VERSION,
        "git_commit": current_git_commit(),
        "historical_data_cutoff": stale["historical_data_cutoff"],
        "data_staleness_days": stale["data_staleness_days"],
    }
