(() => {
  "use strict";
  for (const form of document.querySelectorAll("[data-confirm]")) {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
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
    let dragging;
    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-move]");
      if (!button) return;
      const row = button.closest("[data-arrange-row]");
      const up = button.dataset.move === "-1";
      const sibling = up ? row.previousElementSibling : row.nextElementSibling;
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
