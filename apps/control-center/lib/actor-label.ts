// CÓMO SE NOMBRA A UN ACTOR (corrección tras la primera misión real). El backend guarda `actor` (un texto) y, en la auditoría, `actor_source`
// (de dónde salió: `token` verificado, `declared` sin comprobar, `cli`, `system`). Nada de lo que se enseña puede hacer pasar por una
// identidad comprobada a un nombre que nadie ha verificado, ni mostrar una dirección de correo:
//   · `declared` ⇒ «sin autenticar» (el nombre no se enseña: lo escribió quien llamó);
//   · `token` ⇒ «persona autenticada» (la firma del token lo verificó); el correo no se enseña nunca;
//   · sin fuente (filas antiguas, aprobaciones, agentes) ⇒ por el propio texto: el actor local sin autenticar, un correo (se oculta) o el texto.
// Nunca se llama «Propietario», «Owner» ni «Usuario autenticado» a nadie sin que el backend lo diga.

/** El sujeto del actor local en los entornos sin autenticación (`LOCAL_SUBJECT` del backend). No es una identidad real. */
export const LOCAL_ACTOR = "local-development";

export function actorLabel(actor: string | null | undefined, source?: string | null): string {
  const text = typeof actor === "string" ? actor.trim() : "";
  if (text === "") return "Sin actor registrado";
  if (source === "declared") return text === LOCAL_ACTOR ? "Operador local (sin autenticar)" : "Actor sin autenticar";
  if (source === "token") return "Persona autenticada";
  if (text === LOCAL_ACTOR) return "Operador local (sin autenticar)";
  if (text.includes("@")) return "Persona (correo no mostrado)";
  return text;
}
