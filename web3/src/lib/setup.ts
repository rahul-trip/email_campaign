import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { client, ok, type Schemas } from "../api/client";

export type SetupItem = Schemas["SetupItemOut"];

/** What the workspace still has to set up, from the server (the same list everywhere). */
export const useSetup = () => useQuery({ queryKey: ["setup"], queryFn: () => ok(client.GET("/api/setup")) });

/** The workspace has no active campaign that says who it reaches: nothing else works yet. */
export const useNeedsCampaign = (): boolean => {
  const setup = useSetup();
  return setup.data?.items.some((i) => i.key === "campaign" && i.status === "missing") ?? false;
};

/** Open the page an item says to fix it on. */
export function useOpen() {
  const navigate = useNavigate();
  return (where: string) => {
    if (where.startsWith("settings:")) void navigate({ to: "/settings", search: { tab: where.slice(9) as "profile" | "mailboxes" } });
    else void navigate({ to: where === "campaigns" ? "/campaigns" : where === "compliance" ? "/compliance" : "/targets" });
  };
}

