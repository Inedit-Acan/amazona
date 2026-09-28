"""Qué nombres distintos designan al mismo proveedor, dicho a mano (Milestone 39).

Mismo principio que el catálogo de productos del Milestone 36: **cada entrada es
una afirmación**, escrita por una persona, con autor y fecha en git, discutible
en una revisión. Identidad declarada, nunca inferida por parecido. Un umbral de
similitud uniría algún día «Shenzhen Volta Electronics» con «Shenzhen Volt
Electronics» y nadie sabría qué día empezó a hacerlo.

## Qué entra aquí

Formas del mismo nombre que la normalización no puede unir sola: la razón social
frente al nombre comercial, una transliteración, una abreviatura de uso corriente.
La clave es el nombre **ya normalizado** (`app.core.text.fold`); el valor, la
forma canónica.

## Qué NO entra

- **Grupos empresariales.** Una filial no es su matriz. Unirlas escondería que
  el riesgo de dependencia está concentrado, que es justo lo que §11 quiere ver.
- **Nombres de fantasía sin comprobar.** Si nadie ha verificado que dos nombres
  son la misma empresa, se quedan separados. Dos proveedores que eran uno son un
  duplicado visible; uno que eran dos es una decisión de compra tomada sobre una
  empresa que no existe.

Empieza vacío a propósito. No hay hoy ni un solo par de nombres del que se pueda
afirmar esto, y rellenarlo con ejemplos del mock crearía equivalencias entre
empresas inventadas.
"""

#: Versión del catálogo. Viaja en el motivo de cada fusión (`alias:v1`) para que
#: una identidad resuelta hoy se pueda atribuir a la lista que había hoy.
CATALOGUE_VERSION = "v1"

#: nombre normalizado -> forma canónica.
SUPPLIER_ALIASES: dict[str, str] = {}
