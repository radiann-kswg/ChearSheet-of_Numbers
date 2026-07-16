const docListEl = document.getElementById("doc-list");
const searchEl = document.getElementById("search");
const docViewEl = document.getElementById("doc-view");
const loreFiltersEl = document.getElementById("lore-filters");
const propertyFiltersEl = document.getElementById("property-filters");
const resultCountEl = document.getElementById("result-count");
const clearFiltersEl = document.getElementById("clear-filters");

const state = {
  records: [],
  filters: { lore: [], properties: [] },
  selectedLore: new Set(),
  selectedProperties: new Set(),
  currentPath: "",
};

const markdownRenderer = new marked.Marked({
  gfm: true,
  breaks: false,
});

function normalizeDocPath(href, basePath) {
  if (!href || href.startsWith("http://") || href.startsWith("https://") || href.startsWith("#")) {
    return null;
  }
  if (!href.endsWith(".md")) {
    return null;
  }

  const baseDir = basePath.includes("/")
    ? basePath.slice(0, basePath.lastIndexOf("/") + 1)
    : "";
  const resolved = new URL(href, `https://local/${baseDir}`).pathname;
  const path = resolved.replace(/^\//, "");

  if (!path.startsWith("numbers/")) {
    return null;
  }
  return path;
}

function setupFilterGroup(container, filterDefs, selectedSet, onChange) {
  container.innerHTML = "";

  for (const filter of filterDefs) {
    const label = document.createElement("label");
    label.className = "chip";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = filter.key;
    input.addEventListener("change", () => {
      if (input.checked) {
        selectedSet.add(filter.key);
      } else {
        selectedSet.delete(filter.key);
      }
      onChange();
    });

    const text = document.createElement("span");
    text.textContent = filter.label;

    label.appendChild(input);
    label.appendChild(text);
    container.appendChild(label);
  }
}

function matchesCategory(recordValues, selectedSet) {
  if (selectedSet.size === 0) {
    return true;
  }
  for (const key of selectedSet) {
    if (recordValues.includes(key)) {
      return true;
    }
  }
  return false;
}

function filterRecords() {
  const keyword = searchEl.value.trim().toLowerCase();

  return state.records.filter((record) => {
    const keywordOk = !keyword || record.searchText.includes(keyword);
    const loreOk = matchesCategory(record.loreFilters, state.selectedLore);
    const propOk = matchesCategory(record.propertyFilters, state.selectedProperties);
    return keywordOk && loreOk && propOk;
  });
}

function renderDocumentList(records) {
  docListEl.innerHTML = "";
  resultCountEl.textContent = `${records.length}件`;

  if (records.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "一致する数字がありません。";
    docListEl.appendChild(li);
    return;
  }

  for (const record of records) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = record.path === state.currentPath ? "active" : "";
    button.addEventListener("click", () => {
      loadDocument(record.path).catch(showError);
    });

    const title = document.createElement("strong");
    title.textContent = record.title;

    const meta = document.createElement("small");
    meta.textContent = record.snippets[0] || "数秘・性質を表示";

    button.appendChild(title);
    button.appendChild(meta);
    li.appendChild(button);
    docListEl.appendChild(li);
  }
}

function renderListByCurrentFilters() {
  const filtered = filterRecords();
  renderDocumentList(filtered);
}

async function loadDocument(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`読み込みに失敗しました: ${path}`);
  }

  state.currentPath = path;

  const markdown = await response.text();
  const html = markdownRenderer.parse(markdown);
  docViewEl.innerHTML = DOMPurify.sanitize(html);
  renderListByCurrentFilters();

  history.replaceState({}, "", `#${encodeURIComponent(path)}`);

  docViewEl.querySelectorAll("a").forEach((anchor) => {
    const href = anchor.getAttribute("href");
    const target = normalizeDocPath(href, path);
    if (!target) {
      return;
    }
    anchor.addEventListener("click", (event) => {
      event.preventDefault();
      loadDocument(target).catch(showError);
    });
  });
}

function showError(error) {
  docViewEl.innerHTML = `<p>表示に失敗しました: ${error.message}</p>`;
}

async function bootstrap() {
  const response = await fetch("assets/numbers-index.json");
  if (!response.ok) {
    throw new Error("assets/numbers-index.json の読み込みに失敗しました。");
  }

  const data = await response.json();
  state.records = data.numbers || [];
  state.filters = data.filters || { lore: [], properties: [] };

  setupFilterGroup(loreFiltersEl, state.filters.lore, state.selectedLore, renderListByCurrentFilters);
  setupFilterGroup(
    propertyFiltersEl,
    state.filters.properties,
    state.selectedProperties,
    renderListByCurrentFilters,
  );

  searchEl.addEventListener("input", renderListByCurrentFilters);
  clearFiltersEl.addEventListener("click", () => {
    state.selectedLore.clear();
    state.selectedProperties.clear();
    searchEl.value = "";
    document
      .querySelectorAll(".chip input[type='checkbox']")
      .forEach((input) => {
        input.checked = false;
      });
    renderListByCurrentFilters();
  });

  renderListByCurrentFilters();

  const hashPath = decodeURIComponent(location.hash.replace(/^#/, ""));
  const initial =
    state.records.find((record) => record.path === hashPath) ||
    state.records[0];

  if (initial) {
    await loadDocument(initial.path);
  }
}

bootstrap().catch(showError);
