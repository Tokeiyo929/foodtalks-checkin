const brands = window.FOODTALKS_BRANDS || [];
const storageKey = "foodtalks-brand-checkins-v1";
const deviceKey = "foodtalks-device-id-v1";
const supabaseConfig = window.SUPABASE_CONFIG || {};
const hasSupabaseConfig = Boolean(supabaseConfig.url && supabaseConfig.anonKey);
const supabaseClient = hasSupabaseConfig && window.supabase
  ? window.supabase.createClient(supabaseConfig.url, supabaseConfig.anonKey)
  : null;

const state = {
  query: "",
  primary: "全部",
  secondary: "全部",
  status: "all",
  sort: "category",
  checked: loadChecked(),
  cloudReady: false,
  cloudError: "",
  user: null,
};

const els = {
  progressText: document.querySelector("#progressText"),
  progressPercent: document.querySelector("#progressPercent"),
  progressBar: document.querySelector("#progressBar"),
  visibleCount: document.querySelector("#visibleCount"),
  categoryCount: document.querySelector("#categoryCount"),
  todayCount: document.querySelector("#todayCount"),
  searchInput: document.querySelector("#searchInput"),
  primaryFilters: document.querySelector("#primaryFilters"),
  secondaryFilters: document.querySelector("#secondaryFilters"),
  brandCards: document.querySelector("#brandCards"),
  emptyState: document.querySelector("#emptyState"),
  listTitle: document.querySelector("#listTitle"),
  sortSelect: document.querySelector("#sortSelect"),
  dialog: document.querySelector("#brandDialog"),
  dialogContent: document.querySelector("#dialogContent"),
  syncStatus: document.querySelector("#syncStatus"),
  authBtn: document.querySelector("#authBtn"),
  signOutBtn: document.querySelector("#signOutBtn"),
};

function loadChecked() {
  try {
    return JSON.parse(localStorage.getItem(storageKey)) || {};
  } catch {
    return {};
  }
}

function saveChecked() {
  localStorage.setItem(storageKey, JSON.stringify(state.checked));
}

function getDeviceId() {
  let id = localStorage.getItem(deviceKey);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(deviceKey, id);
  }
  return id;
}

async function initCloudStorage() {
  if (!supabaseClient) {
    setSyncStatus("本地模式", "");
    renderAuthControls();
    return;
  }

  setSyncStatus("连接云端...", "");
  try {
    const { data: sessionData } = await supabaseClient.auth.getSession();
    const session = sessionData.session;
    state.user = session?.user || null;
    renderAuthControls();

    if (!session?.user?.id) throw new Error("未登录 GitHub");

    await loadCloudCheckins();
    state.cloudReady = true;
    setSyncStatus("云端同步", "cloud");
  } catch (error) {
    state.cloudError = error.message || String(error);
    state.cloudReady = false;
    if (!state.user) {
      setSyncStatus("登录后云端同步", "");
    } else {
      setSyncStatus("云端不可用，已转本地", "error");
    }
    console.warn("Supabase sync failed:", error);
  }
}

async function signInWithGitHub() {
  if (!supabaseClient) {
    setSyncStatus("缺少 Supabase 配置", "error");
    return;
  }
  const redirectTo = window.location.origin + window.location.pathname;
  const { error } = await supabaseClient.auth.signInWithOAuth({
    provider: "github",
    options: { redirectTo },
  });
  if (error) {
    state.cloudError = error.message || String(error);
    setSyncStatus("GitHub 登录不可用", "error");
    console.warn("GitHub login failed:", error);
  }
}

async function signOut() {
  if (!supabaseClient) return;
  await supabaseClient.auth.signOut();
  state.user = null;
  state.cloudReady = false;
  state.checked = {};
  saveChecked();
  setSyncStatus("登录后云端同步", "");
  renderAuthControls();
  render();
}

