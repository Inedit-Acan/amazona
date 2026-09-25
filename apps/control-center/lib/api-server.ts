import "server-only";

import { setAccessTokenResolver } from "./api";
import { getServerAccessToken } from "./auth-server";

// Al importar este módulo, las llamadas de `api` hechas en servidor pasan a
// leer el token de las cookies de la petición en vez de buscarlo en una sesión
// de navegador que ahí no existe (Milestone 29.1).
//
// Por eso TODA página renderizada en servidor debe importar `api` desde aquí y
// no desde "@/lib/api": si lo hace del sitio equivocado, sus peticiones salen
// sin `Authorization` y el backend las rechazará en staging/production. Hay un
// test que lo comprueba (`lib/server-api-boundary.test.ts`), porque es un fallo
// silencioso en desarrollo y ruidoso solo en producción.
setAccessTokenResolver(getServerAccessToken);

export * from "./api";
