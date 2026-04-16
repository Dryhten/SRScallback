const state = {
  routes: [],
  deliveries: [],
  failures: [],
  editingRouteId: null,
};

const views = {
  routes: document.getElementById("routesView"),
  deliveries: document.getElementById("deliveriesView"),
  failures: document.getElementById("failuresView"),
};

const sessionUsername = document.getElementById("sessionUsername");
let adminToken = localStorage.getItem("adminToken") || "";

function clearSession() {
  adminToken = "";
  localStorage.removeItem("adminToken");
  localStorage.removeItem("adminUsername");
}

function redirectToLogin(reason) {
  clearSession();
  const q = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  window.location.replace(`/login${q}`);
}

document.getElementById("logoutButton").addEventListener("click", () => {
  clearSession();
  window.location.replace("/login");
});

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    Object.values(views).forEach((view) => view.classList.remove("active"));
    views[button.dataset.view].classList.add("active");
  });
});

document.getElementById("newRouteButton").addEventListener("click", () => {
  state.editingRouteId = null;
  renderRouteForm();
});

document.getElementById("deliveryStatusFilter").addEventListener("change", refreshDeliveries);

function authHeaders() {
  return adminToken ? { Authorization: `Bearer ${adminToken}` } : {};
}

async function readApiError(response) {
  const text = await response.text();
  if (!text) {
    return `请求失败（${response.status}）`;
  }
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") {
      return data.detail;
    }
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => (typeof item === "object" && item.msg ? item.msg : String(item))).join("；");
    }
  } catch {
    /* ignore */
  }
  return text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
    ...options,
  });
  if (response.status === 401) {
    redirectToLogin("session");
    throw new Error("未授权或会话已失效");
  }
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function escapeHtml(value) {
  return (value ?? "").toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function statusTag(status) {
  const map = {
    pending: "warning",
    retrying: "warning",
    processing: "warning",
    succeeded: "success",
    failed: "danger",
  };
  return `<span class="tag ${map[status] || ""}">${escapeHtml(status)}</span>`;
}

/** 兼容 raw（原始 SRS 体）与 extended 两种投递 payload 结构 */
function deliveryPayloadEventType(payload) {
  if (!payload || typeof payload !== "object") {
    return "—";
  }
  const t = payload.eventType ?? payload.action;
  return t ? String(t) : "—";
}

function extractDeliveryStreamContext(payload) {
  if (!payload || typeof payload !== "object") {
    return { vhost: null, app: null, stream: null };
  }
  const sc = payload.streamContext;
  if (sc && typeof sc === "object") {
    return {
      vhost: sc.vhost ?? null,
      app: sc.app ?? null,
      stream: sc.stream ?? null,
    };
  }
  return {
    vhost: payload.vhost ?? null,
    app: payload.app ?? null,
    stream: payload.stream ?? null,
  };
}

function formatStreamPathLabel(ctx) {
  const vhostRaw = ctx.vhost;
  const vhost = vhostRaw && vhostRaw !== "__defaultVhost__" ? vhostRaw : null;
  const app = (ctx.app ?? "").trim();
  const stream = (ctx.stream ?? "").trim();
  if (!vhost && !app && !stream) {
    return null;
  }
  const parts = [];
  if (vhost) {
    parts.push(vhost);
  }
  if (app) {
    parts.push(app);
  }
  if (stream) {
    parts.push(stream);
  }
  return parts.join(" / ");
}

function eventTypeTag(label) {
  return `<span class="tag tag-event">${escapeHtml(label)}</span>`;
}

function renderDeliveryEventCell(delivery) {
  const payload = delivery.payload || {};
  const eventLabel = deliveryPayloadEventType(payload);
  const path = formatStreamPathLabel(extractDeliveryStreamContext(payload));
  const routeName = delivery.routeName || delivery.routeId || "—";
  const pathPart = path
    ? `<span class="delivery-event-path-inline" title="${escapeHtml(path)}">${escapeHtml(path)}</span>`
    : '<span class="delivery-event-path-inline delivery-event-path--empty">无流</span>';
  return `
    <div class="delivery-event delivery-event--compact">
      <div class="delivery-event-line1">
        ${eventTypeTag(eventLabel)}
        <span class="delivery-event-sep" aria-hidden="true">·</span>
        ${pathPart}
      </div>
      <div class="delivery-event-line2">
        <span class="delivery-meta-label">路由</span>
        <span class="delivery-route-name">${escapeHtml(routeName)}</span>
      </div>
    </div>
  `;
}

const DELIVERY_STATUS_LABELS = {
  pending: "待处理",
  retrying: "重试中",
  processing: "处理中",
  succeeded: "成功",
  failed: "失败",
};

function deliveryStatusTag(status) {
  const map = {
    pending: "warning",
    retrying: "warning",
    processing: "warning",
    succeeded: "success",
    failed: "danger",
  };
  const label = DELIVERY_STATUS_LABELS[status] || status;
  return `<span class="tag ${map[status] || ""}">${escapeHtml(label)}</span>`;
}

function formatDeliveryDateTime(iso) {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return String(iso);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

function truncateDetail(text, maxLen) {
  const s = (text ?? "").toString().trim();
  if (!s) {
    return "";
  }
  if (s.length <= maxLen) {
    return s;
  }
  return `${s.slice(0, Math.max(0, maxLen - 1))}…`;
}

function renderHttpUrlLink(url, extraClass) {
  const u = (url || "").trim();
  if (!u) {
    return '<span class="delivery-cell-muted">—</span>';
  }
  const safe = escapeHtml(u);
  const canOpen = /^https?:\/\//i.test(u);
  const cls = ["delivery-target-url", extraClass].filter(Boolean).join(" ");
  if (!canOpen) {
    return `<span class="${cls} delivery-target-url--plain" title="${safe}">${safe}</span>`;
  }
  return `<a class="${cls}" href="${safe}" target="_blank" rel="noopener noreferrer" title="${safe}">${safe}</a>`;
}

function renderDeliveryTargetCell(delivery) {
  return renderHttpUrlLink(delivery.targetUrl);
}

const ROUTE_AUTH_LABELS = {
  none: "无",
  bearer: "Bearer",
  hmac_sha256: "HMAC-SHA256",
};

function routeEnabledTag(enabled) {
  return enabled
    ? '<span class="tag success">启用</span>'
    : '<span class="tag danger">停用</span>';
}

function renderRouteNameCell(route) {
  return `
    <div class="route-name-cell">
      <div class="route-name-title">${escapeHtml(route.name)}</div>
      <div class="route-id-row">
        <span class="delivery-meta-label">ID</span>
        <code class="route-id-code" title="${escapeHtml(route.id)}">${escapeHtml(route.id)}</code>
      </div>
    </div>
  `;
}

function renderRouteMatchCell(route) {
  const m = route.match;
  const chips = (m.eventTypes || [])
    .map((e) => `<span class="route-event-chip">${escapeHtml(e)}</span>`)
    .join("");
  return `
    <div class="route-match">
      <div class="route-kv"><span class="delivery-meta-label">vhost</span><code class="route-code">${escapeHtml(m.vhost)}</code></div>
      <div class="route-kv"><span class="delivery-meta-label">app</span><code class="route-code">${escapeHtml(m.app)}</code></div>
      <div class="route-kv"><span class="delivery-meta-label">stream</span><code class="route-code">${escapeHtml(m.stream)}</code></div>
      <div class="route-match-events"><span class="delivery-meta-label">事件</span><span class="route-event-chips">${chips}</span></div>
    </div>
  `;
}

function renderRouteTargetCell(route) {
  const url = route.target?.url ?? "";
  const authType = route.target?.authType ?? "none";
  const authLabel = ROUTE_AUTH_LABELS[authType] || authType;
  return `
    <div class="route-target-wrap">
      <div class="route-target-url-line">${renderHttpUrlLink(url, "route-url")}</div>
      <div class="route-kv route-kv--inline"><span class="delivery-meta-label">鉴权</span><span>${escapeHtml(authLabel)}</span></div>
    </div>
  `;
}

function renderRouteRetryCell(route) {
  const r = route.retry;
  return `
    <div class="route-retry-cell">
      <div class="route-kv"><span class="delivery-meta-label">优先级</span><span>${escapeHtml(String(route.priority))}</span></div>
      <div class="route-kv"><span class="delivery-meta-label">重试</span><span>${r.maxAttempts} 次 · 间隔 ${r.backoffMs} ms</span></div>
    </div>
  `;
}

function isTrivialSuccessBody(body, httpLine) {
  const b = (body ?? "").trim();
  if (!b || !httpLine.startsWith("HTTP 2")) {
    return false;
  }
  return /^(0+|[Oo][Kk]|success)$/i.test(b);
}

function renderDeliveryResultCell(delivery, { failureMode = false } = {}) {
  const attempt = `${delivery.attemptCount}/${delivery.maxAttempts}`;
  const http = delivery.responseStatus != null ? `HTTP ${delivery.responseStatus}` : "";
  const err = (delivery.lastError || "").trim();
  const body = (delivery.responseBody || "").trim();
  const detailRaw = err || body;
  const maxLen = failureMode ? 220 : 120;
  const detail = truncateDetail(detailRaw, maxLen);
  const detailEscaped = escapeHtml(detail);
  const detailTitle = escapeHtml(detailRaw);

  const rowsRetry = `<div class="delivery-result-row"><span class="delivery-meta-label">重试</span><span>${escapeHtml(attempt)}</span></div>`;
  const rowsHttp = http ? `<div class="delivery-result-row"><span class="delivery-meta-label">响应</span><span>${escapeHtml(http)}</span></div>` : "";

  if (failureMode) {
    const reasonBlock = detail
      ? `<div class="delivery-result-reason" title="${detailTitle}"><span class="delivery-meta-label">原因</span><span class="delivery-error-text">${detailEscaped}</span></div>`
      : '<div class="delivery-result-reason delivery-cell-muted"><span class="delivery-meta-label">原因</span><span>—</span></div>';
    return `
      <div class="delivery-result delivery-result--failure">
        ${reasonBlock}
        ${rowsRetry}
        ${rowsHttp}
      </div>
    `;
  }

  const httpLine = http || "";
  let extraRow = "";
  if (err) {
    const t = truncateDetail(err, maxLen);
    extraRow = `<div class="delivery-result-row delivery-result-msg delivery-result-msg-error"><span class="delivery-meta-label">错误</span><span class="delivery-result-msg-text" title="${escapeHtml(err)}">${escapeHtml(t)}</span></div>`;
  } else if (body) {
    if (isTrivialSuccessBody(body, httpLine)) {
      extraRow = `<div class="delivery-result-trivial" title="${escapeHtml(body)}"><span class="delivery-meta-label">响应体</span><span class="delivery-cell-muted">${escapeHtml(body)}（下游常见占位，表示成功）</span></div>`;
    } else {
      const t = truncateDetail(body, maxLen);
      extraRow = `<div class="delivery-result-row delivery-result-msg"><span class="delivery-meta-label">响应体</span><span class="delivery-result-msg-text" title="${escapeHtml(body)}">${escapeHtml(t)}</span></div>`;
    }
  }

  return `
    <div class="delivery-result">
      ${rowsRetry}
      ${rowsHttp}
      ${extraRow}
    </div>
  `;
}

function renderDeliveryTimeCell(delivery) {
  const c = formatDeliveryDateTime(delivery.createdAt);
  const u = formatDeliveryDateTime(delivery.updatedAt);
  return `
    <div class="delivery-time">
      <div class="delivery-time-row"><span class="delivery-meta-label">创建</span><time datetime="${escapeHtml(delivery.createdAt)}">${escapeHtml(c)}</time></div>
      <div class="delivery-time-row"><span class="delivery-meta-label">更新</span><time datetime="${escapeHtml(delivery.updatedAt)}">${escapeHtml(u)}</time></div>
    </div>
  `;
}

function renderRouteForm(route) {
  const container = document.getElementById("routeFormContainer");
  const current = route || {
    name: "",
    enabled: true,
    match: { vhost: "*", app: "*", stream: "*", eventTypes: ["on_publish", "on_unpublish", "on_play", "on_stop"] },
    target: { url: "", timeoutMs: 5000, authType: "none", authConfig: {} },
    retry: { maxAttempts: 5, backoffMs: 5000 },
    priority: 100,
  };
  container.classList.remove("hidden");
  container.innerHTML = `
    <h3>${route ? "编辑规则" : "新建规则"}</h3>
    <form id="routeForm" class="form-grid">
      <label class="field">
        <span>名称</span>
        <input name="name" value="${escapeHtml(current.name)}" required>
      </label>
      <label class="field">
        <span>优先级</span>
        <input name="priority" type="number" value="${current.priority}" min="0" max="10000">
      </label>
      <label class="field">
        <span>vhost</span>
        <input name="vhost" value="${escapeHtml(current.match.vhost)}">
      </label>
      <label class="field">
        <span>app</span>
        <input name="app" value="${escapeHtml(current.match.app)}">
      </label>
      <label class="field">
        <span>stream</span>
        <input name="stream" value="${escapeHtml(current.match.stream)}">
      </label>
      <label class="field">
        <span>事件类型</span>
        <input name="eventTypes" value="${escapeHtml(current.match.eventTypes.join(","))}">
      </label>
      <label class="field full">
        <span>目标 URL</span>
        <input name="targetUrl" type="url" value="${escapeHtml(current.target.url)}" required>
      </label>
      <label class="field">
        <span>鉴权方式</span>
        <select name="authType">
          ${["none", "bearer", "hmac_sha256"].map((item) => `<option value="${item}" ${item === current.target.authType ? "selected" : ""}>${item}</option>`).join("")}
        </select>
      </label>
      <label class="field">
        <span>鉴权配置 JSON</span>
        <input name="authConfig" value='${escapeHtml(JSON.stringify(current.target.authConfig || {}))}'>
      </label>
      <label class="field">
        <span>超时 ms</span>
        <input name="timeoutMs" type="number" value="${current.target.timeoutMs}" min="500">
      </label>
      <label class="field">
        <span>最大重试次数</span>
        <input name="maxAttempts" type="number" value="${current.retry.maxAttempts}" min="1" max="20">
      </label>
      <label class="field">
        <span>重试退避 ms</span>
        <input name="backoffMs" type="number" value="${current.retry.backoffMs}" min="500">
      </label>
      <label class="field">
        <span>启用</span>
        <select name="enabled">
          <option value="true" ${current.enabled ? "selected" : ""}>启用</option>
          <option value="false" ${!current.enabled ? "selected" : ""}>停用</option>
        </select>
      </label>
      <div class="actions field full">
        <button type="button" class="secondary" id="cancelRouteForm">取消</button>
        <button type="submit" class="route-form-submit">${route ? "保存修改" : "创建规则"}</button>
      </div>
    </form>
  `;
  document.getElementById("cancelRouteForm").addEventListener("click", () => {
    container.classList.add("hidden");
    container.innerHTML = "";
    state.editingRouteId = null;
  });
  document.getElementById("routeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = {
      name: form.get("name"),
      enabled: form.get("enabled") === "true",
      match: {
        vhost: form.get("vhost") || "*",
        app: form.get("app") || "*",
        stream: form.get("stream") || "*",
        eventTypes: String(form.get("eventTypes") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      },
      target: {
        url: form.get("targetUrl"),
        timeoutMs: Number(form.get("timeoutMs")),
        authType: form.get("authType"),
        authConfig: JSON.parse(String(form.get("authConfig") || "{}")),
      },
      retry: {
        maxAttempts: Number(form.get("maxAttempts")),
        backoffMs: Number(form.get("backoffMs")),
      },
      priority: Number(form.get("priority")),
    };
    if (state.editingRouteId) {
      await api(`/api/routes/${state.editingRouteId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/api/routes", { method: "POST", body: JSON.stringify(payload) });
    }
    container.classList.add("hidden");
    container.innerHTML = "";
    state.editingRouteId = null;
    await refreshRoutes();
  });
}

function renderRoutes() {
  const target = document.getElementById("routesTable");
  if (!state.routes.length) {
    target.innerHTML = '<div class="table-empty">暂无路由规则，点击右上角「新建规则」添加。</div>';
    return;
  }
  target.innerHTML = `
    <table class="table-routes">
      <thead>
        <tr>
          <th>名称</th>
          <th>匹配条件</th>
          <th>目标</th>
          <th>优先级与重试</th>
          <th class="cell-route-status">状态</th>
          <th class="cell-route-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        ${state.routes.map((route) => `
          <tr>
            <td class="cell-route-name">${renderRouteNameCell(route)}</td>
            <td class="cell-route-match">${renderRouteMatchCell(route)}</td>
            <td class="cell-route-target">${renderRouteTargetCell(route)}</td>
            <td class="cell-route-retry">${renderRouteRetryCell(route)}</td>
            <td class="cell-route-status">${routeEnabledTag(route.enabled)}</td>
            <td class="cell-route-actions">
              <div class="compact-actions">
                <button type="button" class="secondary" data-edit-route="${route.id}">编辑</button>
                <button type="button" class="danger" data-delete-route="${route.id}">删除</button>
              </div>
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  target.querySelectorAll("[data-edit-route]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingRouteId = button.dataset.editRoute;
      renderRouteForm(state.routes.find((route) => route.id === state.editingRouteId));
    });
  });
  target.querySelectorAll("[data-delete-route]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!confirm("确认删除这条路由规则吗？")) {
        return;
      }
      await api(`/api/routes/${button.dataset.deleteRoute}`, { method: "DELETE" });
      await refreshRoutes();
    });
  });
}

