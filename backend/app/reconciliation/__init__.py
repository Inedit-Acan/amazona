"""Reconciliación programada (Milestone 45, ADR 0029): quién mira lo que puede bloquear un pedido cuando nadie está
mirando.

- `actions`: el barrido de acciones externas abandonadas (`PENDING` que nunca salió → liberada; `CALLING` abandonada
→ `UNKNOWN_OUTCOME`).
- `events`: reanudar los eventos de pago `RECEIVED`, con un tope de intentos que no inventa estados, y `retry_event`
(la salida humana).
- `report`: el estado de solo lectura (lo desconocido, los eventos topados, cuándo corrió cada trabajo).
- `config_check`: la validación de arranque del techo de una llamada externa.

Nada de esto ejecuta efectos externos: no llama a `execute`, no repite peticiones y no cierra un `UNKNOWN_OUTCOME`.
"""
