# Exercício 3 — Webhooks

Duas aplicações em processos separados (Python + FastAPI) que implementam as duas pontas de um webhook.

## Quem é quem

| Papel | Pasta | Porta | Função |
|---|---|---|---|
| **Emissor** | `emissor/` | 8000 | Cadastra pedidos, avança o status em segundo plano e notifica cada mudança. |
| **Receptor** | `receptor/` | 8001 | Recebe as notificações, valida, registra e lista. |

## Evento que dispara a notificação

Cada **mudança de status** de um pedido. O pedido nasce como `recebido` (cadastro, sem notificação) e uma thread em segundo plano o avança a cada `INTERVALO` segundos:

`recebido → aprovado → enviado → entregue`

Cada avanço gera um webhook (aprovado, enviado e entregue = 3 eventos por pedido).

## Endpoints e payload

**Emissor**
- `POST /pedidos/{pedido_id}` — cadastra o pedido com status `recebido` (201; 409 se já existe).
- `GET /pedidos` — status atual dos pedidos (apoio para depuração).

**Receptor**
- `POST /webhook` — recebe o evento, registra e responde 2xx.
- `GET /eventos` — lista os eventos registrados.

**Payload enviado pelo emissor** (o `id` é do *evento*, não do pedido; cada mudança tem um id novo):

```json
{ "id": "evt_06aecd1b", "pedido_id": "ped_1", "status": "aprovado" }
```

Cabeçalhos: `Content-Type: application/json` e `X-Assinatura: sha256=<64 hex>`.

## Extras implementados

- **HMAC-SHA256**: o emissor assina os bytes do corpo com o segredo compartilhado e envia em `X-Assinatura`. O receptor recalcula sobre os bytes crus (antes de ler o JSON) e compara com `hmac.compare_digest`. Assinatura ausente/inválida → **401** e o evento não é registrado. O segredo vem da variável de ambiente `WEBHOOK_SEGREDO` (não está no código nem no repositório).
- **Idempotência**: o receptor guarda os ids já vistos; um id repetido recebe 2xx (`"duplicado": true`) sem ser registrado de novo. O emissor, se a entrega falhar, tenta até 3 vezes **reutilizando o mesmo id**.

## Como subir (nesta ordem)

Requer Python 3.10+. Instalar dependências uma vez:

```bash
pip install -r receptor/requirements.txt
```

Use o **mesmo segredo** nos dois terminais (valor fictício de exemplo).

**Terminal 1 — receptor**

```powershell
cd receptor
$env:WEBHOOK_SEGREDO="segredo-ficticio-123"
python -m uvicorn receptor:app --port 8001
```

**Terminal 2 — emissor**

```powershell
cd emissor
$env:WEBHOOK_SEGREDO="segredo-ficticio-123"
$env:INTERVALO="5"   # opcional: segundos entre mudanças (padrão 5)
python -m uvicorn emissor:app --port 8000
```

(Em Linux/macOS: `export WEBHOOK_SEGREDO=segredo-ficticio-123`.)

**Terminal 3 — testar**

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/pedidos/ped_1
# aguarde ~15 s
Invoke-RestMethod http://localhost:8001/eventos
```

(Com curl: `curl -X POST localhost:8000/pedidos/ped_1` e `curl localhost:8001/eventos`.)

## Evidência de funcionamento

Execução com `INTERVALO=2`.

**`POST /pedidos/ped_1` no emissor**

```json
{"pedido_id":"ped_1","status":"recebido"}
```

**Log do emissor**

```
[emissor] evt_06aecd1b ped_1->aprovado: HTTP 200
[emissor] evt_1ecb96ef ped_1->enviado: HTTP 200
[emissor] evt_fa62e141 ped_1->entregue: HTTP 200
```

**Log do receptor**

```
[receptor] evento registrado: {'id': 'evt_06aecd1b', 'pedido_id': 'ped_1', 'status': 'aprovado'}
[receptor] evento registrado: {'id': 'evt_1ecb96ef', 'pedido_id': 'ped_1', 'status': 'enviado'}
[receptor] evento registrado: {'id': 'evt_fa62e141', 'pedido_id': 'ped_1', 'status': 'entregue'}
```

**`GET /eventos` no receptor** (ciclo completo)

```json
[
  { "id": "evt_06aecd1b", "pedido_id": "ped_1", "status": "aprovado" },
  { "id": "evt_1ecb96ef", "pedido_id": "ped_1", "status": "enviado" },
  { "id": "evt_fa62e141", "pedido_id": "ped_1", "status": "entregue" }
]
```

**Testes dos extras**

- `POST /webhook` sem `X-Assinatura` → **401**; com assinatura errada → **401**; nenhum dos dois foi registrado.
- Mesmo evento (`evt_dup`) enviado duas vezes com assinatura válida → 1ª `{"ok":true,"duplicado":false}`, 2ª `{"ok":true,"duplicado":true}`; `GET /eventos` mostra o evento apenas uma vez.