function renderDeliveries(targetId, rows, options = {}) {
  const variant = options.variant ?? (targetId === "failuresTable" ? "failures" : "deliveries");
  const isFailureView = variant === "failures";
  const target = document.getElementById(targetId);
  const emptyMsg = isFailureView ? "暂无失败记录" : "暂无投递记录";
  if (!rows.length) {
    target.innerHTML = `<div class="table-empty">${emptyMsg}</div>`;
    return;
  }
  const opHint = "重新入队：POST /api/deliveries/{id}/retry，将任务重新加入投递队列";
  const actionHeader = isFailureView
    ? `<th class="cell-action" title="${escapeHtml(opHint)}">操作</th>`
    : "";
  const actionCell = (delivery) => {
    if (!isFailureView) {
      return "";
    }
    return `<td class="cell-action">
      <button type="button" class="secondary" data-retry-delivery="${delivery.id}" title="重新入队：POST /api/deliveries/${escapeHtml(delivery.id)}/retry">重新入队</button>
    </td>`;
  };
  target.innerHTML = `
    <table class="table-deliveries" data-table-variant="${variant}">
      <thead>
        <tr>
          <th>状态</th>
          <th>事件</th>
          <th>目标</th>
          <th>${isFailureView ? "失败信息" : "结果"}</th>
          <th>时间</th>
          ${actionHeader}
        </tr>
      </thead>
      <tbody>
        ${rows.map((delivery) => `
          <tr>
            <td class="cell-status">${deliveryStatusTag(delivery.status)}</td>
            <td class="cell-event">${renderDeliveryEventCell(delivery)}</td>
            <td class="cell-target">${renderDeliveryTargetCell(delivery)}</td>
            <td class="cell-result">${renderDeliveryResultCell(delivery, { failureMode: isFailureView })}</td>
            <td class="cell-time">${renderDeliveryTimeCell(delivery)}</td>
            ${actionCell(delivery)}
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  target.querySelectorAll("[data-retry-delivery]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.retryDelivery;
      button.disabled = true;
      const prev = button.textContent;
      button.textContent = "处理中…";
      try {
        await api(`/api/deliveries/${id}/retry`, { method: "POST" });
        await refreshDeliveries();
      } catch (e) {
        button.disabled = false;
        button.textContent = prev;
        const message = e instanceof Error ? e.message : String(e);
        window.alert(`重新入队失败：${message}`);
      }
    });
  });
}

async function refreshRoutes() {
  state.routes = await api("/api/routes");
  renderRoutes();
}

async function refreshDeliveries() {
  const status = document.getElementById("deliveryStatusFilter").value;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  state.deliveries = await api(`/api/deliveries${query}`);
  renderDeliveries("deliveriesTable", state.deliveries, { variant: "deliveries" });
  state.failures = await api("/api/deliveries?status=failed");
  renderDeliveries("failuresTable", state.failures, { variant: "failures" });
}

async function refreshAll() {
  if (!adminToken) {
    window.location.replace("/login");
    return;
  }
  try {
    await Promise.all([refreshRoutes(), refreshDeliveries()]);
    const storedName = localStorage.getItem("adminUsername") || "admin";
    sessionUsername.textContent = storedName;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message === "未授权或会话已失效") {
      return;
    }
    document.getElementById("routesTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
    document.getElementById("deliveriesTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
    document.getElementById("failuresTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
  }
}

refreshAll();
