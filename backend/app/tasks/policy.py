"""La política de intentos de una tarea: UNA sola definición (M49, Commit 8).

`DEFAULT_MAX_TASK_RETRIES` son los reintentos AUTOMÁTICOS del mismo agente dentro de una ejecución del orquestador
(el intento 1 y dos más). De ahí salen los dos límites que el reintento explícito respeta, sin escribir ningún
número más en otro sitio:

- `MAX_ATTEMPTS_PER_ASSIGNMENT`: los intentos que puede gastar el agente ASIGNADO. Agotados, repetir con él no
  sirve: hay que reasignar (decisión del orquestador o de una persona), y el agente nuevo empieza con sus propios
  intentos.
- `MAX_ATTEMPTS_PER_TASK`: el tope de toda la tarea, pase por los agentes que pase. Alcanzado, el fallo es
  definitivo: ni reintentar ni reasignar lo reabren sin una decisión humana nueva."""

DEFAULT_MAX_TASK_RETRIES = 2

MAX_ATTEMPTS_PER_ASSIGNMENT = DEFAULT_MAX_TASK_RETRIES + 1
MAX_ATTEMPTS_PER_TASK = 2 * MAX_ATTEMPTS_PER_ASSIGNMENT
