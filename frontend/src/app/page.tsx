"use client";

/* ==============================================================================
 * MedLearn AI — Frontend (single-file build)
 * ==============================================================================
 * Everything — types, API client, all components, the page itself — lives
 * in this one file on purpose, matching the backend's single-file pattern.
 *
 * Design direction: "field notes for the body." Deep ink-navy for
 * structure/trust, a warm signal-red used ONLY for the safety/disclaimer
 * element, soft paper background for long reading. Serif for lesson
 * headings, clean grotesk for UI chrome and body copy.
 * ============================================================================== */

import { useEffect, useState, useRef } from "react";
import VisualizationPlayer from "@/components/VisualizationPlayer";
import HumanBodyExplorer from "@/components/HumanBodyExplorer";
import SimulationPlayer from "@/components/SimulationPlayer";

// ---- Types (mirrors backend Pydantic schema) --------------------------------

type Level = "child" | "high_school" | "college" | "medical_student" | "general_public";

interface SourceRef {
  org: string;
  url: string;
  title: string;
}

interface LessonSectionData {
  id: string;
  title: string;
  content: string;
  diagram_type: string;
  sources: SourceRef[];
}

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

interface Lesson {
  id: string | null;
  topic: string;
  level: Level;
  sections: LessonSectionData[];
  quiz: QuizQuestion[];
  disclaimer: string;
  safety_flags: string[];
}

const LEVELS: Level[] = ["child", "high_school", "college", "medical_student", "general_public"];

const LEVEL_LABELS: Record<Level, string> = {
  child: "Kid-friendly (8-12)",
  high_school: "High School",
  college: "College Biology",
  medical_student: "Medical Student",
  general_public: "General Public",
};

// ---- Auth types ---------------------------------------------------------------

interface UserProfile {
  id: string;
  email: string;
  role: string;
  is_verified: boolean;
  created_at: string;
}

interface AuthTokens {
  access_token: string;
  refresh_token: string;
}

interface TutorMessage {
  role: "user" | "assistant";
  content: string;
}

// ---- Admin types ----------------------------------------------------------------

interface AdminUserView {
  id: string;
  email: string;
  role: string;
  is_verified: boolean;
  is_active: boolean;
  created_at: string;
}

interface AdminLessonSummary {
  id: string;
  topic: string;
  level: Level;
  safety_flags: string[];
  created_at: string;
  view_count: number;
  feedback_count: number;
}

interface FeedbackView {
  id: string;
  lesson_id: string;
  lesson_topic: string;
  user_email: string | null;
  message: string;
  status: string;
  created_at: string;
  reviewed_at: string | null;
}

interface PlatformAnalytics {
  users: { total_users: number; verified_users: number; users_by_role: Record<string, number> };
  search: {
    total_lessons_generated: number;
    total_unique_topics: number;
    top_topics: { topic: string; search_count: number; view_count: number }[];
    level_distribution: Record<string, number>;
  };
  quiz: { total_attempts: number; total_lessons_with_attempts: number; average_score: number | null; completion_rate: number | null };
  tutor: { total_questions: number; lessons_with_tutor_activity: number; anonymous_question_count: number; signed_in_question_count: number };
  safety_flag_count: number;
}

// ---- API client ---------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function parseApiError(errData: any, fallback: string): string {
  if (!errData) return fallback;
  if (typeof errData.detail === "string") return errData.detail;
  if (errData.detail && typeof errData.detail === "object" && errData.detail.message) {
    return errData.detail.message;
  }
  if (typeof errData.message === "string") return errData.message;
  return fallback;
}

async function searchLesson(topic: string, level: Level): Promise<Lesson> {
  const res = await fetch(`${API_BASE}/api/v1/lessons/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, level }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseApiError(err, `Request failed: ${res.status}`));
  }

  return res.json();
}

// ---- Auth token storage --------------------------------------------------------
// Plain localStorage, not artifact sandbox storage — this is a real Next.js
// app served by its own origin, not a claude.ai artifact iframe, so the
// browser-storage restriction that applies to artifacts doesn't apply here.

const TOKEN_STORAGE_KEY = "medlearn_tokens";

export function loadTokens(): AuthTokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function saveTokens(tokens: AuthTokens): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens));
}

export function clearTokens(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

// ---- Auth + Learning Engine + Tutor API client -----------------------------------

export async function apiRegister(email: string, password: string): Promise<AuthTokens> {
  const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Registration failed" }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function apiLogin(email: string, password: string): Promise<AuthTokens> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function apiGetMe(accessToken: string): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/api/v1/users/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error("Could not load profile");
  return res.json();
}

/** Wraps a fetch with the current access token; on a 401, tries one silent
 * refresh via the stored refresh token before giving up. Returns null if
 * there's no session at all (caller should treat that as "not signed in"
 * rather than an error) or if refresh also fails (session is dead). */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response | null> {
  const tokens = loadTokens();
  if (!tokens) return null;

  const withAuth = (accessToken: string): RequestInit => ({
    ...init,
    headers: { ...(init.headers || {}), Authorization: `Bearer ${accessToken}` },
  });

  let res = await fetch(`${API_BASE}${path}`, withAuth(tokens.access_token));
  if (res.status !== 401) return res;

  // Access token expired — try a silent refresh once.
  const refreshRes = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!refreshRes.ok) {
    clearTokens();
    return null;
  }
  const newTokens: AuthTokens = await refreshRes.json();
  saveTokens(newTokens);
  res = await fetch(`${API_BASE}${path}`, withAuth(newTokens.access_token));
  return res;
}

async function setBookmark(lessonId: string, bookmarked: boolean): Promise<void> {
  await authFetch(`/api/v1/lessons/${lessonId}/bookmark?bookmarked=${bookmarked}`, { method: "PUT" });
}

async function recordView(lessonId: string): Promise<void> {
  await authFetch(`/api/v1/lessons/${lessonId}/view`, { method: "POST" });
}

interface QuizSubmitResult {
  score: number;
  correct_count: number;
  total: number;
}

/** Submits quiz answers for server-side scoring + history tracking
 * (best-score-across-attempts, per main.py's submit_quiz). Only meaningful
 * for signed-in users — returns null if there's no session, so the caller
 * falls back to client-side scoring rather than erroring the whole quiz
 * flow over something that's an expected, normal case (anonymous use). */
async function submitQuiz(lessonId: string, answers: number[]): Promise<QuizSubmitResult | null> {
  const res = await authFetch(`/api/v1/lessons/${lessonId}/quiz/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });
  if (!res || !res.ok) return null;
  return res.json();
}

