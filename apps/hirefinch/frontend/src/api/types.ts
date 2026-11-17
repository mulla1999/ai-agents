// Response and request shapes, mirroring backend/src/hirefinch/api/deps.py and domain.py.

export type WorkMode = "remote" | "hybrid" | "onsite";
export type Band = "high" | "good" | "review" | "low" | "disqualified";
export type Outcome = "pending" | "confirmed" | "uncertain" | "failed";

export const JOB_STATUSES = [
  "discovered",
  "match_evaluated",
  "shortlisted",
  "resume_pending",
  "resume_ready",
  "awaiting_approval",
  "ready_to_apply",
  "application_in_progress",
  "applied",
  "recruiter_contacted",
  "interview_scheduled",
  "rejected",
  "withdrawn",
  "expired",
  "application_failed",
  "needs_manual",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export type Role = "superadmin" | "admin" | "user";
export type UserStatus = "pending_verification" | "active" | "disabled";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: Role;
  status: UserStatus;
  email_verified: boolean;
  created_at: string | null;
  last_login_at: string | null;
  two_factor?: boolean;
  google_linked?: boolean;
  recovery_codes_left?: number;
}

export interface AuthState {
  authenticated: boolean;
  user: User | null;
}

export interface LoginResponse {
  authenticated: boolean;
  user?: User;
  two_factor_required?: boolean;
  challenge?: string;
}

export interface TwoFactorSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

/** register / forgot-password / resend: dev_link only in development without a platform email. */
export interface AuthMessage {
  message: string;
  dev_link?: string;
  active?: boolean; // registration: the account works now (email confirmation is off)
}

export interface AuditEvent {
  id: number;
  at: string;
  actor: string;
  action: string;
  level: "info" | "warning" | "error";
  entity_type: string | null;
  entity_id: number | null;
  message: string;
  details: Record<string, unknown>;
}

export interface Dashboard {
  metrics: {
    discovered_today: number;
    high_match: number;
    awaiting_resume_review: number;
    applications_submitted: number;
    recruiters_contacted: number;
    pending_approvals: number;
    interviews: number;
    needs_attention: number;
    failed_applications: number;
    dead_notifications: number;
  };
  funnel: Record<string, number>;
  trend: { date: string; discovered: number; applied: number }[];
  summary: Record<string, number>;
  recent_activity: AuditEvent[];
  warnings: { level: "info" | "warning" | "error"; message: string }[];
  mode: "supervised" | "automatic";
  paused: boolean;
  emergency_stop: boolean;
}

export interface JobFlags {
  prompt_injection?: boolean;
  suspicious?: boolean;
  suspicious_reasons?: string[];
  duplicate?: boolean;
  repost?: boolean;
  similarity?: number;
  truncated_description?: boolean;
  mock_behavior?: string;
  /** A verified email address exists for this job. */
  email_available?: boolean;
  /** Where the listing came from, e.g. "LinkedIn job alert", "Jooble (...)", "The Muse". */
  via?: string;
}

export interface JobSummary {
  id: number;
  title: string;
  company: string;
  location: string | null;
  work_mode: WorkMode | null;
  source: string | null;
  url: string;
  status: JobStatus;
  status_reason: string | null;
  liveness: string;
  posted_at: string | null;
  discovered_at: string | null;
  salary_text: string | null;
  salary_min_lpa: number | null;
  salary_max_lpa: number | null;
  experience_min: number | null;
  experience_max: number | null;
  apply_method: "mock" | "email" | "manual";
  duplicate_of_id: number | null;
  flags: JobFlags;
  score: number | null;
  band: Band | null;
  confidence: "high" | "medium" | "low" | null;
}

export interface JobList {
  total: number;
  items: JobSummary[];
}

export interface Criterion {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  detail: string;
}

export interface MatchExplanation {
  why_matches: string[];
  strongest_skills: { skill: string; evidence: string[]; mentions: number }[];
  relevant_projects: { project: string; matching_skills: string[] }[];
  missing_required: string[];
  missing_preferred: string[];
  resume_gaps: string[];
  recommendation: string;
  interview_emphasis: string[];
  confidence_reasons: string[];
  unknown_criteria: string[];
  role_family: string;
  years_used: number;
}

