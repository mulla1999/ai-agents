import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Application,
  ApplicationStatus,
  AuthConfig,
  ChatMessage,
  Citizen,
  CitizenDetails,
  Match,
  Profile,
  ProfileField,
  Role,
  Scheme,
  SchemeInput,
  SchemeRevision,
  Stats,
  User,
} from "./types";

export const keys = {
  me: ["me"] as const,
  citizen: (id: string) => ["citizen", id] as const,
  eligibility: (id: string) => ["eligibility", id] as const,
  messages: (id: string) => ["messages", id] as const,
  applications: (id: string) => ["applications", id] as const,
};

// --- auth ---------------------------------------------------------------------------------

export const useAuthConfig = () =>
  useQuery({ queryKey: ["auth-config"], queryFn: () => api<AuthConfig>("/auth/config"), staleTime: Infinity });

export const useProfileFields = () =>
  useQuery({ queryKey: ["profile-fields"], queryFn: () => api<ProfileField[]>("/profile-fields"), staleTime: Infinity });

export function useRequestOtp() {
  return useMutation({ mutationFn: (phone: string) => api("/auth/otp/request", { method: "POST", body: { phone } }) });
}

export function useVerifyOtp() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { phone: string; code: string }) => api<User>("/auth/otp/verify", { method: "POST", body }),
    onSuccess: (user) => client.setQueryData(keys.me, user),
  });
}

export function useRegister() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: CitizenDetails & { phone: string; code: string; consent: true }) =>
      api<User>("/auth/register", { method: "POST", body }),
    onSuccess: (user) => client.setQueryData(keys.me, user),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSettled: () => {
      client.clear();
      client.setQueryData(keys.me, null);
    },
  });
}

// --- citizens -----------------------------------------------------------------------------

/** The signed-in user's own record (``self``) or a record they manage. */
export function useCitizen(citizenId: string | "self") {
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.citizen(citizenId),
    queryFn: async () => {
      const citizen = await api<Citizen>(citizenId === "self" ? "/me/citizen" : `/citizens/${citizenId}`);
      client.setQueryData(keys.citizen(citizen.id), citizen);
      return citizen;
    },
  });
}

function useCitizenUpdate<T>(citizenId: string, fn: (body: T) => Promise<Citizen>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (citizen) => {
      client.setQueryData(keys.citizen(citizen.id), citizen);
      client.invalidateQueries({ queryKey: keys.citizen("self") });
      client.invalidateQueries({ queryKey: keys.eligibility(citizenId) });
    },
  });
}

export const useGiveConsent = (citizenId: string) =>
  useCitizenUpdate<void>(citizenId, () => api<Citizen>(`/citizens/${citizenId}/consent`, { method: "POST" }));

export const useUpdateProfile = (citizenId: string) =>
  useCitizenUpdate<Profile>(citizenId, (profile) =>
    api<Citizen>(`/citizens/${citizenId}/profile`, { method: "PUT", body: profile }),
  );

export const useUpdateDetails = (citizenId: string) =>
  useCitizenUpdate<CitizenDetails>(citizenId, (details) =>
    api<Citizen>(`/citizens/${citizenId}/details`, { method: "PUT", body: details }),
  );

export const useEligibility = (citizenId: string) =>
  useQuery({ queryKey: keys.eligibility(citizenId), queryFn: () => api<Match[]>(`/citizens/${citizenId}/eligibility`) });

export const useCitizens = (q: string) =>
  useQuery({
    queryKey: ["citizens", q],
    queryFn: () => api<Citizen[]>(`/citizens${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

export function useCreateCitizen() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { display_name: string; language?: string }) =>
      api<Citizen>("/citizens", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["citizens"] }),
  });
}

export function useEraseCitizen() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (citizenId: string) => api(`/citizens/${citizenId}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["citizens"] }),
  });
}

