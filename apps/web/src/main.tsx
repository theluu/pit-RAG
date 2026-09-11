import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  GitCompareArrows,
  LayoutDashboard,
  Play,
  Plus,
  Search,
  Lock,
  LogIn,
  LogOut,
  Share2,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UploadCloud,
} from "lucide-react";
import "./styles.css";
import "./ingestion.css";
import "./graph.css";
import "./pipeline.css";
import "./mobile.css";

// Default to same-origin relative paths: a production build served behind the app's
// own reverse proxy must not carry a hardcoded host. Dev sets this in .env.development.
const API = import.meta.env.VITE_API_URL ?? "";
type View = "query" | "pipeline" | "admin" | "evaluation";
type Citation = {
  provision_id: string;
  document_number: string;
  title: string;
  article: string;
  clause?: string;
  point?: string;
  quote: string;
  source_url?: string;
  score: number;
};
type Retrieved = {
  vector_score: number;
  keyword_score: number;
  fusion_score: number;
  rerank_score: number;
  match_reasons: string[];
  provision: { id: string; article: string; content: string };
};
type Timeline = {
  relation_type: string;
  effective_from?: string;
  source_document_id: string;
  target_document_id: string;
  evidence_text?: string;
};
type Result = {
  run_id: string;
  answer: string;
  citations: Citation[];
  confidence: number;
  warnings: string[];
  pipeline_version: string;
  generation_mode: string;
  fallback_reason?: string;
  latency_ms: number;
  retrieved_provisions: Retrieved[];
  query_analysis: { concepts: string[] };
  diagnostics: Record<string, unknown>;
  legal_timeline: Timeline[];
};
type GraphStatus = {
  enabled: boolean;
  available: boolean;
  nodes: number;
  relationships: number;
  last_error?: string;
};
type Summary = {
  documents: number;
  documents_by_status: Record<string, number>;
  provisions: number;
  runs: number;
  feedback: number;
  audit_events: number;
  published_index_documents: number;
  capabilities: {
    database: boolean;
    redis: boolean;
    neo4j: GraphStatus;
    provider: {
      configured: boolean;
      available: boolean;
      circuit_open: boolean;
      model: string;
      last_error?: string;
    };
  };
};
type AdminDoc = {
  id: string;
  document_number: string;
  title: string;
  document_type?: string;
  issuing_authority?: string;
  issued_date?: string;
  domain: string;
  status: string;
  review_status: string;
  effective_from: string;
  effective_to?: string;
};
type Job = {
  id: string;
  status: string;
  progress: number;
  attempt: number;
  error?: string;
  warnings: string[];
};
type Preview = {
  document: AdminDoc;
  pages: {
    page_number: number;
    text: string;
    extraction_method: string;
    confidence?: number;
  }[];
  provisions: {
    id: string;
    article: string;
    clause?: string;
    point?: string;
    content: string;
    quality_flags: string[];
    page_from?: number;
    page_to?: number;
    extraction_method: string;
    extraction_confidence?: number;
  }[];
};
type EvalReport = {
  pipeline: string;
  cases: number;
  citation_precision: number;
  citation_recall: number;
  retrieval_hit_rate: number;
  mean_reciprocal_rank: number;
  abstention_rate: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  results: {
    id: string;
    citation_precision: number;
    citation_recall: number;
    abstained: boolean;
    latency_ms: number;
  }[];
};
function today(): string {
  return new Date().toISOString().slice(0, 10);
}
const domains = [
  ["labor", "Lao động"],
  ["social_insurance", "Bảo hiểm xã hội"],
  ["personal_income_tax", "Thuế TNCN"],
];
const examples = [
  ["labor", "Làm thêm ngày nghỉ hằng tuần được trả tối thiểu bao nhiêu?"],
  ["labor", "Thử việc tối đa bao lâu với vị trí cần trình độ cao đẳng?"],
  [
    "social_insurance",
    "Năm 2026 cần đóng BHXH bao nhiêu năm để hưởng lương hưu?",
  ],
  ["personal_income_tax", "Mức giảm trừ cho mỗi người phụ thuộc là bao nhiêu?"],
];
const pipelineInfo: Record<string, string> = {
  L0: "Không truy xuất",
  L1: "Tương đồng",
  L2: "+ hiệu lực",
  L3: "Hybrid RRF",
  L4: "Legal rerank",
  L5: "GraphRAG",
  L6: "Multi-query RAG",
  L7: "Adaptive RAG",
};

const TOKEN_KEY = "pitrag-token";

