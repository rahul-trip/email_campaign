/** Settings → Team (who works in this workspace) and Your account (password, sessions). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { useCurrent, useIsAdmin } from "../app/session";
import { Avatar, Button, Callout, Card, Confirm, Field, Input, Problem, QueryState, SaveNote, Select, Table, Td, Th } from "../components/ui";
import { ago, when } from "../lib/format";

type Role = "admin" | "member";
type TeamOut = Schemas["TeamOut"];
const ROLE_HINT: Record<Role, string> = {
  admin: "Everything, including the team, compliance and settings",
  member: "Day-to-day work: leads, runs, review, campaigns",
};

export function Team() {
  const admin = useIsAdmin();
  const queryClient = useQueryClient();
  const team = useQuery({ queryKey: ["team"], queryFn: () => ok(client.GET("/api/team")) });
  const update = (data: TeamOut) => queryClient.setQueryData(["team"], data);
  return (
    <div className="space-y-4">
      {admin ? <Invite onDone={update} /> : <Callout>Only admins invite people and change roles. Ask one of the admins below.</Callout>}
      <QueryState query={team}>{(data) => <Members team={data} admin={admin} onChange={update} />}</QueryState>
    </div>
  );
}

function Invite({ onDone }: { onDone: (team: TeamOut) => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const invite = useMutation({
    mutationFn: () => ok(client.POST("/api/team/invitations", { body: { email: email.trim(), role } })),
    onSuccess: (team) => {
      onDone(team);
      setEmail("");
    },
  });
  return (
    <Card tour="team-invite" title="Invite someone" subtitle="They get an email with a link that works once, for 7 days, to choose a password and join.">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          invite.mutate();
        }}
      >
        <Field label="Email" className="min-w-[240px] flex-1">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@yourcompany.com" className="w-full" />
        </Field>
        <Field label="Role" hint={ROLE_HINT[role]}>
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </Select>
        </Field>
        <Button type="submit" busy={invite.isPending} disabled={!email.includes("@")}>
          Send invitation
        </Button>
      </form>
      <div className="mt-2">
        <SaveNote mutation={invite} done="Invitation sent." />
      </div>
    </Card>
  );
}

function Members({ team, admin, onChange }: { team: TeamOut; admin: boolean; onChange: (team: TeamOut) => void }) {
  const { me } = useCurrent();
  const [removing, setRemoving] = useState<Schemas["MemberOut"] | null>(null);
  const role = useMutation({
    mutationFn: ({ userId, next }: { userId: string; next: Role }) => ok(client.PATCH("/api/team/members/{user_id}", { params: { path: { user_id: userId } }, body: { role: next } })),
    onSuccess: onChange,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => ok(client.DELETE("/api/team/members/{user_id}", { params: { path: { user_id: userId } } })),
    onSuccess: (data) => {
      onChange(data);
      setRemoving(null);
    },
  });
  const resend = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/team/invitations/{invitation_id}/resend", { params: { path: { invitation_id: id } } })),
    onSuccess: onChange,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => ok(client.DELETE("/api/team/invitations/{invitation_id}", { params: { path: { invitation_id: id } } })),
    onSuccess: onChange,
  });
  return (
    <>
      <Card tour="team-members" title="Members" subtitle={`${team.members.length} ${team.members.length === 1 ? "person" : "people"}. A workspace always keeps at least one admin.`}>
        <Problem error={role.error ?? resend.error ?? revoke.error} className="mb-3" />
        <Table>
          <thead>
            <tr>
              <Th>Person</Th>
              <Th>Role</Th>
              <Th>Last signed in</Th>
              {admin && <Th />}
            </tr>
          </thead>
          <tbody>
            {team.members.map((member) => {
              const you = member.user_id === me.user.id;
              return (
                <tr key={member.user_id}>
                  <Td>
                    <span className="flex items-center gap-2">
                      <Avatar name={member.name || member.email} />
                      <span>
                        <span className="block font-medium">
                          {member.name || member.email}
                          {you && <span className="ml-1 text-[11px] text-muted">(you)</span>}
                        </span>
                        {member.name && <span className="block text-[11px] text-muted">{member.email}</span>}
                      </span>
                    </span>
                  </Td>
                  <Td>
                    {admin ? (
                      <Select aria-label={`Role of ${member.email}`} value={member.role} disabled={role.isPending} onChange={(e) => role.mutate({ userId: member.user_id, next: e.target.value as Role })}>
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </Select>
                    ) : (
                      <span className="capitalize">{member.role}</span>
                    )}
                  </Td>
                  <Td className="text-muted">{member.last_login_at ? <span title={when(member.last_login_at)}>{ago(member.last_login_at)}</span> : "Never"}</Td>
                  {admin && (
                    <Td className="text-right">
                      <Button size="sm" variant="danger-ghost" onClick={() => setRemoving(member)}>
                        {you ? "Leave" : "Remove"}
                      </Button>
                    </Td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>
      {team.invitations.length > 0 && (
        <Card title="Waiting to join" subtitle="Invitations not used yet. Sending again makes a new link; the old one stops working.">
          <Table>
            <thead>
              <tr>
                <Th>Email</Th>
                <Th>Role</Th>
                <Th>Link works until</Th>
                {admin && <Th />}
              </tr>
            </thead>
            <tbody>
              {team.invitations.map((invitation) => (
                <tr key={invitation.id}>
                  <Td>{invitation.email}</Td>
                  <Td className="capitalize">{invitation.role}</Td>
                  <Td className="text-muted">{when(invitation.expires_at)}</Td>
                  {admin && (
                    <Td className="space-x-1 text-right">
                      <Button size="sm" variant="ghost" busy={resend.isPending && resend.variables === invitation.id} onClick={() => resend.mutate(invitation.id)}>
                        Send again
                      </Button>
                      <Button size="sm" variant="danger-ghost" onClick={() => revoke.mutate(invitation.id)}>
                        Withdraw
                      </Button>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {removing && (
        <Confirm
          title={removing.user_id === me.user.id ? "Leave this workspace?" : `Remove ${removing.name || removing.email}?`}
          confirmLabel={removing.user_id === me.user.id ? "Leave" : "Remove"}
          busy={remove.isPending}
          error={remove.error}
          onClose={() => setRemoving(null)}
          onConfirm={() => remove.mutate(removing.user_id)}
        >
          They lose access to this workspace at once. Their leads, reviews and history stay. They can be invited again later.
        </Confirm>
      )}
    </>
  );
}

// ------------------------------------------------------------------ your account

export function Account() {
  const { me } = useCurrent();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/password/change", { body: { current_password: current, new_password: next } })).then(() => undefined),
    onSuccess: () => {
      setCurrent("");
      setNext("");
    },
  });
  const others = useMutation({ mutationFn: () => ok(client.POST("/api/auth/logout-others")) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card tour="account-password" title="Password" subtitle={`You sign in as ${me.user.email}.`}>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            change.mutate();
          }}
        >
          <Field label="Current password">
            <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className="w-full" />
          </Field>
          <Field label="New password" hint="At least 15 characters. A few ordinary words in a row make a good one.">
            <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className="w-full" />
          </Field>
          <div className="flex items-center gap-3">
            <Button type="submit" busy={change.isPending} disabled={!current || next.length < 15}>
              Change password
            </Button>
            <SaveNote mutation={change} done="Changed. Other devices are signed out." />
          </div>
        </form>
      </Card>
      <Card title="Where you are signed in" subtitle="Sign out every other browser and device, for example after using a shared computer.">
        <div className="flex items-center gap-3">
          <Button variant="secondary" busy={others.isPending} onClick={() => others.mutate()}>
            Sign out everywhere else
          </Button>
          {others.isSuccess && <span className="text-xs text-muted">Signed out of {others.data.signed_out} other session(s).</span>}
        </div>
        <Problem error={others.error} className="mt-2" />
      </Card>
    </div>
  );
}
