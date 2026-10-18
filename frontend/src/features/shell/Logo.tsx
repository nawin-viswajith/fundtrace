export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <rect width="32" height="32" fill="var(--accent)" />
      <path d="M7 22 L13 14 L18 18.5 L25 10" stroke="var(--on-accent)" strokeWidth="2.6" fill="none" strokeLinecap="square" strokeLinejoin="miter" />
      <rect x="22.6" y="7.6" width="4.8" height="4.8" fill="var(--on-accent)" />
      <rect x="5" y="20" width="4" height="4" fill="var(--on-accent)" />
    </svg>
  );
}