export function useDeleteMyAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api("/me", { method: "DELETE" }),
    onSuccess: () => {
      client.clear();
      client.setQueryData(keys.me, null);
    },
  });
}

// --- chat ---------------------------------------------------------------------------------

export const useMessages = (citizenId: string) =>
  useQuery({ queryKey: keys.messages(citizenId), queryFn: () => api<ChatMessage[]>(`/citizens/${citizenId}/messages`) });

export function useSendMessage(citizenId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (message: string) =>
      api<{ reply: string; profile: Profile }>(`/citizens/${citizenId}/chat`, { method: "POST", body: { message } }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.messages(citizenId) });
      client.invalidateQueries({ queryKey: keys.citizen(citizenId) });
      client.invalidateQueries({ queryKey: keys.eligibility(citizenId) });
    },
  });
}

// --- schemes & applications ---------------------------------------------------------------

export const useScheme = (schemeId: string | null) =>
  useQuery({
    queryKey: ["scheme", schemeId],
    queryFn: () => api<Scheme>(`/schemes/${schemeId}`),
    enabled: schemeId !== null,
  });

export const useApplications = (citizenId: string) =>
  useQuery({
    queryKey: keys.applications(citizenId),
    queryFn: () => api<Application[]>(`/citizens/${citizenId}/applications`),
  });

export function useStartApplication(citizenId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (schemeId: string) =>
      api<Application>(`/citizens/${citizenId}/applications`, { method: "POST", body: { scheme_id: schemeId } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.applications(citizenId) }),
  });
}

export interface ApplicationPatch {
  status?: ApplicationStatus;
  note?: string;
  checklist?: Record<string, boolean>;
  portal_reference?: string;
  notes?: string;
}

export function useUpdateApplication(citizenId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ApplicationPatch }) =>
      api<Application>(`/applications/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.applications(citizenId) }),
  });
}

// --- admin --------------------------------------------------------------------------------

export const useAdminSchemes = () =>
  useQuery({ queryKey: ["admin-schemes"], queryFn: () => api<Scheme[]>("/admin/schemes") });

export const useAdminScheme = (schemeId: string | undefined) =>
  useQuery({
    queryKey: ["admin-scheme", schemeId],
    queryFn: () => api<Scheme>(`/admin/schemes/${schemeId}`),
    enabled: !!schemeId,
  });

export const useSchemeRevisions = (schemeId: string | undefined) =>
  useQuery({
    queryKey: ["admin-scheme-revisions", schemeId],
    queryFn: () => api<SchemeRevision[]>(`/admin/schemes/${schemeId}/revisions`),
    enabled: !!schemeId,
  });

export function useSaveScheme(existing: boolean) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scheme: SchemeInput) =>
      existing
        ? api<Scheme>(`/admin/schemes/${scheme.id}`, { method: "PUT", body: scheme })
        : api<Scheme>("/admin/schemes", { method: "POST", body: scheme }),
    onSuccess: (scheme) => {
      client.invalidateQueries({ queryKey: ["admin-schemes"] });
      client.setQueryData(["admin-scheme", scheme.id], scheme);
      client.invalidateQueries({ queryKey: ["admin-scheme-revisions", scheme.id] });
    },
  });
}

export function useSchemeAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "verify" | "archive" }) =>
      api<Scheme>(`/admin/schemes/${id}/${action}`, { method: "POST" }),
    onSuccess: (scheme) => {
      client.invalidateQueries({ queryKey: ["admin-schemes"] });
      client.setQueryData(["admin-scheme", scheme.id], scheme);
    },
  });
}

export const useUsers = (q: string, role: Role | "") =>
  useQuery({
    queryKey: ["users", q, role],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (role) params.set("role", role);
      return api<User[]>(`/admin/users?${params}`);
    },
  });

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { role?: Role; is_active?: boolean } }) =>
      api<User>(`/admin/users/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["users"] }),
  });
}

export const useStats = () => useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/admin/stats") });