function renderAuthControls() {
  const signedIn = Boolean(state.user);
  els.authBtn.hidden = signedIn;
  els.signOutBtn.hidden = !signedIn;
  if (signedIn) {
    const name = state.user.user_metadata?.user_name || state.user.user_metadata?.preferred_username || "GitHub";
    els.syncStatus.textContent = state.cloudReady ? `云端同步：${name}` : `已登录：${name}`;
  }
}

async function loadCloudCheckins() {
  const { data, error } = await supabaseClient
    .from("checkins")
    .select("brand_id, checked_at");
  if (error) throw error;

  const cloudChecked = {};
  for (const row of data || []) {
    cloudChecked[row.brand_id] = row.checked_at;
  }

  const localOnly = Object.entries(state.checked).filter(([id]) => !cloudChecked[id]);
  state.checked = { ...state.checked, ...cloudChecked };
  saveChecked();
  render();

  for (const [id, checkedAt] of localOnly) {
    await upsertCloudCheckin(Number(id), checkedAt);
  }
}

async function upsertCloudCheckin(id, checkedAt) {
  if (!state.cloudReady || !supabaseClient) return;
  const { data: userData, error: userError } = await supabaseClient.auth.getUser();
  if (userError) throw userError;
  const userId = userData.user?.id;
  if (!userId) throw new Error("缺少 Supabase 用户 ID");

  const { error } = await supabaseClient.from("checkins").upsert(
    {
      user_id: userId,
      brand_id: id,
      checked_at: checkedAt,
    },
    { onConflict: "user_id,brand_id" }
  );
  if (error) throw error;
}

async function deleteCloudCheckin(id) {
  if (!state.cloudReady || !supabaseClient) return;
  const { error } = await supabaseClient
    .from("checkins")
    .delete()
    .eq("brand_id", id);
  if (error) throw error;
}

async function clearCloudCheckins() {
  if (!state.cloudReady || !supabaseClient) return;
  const { error } = await supabaseClient
    .from("checkins")
    .delete()
    .neq("brand_id", -1);
  if (error) throw error;
}

function setSyncStatus(text, className) {
  els.syncStatus.textContent = text;
  els.syncStatus.className = `sync-status ${className || ""}`.trim();
}

function handleCloudWriteError(error) {
  state.cloudReady = false;
  state.cloudError = error.message || String(error);
  setSyncStatus("云端写入失败，已保留本地", "error");
  console.warn("Supabase write failed:", error);
}

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function checkedIds() {
  return Object.keys(state.checked).filter((id) => state.checked[id]);
}

function checkedTodayCount() {
  const today = new Date().toISOString().slice(0, 10);
  return checkedIds().filter((id) => state.checked[id].slice(0, 10) === today).length;
}

