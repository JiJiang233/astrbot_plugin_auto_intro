const bridge = window.AstrBotPluginPage;
const labels = { tools: "工具", plugins: "插件", commands: "命令" };
const state = { groups: {}, allow: {}, block: {} };

function setStatus(message, error) {
  const element = document.getElementById("status");
  element.textContent = message;
  element.className = error ? "error" : "success";
}

function optionText(item) {
  const span = document.createElement("span");
  const name = document.createElement("b");
  name.textContent = item.value;
  const owner = document.createElement("small");
  owner.textContent = item.owner || "未标注来源";
  const description = document.createElement("em");
  description.textContent = item.description || "无补充说明";
  span.append(name, owner, description);
  return span;
}

function renderGroup(group) {
  const items = state.groups[group] || [];
  const allow = new Set(state.allow[group] || []);
  const block = new Set(state.block[group] || []);
  const article = document.createElement("article");
  article.className = "group";

  const head = document.createElement("div");
  head.className = "group-head";
  const titleBox = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = labels[group];
  const count = document.createElement("p");
  count.textContent = items.length + " 个当前可选项";
  titleBox.append(title, count);
  const search = document.createElement("input");
  search.className = "search";
  search.type = "search";
  search.placeholder = "搜索" + labels[group];
  head.append(titleBox, search);

  const columns = document.createElement("div");
  columns.className = "columns";

  function createColumn(mode, heading, help) {
    const column = document.createElement("div");
    column.className = mode === "block" ? "column danger" : "column";
    column.dataset.mode = mode;
    const columnHead = document.createElement("div");
    columnHead.className = "column-head";
    const strong = document.createElement("strong");
    strong.textContent = heading;
    const clear = document.createElement("button");
    clear.textContent = "清空";
    clear.addEventListener("click", () => {
      if (mode === "allow") allow.clear(); else block.clear();
      state[mode][group] = [];
      fill();
    });
    columnHead.append(strong, clear);
    const hint = document.createElement("p");
    hint.textContent = help;
    const options = document.createElement("div");
    options.className = "options";
    column.append(columnHead, hint, options);
    return column;
  }

  columns.append(
    createColumn("allow", "白名单", "为空时公开全部未被拉黑的项目。"),
    createColumn("block", "黑名单", "始终排除所选项目，优先级高于白名单。")
  );
  article.append(head, columns);

  function fill() {
    const query = search.value.trim().toLowerCase();
    for (const mode of ["allow", "block"]) {
      const own = mode === "allow" ? allow : block;
      const other = mode === "allow" ? block : allow;
      const container = article.querySelector('[data-mode="' + mode + '"] .options');
      container.textContent = "";
      for (const item of items) {
        const haystack = (item.value + " " + (item.description || "") + " " + (item.owner || "")).toLowerCase();
        if (query && !haystack.includes(query)) continue;
        const label = document.createElement("label");
        label.className = "option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = own.has(item.value);
        input.addEventListener("change", () => {
          if (input.checked) {
            own.add(item.value);
            other.delete(item.value);
          } else {
            own.delete(item.value);
          }
          state.allow[group] = Array.from(allow);
          state.block[group] = Array.from(block);
          fill();
        });
        label.append(input, optionText(item));
        container.append(label);
      }
    }
  }

  search.addEventListener("input", fill);
  fill();
  return article;
}

async function load() {
  await bridge.ready();
  const data = await bridge.apiGet("filters");
  state.groups = data.groups || {};
  state.allow = data.selected && data.selected.allow ? data.selected.allow : {};
  state.block = data.selected && data.selected.block ? data.selected.block : {};
  const root = document.getElementById("groups");
  for (const group of ["tools", "plugins", "commands"]) root.append(renderGroup(group));
}

document.getElementById("save").addEventListener("click", async () => {
  try {
    await bridge.apiPost("filters/save", { allow: state.allow, block: state.block });
    setStatus("已保存。新规则会在下一次 LLM 请求中生效。", false);
  } catch (error) {
    setStatus(error.message || String(error), true);
  }
});

load().catch((error) => setStatus(error.message || String(error), true));
