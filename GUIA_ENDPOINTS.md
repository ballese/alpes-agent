# Guía de endpoints — Estudiantes del curso

Esta guía cubre **solo** los endpoints que usará como estudiante para consultar
el RAG. La base de datos vectorial es **compartida y de solo lectura**: un
administrador cargó los documentos; usted solo hace preguntas.

- **URL base:** `http://34.71.149.196:8000`
- **Todos los endpoints van bajo** `/api/v1`
- **Autenticación:** token *Bearer* (JWT) que obtiene al hacer login.

> Su usuario es `grupoNN_<caso>@uniandes.edu.co` (se lo entregó el equipo del
> curso junto con su contraseña — están en el README de su repositorio).

---

## Colección que le corresponde a su grupo

En cada consulta debe indicar su colección según su caso:

| Caso | Colección (campo `collection`) |
|---|---|
| Finanzas | `finanzas` |
| Telecom | `telecom` |
| Centro de Proyectos | `centro_proyectos` |

Puede verificar las colecciones disponibles con `GET /collections/` (abajo).

---

## 1. Login — obtener el token

`POST /api/v1/login`

Body **JSON** (no formulario):

```json
{ "email": "grupo01_finanzas@uniandes.edu.co", "password": "TU_PASSWORD" }
```

Respuesta `200`:

```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```

Use ese `access_token` en el header `Authorization: Bearer <token>` en todas las
demás llamadas.

```bash
curl -s -X POST http://34.71.149.196:8000/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"email":"grupo01_finanzas@uniandes.edu.co","password":"TU_PASSWORD"}'
```

Errores: `401` email o contraseña inválidos.

---

## 2. (Opcional) Ver su perfil

`GET /api/v1/me`  · requiere `Authorization: Bearer <token>`

```json
{ "id": 12, "email": "grupo01_finanzas@uniandes.edu.co", "vector_db_name": "course_shared", "is_admin": false }
```

---

## 3. (Opcional) Ver las colecciones disponibles

`GET /api/v1/collections/`  · requiere token. Devuelve una lista de nombres:

```json
["finanzas", "telecom", "centro_proyectos"]
```

```bash
curl -s http://34.71.149.196:8000/api/v1/collections/ \
  -H "Authorization: Bearer $TOKEN"
```

---

## 4. Preguntar al RAG  ⭐ (el endpoint principal)

`POST /api/v1/ask`  · requiere token · **consume su cuota de rate limit**

Body **JSON**:

```json
{
  "pregunta": "¿Cuáles son los puntos clave del documento?",
  "collection": "finanzas",
  "top_k": 5,
  "reraking": false,
  "evaluate": false
}
```

| Campo | Tipo | Obligatorio | Descripción |
|---|---|:--:|---|
| `pregunta` | string | ✅ | Su pregunta en lenguaje natural |
| `collection` | string | ✅ | La colección de su caso (ver tabla arriba) |
| `top_k` | int | — | Nº de fragmentos a recuperar (default 5) |
| `reraking` | bool | — | Reordenar resultados con el reranker (default false) |
| `evaluate` | bool | — | Calcular métricas RAGAS de la respuesta (más lento; default true) |

> ⚠️ El campo se llama `reraking`, así escrito — no `reranking`. Es el nombre
> real que expone la API (aunque parece un typo). Si lo "corrige" en su
> código, el campo simplemente se ignora y no obtendrá el efecto esperado.

Respuesta `200` (campos principales):

```json
{
  "pregunta": "…",
  "respuesta": "Texto de la respuesta generada por el LLM…",
  "collection": "finanzas",
  "files_consulted": ["doc_banco_andes_catalogo"],
  "context_docs": [
    { "file_name": "doc_banco_andes_catalogo", "page_number": null, "snippet": "…" }
  ],
  "reranker_used": false,
  "response_time_sec": 7.3,
  "eval_score": 0.82
}
```

- `respuesta` — lo que responde el modelo.
- `files_consulted` / `context_docs` — de qué documentos salió la respuesta (citas).
- `response_time_sec` — cuánto tardó.
- `eval_score` — solo si envió `evaluate: true`.

```bash
curl -s -X POST http://34.71.149.196:8000/api/v1/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pregunta":"¿Cuáles son los puntos clave?","collection":"finanzas","evaluate":false}'
```

Errores posibles:

| Código | Significado |
|---|---|
| `400` | Pregunta vacía o contenido no permitido (inyección de prompt) |
| `401` | Token ausente, inválido o expirado → vuelva a hacer login |
| `404` | La `collection` no existe / no está disponible |
| `429` | Alcanzó el rate limit (ver sección 6) |

> ⏱️ La **primera** consulta tras reiniciar el servidor puede tardar ~90 s
> (carga el modelo de embeddings). Las siguientes son de segundos.

---

## 5. (Opcional) Preguntar en modo streaming

`POST /api/v1/ask/stream`  · mismo body que `/ask` · también consume cuota.

Devuelve la respuesta en trozos (Server-Sent Events / streaming) en lugar de un
único JSON. Útil si quiere mostrar la respuesta a medida que se genera. Si no lo
necesita, use `/ask`.

---

## 6. Ver su cuota (rate limit)

`GET /api/v1/rate-limit`  · requiere token · **NO consume cuota**

```json
{
  "enabled": true,
  "limits": [
    { "name": "per_minute", "limit": 10,  "used": 3,  "remaining": 7,  "window_seconds": 60,    "reset_seconds": 42 },
    { "name": "quota",      "limit": 100, "used": 12, "remaining": 88, "window_seconds": 86400, "reset_seconds": 51230 }
  ]
}
```

Hay **dos límites simultáneos** y toda consulta debe respetar ambos:

- **`per_minute`** — máximo **10 consultas por minuto** (anti-ráfaga).
- **`quota`** — máximo **100 consultas por día** (ventana de 24 h).

Cuando supera cualquiera de los dos, `/ask` responde **`429 Too Many Requests`**
con un header **`Retry-After: <segundos>`** y un mensaje como:

```
Límite de consultas alcanzado (10 por minuto). Intenta de nuevo en 37s.
```

**Recomendación:** en su agente, si recibe un `429`, espere los segundos que
indica `Retry-After` (o `reset_seconds`) y reintente. No haga ráfagas de
consultas en paralelo.

```bash
curl -s http://34.71.149.196:8000/api/v1/rate-limit \
  -H "Authorization: Bearer $TOKEN"
```

---

## Flujo típico desde su agente

1. `POST /login` una vez → guarde el `access_token`.
2. (Opcional) `GET /collections/` para confirmar el nombre de su colección.
3. `POST /ask` con su `pregunta` y su `collection` → use `respuesta` y
   `files_consulted`.
4. Si recibe `429`, respete `Retry-After` y reintente.
5. (Opcional) `GET /rate-limit` para saber cuánta cuota le queda.

## Lo que NO puede hacer como estudiante

- **Cargar o borrar documentos** — en modo curso la base es compartida y de solo
  lectura; `POST /documents/load-document` responde `403` para estudiantes.
- Endpoints de administración (`/admin/...`) — solo para el equipo del curso.
- Solo se permiten cuentas con dominio `@uniandes.edu.co`.
