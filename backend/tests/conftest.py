"""Configuración común de las pruebas.

Los tests no leen `backend/.env`. En CI ese fichero no existe y `DATABASE_URL` llega
del entorno (el servicio PostgreSQL efímero del workflow); en local sí existe y apunta a
la base real, así que un `pytest` a secas ejecutaba los tests de conectividad contra
ella, y cualquier test que escribiera en «la base configurada» habría escrito allí.

Quitar el `.env` de la lectura hace que local y CI vean los mismos valores por
defecto. Quien quiera probar contra una base concreta sigue pudiendo: exporta
`DATABASE_URL` en el entorno (las variables de entorno no se tocan aquí).
"""

from app.core.config import Settings

Settings.model_config["env_file"] = None
