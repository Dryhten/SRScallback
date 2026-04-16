const usernameInput = document.getElementById("adminUsername");
const passwordInput = document.getElementById("adminPassword");
const loginStatus = document.getElementById("loginStatus");
const loginForm = document.getElementById("loginForm");
const loginButton = document.getElementById("loginButton");

function showStatus(message, variant) {
  loginStatus.textContent = message;
  loginStatus.classList.remove("login-hint", "login-error", "login-success");
  loginStatus.setAttribute("role", variant === "error" ? "alert" : "status");
  if (variant === "error") {
    loginStatus.classList.add("login-error");
  } else if (variant === "success") {
    loginStatus.classList.add("login-success");
  } else {
    loginStatus.classList.add("login-hint");
  }
}

function readReasonMessage() {
  const reason = new URLSearchParams(window.location.search).get("reason");
  if (reason === "session") {
    showStatus("登录已过期或凭证无效，请重新登录。", "error");
    window.history.replaceState({}, "", "/login");
  }
}

function humanizeLoginDetail(detail) {
  const map = {
    "invalid username or password": "账号或密码错误",
    unauthorized: "未授权",
  };
  if (map[detail]) {
    return map[detail];
  }
  if (detail === "Failed to fetch" || detail === "NetworkError when attempting to fetch resource.") {
    return "无法连接服务器，请检查网络或服务是否已启动。";
  }
  return detail;
}

async function readErrorMessage(response) {
  const text = await response.text();
  if (!text) {
    return `登录失败（${response.status}）`;
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

const existingToken = localStorage.getItem("adminToken");
if (existingToken) {
  window.location.replace("/admin");
}

readReasonMessage();

function setLoading(loading) {
  loginButton.disabled = loading;
  loginButton.setAttribute("aria-busy", loading ? "true" : "false");
  loginButton.textContent = loading ? "登录中…" : "进入后台";
  usernameInput.disabled = loading;
  passwordInput.disabled = loading;
}

async function login() {
  const username = usernameInput.value.trim();
  if (!username) {
    showStatus("请输入账号。", "error");
    usernameInput.focus();
    return;
  }
  if (!passwordInput.value) {
    showStatus("请输入密码。", "error");
    passwordInput.focus();
    return;
  }

  setLoading(true);
  try {
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password: passwordInput.value,
      }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    const payload = await response.json();
    localStorage.setItem("adminToken", payload.token);
    localStorage.setItem("adminUsername", payload.username);
    passwordInput.value = "";
    showStatus("登录成功，正在跳转…", "success");
    window.location.replace("/admin");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const friendly = humanizeLoginDetail(message);
    showStatus(`登录失败：${friendly}`, "error");
  } finally {
    setLoading(false);
  }
}

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  login();
});
