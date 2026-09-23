"""Ponto de entrada da API.

LOTE A: app, CORS restrito aos hosts locais do Vite, tratamento central de
erros e os routers de saude/metadados. LOTE C acrescenta a rota de
calendario. LOTE D acrescenta a rota de radar do dia. LOTE E acrescenta o
upload de print (armazenamento, sem interpretacao). Confirmacao/leitura de
print, odds e forward test ainda nao existem -- ver
docs/018_PWA_ARQUITETURA.md secao 14 para os proximos lotes.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.routes import calendar, forward, health, info, radar, screenshots

logger = logging.getLogger("tennis_radar.api")

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
)

# CORS apenas para os hosts locais necessarios ao dev server do Vite
# (docs/018_PWA_ARQUITETURA.md, LOTE B) -- nunca "*", nunca host remoto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Tratamento central de erros: qualquer excecao nao tratada por um
    handler mais especifico vira uma resposta JSON generica (nunca
    stacktrace/detalhe interno exposto ao cliente)."""
    logger.exception("Erro nao tratado em %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Erro interno inesperado."})


app.include_router(health.router, prefix="/api")
app.include_router(info.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(radar.router, prefix="/api")
app.include_router(screenshots.router, prefix="/api")
app.include_router(forward.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    # Bind projetado para localhost (docs/018 risco R5) -- nunca 0.0.0.0.
    uvicorn.run(app, host=settings.host, port=settings.port)
