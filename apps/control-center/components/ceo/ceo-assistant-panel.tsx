import { Brain, CircleSlash, MessageSquare, Mic, MicOff, Monitor, Send } from "lucide-react";
import { LevelChip } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { READ_UNAVAILABLE_VALUE } from "@/lib/read-state";

/** El panel del CEO IA (M47, Commit 2): el ESQUELETO visual del mockup —cabecera, pestañas Chat / Voz / Pantalla, controles y caja
 * de mensaje— para validar proporciones, sticky y drawer. TODO lo funcional dice que no está disponible, porque hoy no existe
 * ninguna infraestructura: el backend no tiene un servicio de conversación (el CEO decide con reglas deterministas, sin modelo),
 * ni historial, ni reconocimiento ni síntesis de voz, ni captura de pantalla. Por eso aquí NO hay «Online», ni «Escuchando…»,
 * ni ondas de audio, ni mensajes, ni respuestas, ni historial, ni micrófono activo. Los Commits 7 y posteriores lo sustituirán
 * cuando exista algo real que enseñar. */

export const ASSISTANT_REASONS = {
  chat: "El backend no tiene un servicio de conversación con el CEO: no hay modelo, ni historial, ni contexto de chat. Hoy el CEO decide con reglas deterministas.",
  voice: "No existe infraestructura de voz: ni reconocimiento ni síntesis, ni micrófono conectado a un servicio.",
  screen: "No existe compartir pantalla ni contexto de pantalla.",
} as const;

function Unavailable({ children }: { children: string }) {
  return (
    <div data-assistant-state="unavailable" className="flex items-start gap-2.5 rounded-lg border border-border bg-muted/30 p-3">
      <CircleSlash aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-sm font-medium">{READ_UNAVAILABLE_VALUE}</p>
        <p className="text-xs leading-snug text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}

export function CeoAssistantPanel() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <header className="flex items-center gap-3 pr-8">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10">
          <Brain aria-hidden className="size-5 text-primary" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-heading text-base font-semibold">CEO IA</h2>
          <p className="truncate text-xs text-muted-foreground">Asistente del Director ejecutivo</p>
        </div>
        <LevelChip tone="neutral" className="shrink-0 gap-1">
          <CircleSlash aria-hidden className="size-3" />
          No disponible
        </LevelChip>
      </header>

      <Tabs defaultValue="chat" className="min-h-0 flex-1">
        <TabsList className="w-full">
          <TabsTrigger value="chat" className="flex-1 gap-1.5">
            <MessageSquare aria-hidden className="size-3.5" /> Chat
          </TabsTrigger>
          <TabsTrigger value="voz" className="flex-1 gap-1.5">
            <Mic aria-hidden className="size-3.5" /> Voz
          </TabsTrigger>
          <TabsTrigger value="pantalla" className="flex-1 gap-1.5">
            <Monitor aria-hidden className="size-3.5" /> Pantalla
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="min-h-0 flex-1 overflow-y-auto">
          <Unavailable>{ASSISTANT_REASONS.chat}</Unavailable>
        </TabsContent>

        <TabsContent value="voz" className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex flex-col items-center gap-4 py-2">
            {/* Un micrófono tachado y quieto: ni anillo animado ni ondas, porque no hay audio. */}
            <span className="flex size-24 items-center justify-center rounded-full border border-dashed border-border bg-muted/30">
              <MicOff aria-hidden className="size-9 text-muted-foreground" />
            </span>
            <div className="flex items-center gap-3">
              <Button type="button" variant="outline" size="sm" disabled title={ASSISTANT_REASONS.voice}>
                Cancelar
              </Button>
              <Button type="button" variant="outline" size="sm" disabled title={ASSISTANT_REASONS.voice}>
                Silenciar
              </Button>
            </div>
            <Unavailable>{ASSISTANT_REASONS.voice}</Unavailable>
          </div>
        </TabsContent>

        <TabsContent value="pantalla" className="min-h-0 flex-1 overflow-y-auto">
          <Unavailable>{ASSISTANT_REASONS.screen}</Unavailable>
        </TabsContent>
      </Tabs>

      <div className="flex items-center gap-2">
        <input
          type="text"
          disabled
          aria-label="Mensaje para el CEO IA (no disponible)"
          placeholder="Chat no disponible"
          className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-3 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
        />
        <Button type="button" size="icon" disabled aria-label="Enviar mensaje (no disponible)" title={ASSISTANT_REASONS.chat}>
          <Send aria-hidden />
        </Button>
      </div>
    </div>
  );
}
