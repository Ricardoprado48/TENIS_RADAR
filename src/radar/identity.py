"""Resolucao de identidade de jogador (item 2 da instrucao).

A resolução é conservadora e nunca escolhe silenciosamente entre candidatos
ambíguos. A ordem é:

  override      -- correção explícita para duplicidade comprovada na própria
                   base canônica (config.PLAYER_IDENTITY_OVERRIDES). O método
                   exposto continua sendo "alias" para não ampliar o contrato.
  exact         -- nome completo normalizado bate com exatamente 1 player_id.
  alias         -- equivalência estrutural inequívoca:
                   * nome completo sem diferença de espaços ("Xinyu" vs "Xin Yu");
                   * mesmos tokens em ordem diferente ("Gabriela Elena" vs
                     "Elena Gabriela");
                   * formato abreviado inicial + sobrenome.
  fuzzy_review  -- nenhum match acima, mas exatamente 1 nome completo fica
                   acima do limiar de similaridade. Pode gerar previsão, porém
                   fica sinalizado para revisão humana.
  unresolved    -- nenhum candidato ou ambiguidade real. Nunca gera previsão.

Nenhum nome é associado por país, ranking ou heurística de "parece ser".
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from . import config as cfg


def normalize_name(raw) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _compact_name(raw) -> str:
    return normalize_name(raw).replace(" ", "")


def _token_key(raw) -> tuple[str, ...]:
    return tuple(sorted(normalize_name(raw).split()))


@dataclass(frozen=True)
class ResolutionResult:
    player_id: str | None
    method: str
    matched_name: str | None
    n_candidates: int
    note: str


class PlayerIndex:
    """Índices de nome construídos uma vez por tour."""

    def __init__(self, players: pd.DataFrame, tour: str | None = None):
        self.players = players
        self.tour = (tour or "").upper().strip()
        self._by_full_name: dict[str, list[str]] = {}
        self._by_compact_name: dict[str, list[tuple[str, str]]] = {}
        self._by_token_key: dict[tuple[str, ...], list[tuple[str, str]]] = {}
        self._by_last_name: dict[str, list[tuple[str, str, str]]] = {}
        self._all_full_names: list[str] = []

        for row in players.itertuples(index=False):
            full_norm = normalize_name(row.name)
            self._by_full_name.setdefault(full_norm, []).append(row.player_id)
            if full_norm:
                self._all_full_names.append(full_norm)
                self._by_compact_name.setdefault(
                    _compact_name(row.name), []
                ).append((row.player_id, row.name))
                self._by_token_key.setdefault(
                    _token_key(row.name), []
                ).append((row.player_id, row.name))

            last_norm = normalize_name(row.name_last)
            first_norm = normalize_name(row.name_first)
            first_letter = first_norm[0] if first_norm else ""
            if last_norm:
                self._by_last_name.setdefault(last_norm, []).append(
                    (row.player_id, first_letter, row.name)
                )

    def resolve(self, raw_name: str) -> ResolutionResult:
        norm = normalize_name(raw_name)
        if not norm:
            return ResolutionResult(None, "unresolved", None, 0, "nome vazio ou invalido")

        override = self._resolve_override(norm)
        if override is not None:
            return override

        exact = self._by_full_name.get(norm, [])
        if len(exact) == 1:
            return ResolutionResult(exact[0], "exact", norm, 1, "match exato de nome completo")
        if len(exact) > 1:
            return ResolutionResult(
                None, "unresolved", norm, len(exact),
                f"nome completo ambiguo: {len(exact)} jogadores com o mesmo nome normalizado",
            )

        structural = self._resolve_structural_alias(raw_name)
        if structural is not None:
            return structural

        alias_result = self._resolve_initial_last_alias(norm)
        if alias_result is not None:
            return alias_result

        return self._resolve_fuzzy(norm)

    def _resolve_override(self, norm: str) -> ResolutionResult | None:
        player_id = cfg.PLAYER_IDENTITY_OVERRIDES.get((self.tour, norm))
        if player_id is None:
            return None

        rows = self.players[self.players["player_id"] == player_id]
        if len(rows) != 1:
            return ResolutionResult(
                None,
                "unresolved",
                None,
                int(len(rows)),
                f"override de identidade aponta para player_id ausente/ambiguo: {player_id}",
            )

        return ResolutionResult(
            player_id,
            "alias",
            str(rows.iloc[0]["name"]),
            1,
            "override canonico comprovado para duplicidade de player_id",
        )

    def _resolve_structural_alias(self, raw_name: str) -> ResolutionResult | None:
        compact = self._by_compact_name.get(_compact_name(raw_name), [])
        compact_unique = {pid: name for pid, name in compact}
        if len(compact_unique) == 1:
            pid, full_name = next(iter(compact_unique.items()))
            return ResolutionResult(
                pid, "alias", full_name, 1,
                "nome equivalente apos remover diferencas de espacamento",
            )
        if len(compact_unique) > 1:
            return ResolutionResult(
                None, "unresolved", None, len(compact_unique),
                f"nome compacto ambiguo: {len(compact_unique)} candidatos",
            )

        token_matches = self._by_token_key.get(_token_key(raw_name), [])
        token_unique = {pid: name for pid, name in token_matches}
        if len(token_unique) == 1:
            pid, full_name = next(iter(token_unique.items()))
            return ResolutionResult(
                pid, "alias", full_name, 1,
                "mesmos componentes de nome em ordem diferente",
            )
        if len(token_unique) > 1:
            return ResolutionResult(
                None, "unresolved", None, len(token_unique),
                f"componentes de nome ambiguos: {len(token_unique)} candidatos",
            )
        return None

    def _resolve_initial_last_alias(self, norm: str) -> ResolutionResult | None:
        parts = norm.split(" ")
        if len(parts) < 2:
            return None

        candidate_lasts = []
        if len(parts[0]) <= 2:
            candidate_lasts.append((parts[0][0], " ".join(parts[1:])))
        candidate_lasts.append((parts[0][0], parts[-1]))

        seen_pids: dict[str, str] = {}
        for first_letter, last_guess in candidate_lasts:
            for pid, fletter, full_name in self._by_last_name.get(last_guess, []):
                if fletter == first_letter:
                    seen_pids[pid] = full_name

        if len(seen_pids) == 1:
            pid, full_name = next(iter(seen_pids.items()))
            return ResolutionResult(pid, "alias", full_name, 1, "sobrenome + inicial do primeiro nome")
        if len(seen_pids) > 1:
            return ResolutionResult(
                None, "unresolved", None, len(seen_pids),
                f"sobrenome + inicial ambiguo: {len(seen_pids)} candidatos",
            )
        return None

    def _resolve_fuzzy(self, norm: str) -> ResolutionResult:
        close = difflib.get_close_matches(
            norm, self._all_full_names, n=3, cutoff=cfg.FUZZY_MATCH_MIN_RATIO
        )
        pids = set()
        for name in close:
            pids.update(self._by_full_name.get(name, []))
        if len(pids) == 1 and close:
            pid = next(iter(pids))
            return ResolutionResult(pid, "fuzzy_review", close[0], 1, "match aproximado (revisar manualmente)")
        if len(pids) > 1:
            return ResolutionResult(
                None, "unresolved", None, len(pids),
                f"match aproximado ambiguo: {len(pids)} candidatos",
            )
        return ResolutionResult(None, "unresolved", None, 0, "nenhum candidato encontrado")


def resolve_matches(upcoming: pd.DataFrame, players_by_tour: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Resolve os dois jogadores sempre dentro do tour correspondente."""

    indexes = {tour: PlayerIndex(df, tour=tour) for tour, df in players_by_tour.items()}

    rows = []
    for row in upcoming.itertuples(index=False):
        idx = indexes[row.tour]
        res_a = idx.resolve(row.player_a_raw)
        res_b = idx.resolve(row.player_b_raw)

        same_player = (
            res_a.player_id is not None and res_a.player_id == res_b.player_id
        )
        if same_player:
            res_a = ResolutionResult(None, "unresolved", res_a.matched_name, res_a.n_candidates,
                                      "jogador A e B resolveram para o mesmo player_id")
            res_b = ResolutionResult(None, "unresolved", res_b.matched_name, res_b.n_candidates,
                                      "jogador A e B resolveram para o mesmo player_id")

        rows.append({
            "raw_match_seq": row.raw_match_seq,
            "source_file": row.source_file,
            "source_url": row.source_url,
            "collected_at": row.collected_at,
            "tour": row.tour,
            "tournament": row.tournament,
            "surface": row.surface,
            "match_date": row.match_date,
            "round": row.round,
            "player_a_raw": row.player_a_raw,
            "player_b_raw": row.player_b_raw,
            "player_id_a": res_a.player_id,
            "resolution_method_a": res_a.method,
            "resolution_note_a": res_a.note,
            "resolved_name_a": res_a.matched_name,
            "player_id_b": res_b.player_id,
            "resolution_method_b": res_b.method,
            "resolution_note_b": res_b.note,
            "resolved_name_b": res_b.matched_name,
        })

    out = pd.DataFrame(rows)
    out["usable_for_prediction"] = (
        out["player_id_a"].notna() & out["player_id_b"].notna()
    )
    return out


def flag_duplicate_matches(resolved: pd.DataFrame) -> pd.DataFrame:
    """Marca mesma dupla, mesma data e mesmo tour como duplicada."""

    df = resolved.copy()
    pair_key = df.apply(
        lambda r: "|".join(sorted([str(r["player_id_a"]), str(r["player_id_b"])]))
        if r["usable_for_prediction"] else f"__unresolved_{r['raw_match_seq']}",
        axis=1,
    )
    df["match_dedup_key"] = df["tour"] + "|" + df["match_date"].astype(str) + "|" + pair_key
    df["is_duplicate"] = df.duplicated(subset=["match_dedup_key"], keep="first")
    return df
