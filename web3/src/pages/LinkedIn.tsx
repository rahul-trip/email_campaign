import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { client, ok } from "../api/client";
import { LinkedInDraftCard } from "../components/LinkedInDraft";
import { Card, Empty, PageHeader, QueryState, Segmented } from "../ui/compat";
import { isViewing, useCurrent } from "../app/session";

type State = "drafted" | "sent" | "skipped";

/** Every LinkedIn message written for the workspace's confirmed people, to work through in one sitting. */
export function LinkedInPage() {
  const { workspace } = useCurrent();
  const queryClient = useQueryClient();
  const [state, setState] = useState<State>("drafted");
  const list = useQuery({
    queryKey: ["linkedin", state],
    queryFn: () => ok(client.GET("/api/linkedin", { params: { query: { state, limit: 100 } } })),
  });
  const refresh = () => {
    for (const key of ["linkedin", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  return (
    <>
      <PageHeader
        title="LinkedIn"
        subtitle="A connection note and a first message for each confirmed decision-maker, written before their email is found. Copy them into LinkedIn yourself: nothing is sent from here."
      />
      <div className="mb-5" data-tour="linkedin-filter">
        <Segmented
          label="Show"
          value={state}
          onChange={setState}
          options={[
            ["drafted", "To send"],
            ["sent", "Sent"],
            ["skipped", "Skipped"],
          ]}
        />
      </div>
      <QueryState query={list} rows={4}>
        {(page) =>
          page.items.length === 0 ? (
            <Card>
              <Empty title={state === "drafted" ? "Nothing to send yet" : "Nothing here"}>
                {state === "drafted" ? "Messages are written when a lead's people are found and a person with a LinkedIn profile is a confirmed decision-maker." : "Messages you mark here will be listed."}
              </Empty>
            </Card>
          ) : (
            <div className="space-y-4" data-tour="linkedin-list">
              {page.items.map((row) => (
                <Card
                  key={row.item.id}
                  title={
                    <Link to="/leads/$companyId" params={{ companyId: row.item.company_id }} className="hover:underline">
                      {row.company_name ?? row.domain}
                    </Link>
                  }
                  subtitle={row.title ?? undefined}
                >
                  <LinkedInDraftCard draft={row.item} person={row.person} profile={row.profile} readOnly={isViewing(workspace)} onChanged={refresh} />
                </Card>
              ))}
              {page.total > page.items.length && <p className="text-small text-muted">Showing the newest {page.items.length} of {page.total}.</p>}
            </div>
          )
        }
      </QueryState>
    </>
  );
}
