const docListEl = document.getElementById("doc-list");
const searchEl = document.getElementById("search");
const docViewEl = document.getElementById("doc-view");
const loreFiltersEl = document.getElementById("lore-filters");
const propertyFiltersEl = document.getElementById("property-filters");
const resultCountEl = document.getElementById("result-count");
const clearFiltersEl = document.getElementById("clear-filters");
const jumpEl = document.getElementById("jump");
const jumpGoEl = document.getElementById("jump-go");

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

	if (!path.startsWith("numbers/") && path !== "index.md") {
		return null;
	}
	return path;
}

function renderMathIn(element) {
	// KaTeX auto-render（CDN が読み込めない場合は数式を素のまま表示）
	if (typeof renderMathInElement === "function") {
		renderMathInElement(element, {
			delimiters: [
				{ left: "$$", right: "$$", display: true },
				{ left: "$", right: "$", display: false },
			],
			throwOnError: false,
		});
	}
}

// --- 数式の保護 ---
// marked は数式内の `<`（HTMLタグと誤認→サニタイズで欠落）や `_` `*`（強調記法）を
// 壊してしまうため、Markdown 変換の前に $...$ / $$...$$ を退避し、変換後に戻す。
const MATH_TOKEN_PREFIX = "\uE000MATH";
const MATH_TOKEN_SUFFIX = "\uE001";

function extractMathSpans(markdown) {
	const spans = [];
	const pattern = /\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g;
	const replaced = markdown.replace(pattern, (match) => {
		const token = `${MATH_TOKEN_PREFIX}${spans.length}${MATH_TOKEN_SUFFIX}`;
		spans.push(match);
		return token;
	});
	return { replaced, spans };
}

function restoreMathSpans(element, spans) {
	if (spans.length === 0) {
		return;
	}
	const tokenPattern = new RegExp(`${MATH_TOKEN_PREFIX}(\\d+)${MATH_TOKEN_SUFFIX}`, "g");
	const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
	const targets = [];
	while (walker.nextNode()) {
		if (walker.currentNode.nodeValue.includes(MATH_TOKEN_PREFIX)) {
			targets.push(walker.currentNode);
		}
	}
	for (const node of targets) {
		node.nodeValue = node.nodeValue.replace(
			tokenPattern,
			(_all, index) => spans[Number(index)] ?? "",
		);
	}
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
	const { replaced, spans } = extractMathSpans(markdown);
	const html = markdownRenderer.parse(replaced);
	docViewEl.innerHTML = DOMPurify.sanitize(html);
	restoreMathSpans(docViewEl, spans);
	renderMathIn(docViewEl);
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

	function jumpToNumber() {
		const value = Number.parseInt(jumpEl.value, 10);
		if (!Number.isInteger(value) || value < 0 || value > 999) {
			return;
		}
		const record = state.records.find((r) => r.n === value);
		if (record) {
			loadDocument(record.path).catch(showError);
		}
	}
	jumpGoEl.addEventListener("click", jumpToNumber);
	jumpEl.addEventListener("keydown", (event) => {
		if (event.key === "Enter") {
			event.preventDefault();
			jumpToNumber();
		}
	});

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
