/** The Settings tabs, kept apart from the page so the router can check a link's tab without loading it. */
export const SETTINGS_TABS = ["setup", "profile", "mailboxes", "limits", "plan", "team", "integrations", "account"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
