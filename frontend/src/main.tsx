import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import {
  Activity,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileCheck2,
  LayoutDashboard,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
  Workflow,
  X,
} from "lucide-react";
import "./styles.css";
import { IntegrationLab } from "./IntegrationLab";

type Integration = {
  id: string;
  name: string;
  status: string;
  last_check: string | null;
  last_successful_sync: string | null;
  entities_checked: number;
  open_incidents: number;
  business_value_at_risk: string;
};
type Incident = {
  id: string;
  title: string;
  description: string;
  type: string;
  severity: string;
  status: string;
  source_external_id: string;
  business_value_at_risk: string;
  currency: string;
  detected_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  timeline: { status: string; at: string }[];
  metadata: { expected_target: Record<string, unknown> };
};
type Rule = {
  id: string;
  name: string;
  maximum_delay: number;
  source_condition: Record<string, string>;
  source_entity_type: string;
  target_entity_type: string;
  match_strategy: string;
};
type Entity = {
  external_id: string;
  source: string;
  created_at: string;
  attributes: {
    amount: string;
    status?: string;
    customer_id: string;
    external_reference?: string;
    currency: string;
  };
};
type Evidence = {
  id: string;
  captured_at: string;
  source_entity: Entity;
  target_lookup_result: {
    complete: boolean;
    match_count: number;
    entities: Entity[];
  };
  connector_health: { source: boolean; target: boolean };
  rule_evaluation: { outcome: string; explanation: string; deadline: string };
  last_successful_observation: string | null;
};
type Detail = Incident & {
  integration: Integration;
  business_rule: Rule;
  evidence: Evidence[];
};
type Stats = {
  integrations: number;
  healthy: number;
  delayed: number;
  broken: number;
  unknown: number;
  open_incidents: number;
  business_value_at_risk: string;
};
type Data = {
  integrations: Integration[];
  incidents: Incident[];
  rules: Rule[];
  stats: Stats;
};

