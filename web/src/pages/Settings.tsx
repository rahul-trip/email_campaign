import { useState } from "react";
import { Tabs } from "../components/ui";
import { Campaigns } from "./settings/Campaigns";
import { Limits } from "./settings/Limits";
import { Mailboxes } from "./settings/Mailboxes";
import { Policies } from "./settings/Policies";
import { SenderProfile } from "./settings/SenderProfile";
import { Suppressions } from "./settings/Suppressions";

const TABS = [
  ["sender", "Sender profile"],
  ["workspace", "Limits"],
  ["campaigns", "Campaigns"],
  ["policies", "Country policies"],
  ["suppressions", "Do not contact"],
  ["mailboxes", "Mailboxes"],
] as const;
type Tab = (typeof TABS)[number][0];

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("sender");
  return (
    <Tabs label="Settings" tour="settings-tabs" tabs={TABS} value={tab} onChange={setTab}>
      {tab === "sender" && <SenderProfile />}
      {tab === "workspace" && <Limits />}
      {tab === "campaigns" && <Campaigns />}
      {tab === "policies" && <Policies />}
      {tab === "suppressions" && <Suppressions />}
      {tab === "mailboxes" && <Mailboxes />}
    </Tabs>
  );
}
