"""Receptor de webhooks.

- POST /webhook : valida a assinatura HMAC, descarta duplicados (idempotência) e registra o evento.
- GET  /eventos : lista os eventos registrados.
"""
import hashlib
import hmac
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SEGREDO = os.environ.get("WEBHOOK_SEGREDO")
if not SEGREDO:
    raise SystemExit("Defina a variável de ambiente WEBHOOK_SEGREDO antes de iniciar.")

app = FastAPI(title="Receptor")

eventos: list[dict] = []        # eventos registrados, em ordem de chegada
ids_recebidos: set[str] = set()  # ids já registrados (idempotência)


def assinatura_valida(corpo: bytes, cabecalho: str | None) -> bool:
    """Recalcula o HMAC sobre os bytes recebidos e compara em tempo constante."""
    if not cabecalho:
        return False
    esperada = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, cabecalho)


@app.post("/webhook")
async def receber_webhook(request: Request):
    corpo = await request.body()  # bytes crus: a assinatura é verificada antes de ler o JSON

    if not assinatura_valida(corpo, request.headers.get("X-Assinatura")):
        return JSONResponse({"erro": "assinatura ausente ou inválida"}, status_code=401)

    try:
        evento = json.loads(corpo)
        evento_id = evento["id"]
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"erro": "corpo inválido"}, status_code=400)

    if evento_id in ids_recebidos:  # reentrega: responde 2xx sem registrar de novo
        print(f"[receptor] duplicado ignorado: {evento_id}")
        return {"ok": True, "duplicado": True}

    ids_recebidos.add(evento_id)
    eventos.append(evento)
    print(f"[receptor] evento registrado: {evento}")
    return {"ok": True, "duplicado": False}


@app.get("/eventos")
def listar_eventos():
    return eventos
