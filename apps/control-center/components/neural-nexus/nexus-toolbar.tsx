"use client";

import { Crosshair, Maximize2, Minimize2 } from "lucide-react";
import { MODE_LABEL, type GraphMode } from "@/lib/neural-nexus";
import { cn } from "@/lib/utils";

function SegmentedButton({
  active,
  disabled,
  title,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

const MODES: GraphMode[] = ["architecture", "execution", "incidents"];

/** Barra superior del grafo (especificación §21): modos, vista 3D/2D, pantalla
 * completa y reinicio de cámara. */
export function NexusToolbar({
  mode,
  onModeChange,
  view,
  onViewChange,
  view3dDisabled,
  view3dDisabledReason,
  fullscreen,
  onToggleFullscreen,
  onResetCamera,
}: {
  mode: GraphMode;
  onModeChange: (mode: GraphMode) => void;
  view: "3d" | "2d";
  onViewChange: (view: "3d" | "2d") => void;
  view3dDisabled: boolean;
  view3dDisabledReason?: string;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onResetCamera: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div
        className="inline-flex items-center gap-0.5 rounded-lg border bg-muted/40 p-0.5"
        role="group"
        aria-label="Modo de visualización"
      >
        {MODES.map((value) => (
          <SegmentedButton key={value} active={mode === value} onClick={() => onModeChange(value)}>
            {MODE_LABEL[value]}
          </SegmentedButton>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex items-center gap-0.5 rounded-lg border bg-muted/40 p-0.5" role="group" aria-label="Tipo de vista">
          <SegmentedButton
            active={view === "3d"}
            disabled={view3dDisabled}
            title={view3dDisabled ? view3dDisabledReason : undefined}
            onClick={() => onViewChange("3d")}
          >
            Vista 3D
          </SegmentedButton>
          <SegmentedButton active={view === "2d"} onClick={() => onViewChange("2d")}>
            Vista 2D
          </SegmentedButton>
        </div>

        <button
          type="button"
          onClick={onResetCamera}
          disabled={view !== "3d"}
          title="Volver a la vista inicial"
          aria-label="Reiniciar cámara"
          className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-panel-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Crosshair className="size-3.5" />
        </button>

        <button
          type="button"
          onClick={onToggleFullscreen}
          aria-label={fullscreen ? "Salir de pantalla completa" : "Pantalla completa"}
          className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-panel-hover hover:text-foreground"
        >
          {fullscreen ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
        </button>
      </div>
    </div>
  );
}