async function askTutor(lessonId: string, question: string, accessToken: string | null): Promise<string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(`${API_BASE}/api/v1/lessons/${lessonId}/tutor`, {
    method: "POST",
    headers,
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseApiError(err, "The tutor couldn't answer that."));
  }
  const data = await res.json();
  return data.answer;
}

/** Signed-in only, per the backend (anonymous tutor conversations aren't
 * retrievable — see main.py's get_tutor_history). Returns [] rather than
 * throwing on any failure, including "not signed in" (no token) — this is
 * called opportunistically on mount and a failure here shouldn't block
 * rendering the rest of the lesson. */
async function getTutorHistory(lessonId: string): Promise<TutorMessage[]> {
  const res = await authFetch(`/api/v1/lessons/${lessonId}/tutor/history`);
  if (!res || !res.ok) return [];
  const data = await res.json();
  return data.map((entry: { role: string; content: string }) => ({ role: entry.role, content: entry.content }));
}

// ---- Admin API client -----------------------------------------------------------
// All admin-* functions return null on failure (including "not an admin" /
// 403) rather than throwing — the AdminDashboard component treats a null
// result as "show an error inline," never as an uncaught exception that
// would crash the panel. These deliberately don't fall back to anything;
// there's no meaningful client-side substitute for admin data the way
// there is for quiz scoring.

