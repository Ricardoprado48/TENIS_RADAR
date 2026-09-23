"""Config e criterios objetivos da Fase 5 (selecao de mercados).

Todos os limiares abaixo sao definidos ANTES de olhar os resultados finais
de classificacao (a analise fold-a-fold e superficie-a-superficie ja estava
pronta quando estes numeros foram fixados) e documentados aqui para que a
classificacao CANDIDATO / EXPERIMENTAL / PAUSAR seja auditavel e nao um
julgamento subjetivo caso a caso.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PHASE4_METRICS_DIR = PROJECT_ROOT / "data" / "outputs" / "phase4" / "metrics"
PHASE5_DIR = PROJECT_ROOT / "data" / "outputs" / "phase5"

FOLDS = ["fold_2024", "fold_2025", "fold_2026"]

# --------------------------------------------------------------------------
# Regra 2 do enunciado da Fase 5: so conta como "ganhou do baseline" se
# a metrica de erro/Brier da variante for estritamente menor que a do
# baseline trivial (naive_train_mean / naive_baserate) no MESMO fold.
# --------------------------------------------------------------------------

# Melhora relativa media minima (sobre os folds em que ganhou) para que a
# melhora seja considerada "real" e nao ruido de arredondamento.
MIN_MEAN_DELTA_REL = 0.03  # 3%

# Melhora relativa minima em CADA fold vencedor individualmente -- evita que
# um unico fold com melhora enorme mascare dois folds com melhora nula.
MIN_PER_FOLD_DELTA_REL_FOR_STRONG_WIN = 0.01  # 1%

# Cobertura minima (n no segmento overall) para o mercado/fold ser
# considerado "com dado suficiente" nesta fase.
MIN_COVERAGE_N = 300

# Amostra minima por superficie para que uma deterioracao naquela
# superficie seja levada em conta na classificacao (superficies com menos
# dados que isso sao apenas reportadas, nao usadas para punir o modelo).
MIN_SURFACE_N_FOR_FLAG = 150

# Deterioracao relativa maxima tolerada numa superficie com amostra
# suficiente antes de sinalizar "instabilidade por superficie".
MAX_SURFACE_DETERIORATION_REL = 0.10  # 10% pior que o naive nessa superficie

# --------------------------------------------------------------------------
# Classificacao final (item 8): regras objetivas, aplicadas em ordem.
# --------------------------------------------------------------------------
# CANDIDATO: venceu o baseline em 3/3 folds, com melhora relativa media
#            >= MIN_MEAN_DELTA_REL, melhora em CADA fold vencedor >=
#            MIN_PER_FOLD_DELTA_REL_FOR_STRONG_WIN, cobertura >= MIN_COVERAGE_N
#            em todos os folds, e sem deterioracao de superficie sinalizada.
# EXPERIMENTAL: venceu em 2/3 folds (qualquer melhora), OU venceu em 3/3 mas
#            com deterioracao de superficie sinalizada, OU venceu em 3/3 com
#            melhora media abaixo de MIN_MEAN_DELTA_REL.
# PAUSAR: venceu em <=1/3 folds, OU nao supera o baseline em nenhum fold,
#            OU cobertura insuficiente em algum fold.