export interface Match {
  id: number;
  score: number;
  band: Band;
  confidence: "high" | "medium" | "low";
  recommended: boolean;
  breakdown: Record<string, Criterion>;
  explanation: MatchExplanation;
  disqualifiers: string[];
  scorer_version: string;
  created_at: string;
}

export interface ValidationSummary {
  passed: boolean;
  errors: string[];
  warnings: string[];
}

export interface ValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
  severity: "error" | "warning";
}

export interface ResumeVersionSummary {
  id: number;
  job_id: number;
  version_no: number;
  role_family: string;
  template_version: string;
  valid: boolean;
  created_at: string;
  docx_name: string;
  pdf_name: string;
  docx_sha256: string;
  pdf_sha256: string;
  validation: ValidationSummary;
  job?: ResumeJob | null;
}

export interface ResumeJob {
  title: string;
  company: string;
  location: string | null;
  status: string;
  url: string;
  score: number | null;
  band: Band | null;
}

export interface TailoringReport {
  role_family: string;
  changes: string[];
  omitted_bullets: { section: string; text: string }[];
  keyword_coverage: { covered: string[]; missing_not_in_profile: string[]; missing_but_verified: string[] };
  gaps: string[];
  llm: string;
  diff: string;
  rewrites?: { original: string; rewritten: string }[];
  rejected_rewrites?: { original: string; proposed: string; reason: string }[];
}

export interface ResumeVersionFull extends Omit<ResumeVersionSummary, "validation"> {
  content: ResumeDocument;
  report: TailoringReport;
  validation: ValidationSummary & { checks: ValidationCheck[] };
  text: string;
  master_text: string;
  versions?: { id: number; version_no: number; valid: boolean; created_at: string }[];
}

export interface Answer {
  id: number;
  question: string;
  category: string;
  answer: string | null;
  source: string;
  sensitive: boolean;
  needs_user: boolean;
}

