/** Banderas simplificadas en SVG (Windows no dibuja los emojis de bandera). */
export type FlagCode = "es" | "eu" | "cn" | "vn" | "mx" | "pl" | "hk" | "fr" | "de" | "it";

const REGION_FLAG: Record<string, FlagCode> = { china: "cn", vietnam: "vn", mexico: "mx", eu: "eu" };

export function regionFlag(region: string | null | undefined): FlagCode | undefined {
  return region ? REGION_FLAG[region] : undefined;
}

export function Flag({ code, className }: { code: FlagCode; className?: string }) {
  return (
    <svg viewBox="0 0 30 20" className={className ?? "h-3.5 w-5 shrink-0 rounded-[2px]"} aria-hidden>
      {code === "es" ? (
        <>
          <rect width="30" height="20" fill="#c60b1e" />
          <rect y="5" width="30" height="10" fill="#ffc400" />
        </>
      ) : code === "eu" ? (
        <>
          <rect width="30" height="20" fill="#003399" />
          {Array.from({ length: 12 }, (_, k) => {
            const a = (k / 12) * 2 * Math.PI;
            return <circle key={k} cx={(15 + 6 * Math.sin(a)).toFixed(2)} cy={(10 - 6 * Math.cos(a)).toFixed(2)} r="0.9" fill="#ffcc00" />;
          })}
        </>
      ) : code === "cn" ? (
        <>
          <rect width="30" height="20" fill="#de2910" />
          <polygon points="5,2.5 5.9,5.2 8.7,5.2 6.4,6.9 7.3,9.6 5,7.9 2.7,9.6 3.6,6.9 1.3,5.2 4.1,5.2" fill="#ffde00" />
        </>
      ) : code === "vn" ? (
        <>
          <rect width="30" height="20" fill="#da251d" />
          <polygon points="15,4 16.4,8.3 20.9,8.3 17.3,11 18.7,15.3 15,12.6 11.3,15.3 12.7,11 9.1,8.3 13.6,8.3" fill="#ffff00" />
        </>
      ) : code === "pl" ? (
        <>
          <rect width="30" height="20" fill="#fff" />
          <rect y="10" width="30" height="10" fill="#dc143c" />
        </>
      ) : code === "fr" || code === "it" ? (
        <>
          <rect width="10" height="20" fill={code === "fr" ? "#002395" : "#009246"} />
          <rect x="10" width="10" height="20" fill="#fff" />
          <rect x="20" width="10" height="20" fill={code === "fr" ? "#ed2939" : "#ce2b37"} />
        </>
      ) : code === "de" ? (
        <>
          <rect width="30" height="7" fill="#000" />
          <rect y="6.67" width="30" height="6.67" fill="#dd0000" />
          <rect y="13.33" width="30" height="6.67" fill="#ffce00" />
        </>
      ) : code === "hk" ? (
        <>
          <rect width="30" height="20" fill="#de2910" />
          <circle cx="15" cy="10" r="4.5" fill="#fff" />
          <circle cx="15" cy="10" r="1.6" fill="#de2910" />
        </>
      ) : (
        <>
          <rect width="30" height="20" fill="#fff" />
          <rect width="10" height="20" fill="#006847" />
          <rect x="20" width="10" height="20" fill="#ce1126" />
        </>
      )}
    </svg>
  );
}
