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

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
type View = "query" | "admin" | "evaluation";
type Citation = {
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

function App() {
  const [token, setToken] = useState(""),
    [view, setView] = useState<View>("query"),
    [question, setQuestion] = useState(examples[0][1]),
    [domain, setDomain] = useState("labor"),
    [date, setDate] = useState("2026-01-01"),
    [level, setLevel] = useState("L7");
  const [result, setResult] = useState<Result | null>(null),
    [compare, setCompare] = useState<Record<string, Result> | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "demo@legalrag.vn", password: "demo1234" }),
    })
      .then((r) => r.json())
      .then((x) => setToken(x.access_token))
      .catch(() => setError("Không thể kết nối API tại cổng 8000."));
  }, []);
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
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(body),
        },
      );
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
      <Header view={view} setView={setView} />
      <main>
        <Sidebar view={view} setView={setView} />
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
                      onClick={() => run(true)}
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
          {view === "admin" && <AdminPanel token={token} />}{" "}
          {view === "evaluation" && <EvaluationPanel token={token} />}
        </section>
      </main>
    </div>
  );
}
function Header({ view, setView }: { view: View; setView: (v: View) => void }) {
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
          </button>
        ))}
      </nav>
      <span className="version">
        <Share2 /> PGVECTOR + NEO4J · v0.4
      </span>
    </header>
  );
}
function Sidebar({
  view,
  setView,
}: {
  view: View;
  setView: (v: View) => void;
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
          className={`nav ${view === "admin" ? "active" : ""}`}
          onClick={() => setView("admin")}
        >
          <Database />
          <span>Quản trị dữ liệu</span>
        </button>
        <button
          className={`nav ${view === "evaluation" ? "active" : ""}`}
          onClick={() => setView("evaluation")}
        >
          <BarChart3 />
          <span>Evaluation Lab</span>
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
      document_type: "Nghị quyết",
      issuing_authority: "Cơ quan demo",
      issued_date: "2026-01-01",
      effective_from: "2026-02-01",
      domain: "labor",
    }).forEach(([k, v]) => form.append(k, v));
    form.append("file", pdf);
    const r = await fetch(`${API}/api/v1/admin/documents/uploads`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    const body = await r.json();
    setBusy(false);
    onDone(
      r.ok
        ? `Đã xếp hàng OCR · job ${body.job_id.slice(0, 8)}`
        : body.detail || "Upload thất bại",
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
