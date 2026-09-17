"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, LayoutDashboard } from "lucide-react";
import { NAV_ITEMS } from "@/components/nav-items";
import { SessionBadge } from "@/components/session-badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground shadow-[0_0_14px_-3px_var(--emerald)]"
                : "text-muted-foreground hover:bg-panel-hover hover:text-foreground",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex min-h-screen w-full flex-col md:flex-row">
      <aside className="hidden w-56 shrink-0 border-r bg-card px-3 py-6 md:flex md:flex-col">
        <div className="mb-6 flex items-center gap-2 px-2">
          <LayoutDashboard className="size-5 text-primary drop-shadow-[0_0_6px_var(--emerald)]" />
          <span className="text-sm font-semibold tracking-tight">AMAZONA</span>
        </div>
        <NavLinks />
        <div className="mt-auto px-2 pt-4">
          <SessionBadge />
        </div>
      </aside>

      <header className="flex items-center justify-between border-b bg-card px-4 py-3 md:hidden">
        <div className="flex items-center gap-2">
          <LayoutDashboard className="size-5 text-primary drop-shadow-[0_0_6px_var(--emerald)]" />
          <span className="text-sm font-semibold tracking-tight">AMAZONA</span>
        </div>
        <div className="flex items-center gap-3">
          <SessionBadge />
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger render={<Button variant="ghost" size="icon" aria-label="Open navigation" />}>
              <Menu className="size-5" />
            </SheetTrigger>
            <SheetContent side="left" className="w-64 px-3 py-6">
              <SheetTitle className="mb-6 px-2 text-sm font-semibold tracking-tight">AMAZONA</SheetTitle>
              <NavLinks onNavigate={() => setOpen(false)} />
            </SheetContent>
          </Sheet>
        </div>
      </header>

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