function isChecked(item) {
  return Boolean(state.checked[item.id]);
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function matchesQuery(item) {
  if (!state.query) return true;
  const haystack = [
    item.primary,
    item.secondary,
    item.tertiary,
    item.company,
    item.brands,
    item.reason,
  ].map(normalize).join(" ");
  return haystack.includes(normalize(state.query));
}

function filteredBrands() {
  let list = brands.filter((item) => {
    if (state.primary !== "全部" && item.primary !== state.primary) return false;
    if (state.secondary !== "全部" && item.secondary !== state.secondary) return false;
    if (state.status === "done" && !isChecked(item)) return false;
    if (state.status === "todo" && isChecked(item)) return false;
    return matchesQuery(item);
  });

  list = list.slice().sort((a, b) => {
    if (state.sort === "checked") return Number(isChecked(b)) - Number(isChecked(a));
    if (state.sort === "unchecked") return Number(isChecked(a)) - Number(isChecked(b));
    if (state.sort === "company") return a.company.localeCompare(b.company, "zh-Hans-CN");
    return (
      a.primary.localeCompare(b.primary, "zh-Hans-CN") ||
      a.secondary.localeCompare(b.secondary, "zh-Hans-CN") ||
      a.tertiary.localeCompare(b.tertiary, "zh-Hans-CN") ||
      Number(a.seq) - Number(b.seq)
    );
  });

  return list;
}

function renderFilters() {
  const primaryValues = ["全部", ...unique(brands.map((item) => item.primary))];
  els.primaryFilters.innerHTML = primaryValues.map((value) => chipHtml(value, value === state.primary, "primary")).join("");

  const secondarySource = state.primary === "全部"
    ? brands
    : brands.filter((item) => item.primary === state.primary);
  const secondaryValues = ["全部", ...unique(secondarySource.map((item) => item.secondary))];
  if (!secondaryValues.includes(state.secondary)) state.secondary = "全部";
  els.secondaryFilters.innerHTML = secondaryValues.map((value) => chipHtml(value, value === state.secondary, "secondary")).join("");
}

function chipHtml(value, active, group) {
  return `<button class="chip ${active ? "active" : ""}" data-group="${group}" data-value="${escapeAttr(value)}" type="button">${escapeHtml(value)}</button>`;
}

function renderStats(list) {
  const total = brands.length;
  const done = checkedIds().length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  els.progressText.textContent = `${done} / ${total}`;
  els.progressPercent.textContent = `${pct}%`;
  els.progressBar.style.width = `${pct}%`;
  els.visibleCount.textContent = String(list.length);
  els.categoryCount.textContent = String(unique(brands.map((item) => item.primary)).length);
  els.todayCount.textContent = String(checkedTodayCount());
}

function renderCards(list) {
  els.brandCards.innerHTML = list.map(cardHtml).join("");
  els.emptyState.hidden = list.length > 0;
  const titleParts = [state.primary, state.secondary].filter((value) => value !== "全部");
  els.listTitle.textContent = titleParts.length ? titleParts.join(" / ") : "全部品牌";
}

function cardHtml(item) {
  const done = isChecked(item);
  const brandsText = item.brands || "未标注代表品牌";
  return `
    <article class="brand-card ${done ? "checked" : ""}" data-id="${item.id}">
      <div class="logo">${logoHtml(item)}</div>
      <div class="card-main">
        <div class="card-top">
          <h3 class="brand-name">${escapeHtml(item.company)}</h3>
          <span class="badge">${done ? "已打卡" : "未打卡"}</span>
        </div>
        <p class="brands">${escapeHtml(brandsText)}</p>
        <p class="category-path">${escapeHtml(item.primary)} / ${escapeHtml(item.secondary)} / ${escapeHtml(item.tertiary)}</p>
        <p class="reason">${escapeHtml(item.reason || "暂无推荐理由")}</p>
        <div class="card-actions">
          <button class="check-button" data-action="toggle" type="button">${done ? "取消打卡" : "吃过，打卡"}</button>
          <button class="detail-button" data-action="detail" type="button" title="查看详情" aria-label="查看详情">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>
          </button>
        </div>
      </div>
    </article>
  `;
}

function logoHtml(item) {
  if (item.logo) {
    return `<img src="${escapeAttr(item.logo)}" alt="${escapeAttr(item.company)} logo" loading="lazy" onerror="this.replaceWith(document.createTextNode('${escapeAttr(initials(item.company))}'))" />`;
  }
  return escapeHtml(initials(item.company));
}

function initials(name) {
  return String(name || "?").trim().slice(0, 2).toUpperCase();
}

function openDetail(item) {
  const done = isChecked(item);
  els.dialogContent.innerHTML = `
    <div class="dialog-hero">
      <div class="logo">${logoHtml(item)}</div>
      <div>
        <p class="label">${escapeHtml(item.primary)} / ${escapeHtml(item.secondary)} / ${escapeHtml(item.tertiary)}</p>
        <h3>${escapeHtml(item.company)}</h3>
      </div>
    </div>
    <dl>
      <dt>代表品牌</dt>
      <dd>${escapeHtml(item.brands || "未标注")}</dd>
      <dt>推荐理由</dt>
      <dd>${escapeHtml(item.reason || "暂无")}</dd>
      <dt>打卡状态</dt>
      <dd>${done ? `已打卡：${escapeHtml(state.checked[item.id])}` : "还没吃过"}</dd>
    </dl>
  `;
  els.dialog.showModal();
}

function render() {
  renderFilters();
  const list = filteredBrands();
  renderStats(list);
  renderCards(list);
}

async function toggleCheckin(id) {
  if (state.checked[id]) {
    delete state.checked[id];
    saveChecked();
    render();
    try {
      await deleteCloudCheckin(id);
    } catch (error) {
      handleCloudWriteError(error);
    }
  } else {
    const checkedAt = new Date().toISOString();
    state.checked[id] = checkedAt;
    saveChecked();
    render();
    try {
      await upsertCloudCheckin(id, checkedAt);
    } catch (error) {
      handleCloudWriteError(error);
    }
  }
}

function pickRandomUnchecked() {
  const list = filteredBrands().filter((item) => !isChecked(item));
  const pool = list.length ? list : brands.filter((item) => !isChecked(item));
  if (!pool.length) return;
  const item = pool[Math.floor(Math.random() * pool.length)];
  state.primary = item.primary;
  state.secondary = item.secondary;
  state.status = "todo";
  state.query = item.company;
  els.searchInput.value = item.company;
  render();
  requestAnimationFrame(() => {
    document.querySelector(`[data-id="${item.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function exportCheckins() {
  const rows = checkedIds().map((id) => {
    const item = brands.find((brand) => String(brand.id) === String(id));
    return {
      checkedAt: state.checked[id],
      primary: item?.primary,
      secondary: item?.secondary,
      tertiary: item?.tertiary,
      company: item?.company,
      brands: item?.brands,
    };
  });
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "foodtalks-checkins.json";
  link.click();
  URL.revokeObjectURL(url);
}

async function resetCheckins() {
  if (!checkedIds().length) return;
  const confirmed = confirm("确定清空所有打卡记录吗？");
  if (!confirmed) return;
  state.checked = {};
  saveChecked();
  render();
  try {
    await clearCloudCheckins();
  } catch (error) {
    handleCloudWriteError(error);
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

els.searchInput.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  render();
});

els.primaryFilters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-group='primary']");
  if (!button) return;
  state.primary = button.dataset.value;
  state.secondary = "全部";
  render();
});

els.secondaryFilters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-group='secondary']");
  if (!button) return;
  state.secondary = button.dataset.value;
  render();
});

document.querySelector(".segmented").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-status]");
  if (!button) return;
  state.status = button.dataset.status;
  document.querySelectorAll(".segmented button").forEach((item) => {
    item.classList.toggle("active", item === button);
  });
  render();
});

els.sortSelect.addEventListener("change", (event) => {
  state.sort = event.target.value;
  render();
});

els.brandCards.addEventListener("click", (event) => {
  const card = event.target.closest(".brand-card");
  const action = event.target.closest("button")?.dataset.action;
  if (!card || !action) return;
  const item = brands.find((brand) => String(brand.id) === String(card.dataset.id));
  if (!item) return;
  if (action === "toggle") toggleCheckin(item.id);
  if (action === "detail") openDetail(item);
});

document.querySelector("#randomBtn").addEventListener("click", pickRandomUnchecked);
document.querySelector("#exportBtn").addEventListener("click", exportCheckins);
document.querySelector("#resetBtn").addEventListener("click", resetCheckins);
els.authBtn.addEventListener("click", signInWithGitHub);
els.signOutBtn.addEventListener("click", signOut);

if (supabaseClient) {
  supabaseClient.auth.onAuthStateChange((_event, session) => {
    state.user = session?.user || null;
    state.cloudReady = false;
    renderAuthControls();
    if (state.user) initCloudStorage();
  });
}

getDeviceId();
render();
initCloudStorage();
