export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path d="M7 22 L13 14 L18 18.5 L25 10" stroke="var(--on-accent)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25" cy="10" r="2.4" fill="var(--on-accent)" />
      <circle cx="7" cy="22" r="2" fill="var(--on-accent)" />
    </svg>
  );
}
