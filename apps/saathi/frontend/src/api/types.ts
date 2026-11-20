export type Role = "citizen" | "helper" | "admin";

export interface User {
  id: string;
  role: Role;
  display_name: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  sign_in_methods?: string[] | null;
}

export interface AuthConfig {
  google_enabled: boolean;
  otp_enabled: boolean;
  whatsapp_login_enabled: boolean;
}

export type Relation = "spouse" | "son" | "daughter" | "father" | "mother" | "other";

// A household member schemes are also checked for. No names or ID numbers.
export interface FamilyMember {
  relation: Relation;
  age?: number;
  gender?: string;
  is_studying_post_matric?: boolean;
  is_widow?: boolean;
  is_pregnant_or_lactating?: boolean;
  disability_percent?: number;
  is_government_employee?: boolean;
}

export type ProfileValue = string | number | boolean;
export type Profile = { [field: string]: ProfileValue | FamilyMember[] | undefined; family_members?: FamilyMember[] };

export interface Citizen {
  id: string;
  display_name: string;
  profile: Profile;
  language: string | null;
  date_of_birth: string | null;
  contact_email: string | null;
  pincode: string | null;
  locality: string | null;
  address_line: string | null;
  consent_version: string | null;
  consent_at: string | null;
  is_self: boolean;
  managed_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CitizenDetails {
  display_name: string;
  date_of_birth?: string | null;
  gender?: string | null;
  contact_email?: string | null;
  state?: string | null;
  district?: string | null;
  pincode?: string | null;
  locality?: string | null;
  address_line?: string | null;
  residence?: string | null;
}

export interface ProfileField {
  name: string;
  label: string;
  question: string;
  type: "enum" | "bool" | "int" | "number" | "state" | "text";
  options: string[];
}

export type MatchStatus = "eligible" | "needs_info" | "not_eligible";

export interface Match {
  scheme_id: string;
  scheme_name: string;
  summary: string;
  benefits: string;
  tags: string[];
  level: "central" | "state";
  state: string | null;
  status: MatchStatus;
  missing_fields: string[];
  failed_reasons: string[];
  member: { index: number; relation: Relation; age: number | null } | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface Rule {
  reason: string;
  field?: string | null;
  op?: string | null;
  value?: unknown;
  any?: Rule[] | null;
  all?: Rule[] | null;
}

export type SchemeStatus = "draft" | "verified" | "archived";

export interface SchemeInput {
  id: string;
  name: string;
  level: "central" | "state";
  state: string | null;
  // "household": one benefit per family, checked only for the person; "person": also for family members.
  applies_to: "person" | "household";
  ministry: string;
  tags: string[];
  summary: string;
  benefits: string;
  eligibility: Rule[];
  documents: string[];
  notes: string[];
  how_to_apply: string;
  apply_url: string | null;
  source_url: string;
}

export interface Scheme extends SchemeInput {
  status: SchemeStatus;
  verified_on: string | null;
  version: number;
  updated_at: string;
}

export interface SchemeRevision {
  version: number;
  data: SchemeInput;
  changed_by_user_id: string | null;
  changed_at: string;
}

export type ApplicationStatus =
  | "interested"
  | "documents_ready"
  | "submitted"
  | "approved"
  | "rejected"
  | "benefit_received"
  | "withdrawn";

export interface Application {
  id: string;
  citizen_id: string;
  scheme_id: string;
  scheme_name: string;
  apply_url: string | null;
  status: ApplicationStatus;
  next_statuses: ApplicationStatus[];
  portal_reference: string | null;
  checklist: Record<string, boolean>;
  notes: string | null;
  created_at: string;
  updated_at: string;
  events: { from_status: string | null; to_status: string; note: string | null; created_at: string }[];
}

export interface Stats {
  users_by_role: Record<string, number>;
  citizens: number;
  citizens_with_consent: number;
  applications_by_status: Record<string, number>;
  schemes_by_status: Record<string, number>;
  chat_messages_last_7_days: number;
}
