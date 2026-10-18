import type { FirebaseWebConfig } from "../../types/api";

/**
 * Google sign-in through Firebase Auth. Returns a Firebase ID token for the backend to verify.
 * The SDK is loaded only when this runs, so password-only deployments never download it.
 * FundTrace keeps its own session cookie; the Firebase session is signed out straight away.
 */
export async function googleIdToken(config: FirebaseWebConfig): Promise<string> {
  const [{ initializeApp, getApps }, auth] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
  const app = getApps().find((a) => a.name === "fundtrace") ?? initializeApp(config, "fundtrace");
  const fa = auth.getAuth(app);
  const provider = new auth.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const cred = await auth.signInWithPopup(fa, provider);
  try {
    return await cred.user.getIdToken();
  } finally {
    await auth.signOut(fa);
  }
}

export function firebaseErrorMessage(e: unknown): string {
  const code = (e as { code?: string })?.code ?? "";
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return "Sign-in was cancelled.";
  if (code === "auth/popup-blocked") return "Your browser blocked the sign-in window. Allow pop-ups for this site and try again.";
  if (code === "auth/unauthorized-domain") return "This site is not an authorised domain in the Firebase project.";
  return "Google sign-in failed. Try again or use your username and password.";
}