const money = (value: string | number, currency = "RUB") =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Number(value));
const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Пока нет данных";
const statusNames: Record<string, string> = {
  OPEN: "Открыт",
  ACKNOWLEDGED: "В работе",
  RESOLVED: "Решён",
  REOPENED: "Открыт повторно",
};
const outcomeNames: Record<string, string> = {
  missing_target: "Заказ отсутствует",
  wrong_amount: "Расхождение суммы",
  duplicate_target: "Дубли заказов",
  synchronization_delay: "Превышен срок",
  healthy_match: "Проверка пройдена",
};
function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value.toLowerCase()}`}>
      <i />
      {statusNames[value] || value}
    </span>
  );
}
function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="empty">
      <ShieldCheck size={36} />
      <p>{children}</p>
    </div>
  );
}

function App() {
  const [route, setRoute] = useState(location.hash.slice(1) || "/");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const [scenario, setScenario] = useState("baseline");
  const [transport, setTransport] = useState("http");
  useEffect(() => {
    const change = () => {
      setRoute(location.hash.slice(1) || "/");
      setError("");
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api<Integration[]>("/api/integrations", { signal: controller.signal }),
      api<Incident[]>("/api/incidents", { signal: controller.signal }),
      api<Rule[]>("/api/rules", { signal: controller.signal }),
      api<Stats>("/api/dashboard", { signal: controller.signal }),
    ])
      .then(([integrations, incidents, rules, stats]) => {
        setData({ integrations, incidents, rules, stats });
        setError("");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [version]);
  const detailId = route.startsWith("/incidents/") ? route.split("/")[2] : null;
  useEffect(() => {
    setDetail(null);
    if (!detailId) {
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    api<Detail>(`/api/incidents/${encodeURIComponent(detailId)}`, {
      signal: controller.signal,
    })
      .then(setDetail)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [detailId, version]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  async function run() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{
        incidents_created: number;
        entities_checked: number;
        status: string;
      }>("/api/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario, transport }),
      });
      setToast(
        `Проверено сущностей: ${result.entities_checked}. Новых инцидентов: ${result.incidents_created}. Статус: ${result.status}.`,
      );
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function ack() {
    if (!detail) return;
    setBusy(true);
    try {
      await api(`/api/incidents/${detail.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "ACKNOWLEDGED" }),
      });
      setVersion((v) => v + 1);
      setToast(
        "Инцидент взят в работу. Проверка восстановления выполняется при следующем запуске.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const nav = [
    { path: "/", label: "Обзор", icon: LayoutDashboard },
    { path: "/integrations", label: "Интеграции", icon: Workflow },
    { path: "/incidents", label: "Инциденты", icon: TriangleAlert },
    { path: "/rules", label: "Бизнес-правила", icon: FileCheck2 },
  ];
  const page = nav.find((n) =>
    n.path === "/" ? route === "/" : route.startsWith(n.path),
  );
  const filtered =
    data?.incidents.filter(
      (i) =>
        (filter === "ALL" || i.status === filter) &&
        `${i.title} ${i.source_external_id}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) || [];
  const table = (recent = false) => (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Инцидент</th>
            <th>Критичность</th>
            <th>Статус</th>
            <th className="right">Под риском</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(recent ? (data?.incidents || []).slice(0, 5) : filtered).map(
            (i) => (
              <tr key={i.id}>
                <td>
                  <a className="incident-link" href={`#/incidents/${i.id}`}>
                    {i.title}
                  </a>
                  <span className="subline">
                    Bitrix24 → 1С <span>•</span> {date(i.detected_at)}
                  </span>
                </td>
                <td>
                  <Badge value={i.severity} />
                </td>
                <td>
                  <span className={`state-text ${i.status.toLowerCase()}`}>
                    {statusNames[i.status]}
                  </span>
                </td>
                <td className="right risk-number">
                  {money(i.business_value_at_risk, i.currency)}
                </td>
                <td>
                  <a
                    className="icon-button"
                    aria-label={`Открыть инцидент ${i.source_external_id}`}
                    href={`#/incidents/${i.id}`}
                  >
                    <ChevronRight size={18} />
                  </a>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      {!(recent ? data?.incidents.length : filtered.length) && (
        <Empty>
          {data?.incidents.length
            ? "Нет инцидентов по выбранным фильтрам."
            : "Инцидентов пока нет. Запустите демо-проверку."}
        </Empty>
      )}
    </div>
  );
  const integrationCard = (i: Integration) => (
    <article className="panel integration-panel" key={i.id}>
      <div className="panel-heading">
        <div className="integration-title">
          <span className="integration-icon">
            <ArrowDownUp size={23} />
          </span>
          <div>
            <h3>{i.name}</h3>
            <p>Сделки и заказы клиентов</p>
          </div>
        </div>
        <Badge value={i.status} />
      </div>
      <div className="system-flow">
        <div>
          <span className="system-logo bitrix">b24</span>
          <strong>Bitrix24</strong>
          <small>Демо-коннектор</small>
        </div>
        <div className="flow-line">
          <span />
          <ArrowRight size={19} />
          <span />
        </div>
        <div>
          <span className="system-logo onec">1C</span>
          <strong>1С:Предприятие</strong>
          <small>Демо-коннектор</small>
        </div>
      </div>
      <div className={`integration-notice ${i.status.toLowerCase()}`}>
        <TriangleAlert size={16} />
        <span>
          {i.open_incidents
            ? `${i.open_incidents} инцидента требуют внимания`
            : i.status === "UNKNOWN"
              ? "Результат проверки неизвестен"
              : "Активных инцидентов нет"}
        </span>
        <strong>{money(i.business_value_at_risk)}</strong>
      </div>
      <div className="integration-meta">
        <div>
          <span>Последняя проверка</span>
          <strong>{date(i.last_check)}</strong>
        </div>
        <div>
          <span>Проверено сущностей</span>
          <strong>{i.entities_checked}</strong>
        </div>
      </div>
      <div className="panel-foot">
        Последняя полностью успешная проверка{" "}
        <span>{date(i.last_successful_sync)}</span>
      </div>
    </article>
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a href="#/" className="brand">
          <span>
            <ShieldCheck size={24} />
          </span>
          SyncGuard
        </a>
        <div className="workspace">
          <span className="workspace-avatar">Д</span>
          <div>
            <strong>Демо-компания</strong>
            <small>Рабочее пространство</small>
          </div>
          <span className="demo-dot" />
        </div>
        <p className="nav-label">МОНИТОРИНГ</p>
        <nav>
          {nav.map(({ path, label, icon: Icon }) => (
            <a
              key={path}
              href={`#${path}`}
              className={page?.path === path ? "active" : ""}
            >
              <Icon size={19} />
              {label}
              {path === "/incidents" && !!data?.stats.open_incidents && (
                <b>{data.stats.open_incidents}</b>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={21} />
          <strong>Под контролем — результат</strong>
          <p>Проверяем, что бизнес-процесс завершился правильно.</p>
          <a href="#/rules">
            Как работают правила <ArrowRight size={14} />
          </a>
        </div>
        <div className="sidebar-bottom">
          <span className="demo-avatar">SG</span>
          <div>
            <strong>Локальное демо</strong>
            <small>HTTP / Memory · v0.3</small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Рабочее пространство <ChevronRight size={14} />{" "}
            <strong>{detailId ? "Инцидент" : page?.label || "Страница"}</strong>
          </div>
          <span className="environment">
            <i /> Демо-среда
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">INTEGRATION RELIABILITY PLATFORM</div>
              <h1>
                {detailId
                  ? "Детали инцидента"
                  : page?.path === "/"
                    ? "Обзор интеграций"
                    : page?.label || "Страница не найдена"}
              </h1>
              <p>
                {detailId
                  ? "Факты, бизнес-правило и история обнаружения."
                  : "Техническое соединение работает. А бизнес-процесс?"}
              </p>
            </div>
            <button className="primary" disabled={busy} onClick={run}>
              {busy ? (
                <RefreshCw className="spin" size={17} />
              ) : (
                <Play size={16} />
              )}{" "}
              {busy ? "Проверяем…" : "Запустить демо-проверку"}
            </button>
          </div>
          {(route === "/" || route === "/integrations") && (
            <IntegrationLab
              scenario={scenario}
              transport={transport}
              onScenario={setScenario}
              onTransport={setTransport}
              busy={busy}
              version={version}
              integrationId={data?.integrations[0]?.id}
            />
          )}
          {error && (
            <div role="alert" className="error">
              <TriangleAlert size={18} />
              <span>{error}</span>
              <button onClick={() => setVersion((v) => v + 1)}>
                Повторить
              </button>
            </div>
          )}
          {toast && (
            <div className="toast" role="status">
              <CheckCircle2 size={18} />
              {toast}
              <button
                aria-label="Закрыть уведомление"
                onClick={() => setToast("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {!data && !error && <Empty>Загружаем данные…</Empty>}
          {data && !detailId && page?.path === "/" && (
            <>
              <div className="metrics">
                {[
                  {
                    label: "Интеграции",
                    value: data.stats.integrations,
                    icon: Workflow,
                    color: "purple",
                  },
                  {
                    label: "Здоровые",
                    value: data.stats.healthy,
                    icon: CheckCircle2,
                    color: "green",
                  },
                  {
                    label: "С задержкой",
                    value: data.stats.delayed,
                    icon: Clock3,
                    color: "amber",
                  },
                  {
                    label: "Нарушены",
                    value: data.stats.broken,
                    icon: Activity,
                    color: "red",
                  },
                  {
                    label: "Открытые инциденты",
                    value: data.stats.open_incidents,
                    icon: TriangleAlert,
                    color: "red",
                  },
                  {
                    label: "Бизнес-сумма под риском",
                    value: money(data.stats.business_value_at_risk),
                    icon: ShieldCheck,
                    color: "purple",
                  },
                ].map((m, i) => (
                  <div className={`metric metric-${i}`} key={m.label}>
                    <span className={`metric-icon ${m.color}`}>
                      <m.icon size={17} />
                    </span>
                    <span className="metric-label">{m.label}</span>
                    <strong>{m.value}</strong>
                    <small>
                      {i === 5
                        ? "Сумма активных рисков"
                        : "По последней проверке"}
                    </small>
                  </div>
                ))}
              </div>
              {data.stats.unknown > 0 && (
                <div className="error">
                  Интеграций с неизвестным состоянием: {data.stats.unknown}.
                  Выполните повторную проверку.
                </div>
              )}
              <div className="section-title">
                <h2>Состояние интеграций</h2>
                <a href="#/integrations">
                  Все интеграции <ArrowRight size={15} />
                </a>
              </div>
              <div className="overview-grid">
                {data.integrations.length ? (
                  data.integrations.map(integrationCard)
                ) : (
                  <div className="panel">
                    <Empty>
                      Запустите демо: создадим интеграцию и проверим три сделки.
                    </Empty>
                  </div>
                )}
                <article className="panel rule-summary">
                  <div className="rule-label">
                    <FileCheck2 size={17} /> БИЗНЕС-ПРАВИЛО
                  </div>
                  <h3>
                    Сделка закрыта.
                    <br />
                    Заказ должен появиться.
                  </h3>
                  <p>
                    Каждая успешная сделка в Bitrix24 должна стать заказом в 1С
                    в течение пяти минут.
                  </p>
                  <div className="rule-step">
                    <span>01</span>
                    <div>
                      <strong>Сделка → WON</strong>
                      <small>Событие в исходной системе</small>
                    </div>
                    <Check size={16} />
                  </div>
                  <div className="rule-step">
                    <span>02</span>
                    <div>
                      <strong>Заказ → существует</strong>
                      <small>Сумма и ссылка совпадают</small>
                    </div>
                    <Clock3 size={16} />
                  </div>
                  <div className="rule-bottom">
                    <span>
                      <Clock3 size={14} /> SLA · 5 минут
                    </span>
                    <a href="#/rules">
                      Правила <ArrowRight size={14} />
                    </a>
                  </div>
                </article>
              </div>
              <section className="panel incidents-panel">
                <div className="panel-heading">
                  <div className="heading-count">
                    <h2>Последние инциденты</h2>
                    <span>{data.incidents.length}</span>
                  </div>
                  <a href="#/incidents">
                    Смотреть все <ArrowRight size={15} />
                  </a>
                </div>
                {table(true)}
              </section>
              <div className="trust-note">
                <ShieldCheck size={15} /> Нарушения определяет код по
                бизнес-правилам. Каждое решение подтверждено данными.
              </div>
            </>
          )}
          {data && !detailId && page?.path === "/integrations" && (
            <div className="integrations-grid">
              {data.integrations.map(integrationCard)}
              {!data.integrations.length && (
                <Empty>Запустите демо-проверку для создания интеграции.</Empty>
              )}
            </div>
          )}
          {data && !detailId && page?.path === "/incidents" && (
            <section className="panel incidents-panel">
              <div className="filters">
                <label className="search">
                  <Search size={17} />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Поиск по сделке или названию"
                    aria-label="Поиск инцидентов"
                  />
                </label>
                <select
                  aria-label="Статус инцидентов"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="ALL">Все статусы</option>
                  <option value="OPEN">Открытые</option>
                  <option value="ACKNOWLEDGED">В работе</option>
                  <option value="RESOLVED">Решённые</option>
                </select>
                <span>{filtered.length} записей</span>
              </div>
              {table()}
            </section>
          )}
          {data && !detailId && page?.path === "/rules" && (
            <div className="rules-list">
              {data.rules.map((rule) => (
                <article className="panel" key={rule.id}>
                  <div className="panel-heading">
                    <h2>{rule.name}</h2>
                    <Badge value="HEALTHY" />
                  </div>
                  <div className="rule-detail">
                    <div>
                      <small>ЕСЛИ</small>
                      <h3>Deal.status = {rule.source_condition.status}</h3>
                      <p>Сделка завершена в Bitrix24</p>
                    </div>
                    <ArrowRight />
                    <div>
                      <small>
                        ТО В ТЕЧЕНИЕ {rule.maximum_delay / 60} МИНУТ
                      </small>
                      <h3>CustomerOrder существует</h3>
                      <p>external_reference = Deal.external_id</p>
                    </div>
                  </div>
                  <div className="rule-explainer">
                    Проверки: наличие заказа, отсутствие дублей, совпадение
                    суммы и валюты, срок создания. До истечения срока отсутствие
                    заказа не создаёт инцидент.
                  </div>
                </article>
              ))}
              {!data.rules.length && (
                <Empty>Правило появится после запуска демо.</Empty>
              )}
            </div>
          )}
          {detailId && detailLoading && (
            <Empty>Загружаем доказательства…</Empty>
          )}
          {detailId && detail && !detailLoading && (
            <>
              <a href="#/incidents" className="back-link">
                <ArrowLeft size={16} /> Все инциденты
              </a>
              <article className="panel incident-hero">
                <div className="incident-hero-top">
                  <div>
                    <Badge value={detail.severity} />{" "}
                    <Badge value={detail.status} />
                  </div>
                  {detail.status === "OPEN" && (
                    <button className="secondary" onClick={ack} disabled={busy}>
                      <Check size={16} /> Взять в работу
                    </button>
                  )}
                </div>
                <h2>{detail.title}</h2>
                <p>{detail.description}</p>
                <div className="incident-facts">
                  <div>
                    <small>Бизнес-сумма под риском</small>
                    <strong className="risk-large">
                      {money(detail.business_value_at_risk, detail.currency)}
                    </strong>
                  </div>
                  <div>
                    <small>Интеграция</small>
                    <strong>{detail.integration.name}</strong>
                  </div>
                  <div>
                    <small>Обнаружен</small>
                    <strong>{date(detail.detected_at)}</strong>
                  </div>
                  <div>
                    <small>Последнее обнаружение</small>
                    <strong>{date(detail.last_seen_at)}</strong>
                  </div>
                </div>
              </article>
              {detail.evidence[0] && (
                <EvidenceView evidence={detail.evidence[0]} detail={detail} />
              )}
              <div className="detail-grid">
                <section className="panel padded">
                  <h2>История инцидента</h2>
                  <div className="timeline">
                    {detail.timeline.map((item, index) => (
                      <div key={index}>
                        <i />
                        <strong>
                          {statusNames[item.status] || item.status}
                        </strong>
                        <span>{date(item.at)}</span>
                      </div>
                    ))}
                  </div>
                </section>
                <section className="panel padded">
                  <h2>Правило обнаружения</h2>
                  <p>{detail.business_rule.name}</p>
                  <div className="code-rule">
                    IF Deal.status == WON
                    <br />
                    THEN CustomerOrder.external_reference
                    <br />
                    == Deal.external_id
                    <br />
                    WITHIN {detail.business_rule.maximum_delay} seconds
                  </div>
                  <p className="small muted">
                    Решение rule engine ·{" "}
                    {outcomeNames[detail.type] || detail.type}
                  </p>
                </section>
              </div>
              <section className="panel padded">
                <h2>
                  Доказательства проверок{" "}
                  <span className="muted">
                    · последние {detail.evidence.length}
                  </span>
                </h2>
                <p className="small muted">
                  Нормализованные данные, полный результат поиска и состояние
                  коннекторов.
                </p>
                {detail.evidence.map((e, index) => (
                  <details key={e.id}>
                    <summary>
                      {date(e.captured_at)}{" "}
                      <span>
                        {index === 0
                          ? "Последняя проверка"
                          : outcomeNames[e.rule_evaluation.outcome] ||
                            e.rule_evaluation.outcome}
                      </span>
                    </summary>
                    <pre>{JSON.stringify(e, null, 2)}</pre>
                  </details>
                ))}
              </section>
            </>
          )}
          {!page && !detailId && (
            <Empty>Такой страницы нет. Перейдите в обзор через меню.</Empty>
          )}
          <footer>
            <span>SyncGuard</span>
            <span>Демо Bitrix24 ↔ 1С · Проверка по запросу</span>
            <a
              href="/openapi.json"
              target="_blank"
              rel="noreferrer"
              className="api-doc-link"
            >
              <CircleHelp size={14} /> API
            </a>
          </footer>
        </main>
      </div>
    </div>
  );
}

function EvidenceView({
  evidence: e,
  detail,
}: {
  evidence: Evidence;
  detail: Detail;
}) {
  return (
    <>
      <div className="section-title">
        <h2>Почему создан инцидент</h2>
        <span className="muted small">{date(e.captured_at)}</span>
      </div>
      <div className="detail-grid">
        <section className="panel padded">
          <div className="evidence-heading">
            <span className="system-logo bitrix small-logo">b24</span>
            <h3>Исходная сделка #{e.source_entity.external_id}</h3>
            <Badge value={e.connector_health.source ? "HEALTHY" : "UNKNOWN"} />
          </div>
          <dl>
            <div>
              <dt>Статус сделки</dt>
              <dd>{e.source_entity.attributes.status}</dd>
            </div>
            <div>
              <dt>Сумма</dt>
              <dd>
                {money(
                  e.source_entity.attributes.amount,
                  e.source_entity.attributes.currency,
                )}
              </dd>
            </div>
            <div>
              <dt>ID контрагента</dt>
              <dd>{e.source_entity.attributes.customer_id}</dd>
            </div>
            <div>
              <dt>Крайний срок заказа</dt>
              <dd>{date(e.rule_evaluation.deadline)}</dd>
            </div>
          </dl>
        </section>
        <section className="panel padded">
          <div className="evidence-heading">
            <span className="system-logo onec small-logo">1C</span>
            <h3>Поиск заказа в 1С</h3>
            <Badge value={e.connector_health.target ? "HEALTHY" : "UNKNOWN"} />
          </div>
          <dl>
            <div>
              <dt>Внешняя ссылка</dt>
              <dd>{detail.source_external_id}</dd>
            </div>
            <div>
              <dt>Найдено заказов</dt>
              <dd>{e.target_lookup_result.match_count}</dd>
            </div>
            <div>
              <dt>Поиск завершён</dt>
              <dd>{e.target_lookup_result.complete ? "Да" : "Нет"}</dd>
            </div>
            {e.target_lookup_result.entities.map((t) => (
              <div key={t.external_id}>
                <dt>{t.external_id}</dt>
                <dd>{money(t.attributes.amount, t.attributes.currency)}</dd>
              </div>
            ))}
            <div>
              <dt>Последнее успешное наблюдение</dt>
              <dd>{date(e.last_successful_observation)}</dd>
            </div>
          </dl>
        </section>
      </div>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
