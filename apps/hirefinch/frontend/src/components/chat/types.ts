export interface ChatJob {
  id: number;
  title: string;
  company: string;
  location: string | null;
  work_mode: string | null;
  url: string;
  status: string;
  posted_at: string | null;
  salary: string | null;
  score: number | null;
  band: string | null;
  apply_method: string | null;
  suspicious: boolean;
}

export type ChatCard =
  | { type: "jobs"; items: ChatJob[] }
  | { type: "job"; job: ChatJob; strong_skills: string[]; gaps: string[]; reasons: string[]; recommendation?: string; application: string | null; description: string }
  | { type: "web_results"; items: { title: string; url: string; snippet: string; fetchable: boolean; ats: boolean }[] }
  | { type: "application"; id: number; job_id: number; title: string; company: string; route: string; status: string; apply_url: string; apply_email: string | null; blockers: string[]; questions: { id: number; question: string; sensitive: boolean }[] }
  | { type: "email"; id: number; to: string; subject: string; body: string; status: string; attachment: string }
  | { type: "applications"; items: { id: number; job_id: number; title: string; company: string; status: string; outcome: string; route: string; submitted_at: string | null; scheduled_for: string | null; needs_answers: number }[] }
  | { type: "checklist"; items: { label: string; done: boolean; how: string }[] }
  | { type: "fetched"; job: { url: string; title: string; company: string; missing: string[]; warnings: string[] } };

export interface ChatAction {
  id: number;
  kind: "apply" | "send_email" | "update_profile";
  summary: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled" | "expired";
  result: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  cards: ChatCard[];
  suggestions: string[];
  action: ChatAction | null;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface AssistantStatus {
  ai: boolean;
  ai_provider: string | null;
  ai_error: string | null;
  ai_verified?: boolean;
  web_search: boolean;
  max_chars: number;
}
