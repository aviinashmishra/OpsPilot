"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus, Users } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useRoles, useUsers } from "@/lib/queries";
import { useSession } from "@/lib/session";
import type { RoleOut, UserIn, UserOut, UserUpdateIn } from "@/lib/types";

function RoleChecklist({ roles, selected, onChange, disabled }: { roles: RoleOut[]; selected: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  return (
    <fieldset className="grid gap-1.5 sm:grid-cols-2">
      <legend className="mb-1 text-xs font-medium text-fg-muted">Roles</legend>
      {roles.map((role) => {
        const checked = selected.includes(role.name);
        return (
          <label key={role.id} className="flex cursor-pointer items-start gap-2 rounded-md border border-border bg-surface-2/50 px-2.5 py-2 text-sm hover:border-border-strong">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[hsl(var(--accent))]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked ? [...selected, role.name] : selected.filter((r) => r !== role.name))} />
            <span className="min-w-0">
              <span className="block font-medium text-fg">{role.name}</span>
              {role.description ? <span className="block text-xs text-fg-muted">{role.description}</span> : null}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function UsersTab() {
  const users = useUsers();
  const roles = useRoles();
  const canAdmin = usePermission("users:admin");
  const me = useSession((s) => s.user);
  const queryClient = useQueryClient();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserUpdateIn }) => api<UserOut>(`/admin/users/${id}`, { method: "PATCH", body }),
    onSuccess: (user) => {
      toast.success("User updated", { description: user.email });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      setEditing(null);
    },
    onError: (error) => toast.error("Could not update user", { description: errorMessage(error) }),
  });

  if (users.isError) return <ErrorState error={users.error} onRetry={() => users.refetch()} />;
  if (users.isLoading) return <SkeletonRows rows={6} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">{users.data?.length ?? 0} users in this tenant.</p>
        <Button variant="primary" size="sm" onClick={() => setInviteOpen(true)} disabled={!canAdmin} leftIcon={<UserPlus className="h-4 w-4" aria-hidden />}>
          Invite user
        </Button>
      </div>
      {users.data && users.data.length === 0 ? (
        <EmptyState icon={Users} title="No users" />
      ) : (
        <TableWrap>
          <Table className="min-w-[720px]">
            <THead>
              <TR>
                <TH>User</TH>
                <TH>Roles</TH>
                <TH>Status</TH>
                <TH align="center">Active</TH>
                <TH align="right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {(users.data ?? []).map((user) => {
                const isMe = me?.id === user.id;
                return (
                  <TR key={user.id}>
                    <TD>
                      <span className="font-medium text-fg">
                        {user.full_name}
                        {isMe ? <Badge size="sm" tone="accent" className="ml-2">you</Badge> : null}
                      </span>
                      <span className="block text-xs text-fg-muted">{user.email}</span>
                    </TD>
                    <TD>
                      <span className="flex flex-wrap gap-1">
                        {user.roles.length === 0 ? <span className="text-xs text-fg-subtle">no roles</span> : null}
                        {user.roles.map((r) => (
                          <Badge key={r} size="sm">
                            {r}
                          </Badge>
                        ))}
                      </span>
                    </TD>
                    <TD>
                      <StatusPill status={user.is_active ? "active" : "disabled"} size="sm" label={user.is_active ? "Active" : "Deactivated"} />
                    </TD>
                    <TD align="center">
                      <Switch size="sm" checked={user.is_active} disabled={!canAdmin || isMe} onCheckedChange={(checked) => update.mutate({ id: user.id, body: { is_active: checked } })} aria-label={`${user.is_active ? "Deactivate" : "Activate"} ${user.full_name}`} />
                    </TD>
                    <TD align="right">
                      <Button size="xs" variant="outline" disabled={!canAdmin} onClick={() => setEditing(user)}>
                        Edit roles
                      </Button>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <InviteUserDialog open={inviteOpen} onOpenChange={setInviteOpen} roles={roles.data ?? []} />
      <EditRolesDialog user={editing} roles={roles.data ?? []} onClose={() => setEditing(null)} onSave={(body) => editing && update.mutate({ id: editing.id, body })} saving={update.isPending} />
    </div>
  );
}

function InviteUserDialog({ open, onOpenChange, roles }: { open: boolean; onOpenChange: (open: boolean) => void; roles: RoleOut[] }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [selected, setSelected] = useState<string[]>(["viewer"]);

  const invite = useMutation({
    mutationFn: () => {
      const body: UserIn = { email: email.trim(), full_name: fullName.trim(), password: password || null, roles: selected };
      return api<UserOut>("/admin/users", { method: "POST", body });
    },
    onSuccess: (user) => {
      toast.success("User created", { description: user.email });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      onOpenChange(false);
      setEmail("");
      setFullName("");
      setPassword("");
      setSelected(["viewer"]);
    },
    onError: (error) => toast.error("Could not create user", { description: errorMessage(error) }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    invite.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Invite a user</DialogTitle>
            <DialogDescription>You can only grant roles whose permissions you hold yourself.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <Field label="Email" htmlFor="inv-email" required>
              <Input id="inv-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </Field>
            <Field label="Full name" htmlFor="inv-name" required>
              <Input id="inv-name" value={fullName} onChange={(e) => setFullName(e.target.value)} required maxLength={200} />
            </Field>
            <Field label="Password" htmlFor="inv-password" hint="Optional (min 12 characters). Leave empty for SSO-only users.">
              <Input id="inv-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={12} />
            </Field>
            <RoleChecklist roles={roles} selected={selected} onChange={setSelected} />
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={invite.isPending} disabled={!email.trim() || !fullName.trim() || (password.length > 0 && password.length < 12)}>
              Create user
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditRolesDialog({ user, roles, onClose, onSave, saving }: { user: UserOut | null; roles: RoleOut[]; onClose: () => void; onSave: (body: UserUpdateIn) => void; saving: boolean }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [fullName, setFullName] = useState("");
  useEffect(() => {
    if (user) {
      setSelected(user.roles);
      setFullName(user.full_name);
    }
  }, [user]);
  return (
    <Dialog open={user !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {user?.full_name}</DialogTitle>
          <DialogDescription>{user?.email}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="Full name" htmlFor="edit-name">
            <Input id="edit-name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} />
          </Field>
          <RoleChecklist roles={roles} selected={selected} onChange={setSelected} />
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={saving} onClick={() => onSave({ roles: selected, full_name: fullName.trim() || undefined })}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
