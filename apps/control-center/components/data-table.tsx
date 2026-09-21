"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { downloadCsv, toCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Si existe, la columna es ordenable por este valor. */
  sortValue?: (row: T) => number | string;
  /** Si existe, la columna entra en la exportación CSV. Las columnas de
   * acciones (botones) no lo definen y quedan fuera. */
  exportValue?: (row: T) => string | number;
  align?: "left" | "right";
}

type SortState = { key: string; direction: "asc" | "desc" } | null;

/** Tabla con búsqueda, orden, selección de fila y exportación CSV, todo en el
 * cliente sobre las filas que ya trajo el backend (catálogo compartido, §4).
 * No pagina: los paneles que la usan hoy manejan como mucho unas decenas de
 * filas reales — paginar sin necesidad sería ruido. */
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  selectedId,
  onSelect,
  getSearchText,
  searchPlaceholder = "Buscar…",
  exportFileName,
  emptyMessage = "Sin resultados.",
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  selectedId?: string | null;
  onSelect?: (row: T) => void;
  getSearchText?: (row: T) => string;
  searchPlaceholder?: string;
  /** Con nombre de fichero se muestra el botón Exportar. */
  exportFileName?: string;
  emptyMessage?: string;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>(null);

  const visibleRows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    let result = normalized && getSearchText ? rows.filter((r) => getSearchText(r).toLowerCase().includes(normalized)) : rows;
    if (sort) {
      const column = columns.find((c) => c.key === sort.key);
      if (column?.sortValue) {
        const value = column.sortValue;
        const factor = sort.direction === "asc" ? 1 : -1;
        result = [...result].sort((a, b) => {
          const va = value(a);
          const vb = value(b);
          if (typeof va === "number" && typeof vb === "number") return (va - vb) * factor;
          return String(va).localeCompare(String(vb), "es") * factor;
        });
      }
    }
    return result;
  }, [rows, query, sort, columns, getSearchText]);

  function toggleSort(key: string) {
    setSort((current) => {
      if (!current || current.key !== key) return { key, direction: "asc" };
      if (current.direction === "asc") return { key, direction: "desc" };
      return null;
    });
  }

  function exportCsv() {
    if (!exportFileName) return;
    const exportable = columns.filter((c) => c.exportValue);
    const csv = toCsv(
      exportable.map((c) => c.header),
      visibleRows.map((row) => exportable.map((c) => c.exportValue!(row))),
    );
    downloadCsv(exportFileName, csv);
  }

  return (
    <div className="space-y-3">
      {getSearchText || exportFileName ? (
        <div className="flex items-center justify-between gap-3">
          {getSearchText ? (
            <label className="relative block min-w-0 max-w-xs flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="w-full rounded-md border bg-background py-1.5 pr-3 pl-9 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </label>
          ) : (
            <span />
          )}
          {exportFileName ? (
            <Button size="sm" variant="outline" onClick={exportCsv} disabled={visibleRows.length === 0}>
              <Download className="size-3.5" />
              Exportar CSV
            </Button>
          ) : null}
        </div>
      ) : null}

      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => {
              const sorted = sort?.key === column.key ? sort.direction : null;
              const SortIcon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
              return (
                <TableHead
                  key={column.key}
                  className={cn("whitespace-nowrap", column.align === "right" && "text-right")}
                  aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={cn(
                        "inline-flex items-center gap-1 hover:text-foreground",
                        column.align === "right" && "flex-row-reverse",
                      )}
                    >
                      {column.header}
                      <SortIcon className={cn("size-3", sorted ? "text-primary" : "opacity-40")} />
                    </button>
                  ) : (
                    column.header
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleRows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="py-8 text-center text-sm text-muted-foreground">
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            visibleRows.map((row) => {
              const id = getRowId(row);
              const selected = selectedId === id;
              return (
                <TableRow
                  key={id}
                  data-state={selected ? "selected" : undefined}
                  onClick={onSelect ? () => onSelect(row) : undefined}
                  className={cn(onSelect && "cursor-pointer", selected && "bg-primary/10 hover:bg-primary/10")}
                >
                  {columns.map((column) => (
                    <TableCell key={column.key} className={cn(column.align === "right" && "text-right")}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      <p className="text-xs text-muted-foreground">
        Mostrando {visibleRows.length} de {rows.length} resultado{rows.length === 1 ? "" : "s"}
      </p>
    </div>
  );
}
