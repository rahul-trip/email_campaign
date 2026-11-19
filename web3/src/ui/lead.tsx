/** Pieces about a lead that more than one screen shows: the fit breakdown and email status. */
import { Check, HelpCircle, X } from "lucide-react";
import { useState } from "react";
import type { Schemas } from "../api/client";
import { cx } from "../lib/cx";
import { describe, emailStatus, isSafeToSend } from "../lib/status";
import { Avatar, Chip } from "./core";

/**
 * A lead's website icon, from DuckDuckGo's icon service (no cookies; the server's content policy
 * allows only that host). Only a plain domain is asked for; anything else, or an icon that does
 * not load, shows the lead's initials instead.
 */
export function LeadIcon({ domain, name, className, size = "md" }: { domain: string; name: string; className?: string; size?: "md" | "lg" }) {
  const [failed, setFailed] = useState(false);
  const plain = /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(domain) ? domain.toLowerCase() : null;
  const big = size === "lg"; // "lg" is for a page's own header; "md" is for rows and cards
  if (!plain || failed) return <Avatar name={name} className={cx(big && "size-12 text-heading", className)} />;
  return (
    <span aria-hidden data-lead-logo className={cx("inline-flex shrink-0 items-center justify-center overflow-hidden border border-line bg-surface", big ? "size-12 rounded-2xl" : "size-9 rounded-xl", className)}>
      <img src={`https://icons.duckduckgo.com/ip3/${plain}.ico`} alt="" width={big ? 28 : 20} height={big ? 28 : 20} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} className={big ? "size-7" : "size-5"} />
    </span>
  );
}

export type Criterion = { id: string; kind: string; criterion: string; weight: number; verdict: string; evidence?: string; source?: string };
export type QualificationData = { score?: number; reason?: string; ruled_out?: boolean; criteria?: Criterion[]; why_now?: string; risks?: string[] };

const KIND: Record<string, string> = { must_have: "Must-haves", signal: "Signs they may buy now", disqualifier: "Rule-outs" };
const ORDER = ["must_have", "signal", "disqualifier"];

/** research.qualification, if research judged the brief's criteria (outbound/domain/qualification.py). */
export const qualificationOf = (company: Schemas["CompanyOut"]): QualificationData | undefined =>
  ((company.research ?? {}) as { qualification?: QualificationData }).qualification;

/** Score points as the server counts them: must-haves up to 80, signals up to 20, a met rule-out gives 0. */
export function FitBreakdown({ data, compact }: { data: QualificationData; compact?: boolean }) {
  const criteria = data.criteria ?? [];
  if (!criteria.length) return null;
  return (
    <div className="space-y-4">
      {ORDER.map((kind) => {
        const items = criteria.filter((c) => c.kind === kind);
        if (!items.length) return null;
        return (
          <div key={kind}>
            <div className="mb-1.5 text-label font-semibold tracking-wide text-faint uppercase">{KIND[kind]}</div>
            <ul className="space-y-2">
              {items.map((c) => {
                // For a rule-out, "met" is the bad outcome.
                const good = kind === "disqualifier" ? c.verdict === "not_met" : c.verdict === "met";
                const bad = kind === "disqualifier" ? c.verdict === "met" : c.verdict === "not_met";
                const Icon = good ? Check : bad ? X : HelpCircle;
                return (
                  <li key={c.id} className="flex gap-2.5">
                    <span className={cx("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full", good ? "bg-good-soft text-good" : bad ? "bg-error-soft text-error" : "bg-surface-3 text-muted")}>
                      <Icon className="size-3.5" aria-label={good ? "Good" : bad ? "Bad" : "Not known"} />
                    </span>
                    <div className="min-w-0">
                      <div className="text-body text-ink">
                        {c.criterion}
                        {c.weight > 1 && kind === "must_have" && <span className="ml-1.5 text-label text-faint">×{c.weight}</span>}
                      </div>
                      {!compact && c.evidence && (
                        <div className="text-small text-muted">
                          “{c.evidence}”
                          {c.source && (
                            <>
                              {" "}
                              <a href={c.source} target="_blank" rel="noreferrer" className="font-medium text-primary hover:underline">
                                source
                              </a>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {data.ruled_out && <Chip tone="error">A rule-out is met, so the score is 0</Chip>}
    </div>
  );
}

export function EmailChip({ address }: { address?: Schemas["EmailOut"] }) {
  if (!address) return <Chip tone="stopped">No address</Chip>;
  const info = describe(emailStatus, address.status);
  return (
    <Chip tone={info.family} dot title={isSafeToSend(address.status, address.verification_skipped) ? "Safe to send" : "Not safe to send"}>
      {info.label}
    </Chip>
  );
}
