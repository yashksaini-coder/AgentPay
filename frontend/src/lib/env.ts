/** Returns true when NEXT_PUBLIC_API_URL points to a remote (non-localhost) backend. */
export function isRemoteBackend(): boolean {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (!env) return false;
  return !env.includes("127.0.0.1") && !env.includes("localhost") && !env.startsWith("/");
}

/** Returns the base API URL for the primary backend. */
export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080";
}
