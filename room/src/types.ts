export type Kind =
  | "stage_start" | "stage_done" | "observation" | "mutation"
  | "finding" | "resolved" | "escalated" | "awaiting_confirm" | "run_done";

export interface LaunchEvent {
  run_id: string;
  seq: number;
  ts: number;
  client: string;
  stage: string;
  kind: Kind;
  human_text: string;
  detail: Record<string, unknown>;
}

/** Fixed order. Chips render greyed at these positions from the first frame and
 *  light up in place - nothing is inserted, so nothing moves and the eye can
 *  track one cell changing. */
export const CHECKS = [
  "spf_single", "spf_lookups", "dkim_present", "dkim_chunking",
  "dmarc_present", "dmarc_policy", "mx_present", "return_path",
  "ns_delegated", "cert_valid", "cert_www", "caa_allows",
  "apex_resolves", "www_redirect", "https_enforced", "ssl_mode",
  "deploy_current", "env_scoped", "env_redeployed", "site_responds",
] as const;

export const CHECK_LABELS: Record<string, string> = {
  spf_single: "One SPF record", spf_lookups: "SPF lookups ≤ 10",
  dkim_present: "DKIM published", dkim_chunking: "DKIM chunking",
  dmarc_present: "DMARC present", dmarc_policy: "DMARC policy",
  mx_present: "MX present", return_path: "Return-path",
  ns_delegated: "Nameservers", cert_valid: "Certificate",
  cert_www: "Certificate (www)", caa_allows: "CAA allows issuer",
  apex_resolves: "Apex resolves", www_redirect: "www → apex",
  https_enforced: "HTTPS enforced", ssl_mode: "SSL mode",
  deploy_current: "Deploy current", env_scoped: "Env scope",
  env_redeployed: "Env applied", site_responds: "Site responds",
};

// `diagnose` is where the agent works out what a failure means. It was missing,
// so the one step that makes this an agent rather than a DNS script never
// appeared in the rail: its events reached the log and nothing else.
export const STAGES = ["deploy", "domain", "dns", "mail", "verify", "diagnose"] as const;
