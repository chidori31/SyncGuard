type ErrorCode =
  | "NOT_FOUND"
  | "CONFLICT"
  | "UNAVAILABLE"
  | "HTTP"
  | "INVALID_RESPONSE"
  | "TIMEOUT"
  | "NETWORK";

export class ApiError extends Error {
  code: ErrorCode;
  constructor(code: ErrorCode, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

export async function api<T>(
  path: string,
  init?: RequestInit,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const controller = new AbortController();
  const caller = init?.signal;
  const cancel = () => controller.abort();
  if (caller?.aborted) throw new DOMException("Request aborted", "AbortError");
  caller?.addEventListener("abort", cancel, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? 60000);
  try {
    const response = await fetch(path, { ...init, signal: controller.signal });
    if (!response.ok) {
      if (response.status === 404)
        throw new ApiError("NOT_FOUND", "Запись не найдена. Обновите список.");
      if (response.status === 409)
        throw new ApiError(
          "CONFLICT",
          "Состояние записи уже изменилось. Обновите данные и повторите действие.",
        );
      if (response.status >= 500)
        throw new ApiError(
          "UNAVAILABLE",
          "Сервис временно недоступен. Проверьте запуск приложения и базы данных, затем повторите запрос.",
        );
      throw new ApiError(
        "HTTP",
        `Не удалось выполнить запрос (${response.status}). Обновите страницу и повторите действие.`,
      );
    }
    // Keep the deadline active until the body has been read and parsed.
    return await response.json();
  } catch (error) {
    if (caller?.aborted)
      throw new DOMException("Request aborted", "AbortError");
    if (timedOut)
      throw new ApiError(
        "TIMEOUT",
        "Сервис не ответил вовремя. Обновите данные перед повторным запуском: проверка могла завершиться на сервере.",
      );
    if (error instanceof ApiError) throw error;
    if (error instanceof SyntaxError)
      throw new ApiError(
        "INVALID_RESPONSE",
        "Сервис вернул некорректный ответ. Проверьте состояние приложения и повторите запрос.",
      );
    throw new ApiError(
      "NETWORK",
      "Нет связи с приложением. Проверьте, что оно запущено, и повторите запрос.",
    );
  } finally {
    clearTimeout(timer);
    caller?.removeEventListener("abort", cancel);
  }
}