export interface Attempt {
  attempt_no: number;
  status: string;
  trigger: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Application {
  id: number;
  job_id: number;
  job_title: string;
  company: string;
  job_status: JobStatus;
  status_reason: string | null;
  route: "mock" | "email" | "manual";
  mode: "supervised" | "automatic";
  outcome: Outcome;
  resume_version_id: number | null;
  submitted_format: string;
  submitted_file: string | null;
  submitted_file_sha256: string | null;
  submitted_at: string | null;
  confirmation_ref: string | null;
  evidence: Record<string, unknown>;
  approved_at: string | null;
  scheduled_for: string | null;
  pause_reasons: string[];
  created_at: string;
  job_url: string;
  apply_url: string | null;
  apply_email: string | null;
  answers: Answer[];
  attempts: Attempt[];
  // Only on queue/detail responses:
  approval_blockers?: string[];
  warnings?: string[];
  auto_blockers?: string[];
  resume_valid?: boolean;
}

export interface Approval {
  id: number;
  kind: "application" | "outreach";
  job_id: number;
  target_id: number;
  status: string;
  reasons: string[];
  created_at: string;
  decided_at: string | null;
}

export interface Queue {
  applications: Application[];
  approvals: Approval[];
  resume_ready_jobs: { id: number; title: string; company: string }[];
}

export interface Contact {
  id: number;
  job_id: number;
  name: string | null;
  title: string | null;
  email: string;
  source: string;
  verified: boolean;
  verification_note: string | null;
  job_title?: string;
  company?: string;
  job_status?: string;
}

export interface Delivery {
  provider: string;
  status: string;
  message_id: string;
  error: string | null;
  attachment_sha256: string | null;
  at: string;
}

export interface Draft {
  id: number;
  job_id: number;
  to: string;
  subject: string;
  body: string;
  status: "draft" | "scheduled" | "sending" | "sent" | "failed" | "cancelled";
  scheduled_for?: string | null;
  resume_version_id: number | null;
  attachment_format: string;
  /** "master" = your base resume is attached (the job had no tailored resume). */
  attachment_source?: "tailored" | "master";
  follow_up_status: "none" | "due" | "done" | "replied";
  created_at: string;
  updated_at: string;
  deliveries: Delivery[];
  job_title?: string;
  company?: string;
  job_status?: string;
}

export interface JobDetail extends JobSummary {
  description: string;
  parsed: Record<string, unknown>;
  employment_type: string | null;
  deadline: string | null;
  apply_url: string | null;
  apply_email: string | null;
  questions: string[];
  injection_snippets: string[];
  requirements: { kind: string; value: string }[];
  match: Match | null;
  score_history: { score: number; at: string }[];
  resume_versions: ResumeVersionSummary[];
  application: Application | null;
  recruiters: Contact[];
  duplicates: number[];
}

// ---------------------------------------------------------------- resume document

export interface Bullet {
  id: string;
  text: string;
}

export interface ResumeDocument {
  contact: { name: string; headline: string | null; email: string | null; phone: string | null; location: string | null; links: string[] };
  summary: string;
  skills: { name: string; items: string[] }[];
  experience: {
    id: string;
    title: string;
    company: string;
    location: string | null;
    start: string | null;
    end: string | null;
    is_current: boolean;
    date_text: string;
    is_internship: boolean;
    bullets: Bullet[];
  }[];
  projects: { id: string; name: string; subtitle: string | null; technologies: string[]; bullets: Bullet[] }[];
  education: string[];
  certifications: string[];
  extra_sections: { title: string; lines: string[] }[];
  warnings: string[];
}

export interface MasterResume {
  id: number;
  filename: string;
  format: string;
  sha256: string;
  is_active: boolean;
  uploaded_at: string;
  corrected: boolean;
  warnings: string[];
  experience_count: number;
  skills_count: number;
  document?: ResumeDocument;
  text?: string;
}

export interface ResumeCandidates {
  search_paths: string[];
  files: { path: string; name: string; size: number; modified: string }[];
}

// ---------------------------------------------------------------- profile, preferences, policy

export interface Profile {
  full_name: string | null;
  headline: string | null;
  contact_email: string | null;
  phone: string | null;
  location: string | null;
  linkedin_url: string | null;
  portfolio_url: string | null;
  notification_email: string | null;
  notice_period_days: number | null;
  current_ctc_lpa: number | null;
  expected_ctc_lpa: number | null;
  authorized_to_work_in: string[];
  requires_sponsorship: boolean | null;
  willing_to_relocate: boolean | null;
  count_internships_as_experience: boolean;
  verified_extra_skills: { name: string; evidence: string }[];
  custom_answers: Record<string, string>;
  email_style?: EmailStyle;
  self_identification?: SelfIdentification;
  common_answers?: CommonAnswers;
}

export interface SelfIdentification {
  gender: string | null;
  pronouns: string | null;
  ethnicity: string | null;
  disability: string | null;
  veteran: string | null;
  date_of_birth: string | null;
}

export interface CommonAnswers {
  country_of_residence: string | null;
  highest_education: string | null;
  managed_team: boolean | null;
  willing_onsite: boolean | null;
  background_check_consent: boolean | null;
  criminal_record: boolean | null;
  how_did_you_hear: string | null;
  accept_declarations: boolean;
}

export interface EmailStyle {
  tone: "professional" | "warm" | "concise" | "enthusiastic";
  length: "short" | "medium";
  signature: string | null;
  template: string | null;
  subject_template: string | null;
  html: boolean;
}

export interface Weights {
  technical: number;
  experience: number;
  role: number;
  domain: number;
  location: number;
  compensation: number;
}

export interface Preferences {
  target_roles: string[];
  min_compensation_lpa: number | null;
  target_compensation_lpa: [number, number] | null;
  fx_rates_to_inr: Record<string, number>;
  preferred_locations: string[];
  work_modes: WorkMode[];
  onsite_only_in_preferred_locations: boolean;
  target_companies: string[];
  excluded_companies: string[];
  excluded_keywords: string[];
  max_experience_gap_years: number;
  weights: Weights;
  thresholds: { high: number; good: number; review: number };
  /** Only jobs published within this many days; null = any age. */
  max_posting_age_days: number | null;
  include_undated: boolean;
}

export interface CandidateSummary {
  name: string;
  years_experience: number;
  years_including_internships: number;
  current_title: string | null;
  current_company: string | null;
  skills: string[];
  has_cs_degree: boolean;
}

export interface ProfileResponse {
  profile: Profile;
  preferences: Preferences;
  candidate: CandidateSummary | null;
}

export interface AutomationPolicy {
  mode: "supervised" | "automatic";
  shortlist_min_score: number;
  tailor_min_score: number;
  auto_apply_min_score: number;
  auto_apply_routes: string[];
  daily_application_limit: number;
  weekly_application_limit: number;
  auto_send_outreach: boolean;
  outreach_daily_limit: number;
  use_llm_for_tailoring: boolean;
  discovery_interval_minutes: number;
  digest_hour_local: number;
  timezone: string;
  send_days: number[];
  send_windows: string[];
  auto_review_minutes: number;
  discovery_hours: string;
  max_bullets_older_roles: number;
  notify: string[];
}

export interface ScheduledTask {
  key: string;
  interval_minutes: number;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface Automation {
  policy: AutomationPolicy;
  paused: boolean;
  emergency_stop: boolean;
  stop_reason: string | null;
  confirmation_phrase: string;
  limits: PlatformLimits;
}

export interface PlatformLimits {
  max_resumes: number;
  max_boards_per_source: number;
  max_career_pages: number;
  min_discovery_minutes: number;
  daily_outreach_cap: number;
  daily_application_cap: number;
}

export interface Source {
  key: string;
  name: string;
  support: "implemented" | "needs_credentials" | "manual" | "unsupported";
  description: string;
  needs_integration: string[];
  enabled: boolean;
  config: Record<string, unknown> | null;
  schedule_minutes: number | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  auth_ok: boolean | null;
  configurable: boolean;
}

export type IntegrationKind = "email" | "llm" | "adzuna" | "jooble" | "imap" | "websearch";

/** A connection as the API shows it: non-secret config plus the names of secret fields that are set. */
export interface IntegrationView {
  kind: string;
  configured: boolean;
  config: Record<string, unknown>;
  secrets_set: string[];
  verified_at?: string | null;
  error?: string | null;
  verified_this_session?: boolean;
  mode?: string;
}

export interface Integrations {
  integrations: Record<"email" | "llm", IntegrationView> & Partial<Record<IntegrationKind, IntegrationView>>;
  sources: Source[];
  notification_email_set: boolean;
  unsupported: { key: string; name: string; reason: string }[];
}

export interface OutboxItem {
  id: number;
  kind: string;
  subject: string;
  status: "pending" | "sent" | "dead" | "held";
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  attachments: string[];
}

export interface RunReport {
  sources?: Record<string, string>;
  new_jobs?: number;
  advanced: Record<string, number>;
  errors: string[];
}

export interface TestResult {
  ok: boolean;
  message: string;
}

// ---------------------------------------------------------------- administration

export interface AdminUser extends User {
  jobs: number;
  applications: number;
  resumes: number;
}

export interface AdminUsers {
  total: number;
  items: AdminUser[];
}

export interface RegistrationSettings {
  open: boolean;
  allowed_domains: string[];
  verify_email: boolean;
}

export interface AdminOverview {
  users: { total: number } & Partial<Record<UserStatus, number>>;
  active_sessions: number;
  jobs: number;
  applications: number;
  system_email_configured: boolean;
  registration: RegistrationSettings;
  limits: PlatformLimits;
  tasks: ScheduledTask[];
}

export interface RetentionSettings {
  inactive_days: number;
  warn_days: number;
  audit_days: number;
  notification_days: number;
}

export interface AdminSettings {
  registration: RegistrationSettings;
  limits: PlatformLimits;
  system_email: IntegrationView;
  retention?: RetentionSettings;
  google_oauth?: IntegrationView & { redirect_uri: string };
}

export interface AdminAuditEvent extends AuditEvent {
  user_email: string | null;
}
