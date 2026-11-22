"""Emissor de webhooks.

- POST /pedidos/{pedido_id} : cadastra o pedido com status "recebido".
- Thread em segundo plano    : a cada INTERVALO segundos avança o status de cada pedido
                               (recebido -> aprovado -> enviado -> entregue) e notifica o receptor.
- Cada notificação é um POST assinado (HMAC-SHA256) com id de evento próprio.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

SEGREDO = os.environ.get("WEBHOOK_SEGREDO")
if not SEGREDO:
    raise SystemExit("Defina a variável de ambiente WEBHOOK_SEGREDO antes de iniciar.")

URL_WEBHOOK = os.environ.get("URL_WEBHOOK", "http://localhost:8001/webhook")
INTERVALO = float(os.environ.get("INTERVALO", "5"))  # segundos entre mudanças de status
TENTATIVAS = 3                                       # tentativas de entrega por evento

SEQUENCIA = ["recebido", "aprovado", "enviado", "entregue"]

pedidos: dict[str, str] = {}  # pedido_id -> status atual
trava = threading.Lock()      # protege `pedidos` (acessado pela API e pela thread)


def assinar(corpo: bytes) -> str:
    """HMAC-SHA256 dos bytes do corpo, no formato sha256=<hex>."""
    return "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()


def notificar(pedido_id: str, status: str) -> None:
    """Envia o webhook. Reentregas (após falha) reutilizam o MESMO id de evento."""
    evento = {"id": f"evt_{uuid.uuid4().hex[:8]}", "pedido_id": pedido_id, "status": status}
    corpo = json.dumps(evento).encode()  # os mesmos bytes são assinados e enviados
    requisicao = urllib.request.Request(
        URL_WEBHOOK,
        data=corpo,
        headers={"Content-Type": "application/json", "X-Assinatura": assinar(corpo)},
        method="POST",
    )

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            with urllib.request.urlopen(requisicao, timeout=5) as resposta:
                print(f"[emissor] {evento['id']} {pedido_id}->{status}: HTTP {resposta.status}")
                return
        except (urllib.error.URLError, OSError) as erro:
            print(f"[emissor] falha ao enviar {evento['id']} (tentativa {tentativa}): {erro}")
            time.sleep(1)
    print(f"[emissor] desistindo de {evento['id']} após {TENTATIVAS} tentativas")


def processar_pedidos() -> None:
    """Loop em segundo plano: avança um passo no status de cada pedido não entregue."""
    while True:
        time.sleep(INTERVALO)
        with trava:
            avancos = []
            for pedido_id, status in pedidos.items():
                if status != SEQUENCIA[-1]:
                    novo = SEQUENCIA[SEQUENCIA.index(status) + 1]
                    pedidos[pedido_id] = novo
                    avancos.append((pedido_id, novo))
        for pedido_id, novo in avancos:  # envia fora da trava para não bloquear a API
            notificar(pedido_id, novo)


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    threading.Thread(target=processar_pedidos, daemon=True).start()
    yield


app = FastAPI(title="Emissor", lifespan=ciclo_de_vida)


@app.post("/pedidos/{pedido_id}", status_code=201)
def criar_pedido(pedido_id: str):
    with trava:
        if pedido_id in pedidos:
            raise HTTPException(status_code=409, detail="pedido já cadastrado")
        pedidos[pedido_id] = SEQUENCIA[0]
    return {"pedido_id": pedido_id, "status": SEQUENCIA[0]}


@app.get("/pedidos")
def listar_pedidos():
    with trava:
        return dict(pedidos)
