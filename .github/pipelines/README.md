# Pipelines del curso

Aquí están los cinco pipelines de verificación, uno por semana. **Los archivos
de esta carpeta están inactivos**: GitHub solo ejecuta lo que esté dentro de
`.github/workflows/`.

## Cómo activar el pipeline de la semana

Copie el de la semana en curso sobre `.github/workflows/entrega.yml`,
**sobrescribiendo** el anterior:

```bash
cp .github/pipelines/semana2.yml .github/workflows/entrega.yml
git add .github/workflows/entrega.yml
git commit -m "Activar pipeline de la semana 2"
git push
```

En `.github/workflows/` debe haber **siempre un solo archivo**: `entrega.yml`.
Si acumula varios, cada push ejecuta todos a la vez y consume la cuota de
GitHub Actions del curso, que es compartida entre los 50 grupos.

La semana 1 ya viene activada.

## Qué verifica cada semana

| Semana | Verifica | Requiere secrets |
| :--- | :--- | :--- |
| 1 | El CLI arranca, la configuración carga, `.env` no está subido | No |
| 2 | ≥3 herramientas con descripción, el grafo compila, el servidor MCP expone tools | No |
| 3 | Credencial de LangSmith válida e instrumentación propia con `@traceable` | Sí |
| 4 | El checkpointer persiste en disco y aísla `thread_id` | No |
| 5 | El grafo de razonamiento compila y tiene red de seguridad | No |

Cada semana incluye además las verificaciones de las anteriores, para detectar
regresiones. La semana 3 queda fuera de esas regresiones porque depende de un
servicio externo.

## Qué NO verifican

Estos pipelines comprueban que el proyecto **avanza**: que las piezas de la
semana existen, se construyen y tienen la forma esperada. No evalúan la calidad
de las respuestas del agente ni si resuelve bien el caso de negocio — eso se
sustenta en los videos y en las entregas 1, 2 y 3.

Por eso ninguna prueba invoca al LLM, ni a la API empresarial, ni descarga
modelos: una corrida así tarda minutos, gasta la cuota del curso y falla por
causas ajenas a su implementación.

## Correr las mismas pruebas en local

Antes de hacer push, con el entorno activado:

```bash
pytest -m semana1     # o semana2, semana3, ...
```

Es idéntico a lo que corre el pipeline, y no gasta minutos de Actions.

## Cómo conecta el pipeline con su código

El pipeline no conoce la arquitectura de su agente: solo importa las funciones
de [`contract.py`](../../contract.py). Organicen el código como prefieran y
reexporten desde ahí.
