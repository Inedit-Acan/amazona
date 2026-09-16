"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { getCurrentEmail, isAuthConfigured, signOut } from "@/lib/auth";
import { Button } from "@/components/ui/button";

export function SessionBadge() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(() => !isAuthConfigured);

  useEffect(() => {
    if (!isAuthConfigured) return;
    getCurrentEmail().then((value) => {
      setEmail(value);
      setLoaded(true);
    });
  }, []);

  if (!isAuthConfigured || !loaded) return null;

  if (!email) {
    return (
      <Link href="/login" className="text-xs text-muted-foreground underline-offset-4 hover:underline">
        Sign in
      </Link>
    );
  }

  async function handleSignOut() {
    await signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="truncate">{email}</span>
      <Button variant="ghost" size="icon-xs" aria-label="Sign out" onClick={handleSignOut}>
        <LogOut className="size-3.5" />
      </Button>
    </div>
  );
}
