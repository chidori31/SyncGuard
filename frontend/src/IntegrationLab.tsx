import { useEffect, useState } from "react";
import { api } from "./api";
import {
  ArrowRight,
  ArrowLeft,
  Cable,
  CheckCircle2,
  Clock3,
  TriangleAlert,
} from "lucide-react";

type Scenario = { id: string; name: string; description: string };
type Metrics = {
  requests?: number;
  pages?: number;
  retries?: number;
  complete?: boolean;
};
type Observation = {
  id: string;
  source_external_id: string;
  outcome: string;
  data: {
    source_entity?: {
      attributes: { status: string; amount: string; currency: string };
    };
    target_lookup_result?: { match_count: number; complete: boolean };
    rule_evaluation?: { value_at_risk: string; explanation: string };
  };
};
type Run = {
  id: string;
  scenario: string;
  transport: string;
  status: string;
  completed_at: string;
  entities_checked: number;
  incidents_created: number;
  diagnostics: {
    connector_health?: { source: boolean; target: boolean };
    failure_phase?: string;
    source?: Metrics;
    target?: Metrics;
  };
  observations: Observation[];
};
const outcomes: Record<string, string> = {
  healthy_match: "Соответствует правилу",
  missing_target: "Заказ отсутствует",
  duplicate_target: "Дубль заказа",
  wrong_amount: "Суммы различаются",
  synchronization_delay: "Заказ создан поздно",
  pending: "Ожидание в пределах SLA",
  unknown: "Не удалось проверить",
  not_applicable: "Правило не применяется",
};

export function IntegrationLab({
  scenario,
  transport,
  onScenario,
  onTransport,
  version,
  integrationId,
  busy,
}: {
  scenario: string;
  transport: string;
  onScenario: (value: string) => void;
  onTransport: (value: string) => void;
  version: number;
  integrationId?: string;
  busy: boolean;
}) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Scenario[]>("/api/demo/scenarios", { signal: controller.signal })
      .then(setScenarios)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!integrationId) return;
    const controller = new AbortController();
    api<Run[]>(`/api/integrations/${integrationId}/checks?limit=10`, {
      signal: controller.signal,
    })
      .then((rows) => {
        setRuns(rows);
        setError("");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [integrationId, version]);
  const latest = runs[0];
  return (
    <section
      className="panel lab-panel"
      aria-label="Стенд взаимодействия систем"
    >
      <div className="panel-heading">
        <div>
          <h2>
            <Cable size={17} /> Стенд взаимодействия систем
          </h2>
          <p>
            Синтетические данные · выберите ситуацию и запустите проверку
            кнопкой сверху.
          </p>
        </div>
        <span className="lab-mode">
          Bitrix24 <ArrowRight size={12} /> SyncGuard <ArrowLeft size={12} /> 1С
        </span>
      </div>
      <div className="lab-controls">
        <label>
          Сценарий
          <select
            aria-label="Сценарий проверки"
            value={scenario}
            disabled={busy}
            onChange={(e) => onScenario(e.target.value)}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Источник данных
          <select
            aria-label="Транспорт проверки"
            value={transport}
            disabled={busy}
            onChange={(e) => onTransport(e.target.value)}
          >
            <option value="http">HTTP-симуляторы API</option>
            <option value="memory">Данные в памяти</option>
          </select>
        </label>
        <p>{scenarios.find((s) => s.id === scenario)?.description}</p>
      </div>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {latest ? (
        <>
          <div className="lab-last">
            <span>
              <Clock3 size={14} /> Последняя проверка:{" "}
              {new Date(latest.completed_at).toLocaleString("ru-RU")}
            </span>
            <strong>{latest.status}</strong>
            <span>
              {latest.transport === "http" ? "HTTP" : "В памяти"} ·{" "}
              {scenarios.find((s) => s.id === latest.scenario)?.name ||
                latest.scenario}
            </span>
          </div>
          <div className="lab-network">
            <span>
              Bitrix24:{" "}
              {latest.diagnostics.connector_health?.source
                ? "прочитан"
                : "не проверен"}
            </span>
            <span>
              1С:{" "}
              {latest.diagnostics.connector_health?.target
                ? "прочитана"
                : "не проверена"}
            </span>
            <span>
              HTTP-запросов:{" "}
              {(latest.diagnostics.source?.requests || 0) +
                (latest.diagnostics.target?.requests || 0)}
            </span>
            <span>
              Страниц:{" "}
              {(latest.diagnostics.source?.pages || 0) +
                (latest.diagnostics.target?.pages || 0)}
            </span>
            <span>
              Повторов:{" "}
              {(latest.diagnostics.source?.retries || 0) +
                (latest.diagnostics.target?.retries || 0)}
            </span>
          </div>
          {latest.status === "UNKNOWN" && (
            <p className="lab-unknown">
              <TriangleAlert size={16} /> Проверка не завершена. Ранее открытые
              инциденты и суммы риска сохранены.
            </p>
          )}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Источник</th>
                  <th>Сумма сделки</th>
                  <th>Заказов в 1С</th>
                  <th>Результат правила</th>
                </tr>
              </thead>
              <tbody>
                {latest.observations.map((o) => (
                  <tr key={o.id}>
                    <td>
                      {o.source_external_id === "__connector__"
                        ? "Коннектор"
                        : `Сделка #${o.source_external_id}`}
                    </td>
                    <td>
                      {o.data.source_entity
                        ? new Intl.NumberFormat("ru-RU", {
                            style: "currency",
                            currency: o.data.source_entity.attributes.currency,
                            maximumFractionDigits: 2,
                          }).format(
                            Number(o.data.source_entity.attributes.amount),
                          )
                        : "—"}
                    </td>
                    <td>
                      {o.data.target_lookup_result?.match_count ?? "Неизвестно"}
                    </td>
                    <td>
                      <span
                        className={`lab-outcome ${o.outcome === "healthy_match" ? "good" : ""}`}
                      >
                        {o.outcome === "healthy_match" ? (
                          <CheckCircle2 size={14} />
                        ) : (
                          <Clock3 size={14} />
                        )}{" "}
                        {outcomes[o.outcome] || o.outcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="lab-history">
            <summary>История проверок · {runs.length}</summary>
            {runs.map((run) => (
              <div className="lab-history-row" key={run.id}>
                <span>
                  {new Date(run.completed_at).toLocaleString("ru-RU")}
                </span>
                <span>
                  {scenarios.find((s) => s.id === run.scenario)?.name ||
                    run.scenario}
                </span>
                <span>{run.transport}</span>
                <strong>{run.status}</strong>
                <span>Новых инцидентов: {run.incidents_created}</span>
              </div>
            ))}
          </details>
        </>
      ) : (
        <p className="lab-empty">
          История появится после первой проверки. Для сетевого теста выберите
          HTTP-симуляторы.
        </p>
      )}
    </section>
  );
}