async function adminListUsers(): Promise<AdminUserView[] | null> {
  const res = await authFetch("/api/v1/admin/users");
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminSetUserRole(userId: string, role: string): Promise<AdminUserView | null> {
  const res = await authFetch(`/api/v1/admin/users/${userId}/role`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminSetUserActive(userId: string, isActive: boolean): Promise<AdminUserView | null> {
  const res = await authFetch(`/api/v1/admin/users/${userId}/active?is_active=${isActive}`, { method: "PUT" });
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminListLessons(flaggedOnly: boolean): Promise<AdminLessonSummary[] | null> {
  const res = await authFetch(`/api/v1/admin/lessons?flagged_only=${flaggedOnly}`);
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminDeleteLesson(lessonId: string): Promise<boolean> {
  const res = await authFetch(`/api/v1/admin/lessons/${lessonId}`, { method: "DELETE" });
  return !!res && res.ok;
}

async function adminListFeedback(statusFilter: string | null): Promise<FeedbackView[] | null> {
  const path = statusFilter ? `/api/v1/admin/feedback?status_filter=${statusFilter}` : "/api/v1/admin/feedback";
  const res = await authFetch(path);
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminUpdateFeedbackStatus(feedbackId: string, status: string): Promise<FeedbackView | null> {
  const res = await authFetch(`/api/v1/admin/feedback/${feedbackId}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res || !res.ok) return null;
  return res.json();
}

async function adminGetAnalytics(): Promise<PlatformAnalytics | null> {
  const res = await authFetch("/api/v1/admin/analytics");
  if (!res || !res.ok) return null;
  return res.json();
}

async function submitFeedback(lessonId: string, message: string, accessToken: string | null): Promise<boolean> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${API_BASE}/api/v1/lessons/${lessonId}/feedback`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
  });
  return res.ok;
}

// ---- Design tokens --------------------------------------------------------------

const T = {
  paper: "#f7f4ee",
  ink: "#1c2b3a",
  inkSoft: "#3d5266",
  signal: "#b3441e",
  signalSoft: "#f0e0d5",
  sage: "#5c7a5e",
  sageSoft: "#e3ece3",
  rule: "#d8d0c0",
  gold: "#b8862e",
};

const fontDisplay = { fontFamily: '"Source Serif 4", Georgia, "Times New Roman", serif' };
const fontBody = { fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' };

// ---- Components -----------------------------------------------------------------

function DisclaimerBanner({ text }: { text: string }) {
  return (
    <div
      style={{
        ...fontBody,
        width: "100%",
        padding: "12px 24px",
        fontSize: "0.875rem",
        display: "flex",
        alignItems: "flex-start",
        gap: "12px",
        backgroundColor: T.signalSoft,
        color: T.signal,
      }}
    >
      <span style={{ ...fontDisplay, fontSize: "1rem", lineHeight: 1, marginTop: "2px" }}>!</span>
      <p style={{ lineHeight: 1.4, margin: 0 }}>{text}</p>
    </div>
  );
}

function LessonSectionView({ section, index }: { section: LessonSectionData; index: number }) {
  return (
    <section style={{ padding: "40px 0", borderBottom: `1px solid ${T.rule}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "16px", marginBottom: "16px" }}>
        <span style={{ ...fontDisplay, fontSize: "0.875rem", color: T.gold }}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <h2 style={{ ...fontDisplay, fontSize: "1.875rem", color: T.ink, margin: 0 }}>{section.title}</h2>
      </div>

      <p style={{ ...fontBody, fontSize: "1.125rem", lineHeight: 1.7, color: T.inkSoft, marginBottom: "24px" }}>
        {section.content}
      </p>

      {section.sources.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {section.sources.map((src, i) => (
            <a
              key={i}
              href={src.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                ...fontBody,
                fontSize: "0.75rem",
                padding: "6px 12px",
                borderRadius: "9999px",
                border: `1px solid ${T.rule}`,
                color: T.inkSoft,
                textDecoration: "none",
              }}
            >
              {src.org} — {src.title}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

function QuizPanel({ quiz, lessonId }: { quiz: QuizQuestion[]; lessonId: string | null }) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);
  const [serverResult, setServerResult] = useState<QuizSubmitResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function selectAnswer(qIndex: number, optionIndex: number) {
    if (submitted) return;
    setAnswers((prev) => ({ ...prev, [qIndex]: optionIndex }));
  }

  async function handleSubmit() {
    setSubmitted(true);
    if (!lessonId) return; // no lesson id (shouldn't normally happen) — client-side score only

    setSubmitting(true);
    try {
      // answers is keyed by question index — build the ordered array the
      // backend expects (one selection per question, in question order).
      const ordered = quiz.map((_, i) => answers[i]);
      const result = await submitQuiz(lessonId, ordered);
      setServerResult(result); // null if anonymous/not signed in — falls back to client-side score below
    } finally {
      setSubmitting(false);
    }
  }

  const clientScore = quiz.filter((q, i) => answers[i] === q.correct_index).length;
  const displayScore = serverResult ? serverResult.correct_count : clientScore;

  return (
    <section style={{ padding: "40px 0" }}>
      <h2 style={{ ...fontDisplay, fontSize: "1.875rem", color: T.ink, marginBottom: "24px" }}>
        Check your understanding
      </h2>

      {quiz.map((q, qi) => (
        <div key={qi} style={{ marginBottom: "28px" }}>
          <p style={{ ...fontBody, fontWeight: 600, color: T.ink, marginBottom: "10px" }}>{q.question}</p>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {q.options.map((opt, oi) => {
              const isSelected = answers[qi] === oi;
              const isCorrect = oi === q.correct_index;
              let bg = "white";
              let border = T.rule;
              if (submitted && isSelected) {
                bg = isCorrect ? T.sageSoft : T.signalSoft;
                border = isCorrect ? T.sage : T.signal;
              } else if (submitted && isCorrect) {
                bg = T.sageSoft;
                border = T.sage;
              } else if (isSelected) {
                border = T.ink;
              }
              return (
                <button
                  key={oi}
                  onClick={() => selectAnswer(qi, oi)}
                  style={{
                    ...fontBody,
                    textAlign: "left",
                    padding: "10px 16px",
                    borderRadius: "10px",
                    border: `1.5px solid ${border}`,
                    backgroundColor: bg,
                    color: T.ink,
                    cursor: submitted ? "default" : "pointer",
                  }}
                >
                  {opt}
                </button>
              );
            })}
          </div>
          {submitted && (
            <p style={{ ...fontBody, fontSize: "0.875rem", color: T.inkSoft, marginTop: "8px" }}>
              {q.explanation}
            </p>
          )}
        </div>
      ))}

      {!submitted ? (
        <button
          onClick={handleSubmit}
          disabled={Object.keys(answers).length < quiz.length}
          style={{
            ...fontBody,
            padding: "10px 24px",
            borderRadius: "9999px",
            border: "none",
            backgroundColor: T.ink,
            color: "white",
            cursor: "pointer",
            opacity: Object.keys(answers).length < quiz.length ? 0.5 : 1,
          }}
        >
          Submit answers
        </button>
      ) : (
        <p style={{ ...fontBody, fontWeight: 600, color: T.ink }}>
          {submitting
            ? "Saving your results…"
            : `You got ${displayScore} of ${quiz.length} correct.${serverResult ? " (saved to your account)" : ""}`}
        </p>
      )}
    </section>
  );
}

function AuthPanel({ onAuthed }: { onAuthed: (tokens: AuthTokens) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = mode === "login" ? await apiLogin(email, password) : await apiRegister(email, password);
      saveTokens(tokens);
      onAuthed(tokens);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 12px",
        borderRadius: "12px",
        border: `1px solid ${T.rule}`,
        backgroundColor: "white",
      }}
    >
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        style={{ ...fontBody, fontSize: "0.875rem", border: "none", outline: "none", width: "140px" }}
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        minLength={8}
        style={{ ...fontBody, fontSize: "0.875rem", border: "none", outline: "none", width: "120px" }}
      />
      <button
        type="submit"
        disabled={loading}
        style={{
          ...fontBody,
          fontSize: "0.8rem",
          padding: "6px 14px",
          borderRadius: "9999px",
          border: "none",
          backgroundColor: T.ink,
          color: "white",
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {loading ? "…" : mode === "login" ? "Sign in" : "Create account"}
      </button>
      <button
        type="button"
        onClick={() => setMode(mode === "login" ? "register" : "login")}
        style={{ ...fontBody, fontSize: "0.75rem", background: "none", border: "none", color: T.inkSoft, cursor: "pointer", whiteSpace: "nowrap" }}
      >
        {mode === "login" ? "Sign up instead" : "Sign in instead"}
      </button>
      {error && <span style={{ ...fontBody, fontSize: "0.75rem", color: T.signal }}>{error}</span>}
    </form>
  );
}

function TutorPanel({ lessonId, accessToken }: { lessonId: string; accessToken: string | null }) {
  const [messages, setMessages] = useState<TutorMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Restore prior conversation for this lesson when signed in. Runs once
  // per lessonId (and again if the user signs in/out while viewing the
  // same lesson, since accessToken is a dependency). Anonymous visitors
  // just start fresh every time — there's no history to restore for them.
  useEffect(() => {
    if (!accessToken) {
      setMessages([]);
      return;
    }
    setHistoryLoading(true);
    getTutorHistory(lessonId)
      .then(setMessages)
      .finally(() => setHistoryLoading(false));
  }, [lessonId, accessToken]);

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question.trim();
    setQuestion("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);
    try {
      const answer = await askTutor(lessonId, q, accessToken);
      setMessages((prev) => [...prev, { role: "assistant", content: answer }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "The tutor couldn't answer that.";
      if (msg.includes("911") || msg.includes("988") || msg.toLowerCase().includes("emergency")) {
        setMessages((prev) => [...prev, { role: "assistant", content: msg }]);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section style={{ padding: "40px 0", borderTop: `1px solid ${T.rule}` }}>
      <h2 style={{ ...fontDisplay, fontSize: "1.875rem", color: T.ink, marginBottom: "16px" }}>
        Ask a follow-up question
      </h2>

      {historyLoading && (
        <p style={{ ...fontBody, fontSize: "0.8rem", color: T.inkSoft, marginBottom: "12px" }}>
          Loading your previous questions…
        </p>
      )}

      {messages.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "20px" }}>
          {messages.map((m, i) => {
            const isEmergency = m.content.includes("911") || m.content.includes("988");
            return (
              <div
                key={i}
                style={{
                  ...fontBody,
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                  padding: isEmergency ? "14px 18px" : "10px 14px",
                  borderRadius: "12px",
                  backgroundColor: m.role === "user" ? T.ink : isEmergency ? "#fef2f2" : "white",
                  color: m.role === "user" ? "white" : isEmergency ? "#991b1b" : T.ink,
                  border: isEmergency ? "2px solid #ef4444" : m.role === "assistant" ? `1px solid ${T.rule}` : "none",
                  fontSize: "0.95rem",
                  lineHeight: 1.6,
                  whiteSpace: "pre-line",
                }}
              >
                {m.content}
              </div>
            );
          })}
        </div>
      )}

      <form onSubmit={handleAsk} style={{ display: "flex", gap: "8px" }}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Why does this happen?"
          style={{
            ...fontBody,
            flex: 1,
            padding: "10px 14px",
            borderRadius: "9999px",
            border: `1.5px solid ${T.rule}`,
            outline: "none",
            fontSize: "0.95rem",
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            ...fontBody,
            padding: "10px 20px",
            borderRadius: "9999px",
            border: "none",
            backgroundColor: T.ink,
            color: "white",
            cursor: loading ? "default" : "pointer",
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? "…" : "Ask"}
        </button>
      </form>
      {error && <p style={{ ...fontBody, fontSize: "0.8rem", color: T.signal, marginTop: "8px" }}>{error}</p>}
    </section>
  );
}

function AdminOverviewPanel() {
  const [data, setData] = useState<PlatformAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminGetAnalytics()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p style={{ ...fontBody, color: T.inkSoft }}>Loading analytics…</p>;
  if (!data) return <p style={{ ...fontBody, color: T.signal }}>Could not load analytics.</p>;

  const statCard = (label: string, value: string | number) => (
    <div style={{ padding: "16px", borderRadius: "12px", border: `1px solid ${T.rule}`, backgroundColor: "white" }}>
      <p style={{ ...fontBody, fontSize: "0.75rem", color: T.inkSoft, marginBottom: "4px" }}>{label}</p>
      <p style={{ ...fontDisplay, fontSize: "1.5rem", color: T.ink }}>{value}</p>
    </div>
  );

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "12px", marginBottom: "24px" }}>
        {statCard("Total users", data.users.total_users)}
        {statCard("Verified users", data.users.verified_users)}
        {statCard("Lessons generated", data.search.total_lessons_generated)}
        {statCard("Unique topics", data.search.total_unique_topics)}
        {statCard("Quiz attempts", data.quiz.total_attempts)}
        {statCard("Avg. quiz score", data.quiz.average_score !== null ? `${Math.round(data.quiz.average_score * 100)}%` : "—")}
        {statCard("Tutor questions", data.tutor.total_questions)}
        {statCard("Flagged lessons", data.safety_flag_count)}
      </div>

      <h3 style={{ ...fontDisplay, fontSize: "1.25rem", color: T.ink, marginBottom: "12px" }}>Top topics</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {data.search.top_topics.map((t) => (
          <div key={t.topic} style={{ ...fontBody, fontSize: "0.9rem", display: "flex", justifyContent: "space-between", padding: "8px 12px", backgroundColor: "white", borderRadius: "8px", border: `1px solid ${T.rule}` }}>
            <span>{t.topic}</span>
            <span style={{ color: T.inkSoft }}>{t.view_count} views · {t.search_count} generated</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AdminUsersPanel() {
  const [users, setUsers] = useState<AdminUserView[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    adminListUsers()
      .then((result) => {
        if (result === null) setError("Could not load users.");
        else setUsers(result);
      })
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleRoleChange(userId: string, role: string) {
    const updated = await adminSetUserRole(userId, role);
    if (updated) load();
  }

  async function handleToggleActive(userId: string, currentlyActive: boolean) {
    const updated = await adminSetUserActive(userId, !currentlyActive);
    if (updated) load();
  }

  if (loading) return <p style={{ ...fontBody, color: T.inkSoft }}>Loading users…</p>;
  if (error) return <p style={{ ...fontBody, color: T.signal }}>{error}</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {users?.map((u) => (
        <div
          key={u.id}
          style={{
            ...fontBody,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            padding: "10px 14px",
            backgroundColor: "white",
            borderRadius: "8px",
            border: `1px solid ${T.rule}`,
            opacity: u.is_active ? 1 : 0.5,
          }}
        >
          <div>
            <p style={{ fontSize: "0.9rem", color: T.ink }}>{u.email}</p>
            <p style={{ fontSize: "0.75rem", color: T.inkSoft }}>
              {u.is_verified ? "Verified" : "Unverified"} · {u.is_active ? "Active" : "Deactivated"}
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <select
              value={u.role}
              onChange={(e) => handleRoleChange(u.id, e.target.value)}
              style={{ ...fontBody, fontSize: "0.8rem", padding: "4px 8px", borderRadius: "6px", border: `1px solid ${T.rule}` }}
            >
              <option value="student">student</option>
              <option value="educator">educator</option>
              <option value="admin">admin</option>
            </select>
            <button
              onClick={() => handleToggleActive(u.id, u.is_active)}
              style={{
                ...fontBody,
                fontSize: "0.8rem",
                padding: "6px 12px",
                borderRadius: "9999px",
                border: `1px solid ${u.is_active ? T.signal : T.sage}`,
                backgroundColor: "white",
                color: u.is_active ? T.signal : T.sage,
                cursor: "pointer",
              }}
            >
              {u.is_active ? "Deactivate" : "Reactivate"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function AdminLessonsPanel() {
  const [lessons, setLessons] = useState<AdminLessonSummary[] | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    adminListLessons(flaggedOnly).then(setLessons).finally(() => setLoading(false));
  }

  useEffect(load, [flaggedOnly]);

  async function handleDelete(lessonId: string) {
    if (!window.confirm("Delete this lesson? This also removes its history, tutor conversations, and feedback.")) return;
    const ok = await adminDeleteLesson(lessonId);
    if (ok) load();
  }

  return (
    <div>
      <label style={{ ...fontBody, fontSize: "0.85rem", display: "flex", alignItems: "center", gap: "6px", marginBottom: "12px" }}>
        <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
        Flagged lessons only
      </label>

      {loading ? (
        <p style={{ ...fontBody, color: T.inkSoft }}>Loading lessons…</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {lessons?.map((l) => (
            <div
              key={l.id}
              style={{
                ...fontBody,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                backgroundColor: l.safety_flags.length > 0 ? T.signalSoft : "white",
                borderRadius: "8px",
                border: `1px solid ${T.rule}`,
              }}
            >
              <div>
                <p style={{ fontSize: "0.9rem", color: T.ink }}>
                  {l.topic} <span style={{ color: T.gold, fontSize: "0.75rem" }}>{LEVEL_LABELS[l.level]}</span>
                </p>
                <p style={{ fontSize: "0.75rem", color: T.inkSoft }}>
                  {l.view_count} views · {l.feedback_count} feedback
                  {l.safety_flags.length > 0 && ` · ${l.safety_flags.length} safety flag(s)`}
                </p>
              </div>
              <button
                onClick={() => handleDelete(l.id)}
                style={{ ...fontBody, fontSize: "0.8rem", padding: "6px 12px", borderRadius: "9999px", border: `1px solid ${T.signal}`, background: "white", color: T.signal, cursor: "pointer" }}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AdminFeedbackPanel() {
  const [feedback, setFeedback] = useState<FeedbackView[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    adminListFeedback(statusFilter || null).then(setFeedback).finally(() => setLoading(false));
  }

  useEffect(load, [statusFilter]);

  async function handleStatusChange(id: string, status: string) {
    const updated = await adminUpdateFeedbackStatus(id, status);
    if (updated) load();
  }

  return (
    <div>
      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        style={{ ...fontBody, fontSize: "0.85rem", padding: "6px 10px", borderRadius: "6px", border: `1px solid ${T.rule}`, marginBottom: "12px" }}
      >
        <option value="open">Open</option>
        <option value="reviewed">Reviewed</option>
        <option value="dismissed">Dismissed</option>
        <option value="">All</option>
      </select>

      {loading ? (
        <p style={{ ...fontBody, color: T.inkSoft }}>Loading feedback…</p>
      ) : feedback?.length === 0 ? (
        <p style={{ ...fontBody, color: T.inkSoft }}>No feedback here.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {feedback?.map((f) => (
            <div key={f.id} style={{ padding: "12px 14px", backgroundColor: "white", borderRadius: "8px", border: `1px solid ${T.rule}` }}>
              <p style={{ ...fontBody, fontSize: "0.75rem", color: T.gold, marginBottom: "4px" }}>
                {f.lesson_topic} · {f.user_email || "anonymous"}
              </p>
              <p style={{ ...fontBody, fontSize: "0.9rem", color: T.ink, marginBottom: "8px" }}>{f.message}</p>
              <select
                value={f.status}
                onChange={(e) => handleStatusChange(f.id, e.target.value)}
                style={{ ...fontBody, fontSize: "0.75rem", padding: "4px 8px", borderRadius: "6px", border: `1px solid ${T.rule}` }}
              >
                <option value="open">open</option>
                <option value="reviewed">reviewed</option>
                <option value="dismissed">dismissed</option>
              </select>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AdminDashboard({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"overview" | "users" | "lessons" | "feedback">("overview");

  const tabs: { id: typeof tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "users", label: "Users" },
    { id: "lessons", label: "Lessons" },
    { id: "feedback", label: "Feedback" },
  ];

  return (
    <div style={{ position: "fixed", inset: 0, backgroundColor: T.paper, zIndex: 50, overflowY: "auto" }}>
      <div style={{ maxWidth: "960px", margin: "0 auto", padding: "32px 24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px" }}>
          <h1 style={{ ...fontDisplay, fontSize: "2rem", color: T.ink }}>Admin</h1>
          <button
            onClick={onClose}
            style={{ ...fontBody, fontSize: "0.85rem", padding: "8px 16px", borderRadius: "9999px", border: `1px solid ${T.rule}`, background: "white", color: T.inkSoft, cursor: "pointer" }}
          >
            Close
          </button>
        </div>

        <div style={{ display: "flex", gap: "8px", marginBottom: "24px" }}>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                ...fontBody,
                fontSize: "0.85rem",
                padding: "8px 16px",
                borderRadius: "9999px",
                border: `1px solid ${tab === t.id ? T.ink : T.rule}`,
                backgroundColor: tab === t.id ? T.ink : "white",
                color: tab === t.id ? "white" : T.inkSoft,
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "overview" && <AdminOverviewPanel />}
        {tab === "users" && <AdminUsersPanel />}
        {tab === "lessons" && <AdminLessonsPanel />}
        {tab === "feedback" && <AdminFeedbackPanel />}
      </div>
    </div>
  );
}

function FeedbackLink({ lessonId, accessToken }: { lessonId: string; accessToken: string | null }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setStatus("sending");
    const ok = await submitFeedback(lessonId, message.trim(), accessToken);
    setStatus(ok ? "sent" : "error");
    if (ok) setMessage("");
  }

  if (status === "sent") {
    return (
      <p style={{ ...fontBody, fontSize: "0.8rem", color: T.sage, padding: "16px 0" }}>
        Thanks — this has been flagged for review.
      </p>
    );
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{ ...fontBody, fontSize: "0.8rem", color: T.inkSoft, background: "none", border: "none", cursor: "pointer", padding: "16px 0" }}
      >
        Report a problem with this lesson
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={{ padding: "16px 0", display: "flex", gap: "8px" }}>
      <input
        type="text"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="What's wrong with this lesson?"
        style={{ ...fontBody, flex: 1, padding: "8px 12px", borderRadius: "8px", border: `1px solid ${T.rule}`, fontSize: "0.85rem", outline: "none" }}
      />
      <button
        type="submit"
        disabled={status === "sending"}
        style={{ ...fontBody, fontSize: "0.8rem", padding: "8px 16px", borderRadius: "9999px", border: "none", backgroundColor: T.ink, color: "white", cursor: "pointer" }}
      >
        {status === "sending" ? "…" : "Send"}
      </button>
      {status === "error" && <span style={{ ...fontBody, fontSize: "0.75rem", color: T.signal, alignSelf: "center" }}>Couldn&apos;t send — try again.</span>}
    </form>
  );
}

// ---- 3D Interactive Organ Explorer & Visualization Components ---------------------

function OrganViewer3D({ meshType = "heart", title = "3D Anatomical Organ Explorer" }: { meshType?: string; title?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [wireframe, setWireframe] = useState(false);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationY, setRotationY] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let angle = rotationY;

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0c1017";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      if (autoRotate) angle += 0.015;

      const cx = canvas.width / 2;
      const cy = canvas.height / 2;

      // Draw background ambient particles
      ctx.fillStyle = "rgba(56, 189, 248, 0.4)";
      for (let i = 0; i < 30; i++) {
        const px = (cx + Math.sin(angle + i) * (80 + i * 3)) % canvas.width;
        const py = (cy + Math.cos(angle * 0.5 + i) * (60 + i * 2)) % canvas.height;
        ctx.beginPath();
        ctx.arc(px, py, (i % 3) + 1, 0, Math.PI * 2);
        ctx.fill();
      }

      // Draw 3D organ mesh projection
      ctx.save();
      ctx.translate(cx, cy);

      const mType = meshType.toLowerCase();
      if (mType.includes("heart")) {
        const scale = 1 + Math.sin(angle * 3) * 0.05;
        ctx.scale(scale, scale);
        ctx.strokeStyle = "#ef4444";
        ctx.lineWidth = wireframe ? 1 : 2;
        ctx.fillStyle = "rgba(239, 68, 68, 0.15)";

        ctx.beginPath();
        ctx.arc(0, 10, 55, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();

        ctx.strokeStyle = "#38bdf8";
        ctx.beginPath();
        ctx.arc(-10, -45, 30, Math.PI * 0.8, Math.PI * 1.9);
        ctx.stroke();
      } else if (mType.includes("lung")) {
        const breathe = 1 + Math.sin(angle * 2) * 0.06;
        ctx.scale(breathe, breathe);
        ctx.strokeStyle = "#0284c7";
        ctx.fillStyle = "rgba(2, 132, 199, 0.15)";
        ctx.lineWidth = 2;

        ctx.beginPath();
        ctx.ellipse(-35, 0, 30, 55, -0.2, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
        ctx.beginPath();
        ctx.ellipse(35, 0, 32, 60, 0.2, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
      } else if (mType.includes("brain")) {
        ctx.strokeStyle = "#a855f7";
        ctx.fillStyle = "rgba(168, 85, 247, 0.15)";
        ctx.lineWidth = 2;

        ctx.beginPath();
        ctx.ellipse(-25, -10, 35, 45, 0, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
        ctx.beginPath();
        ctx.ellipse(25, -10, 35, 45, 0, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
      } else if (mType.includes("virus")) {
        ctx.strokeStyle = "#f43f5e";
        ctx.fillStyle = "rgba(244, 63, 94, 0.2)";
        ctx.lineWidth = 2;

        ctx.beginPath();
        ctx.arc(0, 0, 45, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();

        for (let i = 0; i < 12; i++) {
          const a = angle + (i * Math.PI) / 6;
          const sx = Math.cos(a) * 45;
          const sy = Math.sin(a) * 45;
          const ex = Math.cos(a) * 65;
          const ey = Math.sin(a) * 65;
          ctx.beginPath();
          ctx.moveTo(sx, sy);
          ctx.lineTo(ex, ey);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(ex, ey, 4, 0, Math.PI * 2);
          ctx.fillStyle = "#f43f5e";
          ctx.fill();
        }
      } else {
        ctx.strokeStyle = "#06b6d4";
        ctx.fillStyle = "rgba(6, 182, 212, 0.15)";
        ctx.lineWidth = 2;

        ctx.beginPath();
        ctx.arc(0, 0, 50, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();
      }

      ctx.restore();
      animId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animId);
  }, [meshType, wireframe, autoRotate, rotationY]);

  const organMappings: Record<string, { name: string; system: string; topics: string[] }> = {
    heart: { name: "Heart", system: "Cardiovascular", topics: ["Coronary Artery Disease", "Hypertension", "Heart Attack"] },
    lungs: { name: "Lungs", system: "Respiratory", topics: ["SARS-CoV-2 (COVID-19)", "Asthma", "Pneumonia"] },
    brain: { name: "Brain", system: "Nervous System", topics: ["Alzheimer's Disease", "Stroke", "Parkinson's"] },
    pancreas: { name: "Pancreas", system: "Endocrine", topics: ["Type 2 Diabetes Mellitus", "Pancreatitis"] },
    virus: { name: "Betacoronavirus Virion", system: "Microbiology", topics: ["SARS-CoV-2 (COVID-19)", "Influenza"] },
    cell: { name: "Cellular Membrane", system: "Cytology", topics: ["Type 2 Diabetes Mellitus", "Receptor Signaling"] },
  };

  const activeMapping = organMappings[meshType.toLowerCase()] || organMappings.heart;

  return (
    <div style={{ backgroundColor: "#090d16", borderRadius: "16px", border: `1px solid ${T.rule}`, padding: "20px", marginTop: "24px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
        <h4 style={{ ...fontBody, fontSize: "0.95rem", fontWeight: 600, color: T.ink }}>{title}</h4>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            onClick={() => setWireframe(!wireframe)}
            style={{ ...fontBody, fontSize: "0.75rem", padding: "4px 10px", borderRadius: "9999px", border: `1px solid ${wireframe ? T.gold : T.rule}`, background: wireframe ? T.signalSoft : "transparent", color: wireframe ? T.gold : T.inkSoft, cursor: "pointer" }}
          >
            Wireframe
          </button>
          <button
            type="button"
            onClick={() => setAutoRotate(!autoRotate)}
            style={{ ...fontBody, fontSize: "0.75rem", padding: "4px 10px", borderRadius: "9999px", border: `1px solid ${autoRotate ? T.gold : T.rule}`, background: autoRotate ? T.signalSoft : "transparent", color: autoRotate ? T.gold : T.inkSoft, cursor: "pointer" }}
          >
            {autoRotate ? "Pause Spin" : "Auto Spin"}
          </button>
        </div>
      </div>

      <div style={{ position: "relative", width: "100%", height: "240px", borderRadius: "12px", overflow: "hidden", border: `1px solid ${T.rule}` }}>
        <canvas ref={canvasRef} width={600} height={240} style={{ width: "100%", height: "100%", display: "block" }} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", marginTop: "12px", gap: "8px" }}>
        <span style={{ ...fontBody, fontSize: "0.75rem", color: T.inkSoft }}>
          Anatomical Node: <strong style={{ color: T.gold }}>{activeMapping.name} ({activeMapping.system})</strong>
        </span>
        <div style={{ display: "flex", gap: "6px" }}>
          {activeMapping.topics.map((top) => (
            <span key={top} style={{ ...fontBody, fontSize: "0.7rem", padding: "2px 8px", borderRadius: "4px", backgroundColor: "rgba(6, 182, 212, 0.1)", color: "#06b6d4", border: "1px solid rgba(6, 182, 212, 0.2)" }}>
              {top}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function FlashcardStudyDeck({ topic }: { topic: string }) {
  const [cards, setCards] = useState<Array<{ id: string; front_prompt: string; back_explanation: string; difficulty_tag: string }>>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);

  useEffect(() => {
    fetch(`/api/v1/quiz/flashcards/${encodeURIComponent(topic)}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.flashcards) setCards(data.flashcards);
      })
      .catch(() => {
        setCards([
          { id: "fc1", front_prompt: `What primary mechanism defines ${topic}?`, back_explanation: `${topic} involves specific cellular receptor alterations and tissue response.`, difficulty_tag: "Medium" },
          { id: "fc2", front_prompt: "How do therapeutic treatments work?", back_explanation: "By restoring molecular signal transduction and tissue homeostasis.", difficulty_tag: "Easy" }
        ]);
      });
  }, [topic]);

  if (!cards.length) return null;
  const card = cards[currentIndex];

  return (
    <div style={{ backgroundColor: "white", borderRadius: "16px", border: `1px solid ${T.rule}`, padding: "20px", marginTop: "24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <span style={{ ...fontBody, fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", color: T.gold }}>
          Interactive Flashcard Deck ({currentIndex + 1} of {cards.length})
        </span>
        <span style={{ ...fontBody, fontSize: "0.7rem", padding: "2px 8px", borderRadius: "9999px", backgroundColor: T.signalSoft, color: T.gold }}>
          {card.difficulty_tag}
        </span>
      </div>

      <div
        onClick={() => setFlipped(!flipped)}
        style={{
          minHeight: "130px",
          padding: "20px",
          borderRadius: "12px",
          backgroundColor: flipped ? "#0f172a" : "#f8fafc",
          border: `1.5px dashed ${flipped ? T.gold : T.rule}`,
          color: flipped ? "white" : T.ink,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          cursor: "pointer",
          transition: "all 0.3s ease"
        }}
      >
        <p style={{ ...fontBody, fontSize: "1rem", fontWeight: 500 }}>
          {flipped ? card.back_explanation : card.front_prompt}
        </p>
        <span style={{ ...fontBody, fontSize: "0.7rem", marginTop: "12px", opacity: 0.6 }}>
          {flipped ? "Click to see Question" : "Click card to flip for Answer"}
        </span>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "12px" }}>
        <button
          type="button"
          disabled={currentIndex === 0}
          onClick={() => { setCurrentIndex((p) => p - 1); setFlipped(false); }}
          style={{ ...fontBody, fontSize: "0.8rem", padding: "6px 14px", borderRadius: "9999px", border: `1px solid ${T.rule}`, background: "white", cursor: currentIndex === 0 ? "default" : "pointer", opacity: currentIndex === 0 ? 0.4 : 1 }}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={currentIndex === cards.length - 1}
          onClick={() => { setCurrentIndex((p) => p + 1); setFlipped(false); }}
          style={{ ...fontBody, fontSize: "0.8rem", padding: "6px 14px", borderRadius: "9999px", border: "none", backgroundColor: T.ink, color: "white", cursor: currentIndex === cards.length - 1 ? "default" : "pointer", opacity: currentIndex === cards.length - 1 ? 0.4 : 1 }}
        >
          Next Card
        </button>
      </div>
    </div>
  );
}

// ---- Page -------------------------------------------------------------------------

export default function MedLearnPage() {
  const [topic, setTopic] = useState("");
  const [level, setLevel] = useState<Level>("general_public");
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [user, setUser] = useState<UserProfile | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [bookmarked, setBookmarked] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);

  // On mount: if there's a saved session, load the profile silently. Not an
  // error if this fails or there's nothing saved — just means signed out.
  useEffect(() => {
    const tokens = loadTokens();
    if (!tokens) return;
    apiGetMe(tokens.access_token)
      .then((profile) => {
        setUser(profile);
        setAccessToken(tokens.access_token);
      })
      .catch(() => clearTokens());
  }, []);

  function handleAuthed(tokens: AuthTokens) {
    setAccessToken(tokens.access_token);
    apiGetMe(tokens.access_token)
      .then(setUser)
      .catch(() => {
        clearTokens();
        setAccessToken(null);
      });
  }

  function handleSignOut() {
    clearTokens();
    setUser(null);
    setAccessToken(null);
    setBookmarked(false);
  }

  async function triggerSearch(targetTopic: string) {
    if (!targetTopic.trim()) return;
    setTopic(targetTopic);
    setLoading(true);
    setError(null);
    setBookmarked(false);
    try {
      const result = await searchLesson(targetTopic.trim(), level);
      setLesson(result);
      if (result.id && user) {
        recordView(result.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setLesson(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!topic.trim()) return;
    await triggerSearch(topic.trim());
  }

  async function handleToggleBookmark() {
    if (!lesson?.id || !user) return;
    const next = !bookmarked;
    setBookmarked(next); // optimistic
    try {
      await setBookmark(lesson.id, next);
    } catch {
      setBookmarked(!next); // revert on failure
    }
  }

  return (
    <main style={{ ...fontBody, minHeight: "100vh", backgroundColor: T.paper, display: "flex", flexDirection: "column" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          alignItems: "center",
          padding: "16px 24px",
          gap: "12px",
        }}
      >
        {user ? (
          <>
            <span style={{ ...fontBody, fontSize: "0.875rem", color: T.inkSoft }}>{user.email}</span>
            {user.role === "admin" && (
              <button
                onClick={() => setShowAdmin(true)}
                style={{
                  ...fontBody,
                  fontSize: "0.8rem",
                  padding: "6px 14px",
                  borderRadius: "9999px",
                  border: `1px solid ${T.gold}`,
                  background: "white",
                  color: T.gold,
                  cursor: "pointer",
                }}
              >
                Admin
              </button>
            )}
            <button
              onClick={handleSignOut}
              style={{
                ...fontBody,
                fontSize: "0.8rem",
                padding: "6px 14px",
                borderRadius: "9999px",
                border: `1px solid ${T.rule}`,
                background: "white",
                color: T.inkSoft,
                cursor: "pointer",
              }}
            >
              Sign out
            </button>
          </>
        ) : (
          <AuthPanel onAuthed={handleAuthed} />
        )}
      </div>

      {lesson && <DisclaimerBanner text={lesson.disclaimer} />}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", padding: "0 24px" }}>
        <div style={{ maxWidth: "720px", width: "100%", textAlign: "center", paddingTop: "64px" }}>
          <p style={{ ...fontBody, fontSize: "0.75rem", letterSpacing: "0.25em", textTransform: "uppercase", color: T.gold, marginBottom: "16px" }}>
            MedLearn — Educational Only
          </p>
          <h1 style={{ ...fontDisplay, fontSize: "2.75rem", lineHeight: 1.1, color: T.ink, marginBottom: "16px" }}>
            Understand how the body works.
          </h1>
          <p style={{ fontSize: "1.125rem", color: T.inkSoft, marginBottom: "40px" }}>
            Search any disease, cell, organ, or process. Get a clear, cited, level-appropriate explanation — not a diagnosis.
          </p>

          <form onSubmit={handleSearch} style={{ width: "100%" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                borderRadius: "9999px",
                border: `2px solid ${T.ink}`,
                padding: "8px",
                marginBottom: "24px",
                backgroundColor: "white",
              }}
            >
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. What is diabetes?"
                style={{
                  ...fontBody,
                  flex: 1,
                  padding: "12px 16px",
                  fontSize: "1.125rem",
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: T.ink,
                }}
              />
              <button
                type="submit"
                disabled={loading}
                style={{
                  ...fontBody,
                  padding: "12px 24px",
                  borderRadius: "9999px",
                  border: "none",
                  backgroundColor: T.ink,
                  color: "white",
                  fontWeight: 500,
                  cursor: loading ? "default" : "pointer",
                  opacity: loading ? 0.7 : 1,
                }}
              >
                {loading ? "Thinking…" : "Explain it"}
              </button>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "8px" }}>
              {LEVELS.map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setLevel(lvl)}
                  style={{
                    ...fontBody,
                    padding: "8px 16px",
                    borderRadius: "9999px",
                    fontSize: "0.875rem",
                    border: `1px solid ${level === lvl ? T.ink : T.rule}`,
                    backgroundColor: level === lvl ? T.ink : "transparent",
                    color: level === lvl ? "white" : T.inkSoft,
                    cursor: "pointer",
                  }}
                >
                  {LEVEL_LABELS[lvl]}
                </button>
              ))}
            </div>
          </form>

          {error && (
            <div
              style={{
                marginTop: "24px",
                padding: "16px 20px",
                borderRadius: "12px",
                backgroundColor: error.includes("911") || error.includes("988") ? "#fef2f2" : "rgba(225, 29, 72, 0.08)",
                border: `2px solid ${error.includes("911") || error.includes("988") ? "#ef4444" : T.signal}`,
                textAlign: "left",
                lineHeight: 1.6,
                whiteSpace: "pre-line",
              }}
            >
              <p style={{ ...fontBody, color: error.includes("911") || error.includes("988") ? "#991b1b" : T.signal, margin: 0, fontSize: "0.95rem" }}>
                {error}
              </p>
            </div>
          )}
        </div>

        {lesson && (
          <div style={{ maxWidth: "720px", width: "100%", paddingTop: "48px", paddingBottom: "64px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "12px" }}>
              <div>
                <h2 style={{ ...fontDisplay, fontSize: "2.25rem", color: T.ink, marginBottom: "8px" }}>
                  {lesson.topic}
                </h2>
                <p style={{ ...fontBody, fontSize: "0.875rem", color: T.gold, marginBottom: "8px" }}>
                  {LEVEL_LABELS[lesson.level]}
                </p>
              </div>
              {user && lesson.id && (
                <button
                  onClick={handleToggleBookmark}
                  style={{
                    ...fontBody,
                    fontSize: "0.8rem",
                    padding: "8px 16px",
                    borderRadius: "9999px",
                    border: `1.5px solid ${bookmarked ? T.gold : T.rule}`,
                    backgroundColor: bookmarked ? T.signalSoft : "white",
                    color: bookmarked ? T.gold : T.inkSoft,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {bookmarked ? "★ Bookmarked" : "☆ Bookmark"}
                </button>
              )}
            </div>

            {lesson.sections.map((section, i) => (
              <LessonSectionView key={section.id} section={section} index={i} />
            ))}

            <VisualizationPlayer topic={lesson.topic} />

            <OrganViewer3D meshType={lesson.topic} title={`${lesson.topic} — 3D Visual Mesh`} />

            <SimulationPlayer topic={lesson.topic} />

            <HumanBodyExplorer onSelectTopic={triggerSearch} />

            {lesson.quiz.length > 0 && <QuizPanel quiz={lesson.quiz} lessonId={lesson.id} />}

            <FlashcardStudyDeck topic={lesson.topic} />

            {lesson.id && <TutorPanel lessonId={lesson.id} accessToken={accessToken} />}

            {lesson.id && <FeedbackLink lessonId={lesson.id} accessToken={accessToken} />}
          </div>
        )}

        {!lesson && (
          <div style={{ maxWidth: "760px", width: "100%", marginTop: "36px", marginBottom: "48px" }}>
            <HumanBodyExplorer onSelectTopic={triggerSearch} />
          </div>
        )}
      </div>

      {!lesson && (
        <footer style={{ textAlign: "center", paddingBottom: "32px", padding: "0 24px 32px" }}>
          <p style={{ ...fontBody, fontSize: "0.75rem", color: T.inkSoft }}>
            For education only. Not a substitute for professional medical advice, diagnosis, or treatment.
          </p>
        </footer>
      )}

      {showAdmin && <AdminDashboard onClose={() => setShowAdmin(false)} />}
    </main>
  );
}
