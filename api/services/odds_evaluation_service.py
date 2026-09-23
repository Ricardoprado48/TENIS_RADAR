"""Servico HTTP do LOTE G: camada fina sobre
`src.odds.screenshot_evaluation` -- nenhuma logica de matching/classificacao
mora aqui, so a adaptacao entre o dict devolvido pelo adapter e o schema
Pydantic da API (mesmo padrao de `api/services/screenshot_service.py`).

LOTE H (secao 22) acrescentou so o calculo de `prediction_id`/
`already_registered_forward_test` por resultado, via `src.forward.ids`
(mesmo `make_prediction_id` que `src.forward.predictions` ja usa) e
`src.forward.build.is_registered` -- nenhuma probabilidade/odd/edge/
classificacao e tocada aqui."""

from __future__ import annotations

from src.forward import build as forward_build
from src.forward import ids as forward_ids
from src.odds import screenshot_evaluation

from api.schemas.odds_evaluation import EvaluateResponse


def _with_registration_status(result: dict) -> dict:
    forward_key = result.get("forward_key")
    if not forward_key:
        return result

    prediction_id = forward_ids.make_prediction_id(
        forward_key["bookmaker"], forward_key["tour"], forward_key["match_id"],
        forward_key["market"], forward_key["player"], forward_key["side"], forward_key["line"],
    )
    return {
        **result,
        "prediction_id": prediction_id,
        "already_registered_forward_test": forward_build.is_registered(prediction_id),
    }


def evaluate_confirmed_markets(upload_id: str) -> EvaluateResponse:
    result = screenshot_evaluation.evaluate_confirmed(upload_id)
    result["results"] = [_with_registration_status(r) for r in result["results"]]
    return EvaluateResponse(**result)
