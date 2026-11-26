(() => {
  "use strict";
  for (const form of document.querySelectorAll("[data-confirm]")) {
    form.addEventListener("submit", (event) => {
      const message = window.SafeOrbitI18N?.translate(form.dataset.confirm) ?? form.dataset.confirm;
      if (!window.confirm(message)) event.preventDefault();
    });
  }
  for (const button of document.querySelectorAll("[data-print]")) {
    button.addEventListener("click", () => window.print());
  }
  const addColumn = document.querySelector("[data-add-column]");
  const columns = document.querySelector("[data-columns]");
  if (addColumn && columns) {
    addColumn.addEventListener("click", () => {
      const field = columns.lastElementChild.cloneNode(true);
      field.querySelector("input").value = "";
      field.querySelector("select").selectedIndex = 0;
      columns.append(field);
      field.querySelector("input").focus();
      addColumn.disabled = columns.children.length >= 12;
    });
  }
  const list = document.querySelector("[data-arrange]");
  if (list) {
    const filter = document.querySelector("[data-module-filter]");
    if (filter) {
      const rows = [...list.querySelectorAll("[data-arrange-row]")];
      const queryBox = filter.querySelector("[data-module-query]");
      const group = filter.querySelector("[data-module-group]");
      const enabled = filter.querySelector("[data-module-enabled]");
      const count = filter.querySelector("[data-module-count]");
      const update = () => {
        const query = queryBox.value.trim().toLocaleLowerCase();
        let visible = 0;
        for (const row of rows) {
          const label = row.querySelector("label").textContent.toLocaleLowerCase();
          const matchesText = !query || label.includes(query) || row.dataset.hint.toLocaleLowerCase().includes(query);
          const matchesGroup = !group.value || group.value === row.dataset.group;
          const matchesStatus = !enabled.checked || row.querySelector("input").checked;
          row.hidden = !(matchesText && matchesGroup && matchesStatus);
          if (!row.hidden) visible++;
        }
        count.value = visible + " / " + rows.length;
      };
      filter.addEventListener("input", update);
      list.addEventListener("change", update);
    }
    let dragging;
    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-move]");
      if (!button) return;
      const row = button.closest("[data-arrange-row]");
      const up = button.dataset.move === "-1";
      const direction = up ? "previousElementSibling" : "nextElementSibling";
      let sibling = row[direction];
      while (sibling?.hidden) sibling = sibling[direction];
      if (sibling) sibling.insertAdjacentElement(up ? "beforebegin" : "afterend", row);
      button.focus();
    });
    list.addEventListener("dragstart", (event) => {
      dragging = event.target.closest("[data-arrange-row]");
      if (dragging) event.dataTransfer.setData("text/plain", dragging.querySelector("input").value);
    });
    list.addEventListener("dragover", (event) => {
      if (dragging) event.preventDefault();
    });
    list.addEventListener("drop", (event) => {
      const target = event.target.closest("[data-arrange-row]");
      if (!dragging || !target || dragging === target) return;
      event.preventDefault();
      const rect = target.getBoundingClientRect();
      target.insertAdjacentElement(event.clientY < rect.top + rect.height / 2 ? "beforebegin" : "afterend", dragging);
      dragging = null;
    });
    list.addEventListener("dragend", () => { dragging = null; });
  }

  for (const map of document.querySelectorAll("[data-cutting]")) {
    const data = JSON.parse(map.dataset.cutting);
    const boards = new Map();
    for (const [index, name, x, y, width, height] of data.rows) {
      if (!boards.has(index)) {
        const label = document.createElement("p");
        label.textContent = "№ " + index;
        const board = document.createElement("div");
        board.className = "board";
        board.style.aspectRatio = data.board_width + " / " + data.board_height;
        map.append(label, board);
        boards.set(index, board);
      }
      const part = document.createElement("div");
      part.className = "cut-part";
      part.title = name;
      part.textContent = name;
      part.style.left = 100 * x / data.board_width + "%";
      part.style.top = 100 * y / data.board_height + "%";
      part.style.width = 100 * width / data.board_width + "%";
      part.style.height = 100 * height / data.board_height + "%";
      boards.get(index).append(part);
    }
  }
})();