function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function App() {
  const [token, setToken] = useState(readToken),
    [view, setView] = useState<View>("query"),
    [question, setQuestion] = useState(examples[0][1]),
    [domain, setDomain] = useState("labor"),
    [date, setDate] = useState(today),
    [level, setLevel] = useState("L7");
  const [result, setResult] = useState<Result | null>(null),
    [compare, setCompare] = useState<Record<string, Result> | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [showLogin, setShowLogin] = useState(false);

  // No credentials ship in this bundle. Searching needs no account at all; a token only
  // appears here after someone signs in, and it is the API that enforces the boundary.
  function signIn(next: string) {
    try {
      localStorage.setItem(TOKEN_KEY, next);
    } catch {
      /* private browsing: the session simply will not outlive the tab */
    }
    setToken(next);
    setShowLogin(false);
  }

  function signOut() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing stored, nothing to clear */
    }
    setToken("");
    setView("query");
  }

  function openProtected(next: View) {
    if (next !== "query" && !token) {
      setShowLogin(true);
      return;
    }
    setView(next);
  }
  async function run(comparing = false) {
    setLoading(true);
    setError("");
    setResult(null);
    setCompare(null);
    try {
      const body = comparing
        ? {
            question,
            applicable_date: date,
            domain,
            pipelines: ["L1", "L3", "L5", "L6", "L7"],
          }
        : { question, applicable_date: date, domain, pipeline_level: level };
      const r = await fetch(
        `${API}/api/v1/${comparing ? "query/compare" : "query"}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(body),
        },
      );
      if (r.status === 401) {
        signOut();
        throw new Error("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.");
      }
      if (!r.ok) throw new Error("Truy vấn thất bại");
      const data = await r.json();
      comparing ? setCompare(data) : setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi xảy ra");
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="app">
      <Header
        view={view}
        setView={openProtected}
        signedIn={Boolean(token)}
        onSignIn={() => setShowLogin(true)}
        onSignOut={signOut}
      />
      {showLogin && (
        <LoginDialog onClose={() => setShowLogin(false)} onToken={signIn} />
      )}
      <main>
        <Sidebar view={view} setView={openProtected} signedIn={Boolean(token)} />
        <section className="workspace">
          {view === "query" && (
            <>
              <div className="hero">
                <div>
                  <p className="eyebrow">
                    <Sparkles size={12} /> LEGAL INTELLIGENCE WORKSPACE
                  </p>
                  <h1>
                    Mỗi câu trả lời.
                    <br />
                    <em>Một chuỗi căn cứ.</em>
                  </h1>
                </div>
                <p className="heroCopy">
                  Hybrid retrieval, kiểm tra hiệu lực và citation tới từng điều
                  khoản — có thể giải thích, đo lường và tái lập.
                </p>
              </div>
              <div className="querybox">
                <div className="queryTop">
                  <Search size={20} />
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run();
                    }}
                  />
                  <span>{question.length}/2000</span>
                </div>
                <div className="controls">
                  <label>
                    Lĩnh vực
                    <select
                      value={domain}
                      onChange={(e) => setDomain(e.target.value)}
                    >
                      {domains.map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Ngày áp dụng
                    <input
                      type="date"
                      value={date}
                      onChange={(e) => setDate(e.target.value)}
                    />
                  </label>
                  <label>
                    Pipeline
                    <select
                      value={level}
                      onChange={(e) => setLevel(e.target.value)}
                    >
                      {Object.entries(pipelineInfo).map(([k, v]) => (
                        <option key={k} value={k}>
                          {k} · {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="actions">
                    <button
                      className="secondary"
                      disabled={!token || loading}
                      onClick={() => (token ? run(true) : setShowLogin(true))}
                    >
                      <GitCompareArrows size={16} />
                      So sánh
                    </button>
                    <button
                      className="primary"
                      disabled={!token || loading}
                      onClick={() => run()}
                    >
                      {loading ? (
                        <span className="spinner" />
                      ) : (
                        <Search size={16} />
                      )}{" "}
                      {loading ? "Đang phân tích" : "Tra cứu"}
                    </button>
                  </div>
                </div>
              </div>
              <div className="examples">
                <span>CÂU HỎI MẪU</span>
                {examples.map(([d, q]) => (
                  <button
                    key={q}
                    onClick={() => {
                      setDomain(d);
                      setQuestion(q);
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
              {error && <Notice text={error} />}{" "}
              {result && (
                <ResultCard
                  data={result}
                  title={`${level} · ${pipelineInfo[level]}`}
                  token={token}
                />
              )}{" "}
              {compare && (
                <div className="compare">
                  {Object.entries(compare).map(([k, v]) => (
                    <ResultCard key={k} data={v} title={k} token={token} />
                  ))}
                </div>
              )}
            </>
          )}
          {view === "pipeline" && <PipelinePanel token={token} />}{" "}
          {view === "admin" && <AdminPanel token={token} />}{" "}
          {view === "evaluation" && <EvaluationPanel token={token} />}
        </section>
      </main>
    </div>
  );
}
function Header({
  view,
  setView,
  signedIn,
  onSignIn,
  onSignOut,
}: {
  view: View;
  setView: (v: View) => void;
  signedIn: boolean;
  onSignIn: () => void;
  onSignOut: () => void;
}) {
  return (
    <header>
      <div className="brand">
        <div className="logo">
          <ShieldCheck size={21} />
        </div>
        <div>
          <strong>Điều Luật</strong>
          <span>Vietnam Legal Intelligence</span>
        </div>
      </div>
      <nav className="topnav">
        {(
          [
            ["query", "Tra cứu"],
            ["pipeline", "Pipeline"],
            ["admin", "Dữ liệu"],
            ["evaluation", "Đánh giá"],
          ] as [View, string][]
        ).map(([v, l]) => (
          <button
            className={view === v ? "active" : ""}
            onClick={() => setView(v)}
            key={v}
          >
            {l}
            {v !== "query" && !signedIn && <Lock className="lockIcon" />}
          </button>
        ))}
      </nav>
      <div className="headerRight">
        <span className="version">
          <Share2 /> PGVECTOR + NEO4J · v0.4
        </span>
        {signedIn ? (
          <button className="authBtn out" onClick={onSignOut}>
            <LogOut /> Đăng xuất
          </button>
        ) : (
          <button className="authBtn" onClick={onSignIn}>
            <LogIn /> Đăng nhập
          </button>
        )}
      </div>
    </header>
  );
}
function Sidebar({
  view,
  setView,
  signedIn,
}: {
  view: View;
  setView: (v: View) => void;
  signedIn: boolean;
}) {
  return (
    <aside>
      <div>
        <p className="eyebrow">WORKSPACE</p>
        <button
          className={`nav ${view === "query" ? "active" : ""}`}
          onClick={() => setView("query")}
        >
          <Search />
          <span>Tra cứu pháp luật</span>
        </button>
        <button
          className={`nav ${view === "pipeline" ? "active" : ""}`}
          onClick={() => setView("pipeline")}
        >
          <Activity />
          <span>Pipeline truy vấn</span>
          {!signedIn && <Lock className="lockIcon" />}
        </button>
        <button
          className={`nav ${view === "admin" ? "active" : ""}`}
          onClick={() => setView("admin")}
        >
          <Database />
          <span>Quản trị dữ liệu</span>
          {!signedIn && <Lock className="lockIcon" />}
        </button>
        <button
          className={`nav ${view === "evaluation" ? "active" : ""}`}
          onClick={() => setView("evaluation")}
        >
          <BarChart3 />
          <span>Evaluation Lab</span>
          {!signedIn && <Lock className="lockIcon" />}
        </button>
      </div>
      <div>
        <div className="asideCard">
          <ShieldCheck />
          <strong>Evidence-first</strong>
          <p>Không đủ căn cứ thì từ chối. Provider lỗi thì fallback an toàn.</p>
        </div>
        <div className="corpus">
          <Activity />
          <span>
            <b>Observable RAG</b>
            <small>Trace · score · citation · audit</small>
          </span>
        </div>
      </div>
    </aside>
  );
}
function Notice({ text }: { text: string }) {
  return (
    <div className="warning">
      <AlertTriangle size={16} />
      {text}
    </div>
  );
}
function ResultCard({
  data,
  title,
  token,
}: {
  data: Result;
  title: string;
  token: string;
}) {
  const [tab, setTab] = useState<"answer" | "evidence" | "signals">("answer"),
    [vote, setVote] = useState("");
  async function feedback(rating: string) {
    setVote(rating);
    await fetch(`${API}/api/v1/runs/${data.run_id}/feedback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ rating }),
    });
  }
  return (
    <article className="result">
      <div className="resultHead">
        <div>
          <span className="pill">{title}</span>
          <span className={`mode ${data.generation_mode}`}>
            {data.generation_mode.replace("_", " ")}
          </span>
          <span className="confidence">
            <i /> Evidence {Math.round(data.confidence * 100)}%
          </span>
          <span className="graphBadge">
            <Share2 />
            {data.diagnostics.graph_path === "neo4j"
              ? "Neo4j graph"
              : "SQL graph fallback"}
          </span>
        </div>
        <span>
          <Clock3 />
          {data.latency_ms} ms
        </span>
      </div>
      <div className="tabs">
        <button
          className={tab === "answer" ? "active" : ""}
          onClick={() => setTab("answer")}
        >
          Câu trả lời
        </button>
        <button
          className={tab === "evidence" ? "active" : ""}
          onClick={() => setTab("evidence")}
        >
          Căn cứ <b>{data.citations.length}</b>
        </button>
        <button
          className={tab === "signals" ? "active" : ""}
          onClick={() => setTab("signals")}
        >
          Tín hiệu
        </button>
      </div>
      {data.warnings.map((w) => (
        <Notice key={w} text={w} />
      ))}
      {tab === "answer" && (
        <div className="answer">
          <div className="answerTitle">
            <CheckCircle2 />
            Kết luận có căn cứ
          </div>
          {data.answer
            .split("\n")
            .filter(Boolean)
            .map((x, i) => (
              <p key={i}>{x}</p>
            ))}
          <div className="concepts">
            <span>Ý định</span>
            {(data.query_analysis?.concepts || []).map((x) => (
              <b key={x}>{x.replaceAll("_", " ")}</b>
            ))}
          </div>
          {data.legal_timeline?.length > 0 && (
            <Timeline items={data.legal_timeline} />
          )}
        </div>
      )}
      {tab === "evidence" && (
        <div className="sources">
          {data.citations.map((c, i) => (
            <div className="source" key={i}>
              <div className="sourceTop">
                <span>
                  <i>{i + 1}</i>
                  <strong>{c.document_number}</strong> · Điều {c.article}
                  {c.clause && `, khoản ${c.clause}`}
                  {c.point && `, điểm ${c.point}`}
                </span>
                <b>{c.score.toFixed(3)}</b>
              </div>
              <p>“{c.quote}”</p>
            </div>
          ))}
        </div>
      )}
      {tab === "signals" && (
        <div className="diagnostics">
          <div className="metricRow">
            <Metric label="Ứng viên" value={data.retrieved_provisions.length} />
            <Metric label="Căn cứ" value={data.citations.length} />
            <Metric label="Generation" value={data.generation_mode} />
            <Metric
              label="Strategy"
              value={String(data.diagnostics.retrieval_strategy || "unknown")}
            />
          </div>
          {Array.isArray(data.diagnostics.query_variants) && (
            <div className="concepts">
              <span>Query variants</span>
              {(data.diagnostics.query_variants as string[]).map((query) => (
                <b key={query}>{query}</b>
              ))}
            </div>
          )}
          <div className="signalList">
            {data.retrieved_provisions.map((r, i) => (
              <div key={r.provision.id}>
                <span>
                  #{i + 1} · Điều {r.provision.article}
                </span>
                <div className="bar">
                  <i
                    style={{ width: `${Math.min(100, r.rerank_score * 75)}%` }}
                  />
                </div>
                <b>{r.rerank_score.toFixed(3)}</b>
                <small>{r.match_reasons.join(" · ")}</small>
              </div>
            ))}
          </div>
        </div>
      )}
      <footer>
        <span>
          {data.pipeline_version} · {data.run_id.slice(0, 8)}
        </span>
        <div>
          <span>Hữu ích?</span>
          <button
            className={vote === "correct" ? "selected" : ""}
            onClick={() => feedback("correct")}
          >
            <ThumbsUp />
          </button>
          <button
            className={vote === "incorrect" ? "selected" : ""}
            onClick={() => feedback("incorrect")}
          >
            <ThumbsDown />
          </button>
        </div>
      </footer>
    </article>
  );
}
function Timeline({ items }: { items: Timeline[] }) {
  return (
    <div className="timeline">
      <div className="answerTitle">
        <Share2 />
        Knowledge Graph · Dòng thời gian pháp lý
      </div>
      {items.map((x, i) => (
        <div className="timelineItem" key={i}>
          <span>{x.relation_type}</span>
          <b>{x.effective_from || "Không rõ ngày"}</b>
          <p>{x.evidence_text}</p>
        </div>
      ))}
    </div>
  );
}
function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function AdminPanel({ token }: { token: string }) {
  const [summary, setSummary] = useState<Summary | null>(null),
    [docs, setDocs] = useState<AdminDoc[]>([]),
    [showForm, setShowForm] = useState(false),
    [message, setMessage] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [editing, setEditing] = useState<AdminDoc | null>(null),
    [job, setJob] = useState<Job | null>(null);
  const headers = { Authorization: `Bearer ${token}` };
  async function load() {
    if (!token) return;
    const [s, d] = await Promise.all([
      fetch(`${API}/api/v1/admin/summary`, { headers }).then((r) => r.json()),
      fetch(`${API}/api/v1/admin/documents`, { headers }).then((r) => r.json()),
    ]);
    setSummary(s);
    setDocs(d);
  }
  useEffect(() => {
    load();
  }, [token]);
  async function publish(id: string) {
    const r = await fetch(`${API}/api/v1/admin/documents/${id}/publish`, {
      method: "POST",
      headers,
    });
    setMessage(
      r.ok
        ? "Đã publish và kích hoạt index mới."
        : "Không thể publish: kiểm tra embedding/provider.",
    );
    load();
  }
  async function reprocess(id: string) {
    const r = await fetch(`${API}/api/v1/admin/documents/${id}/reprocess`, {
      method: "POST",
      headers,
    });
    const b = await r.json();
    if (r.ok) {
      setJob({
        id: b.job_id,
        status: "queued",
        progress: 0,
        attempt: 0,
        warnings: [],
      });
      setMessage("Đã xếp hàng xử lý lại.");
    } else setMessage(b.detail || "Không xếp hàng được");
  }
  async function inspect(id: string) {
    const r = await fetch(`${API}/api/v1/admin/documents/${id}/preview`, {
      headers,
    });
    if (r.ok) setPreview(await r.json());
  }
  useEffect(() => {
    if (!job || ["review_ready", "failed"].includes(job.status)) return;
    const timer = setInterval(async () => {
      const r = await fetch(`${API}/api/v1/admin/ingestion-jobs/${job.id}`, {
        headers,
      });
      if (!r.ok) return;
      const next: Job = await r.json();
      setJob(next);
      if (["review_ready", "failed"].includes(next.status)) load();
    }, 1500);
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  return (
    <>
      <PageTitle
        eyebrow="DATA OPERATIONS"
        title="Quản trị knowledge base"
        copy="Upload PDF, kiểm tra OCR/chunk rồi publish vào index có phiên bản."
      />
      <div className="toolbar">
        <div className="health">
          {summary && (
            <>
              <Status ok={summary.capabilities.database} label="Database" />
              <Status ok={summary.capabilities.redis} label="Redis" />
              <Status
                ok={summary.capabilities.neo4j.available}
                label={
                  summary.capabilities.neo4j.enabled
                    ? "Neo4j Knowledge Graph"
                    : "Neo4j disabled"
                }
              />
              <Status
                ok={summary.capabilities.provider.available}
                label={
                  summary.capabilities.provider.circuit_open
                    ? "OpenAI circuit open"
                    : "OpenAI"
                }
              />
            </>
          )}
        </div>
        <button
          className="primary standalone"
          onClick={() => setShowForm(!showForm)}
        >
          <Plus />
          Upload PDF
        </button>
      </div>
      {message && (
        <div className="success">
          <Check /> {message}
        </div>
      )}
      {summary && (
        <div className="metricRow dashboard">
          <Metric label="Tổng văn bản" value={summary.documents} />
          <Metric
            label="Published"
            value={summary.documents_by_status.published || 0}
          />
          <Metric
            label="Draft/Review"
            value={
              (summary.documents_by_status.draft || 0) +
              (summary.documents_by_status.review_ready || 0)
            }
          />
          <Metric label="Điều khoản" value={summary.provisions} />
          <Metric
            label="Graph nodes"
            value={summary.capabilities.neo4j.nodes}
          />
          <Metric
            label="Graph edges"
            value={summary.capabilities.neo4j.relationships}
          />
          <Metric label="Query runs" value={summary.runs} />
          <Metric label="Audit events" value={summary.audit_events} />
        </div>
      )}
      {showForm && (
        <IngestForm
          token={token}
          onDone={(m, started) => {
            setMessage(m);
            setJob(started);
            load();
          }}
        />
      )}
      {job && <JobTracker job={job} />}
      {preview && (
        <div className="previewPanel">
          <strong>Preview · {preview.document.document_number}</strong>
          <small>
            {preview.pages.length} trang · {preview.provisions.length} chunks
          </small>
          <ExtractionQuality preview={preview} />
          {preview.pages.slice(0, 3).map((p) => (
            <div key={p.page_number}>
              <b>
                Trang {p.page_number} · {p.extraction_method}
                {p.confidence != null &&
                  ` · ${(p.confidence * 100).toFixed(0)}%`}
              </b>
              <p>{p.text.slice(0, 700)}</p>
            </div>
          ))}
          <div>
            <b>Provenance điều khoản</b>
            <ul className="provenanceList">
              {preview.provisions.slice(0, 12).map((pr) => (
                <li key={pr.id}>
                  <span>
                    Điều {pr.article}
                    {pr.clause && `.${pr.clause}`}
                  </span>
                  <span>
                    {pr.page_from
                      ? pr.page_to && pr.page_to !== pr.page_from
                        ? `trang ${pr.page_from}–${pr.page_to}`
                        : `trang ${pr.page_from}`
                      : "chưa xác định trang"}{" "}
                    · {pr.extraction_method}
                    {pr.extraction_confidence != null &&
                      ` ${(pr.extraction_confidence * 100).toFixed(0)}%`}
                  </span>
                  {pr.quality_flags.length > 0 && (
                    <span className="flagChips">
                      {pr.quality_flags.join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {editing && (
        <MetadataForm
          token={token}
          doc={editing}
          onClose={() => setEditing(null)}
          onSaved={(text) => {
            setEditing(null);
            setMessage(text);
            load();
          }}
        />
      )}
      <div className="dataTable">
        <div className="tableHead">
          <span>Văn bản</span>
          <span>Lĩnh vực</span>
          <span>Hiệu lực</span>
          <span>Trạng thái</span>
          <span />
        </div>
        {docs.map((d) => (
          <div className="tableRow" key={d.id}>
            <span>
              <b>{d.document_number}</b>
              <small>{d.title}</small>
            </span>
            <span>{d.domain}</span>
            <span>
              {d.effective_from}
              {d.effective_to && ` → ${d.effective_to}`}
            </span>
            <span>
              <i className={`statusDot ${d.review_status}`} />
              {d.review_status}
            </span>
            <span>
              <button className="tiny" onClick={() => inspect(d.id)}>
                Preview
              </button>
              <button className="tiny" onClick={() => setEditing(d)}>
                Sửa thông tin
              </button>
              {["draft", "review_ready"].includes(d.review_status) && (
                <button className="tiny" onClick={() => publish(d.id)}>
                  Publish <ArrowRight />
                </button>
              )}
              {["failed", "processing"].includes(d.review_status) && (
                <button className="tiny" onClick={() => reprocess(d.id)}>
                  Xử lý lại
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}
const JOB_STAGES: Record<string, string> = {
  queued: "Đang chờ worker",
  extracting: "Trích xuất text layer",
  ocr: "Nhận dạng OCR",
  parsing: "Bóc tách Điều/Khoản",
  embedding: "Tạo embedding",
  review_ready: "Sẵn sàng kiểm duyệt",
  failed: "Thất bại",
};
function JobTracker({ job }: { job: Job }) {
  const done = job.status === "review_ready",
    failed = job.status === "failed";
  return (
    <div className={`jobTracker ${job.status}`}>
      <div className="jobHead">
        <strong>
          {done ? <CheckCircle2 /> : failed ? <AlertTriangle /> : <Clock3 />}{" "}
          {JOB_STAGES[job.status] || job.status}
        </strong>
        <small>
          job {job.id.slice(0, 8)} · lần thử {job.attempt}
        </small>
      </div>
      <div className="jobBar">
        <i style={{ width: `${job.progress}%` }} />
      </div>
      {failed && job.error && <p className="jobError">{job.error}</p>}
      {job.warnings.length > 0 && (
        <ul className="jobWarnings">
          {job.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
function IngestForm({
  token,
  onDone,
}: {
  token: string;
  onDone: (message: string, job: Job | null) => void;
}) {
  const [number, setNumber] = useState("DEMO/2026/01"),
    [title, setTitle] = useState("Văn bản PDF cần kiểm duyệt"),
    [docType, setDocType] = useState("Luật"),
    [authority, setAuthority] = useState("Quốc hội"),
    [issued, setIssued] = useState(today),
    [effective, setEffective] = useState(today),
    [uploadDomain, setUploadDomain] = useState("labor"),
    [pdf, setPdf] = useState<File | null>(null),
    [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!pdf) return;
    setBusy(true);
    const form = new FormData();
    Object.entries({
      document_number: number,
      title,
      document_type: docType,
      issuing_authority: authority,
      issued_date: issued,
      effective_from: effective,
      domain: uploadDomain,
    }).forEach(([k, v]) => form.append(k, v));
    form.append("file", pdf);
    let r: Response;
    try {
      r = await fetch(`${API}/api/v1/admin/documents/uploads`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
    } catch {
      setBusy(false);
      onDone("Không gọi được API. Kiểm tra kết nối mạng.", null);
      return;
    }
    // A 500 answers in plain text, so parsing before checking the status threw a
    // SyntaxError that nothing caught — the spinner then span forever.
    const body = await r
      .clone()
      .json()
      .catch(() => ({}) as Record<string, string>);
    setBusy(false);
    onDone(
      r.ok
        ? `Đã xếp hàng OCR · job ${String(body.job_id ?? "").slice(0, 8)}`
        : body.detail || `Upload thất bại (HTTP ${r.status})`,
      r.ok
        ? {
            id: body.job_id,
            status: "queued",
            progress: 0,
            attempt: 0,
            warnings: [],
          }
        : null,
    );
  }
  return (
    <form className="ingestForm" onSubmit={submit}>
      <div>
        <UploadCloud />
        <strong>PDF born-digital, scan hoặc hybrid</strong>
      </div>
      <label>
        Số hiệu
        <input value={number} onChange={(e) => setNumber(e.target.value)} />
      </label>
      <label>
        Tiêu đề
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Loại văn bản
        <input value={docType} onChange={(e) => setDocType(e.target.value)} />
      </label>
      <label>
        Cơ quan ban hành
        <input
          value={authority}
          onChange={(e) => setAuthority(e.target.value)}
        />
      </label>
      <label>
        Ngày ban hành
        <input
          type="date"
          value={issued}
          onChange={(e) => setIssued(e.target.value)}
        />
      </label>
      <label>
        Ngày có hiệu lực
        <input
          type="date"
          value={effective}
          onChange={(e) => setEffective(e.target.value)}
        />
      </label>
      <label>
        Lĩnh vực
        <select
          value={uploadDomain}
          onChange={(e) => setUploadDomain(e.target.value)}
        >
          {domains.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label>
        PDF
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => setPdf(e.target.files?.[0] || null)}
        />
      </label>
      <button disabled={!pdf || busy} className="primary standalone">
        {busy ? "Đang tải…" : "Upload & OCR"}
      </button>
    </form>
  );
}
function Status({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? "online" : "offline"}>
      <i />
      {label}
    </span>
  );
}

function EvaluationPanel({ token }: { token: string }) {
  const [reports, setReports] = useState<Record<string, EvalReport>>({}),
    [running, setRunning] = useState(false);
  async function run() {
    setRunning(true);
    const entries = await Promise.all(
      ["L1", "L3", "L5", "L6", "L7"].map(
        async (p) =>
          [
            p,
            await fetch(`${API}/api/v1/admin/evaluations/${p}`, {
              method: "POST",
              headers: { Authorization: `Bearer ${token}` },
            }).then((r) => r.json()),
          ] as const,
      ),
    );
    setReports(Object.fromEntries(entries));
    setRunning(false);
  }
  return (
    <>
      <PageTitle
        eyebrow="EVALUATION LAB"
        title="Đo chất lượng, không đo cảm giác"
        copy="So sánh dense, hybrid, GraphRAG, multi-query và adaptive bằng citation, hit-rate, MRR và latency."
      />
      <div className="evalHero">
        <div>
          <strong>Benchmark suite</strong>
          <span>Dense → Hybrid → GraphRAG → Multi-query → Adaptive</span>
        </div>
        <button
          className="primary standalone"
          disabled={running || !token}
          onClick={run}
        >
          {running ? <span className="spinner" /> : <Play />}
          {running ? "Đang chạy" : "Chạy benchmark"}
        </button>
      </div>
      {Object.keys(reports).length === 0 ? (
        <div className="emptyEval">
          <BarChart3 />
          <strong>Chưa có benchmark trong phiên này</strong>
          <span>Nhấn chạy để benchmark 5 chiến lược RAG trên cùng bộ câu hỏi.</span>
        </div>
      ) : (
        <div className="evalGrid">
          {Object.values(reports).map((r) => (
            <div className="evalCard" key={r.pipeline}>
              <span className="pill">{r.pipeline}</span>
              <h3>{Math.round(r.citation_precision * 100)}%</h3>
              <p>Citation precision</p>
              <div>
                <span>Recall</span>
                <b>{Math.round(r.citation_recall * 100)}%</b>
              </div>
              <div>
                <span>Retrieval hit-rate</span>
                <b>{Math.round(r.retrieval_hit_rate * 100)}%</b>
              </div>
              <div>
                <span>MRR</span>
                <b>{r.mean_reciprocal_rank.toFixed(3)}</b>
              </div>
              <div>
                <span>P95 latency</span>
                <b>{r.latency_p95_ms} ms</b>
              </div>
              <div>
                <span>Cases</span>
                <b>{r.cases}</b>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
function PageTitle({
  eyebrow,
  title,
  copy,
}: {
  eyebrow: string;
  title: string;
  copy: string;
}) {
  return (
    <div className="pageTitle">
      <p className="eyebrow">
        <LayoutDashboard />
        {eyebrow}
      </p>
      <h1>{title}</h1>
      <p>{copy}</p>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// ---------------------------------------------------------------------------
// Pipeline view
//
// Two signals sit on every stage. The amber "flowed" state is read back from the
// execution_trace the API returns for a real query, so the counts are measured
// rather than illustrated; the green tick is the operator's own record that the
// stage has been verified against the runbook. A stage the chosen level never
// reaches is drawn dimmed rather than hidden — the gap between levels is the
// point of the view.
// ---------------------------------------------------------------------------

type Trace = { stage: string; count?: number; path?: string; enabled?: boolean };
type StageView = {
  ran: boolean;
  count?: number;
  facts: [string, string][];
};

const STAGES: {
  key: string;
  name: string;
  sub: string;
  why: string;
  tests: string;
}[] = [
  {
    key: "input",
    name: "Câu hỏi và bối cảnh",
    sub: "Người dùng nhập câu hỏi, chọn lĩnh vực và thời điểm áp dụng",
    why: "Thời điểm áp dụng là tham số quyết định, không phải tuỳ chọn. Cùng một câu hỏi hỏi cho năm 2020 và cho hôm nay phải ra hai văn bản khác nhau.",
    tests: "A1 · D1",
  },
  {
    key: "analysis",
    name: "Phân tích ý định",
    sub: "Nhận diện khái niệm pháp lý và đơn vị đo trong câu hỏi",
    why: "Nhận ra câu hỏi đang hỏi số giờ hay hỏi phần trăm tiền lương. Thiếu bước này thì điều khoản trùng từ nhưng khác đơn vị sẽ chen lên đầu.",
    tests: "C4",
  },
  {
    key: "expansion",
    name: "Mở rộng truy vấn",
    sub: "Sinh biến thể tiếng Việt bằng luật xác định, không nhờ mô hình",
    why: "Người dùng viết nghỉ hưu, văn bản viết hưởng lương hưu. Biến thể sinh bằng luật nên tái lập được và kiểm toán được — điều kiện bắt buộc với hệ pháp lý.",
    tests: "B6",
  },
  {
    key: "retrieval",
    name: "Truy hồi lai",
    sub: "pgvector ANN và full-text PostgreSQL, hợp nhất bằng RRF",
    why: "Vector bắt được ý nghĩa nhưng bỏ sót thuật ngữ chính xác; full-text thì ngược lại. Hợp nhất hai nhánh để không mất kiểu nào.",
    tests: "B1 · B3 · G3",
  },
  {
    key: "temporal",
    name: "Chốt hiệu lực",
    sub: "Loại văn bản chưa có hoặc đã hết hiệu lực tại thời điểm hỏi",
    why: "Embedding không biết khái niệm hiệu lực: Luật BHXH 2014 và 2024 nằm sát nhau trong không gian vector. Chỉ bộ lọc metadata mới tách được.",
    tests: "B2 · D1 · D2",
  },
  {
    key: "graph",
    name: "Mở rộng đồ thị",
    sub: "Duyệt quan hệ thay thế, sửa đổi, bổ sung, hướng dẫn trong Neo4j",
    why: "SQL vẫn là nguồn sự thật; Neo4j chỉ là hình chiếu. Đồ thị chết thì truy vấn vẫn chạy, chỉ mất phần mở rộng quan hệ.",
    tests: "E1 · E3 · E4",
  },
  {
    key: "rerank",
    name: "Rerank pháp lý",
    sub: "Chấm lại theo khái niệm, tham chiếu chéo và đơn vị đo",
    why: "Bước đóng góp nhiều nhất. Nó dọn đúng thứ mà truy hồi lai kéo nhầm về, nên L4 mới là mức mặc định chứ không phải L3.",
    tests: "B3 · B4 · H1",
  },
  {
    key: "generation",
    name: "Sinh câu trả lời có kiểm chứng",
    sub: "Mô hình viết câu trả lời, hệ đối chiếu lại từng trích dẫn",
    why: "Trích dẫn của mô hình được kiểm lại với tập căn cứ thật. Không khớp thì lùi về trích nguyên văn điều khoản; mô hình báo không đủ căn cứ thì từ chối hẳn.",
    tests: "C1 · C2 · C3",
  },
  {
    key: "answer",
    name: "Trả lời kèm căn cứ",
    sub: "Câu trả lời, trích dẫn tới cấp điểm, độ tin cậy và cảnh báo",
    why: "Đơn vị trích dẫn nhỏ nhất là điều khoản chứ không phải trang, nên người đọc kiểm chứng được tới đúng Điều, khoản, điểm.",
    tests: "C2 · I3",
  },
];

const PIPE_EXAMPLES: [string, string, string][] = [
  ["social_insurance", "", "Điều kiện hưởng lương hưu là gì?"],
  ["social_insurance", "2020-01-01", "Điều kiện hưởng lương hưu là gì?"],
  ["labor", "", "Quyền và nghĩa vụ về an toàn, vệ sinh lao động của người lao động là gì?"],
  ["labor", "", "Thủ tục đăng ký kết hôn như thế nào?"],
];

function readValidated(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem("pitrag-pipeline-validated") || "{}");
  } catch {
    return {};
  }
}

function deriveStages(result: Result | null): Record<string, StageView> {
  const out: Record<string, StageView> = {};
  for (const s of STAGES) out[s.key] = { ran: false, facts: [] };
  if (!result) return out;

  const d = result.diagnostics || {};
  const trace = (d.execution_trace as Trace[]) || [];
  const at = (name: string) => trace.find((t) => t.stage === name);

  out.input = {
    ran: true,
    facts: [["pipeline", result.pipeline_version]],
  };
  const concepts = result.query_analysis?.concepts || [];
  out.analysis = {
    ran: concepts.length > 0,
    count: concepts.length,
    facts: concepts.map((c) => ["khái niệm", c] as [string, string]),
  };

  const exp = at("query_expansion");
  const variants = (d.query_variants as string[]) || [];
  out.expansion = {
    ran: Boolean(exp),
    count: exp?.count ?? variants.length,
    facts: [],
  };

  const hyb = at("hybrid_retrieval");
  out.retrieval = {
    ran: Boolean(hyb) || result.retrieved_provisions.length > 0,
    count: hyb?.count ?? result.retrieved_provisions.length,
    facts: [["đường truy hồi", String(d.retrieval_path ?? "—")]],
  };

  const tg = at("temporal_guard");
  out.temporal = {
    ran: Boolean(tg?.enabled) || d.effective_date_checked === true,
    facts: [],
  };

  const gr = at("graph_expansion");
  out.graph = {
    ran: Boolean(gr),
    count: gr?.count,
    facts: gr?.path ? [["đường đồ thị", gr.path]] : [],
  };

  const reranked = result.retrieved_provisions.filter((r) => r.rerank_score > 0);
  out.rerank = {
    ran: reranked.length > 0,
    count: (d.candidate_count as number) ?? reranked.length,
    facts: [["điểm cao nhất", String(d.top_score ?? "—")]],
  };

  out.generation = {
    ran: true,
    count: d.evidence_count as number | undefined,
    facts: [
      ["chế độ", result.generation_mode],
      ["độ tin cậy", result.confidence.toFixed(2)],
    ],
  };

  out.answer = {
    ran: result.citations.length > 0,
    count: result.citations.length,
    facts: [["độ trễ", `${Math.round(result.latency_ms)} ms`]],
  };
  return out;
}

function PipelinePanel({ token }: { token: string }) {
  const [question, setQuestion] = useState(PIPE_EXAMPLES[0][2]),
    [domain, setDomain] = useState(""),
    [date, setDate] = useState(today),
    [level, setLevel] = useState("L7"),
    [result, setResult] = useState<Result | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [valid, setValid] = useState<Record<string, boolean>>(readValidated);

  function toggle(key: string) {
    setValid((prev) => {
      const next = { ...prev };
      if (next[key]) delete next[key];
      else next[key] = true;
      try {
        localStorage.setItem("pitrag-pipeline-validated", JSON.stringify(next));
      } catch {
        /* private browsing: the tick just doesn't persist */
      }
      return next;
    });
  }

  async function run() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const r = await fetch(`${API}/api/v1/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question,
          applicable_date: date,
          pipeline_level: level,
          ...(domain ? { domain } : {}),
        }),
      });
      if (!r.ok) throw new Error(`Truy vấn thất bại (HTTP ${r.status})`);
      setResult(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Có lỗi xảy ra");
    } finally {
      setLoading(false);
    }
  }

  const stages = deriveStages(result);
  const validCount = STAGES.filter((s) => valid[s.key]).length;
  const citedIds = new Set((result?.citations || []).map((c) => c.provision_id));

  return (
    <>
      <PageTitle
        eyebrow="PIPELINE TRUY VẤN"
        title="Câu hỏi đi qua những đâu"
        copy="Chạy một câu hỏi thật và xem từng chặng sáng lên với số liệu đo được từ execution_trace. Đánh dấu chặng nào đã tự kiểm chứng để biết mình đã nắm chắc phần nào."
      />

      {error && <div className="pipeError">{error}</div>}

      <div className="pipeRun">
        <div className="pipeRunTop">
          <Search size={17} color="#567066" />
          <input
            id="pipe-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !loading && token) run();
            }}
            placeholder="Nhập câu hỏi pháp luật…"
          />
        </div>
        <div className="pipeRunMeta">
          <span>
            <label htmlFor="pipe-domain">Lĩnh vực</label>
            <select
              id="pipe-domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            >
              <option value="">Tất cả lĩnh vực</option>
              {domains.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </span>
          <span>
            <label htmlFor="pipe-level">Mức pipeline</label>
            <select
              id="pipe-level"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
            >
              {Object.entries(pipelineInfo).map(([k, v]) => (
                <option key={k} value={k}>
                  {k} · {v}
                </option>
              ))}
            </select>
          </span>
          <span>
            <label htmlFor="pipe-date">Áp dụng ngày</label>
            <select
              id="pipe-date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            >
              <option value={today()}>{today()} (hôm nay)</option>
              <option value="2020-01-01">2020-01-01 (quá khứ)</option>
            </select>
          </span>
          <span>
            <button
              className="pipeAsk"
              onClick={() => run()}
              disabled={loading || !token}
            >
              {loading ? <i className="spinner" /> : <Play />}
              {loading ? "Đang chạy" : "Chạy pipeline"}
            </button>
          </span>
        </div>
        <div className="pipeChips">
          <span>THỬ NGAY</span>
          {PIPE_EXAMPLES.map(([, dt, q]) => (
            <button
              key={q + dt}
              onClick={() => {
                setDate(dt || today());
                setQuestion(q);
              }}
            >
              {q.length > 42 ? `${q.slice(0, 42)}…` : q}
              {dt === "2020-01-01" ? " · 2020" : ""}
            </button>
          ))}
        </div>
      </div>

      <div className="pipeWrap">
        <div className="pipeStages">
          {STAGES.map((s, i) => {
            const st = stages[s.key];
            const skipped = Boolean(result) && !st.ran;
            const prev = i > 0 ? stages[STAGES[i - 1].key] : null;
            return (
              <React.Fragment key={s.key}>
                {i > 0 && (
                  <div
                    className={`pipeLink ${prev?.ran && st.ran ? "flowed" : ""}`}
                  />
                )}
                <article
                  className="pipeStage"
                  data-ran={st.ran ? "1" : "0"}
                  data-skipped={skipped ? "1" : "0"}
                  data-valid={valid[s.key] ? "1" : "0"}
                >
                  <div className="pipeHead">
                    <span className="pipeNum">{i + 1}</span>
                    <span className="pipeName">
                      <strong>{s.name}</strong>
                      <span>{s.sub}</span>
                    </span>
                    <span className="pipeSignal">
                      {st.ran && st.count !== undefined && (
                        <span className="pipeCount">{st.count} mục</span>
                      )}
                      {st.ran && st.count === undefined && (
                        <span className="pipeCount">đã chạy</span>
                      )}
                      {skipped && (
                        <span className="pipeSkipTag">
                          {level} không dùng
                        </span>
                      )}
                      <button
                        className="pipeCheck"
                        data-on={valid[s.key] ? "1" : "0"}
                        onClick={() => toggle(s.key)}
                        title="Đánh dấu đã tự kiểm chứng chặng này"
                        aria-label={`Đánh dấu đã kiểm chứng: ${s.name}`}
                      >
                        <Check />
                      </button>
                    </span>
                  </div>
                  <div className="pipeBody">
                    {st.ran && st.facts.length > 0 && (
                      <div className="pipeFacts">
                        {st.facts.map(([k, v], n) => (
                          <span key={`${k}-${n}`}>
                            {k} <b>{v}</b>
                          </span>
                        ))}
                      </div>
                    )}
                    {s.key === "expansion" &&
                      st.ran &&
                      ((result?.diagnostics?.query_variants as string[]) || [])
                        .length > 0 && (
                        <div className="pipeVariants">
                          {(
                            (result?.diagnostics
                              ?.query_variants as string[]) || []
                          ).map((v, n) => (
                            <code key={n}>{v}</code>
                          ))}
                        </div>
                      )}
                    <p className="pipeWhy">{s.why}</p>
                    <span className="pipeTests">Kiểm chứng ở: {s.tests}</span>
                  </div>
                </article>
              </React.Fragment>
            );
          })}

          {result && result.retrieved_provisions.length > 0 && (
            <>
              <div className="sectionTitle">
                <div>
                  <BarChart3 size={14} /> Điểm số từng ứng viên qua các chặng
                </div>
                <span>{result.retrieved_provisions.length} ứng viên</span>
              </div>
              <div className="pipeTableWrap">
                <table className="pipeTable">
                  <thead>
                    <tr>
                      <th>Điều khoản</th>
                      <th>Vector</th>
                      <th>Từ khoá</th>
                      <th>Hợp nhất</th>
                      <th>Sau rerank</th>
                      <th>Lý do khớp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.retrieved_provisions.map((r) => {
                      const cited = citedIds.has(r.provision.id);
                      return (
                        <tr
                          key={r.provision.id}
                          className={cited ? "cited" : ""}
                        >
                          <td className="doc">
                            Điều {r.provision.article}
                            {cited && <span className="citedTag">trích dẫn</span>}
                            <small>
                              {r.provision.content.slice(0, 64)}
                              {r.provision.content.length > 64 ? "…" : ""}
                            </small>
                          </td>
                          <td className="n">{r.vector_score.toFixed(3)}</td>
                          <td className="n">{r.keyword_score.toFixed(3)}</td>
                          <td className="n">{r.fusion_score.toFixed(3)}</td>
                          <td className="n">{r.rerank_score.toFixed(3)}</td>
                          <td className="n">
                            {r.match_reasons.slice(0, 2).join(" · ") || "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="pipeNote">
                <ShieldCheck />
                Dòng nền xanh là điều khoản được đưa vào trích dẫn. So cột Hợp
                nhất với cột Sau rerank để thấy chính xác bước rerank đã đổi thứ
                hạng như thế nào.
              </p>
            </>
          )}
        </div>

        <aside className="pipeRail">
          <h3>Bạn đã nắm chắc phần nào</h3>
          <p>
            Tự đánh dấu sau khi kiểm chứng chặng đó theo sổ kiểm thử. Lưu trong
            trình duyệt này.
          </p>
          <div className="pipeMeter">
            <span>Đã kiểm chứng</span>
            <b>
              {validCount}/{STAGES.length}
            </b>
          </div>
          <div className="pipeBar">
            <i style={{ width: `${(validCount / STAGES.length) * 100}%` }} />
          </div>
          <div className="pipeLegend">
            <div>
              <em className="on" />
              <span>
                Viền xanh trái: bạn đã tự kiểm chứng chặng này.
              </span>
            </div>
            <div>
              <em className="ran" />
              <span>
                Mũi tên vàng: dữ liệu thật vừa chảy qua, số liệu lấy từ
                execution_trace của lần chạy.
              </span>
            </div>
            <div>
              <em className="skip" />
              <span>
                Chặng mờ: mức {level} không dùng tới. Đổi mức để thấy chặng nào
                bật lên.
              </span>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}

function MetadataForm({
  token,
  doc,
  onClose,
  onSaved,
}: {
  token: string;
  doc: AdminDoc;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [number, setNumber] = useState(doc.document_number),
    [title, setTitle] = useState(doc.title),
    [docType, setDocType] = useState(doc.document_type ?? ""),
    [authority, setAuthority] = useState(doc.issuing_authority ?? ""),
    [issued, setIssued] = useState(doc.issued_date ?? ""),
    [effective, setEffective] = useState(doc.effective_from ?? ""),
    [domain, setDomain] = useState(doc.domain),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    // Send only what changed: the endpoint treats an unset field as "leave it alone".
    const changes: Record<string, string> = {};
    const pairs: [string, string, string | undefined][] = [
      ["document_number", number, doc.document_number],
      ["title", title, doc.title],
      ["document_type", docType, doc.document_type],
      ["issuing_authority", authority, doc.issuing_authority],
      ["issued_date", issued, doc.issued_date],
      ["effective_from", effective, doc.effective_from],
      ["domain", domain, doc.domain],
    ];
    pairs.forEach(([key, next, before]) => {
      if (next && next !== before) changes[key] = next;
    });
    if (!Object.keys(changes).length) {
      setBusy(false);
      onClose();
      return;
    }
    let r: Response;
    try {
      r = await fetch(`${API}/api/v1/admin/documents/${doc.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(changes),
      });
    } catch {
      setBusy(false);
      setError("Không gọi được API.");
      return;
    }
    const body = await r
      .clone()
      .json()
      .catch(() => ({}) as Record<string, string>);
    setBusy(false);
    if (!r.ok) {
      setError(body.detail || `Lưu thất bại (HTTP ${r.status})`);
      return;
    }
    onSaved(
      `Đã sửa ${Object.keys(changes).length} trường · cần rebuild index để truy vấn thấy thay đổi`,
    );
  }

  return (
    <form className="ingestForm metaForm" onSubmit={submit}>
      <div>
        <FileCheck2 />
        <strong>Sửa thông tin văn bản</strong>
      </div>
      <label>
        Số hiệu
        <input value={number} onChange={(e) => setNumber(e.target.value)} />
      </label>
      <label>
        Loại văn bản
        <input value={docType} onChange={(e) => setDocType(e.target.value)} />
      </label>
      <label>
        Tiêu đề
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Cơ quan ban hành
        <input
          value={authority}
          onChange={(e) => setAuthority(e.target.value)}
        />
      </label>
      <label>
        Ngày ban hành
        <input
          type="date"
          value={issued}
          onChange={(e) => setIssued(e.target.value)}
        />
      </label>
      <label>
        Ngày có hiệu lực
        <input
          type="date"
          value={effective}
          onChange={(e) => setEffective(e.target.value)}
        />
      </label>
      <label>
        Lĩnh vực
        <select value={domain} onChange={(e) => setDomain(e.target.value)}>
          {domains.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="metaError">{error}</p>}
      <div className="metaActions">
        <button disabled={busy} className="primary standalone">
          {busy ? "Đang lưu…" : "Lưu thay đổi"}
        </button>
        <button type="button" className="tiny" onClick={onClose}>
          Huỷ
        </button>
      </div>
    </form>
  );
}


// Extraction quality, computed from the preview payload the API already returns.
// The numbers that matter after an OCR run are not "how many chunks" but whether the
// article sequence has holes and whether any two chunks carry the same citation label:
// a gap means content was lost, a repeated label means a citation points at two places.
function ExtractionQuality({ preview }: { preview: Preview }) {
  const numbers = preview.provisions
    .map((p) => Number(p.article))
    .filter((n) => Number.isInteger(n) && n > 0);
  const unique = Array.from(new Set(numbers)).sort((a, b) => a - b);
  const gaps: number[] = [];
  if (unique.length) {
    for (let n = unique[0]; n <= unique[unique.length - 1]; n++) {
      if (!unique.includes(n)) gaps.push(n);
    }
  }
  const nonNumeric = Array.from(
    new Set(
      preview.provisions
        .map((p) => p.article)
        .filter((a) => !Number.isInteger(Number(a))),
    ),
  );

  const seen = new Map<string, number>();
  preview.provisions.forEach((p) => {
    const key = `${p.article}.${p.clause ?? ""}.${p.point ?? ""}`;
    seen.set(key, (seen.get(key) ?? 0) + 1);
  });
  const duplicated = Array.from(seen.values()).filter((n) => n > 1).length;

  const byMethod = new Map<string, number>();
  preview.pages.forEach((pg) => {
    byMethod.set(
      pg.extraction_method,
      (byMethod.get(pg.extraction_method) ?? 0) + 1,
    );
  });
  const confidences = preview.pages
    .map((pg) => pg.confidence)
    .filter((c): c is number => c != null);
  const lowest = confidences.length ? Math.min(...confidences) : null;
  const thin = preview.pages.filter(
    (pg) => pg.extraction_method !== "ocr" && pg.text.length < 400,
  );
  const flagged = preview.provisions.filter(
    (pr) => pr.quality_flags.length > 0,
  ).length;

  const ok = !gaps.length && !nonNumeric.length && !duplicated && !thin.length;

  return (
    <div className="quality">
      <b>
        Chất lượng bóc tách
        <span className={`qualityTag ${ok ? "good" : "warn"}`}>
          {ok ? "không phát hiện vấn đề" : "có điểm cần xem"}
        </span>
      </b>
      <div className="qualityGrid">
        <QualityStat
          label="Điều liên tục"
          value={
            unique.length
              ? `${unique.length} · Điều ${unique[0]}–${unique[unique.length - 1]}`
              : "—"
          }
          bad={false}
        />
        <QualityStat
          label="Điều bị thiếu"
          value={gaps.length ? gaps.join(", ") : "không"}
          bad={gaps.length > 0}
        />
        <QualityStat
          label="Nhãn trích dẫn trùng"
          value={duplicated ? `${duplicated} nhóm` : "không"}
          bad={duplicated > 0}
        />
        <QualityStat
          label="Số điều đọc sai"
          value={nonNumeric.length ? nonNumeric.join(", ") : "không"}
          bad={nonNumeric.length > 0}
        />
        <QualityStat
          label="Trang theo cách bóc"
          value={Array.from(byMethod)
            .map(([m, n]) => `${n} ${m}`)
            .join(" · ")}
          bad={false}
        />
        <QualityStat
          label="Trang text mỏng, chưa OCR"
          value={
            thin.length
              ? thin.map((pg) => `trang ${pg.page_number}`).join(", ")
              : "không"
          }
          bad={thin.length > 0}
        />
        <QualityStat
          label="Confidence OCR thấp nhất"
          value={lowest == null ? "—" : `${(lowest * 100).toFixed(1)}%`}
          bad={lowest != null && lowest < 0.8}
        />
        <QualityStat
          label="Điều khoản có cảnh báo"
          value={flagged ? `${flagged}` : "không"}
          bad={false}
        />
      </div>
      <small className="qualityNote">
        Điều bị thiếu nghĩa là nội dung không vào được kho. Nhãn trùng nghĩa là
        hai đoạn cùng một số trích dẫn — người đọc không lần ngược được về đúng
        chỗ. Trang text mỏng mà chưa OCR thường là trang scan chỉ có con dấu chữ
        ký số.
      </small>
    </div>
  );
}

function QualityStat({
  label,
  value,
  bad,
}: {
  label: string;
  value: string;
  bad: boolean;
}) {
  return (
    <div className={`qualityStat ${bad ? "bad" : ""}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}


// The sign-in surface. Nothing here is pre-filled: the previous build shipped the demo
// account's password as a literal in the bundle, which handed every visitor the admin
// role. Credentials now travel only from this form to the login endpoint.
function LoginDialog({
  onClose,
  onToken,
}: {
  onClose: () => void;
  onToken: (token: string) => void;
}) {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    let r: Response;
    try {
      r = await fetch(`${API}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      setBusy(false);
      setError("Không gọi được API. Kiểm tra kết nối mạng.");
      return;
    }
    const body = await r
      .clone()
      .json()
      .catch(() => ({}) as Record<string, string>);
    setBusy(false);
    if (!r.ok || !body.access_token) {
      setError(
        r.status === 401
          ? "Email hoặc mật khẩu không đúng."
          : body.detail || `Đăng nhập thất bại (HTTP ${r.status})`,
      );
      return;
    }
    onToken(body.access_token as string);
  }

  return (
    <div
      className="loginOverlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form className="loginCard" onSubmit={submit}>
        <div className="loginHead">
          <ShieldCheck />
          <div>
            <strong>Đăng nhập</strong>
            <span>Tra cứu thì mở cho mọi người. Quản trị dữ liệu, pipeline và đánh giá cần tài khoản.</span>
          </div>
        </div>
        <label htmlFor="login-email">
          Email
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label htmlFor="login-password">
          Mật khẩu
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="loginError">{error}</p>}
        <div className="loginActions">
          <button className="primary standalone" disabled={busy}>
            {busy ? "Đang kiểm tra…" : "Đăng nhập"}
          </button>
          <button type="button" className="tiny" onClick={onClose}>
            Để sau
          </button>
        </div>
      </form>
    </div>
  );
}
