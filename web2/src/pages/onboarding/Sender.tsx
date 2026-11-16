/** Step 2: who signs, and the legal lines every footer prints. */
import { useEffect, useRef } from "react";
import { useCurrent } from "../../app/session";
import { Button, Card, Problem, QueryState } from "../../components/ui";
import { FooterPreview, LegalFields, OutreachGoal, SignatureFields, useSenderProfile } from "../SenderProfileParts";

export function Sender({ onNext }: { onNext: () => void }) {
  const p = useSenderProfile();
  const { me } = useCurrent();
  const prefilled = useRef(false);
  const loaded = p.query.data as Record<string, unknown> | undefined;
  // Blank fields only: the person's account name and the company name are good first guesses.
  useEffect(() => {
    if (!loaded || prefilled.current) return;
    prefilled.current = true;
    p.setDraft((old) => ({
      ...old,
      ...(!String(old.signature_name ?? "").trim() && me.user.name ? { signature_name: me.user.name } : {}),
      ...(!String(old.legal_name ?? "").trim() && old.company_name ? { legal_name: old.company_name } : {}),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);
  return (
    <QueryState query={p.query} rows={6}>
      {() => (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-4">
            <SignatureFields p={p} />
            <OutreachGoal p={p} />
            <Card title="Legal lines" subtitle="Printed in the footer the law of each country requires.">
              <LegalFields p={p} />
            </Card>
            <div className="flex flex-wrap items-center gap-3">
              <Button busy={p.save.isPending} onClick={() => p.save.mutate(undefined, { onSuccess: onNext })}>
                Confirm and continue
              </Button>
              <span className="text-xs text-muted">Greeting and examples of your own emails are under Settings → Sender profile.</span>
            </div>
            <Problem error={p.save.error} />
          </div>
          <FooterPreview profile={p.draft} />
        </div>
      )}
    </QueryState>
  );
}
