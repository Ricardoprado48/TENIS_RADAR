"""Resolucao de identidade de jogador (item 2 da instrucao).

Nao existe, em nenhuma fase anterior do projeto, uma tabela de aliases nem
uma funcao de casamento de nomes -- `data/processed/{tour}/players.parquet`
(Fase 2) so guarda um nome canonico por `player_id`. Esta fase implementa
tres niveis deterministicos de casamento, do mais para o menos confiavel,
NUNCA escolhendo silenciosamente entre candidatos ambiguos (associa so
quando exatamente 1 candidato sobra em cada nivel):

  exact         -- nome completo normalizado bate com exatamente 1 player_id.
  alias         -- formato abreviado tipico de quadros de torneio ("J.
                    Ostapenko"): inicial do primeiro nome + sobrenome,
                    resolvido por sobrenome + inicial contra a base de
                    jogadores do tour, com exatamente 1 candidato.
  fuzzy_review  -- nenhum match exato/alias, mas exatamente 1 nome completo
                    do tour fica acima do limiar de similaridade
                    (difflib.SequenceMatcher, stdlib -- nenhuma dependencia
                    nova). Usado para gerar previsao, mas sinalizado para
                    revisao humana (nunca tratado como certeza).
  unresolved    -- nenhum candidato, ou mais de um candidato igualmente
                    plausivel em qualquer nivel. Nunca gera previsao
                    (item 2 da instrucao).
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


@dataclass(frozen=True)
class ResolutionResult:
    player_id: str | None
    method: str
    matched_name: str | None
    n_candidates: int
    note: str


class PlayerIndex:
    """Indices de nome construidos uma vez por tour e reaproveitados para
    todas as partidas daquele tour na mesma execucao."""

    def __init__(self, players: pd.DataFrame):
        self.players = players
        self._by_full_name: dict[str, list[str]] = {}
        self._by_last_name: dict[str, list[tuple[str, str, str]]] = {}
        self._all_full_names: list[str] = []

        for row in players.itertuples(index=False):
            full_norm = normalize_name(row.name)
            self._by_full_name.setdefault(full_norm, []).append(row.player_id)
            if full_norm:
                self._all_full_names.append(full_norm)

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

        exact = self._by_full_name.get(norm, [])
        if len(exact) == 1:
            return ResolutionResult(exact[0], "exact", norm, 1, "match exato de nome completo")
        if len(exact) > 1:
            return ResolutionResult(
                None, "unresolved", norm, len(exact),
                f"nome completo ambiguo: {len(exact)} jogadores com o mesmo nome normalizado",
            )

        alias_result = self._resolve_alias(norm)
        if alias_result is not None:
            return alias_result

        return self._resolve_fuzzy(norm)

    def _resolve_alias(self, norm: str) -> ResolutionResult | None:
        parts = norm.split(" ")
        if len(parts) < 2:
            return None

        candidate_lasts = []
        # formato "j ostapenko" (inicial + sobrenome) -- o mais comum em
        # quadros de torneio.
        if len(parts[0]) <= 2:
            candidate_lasts.append((parts[0][0], " ".join(parts[1:])))
        # nome completo dado mas com sobrenome composto/grafia diferente da
        # canonica -- tenta so a ultima palavra como sobrenome.
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
        # varios nomes normalizados diferentes podem mapear para o mesmo
        # player_id (nao deveria, mas nao assumimos); so aceita se todos os
        # nomes proximos resolverem para o mesmo unico player_id.
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
    """Para cada partida bruta, resolve jogador A e jogador B contra a base
    de jogadores do TOUR correspondente (nunca cruza ATP com WTA)."""

    indexes = {tour: PlayerIndex(df) for tour, df in players_by_tour.items()}

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
    """item 10: 'partidas repetidas' -- mesma dupla de jogadores (ordem
    livre) no mesmo tour/data conta como a mesma partida; mantem a primeira
    ocorrencia para geracao de previsao e marca as demais."""

    df = resolved.copy()
    pair_key = df.apply(
        lambda r: "|".join(sorted([str(r["player_id_a"]), str(r["player_id_b"])]))
        if r["usable_for_prediction"] else f"__unresolved_{r['raw_match_seq']}",
        axis=1,
    )
    df["match_dedup_key"] = df["tour"] + "|" + df["match_date"].astype(str) + "|" + pair_key
    df["is_duplicate"] = df.duplicated(subset=["match_dedup_key"], keep="first")
    return df
