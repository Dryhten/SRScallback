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

const tokenInput = document.getElementById("adminToken");
tokenInput.value = localStorage.getItem("adminToken") || "";

document.getElementById("saveTokenButton").addEventListener("click", () => {
  localStorage.setItem("adminToken", tokenInput.value.trim());
  refreshAll();
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
  const token = tokenInput.value.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
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
        <button type="submit">${route ? "保存修改" : "创建规则"}</button>
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
  target.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>名称</th>
          <th>匹配条件</th>
          <th>目标</th>
          <th>重试</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${state.routes.map((route) => `
          <tr>
            <td>
              <strong>${escapeHtml(route.name)}</strong><br>
              <small>ID: ${escapeHtml(route.id)}</small>
            </td>
            <td>
              <small>vhost=${escapeHtml(route.match.vhost)}</small><br>
              <small>app=${escapeHtml(route.match.app)}</small><br>
              <small>stream=${escapeHtml(route.match.stream)}</small><br>
              <small>${escapeHtml(route.match.eventTypes.join(", "))}</small>
            </td>
            <td>
              <small>${escapeHtml(route.target.url)}</small><br>
              <small>auth=${escapeHtml(route.target.authType)}</small>
            </td>
            <td>
              <small>priority=${route.priority}</small><br>
              <small>${route.retry.maxAttempts} attempts / ${route.retry.backoffMs} ms</small>
            </td>
            <td>${route.enabled ? '<span class="tag success">enabled</span>' : '<span class="tag danger">disabled</span>'}</td>
            <td>
              <div class="compact-actions">
                <button class="secondary" data-edit-route="${route.id}">编辑</button>
                <button class="danger" data-delete-route="${route.id}">删除</button>
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

function renderDeliveries(targetId, rows) {
  const target = document.getElementById(targetId);
  target.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>状态</th>
          <th>事件</th>
          <th>目标</th>
          <th>结果</th>
          <th>时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((delivery) => `
          <tr>
            <td>${statusTag(delivery.status)}</td>
            <td>
              <strong>${escapeHtml(delivery.payload.eventType)}</strong><br>
              <small>${escapeHtml(delivery.payload.streamContext?.app || "-")} / ${escapeHtml(delivery.payload.streamContext?.stream || "-")}</small><br>
              <small>route=${escapeHtml(delivery.routeName || delivery.routeId)}</small>
            </td>
            <td><small>${escapeHtml(delivery.targetUrl)}</small></td>
            <td>
              <small>attempt=${delivery.attemptCount}/${delivery.maxAttempts}</small><br>
              <small>${escapeHtml(delivery.lastError || delivery.responseBody || "-")}</small>
            </td>
            <td>
              <small>created=${escapeHtml(delivery.createdAt)}</small><br>
              <small>updated=${escapeHtml(delivery.updatedAt)}</small>
            </td>
            <td>
              ${delivery.status === "failed" ? `<button class="secondary" data-retry-delivery="${delivery.id}">重新入队</button>` : ""}
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  target.querySelectorAll("[data-retry-delivery]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/deliveries/${button.dataset.retryDelivery}/retry`, { method: "POST" });
      await refreshDeliveries();
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
  renderDeliveries("deliveriesTable", state.deliveries);
  state.failures = await api("/api/deliveries?status=failed");
  renderDeliveries("failuresTable", state.failures);
}

async function refreshAll() {
  try {
    await Promise.all([refreshRoutes(), refreshDeliveries()]);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    document.getElementById("routesTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
    document.getElementById("deliveriesTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
    document.getElementById("failuresTable").innerHTML = `<div class="card">加载失败：${escapeHtml(message)}</div>`;
  }
}

refreshAll();
