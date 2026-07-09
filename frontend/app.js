const rows = ["A", "B", "C", "D", "E"];
const cols = ["1", "2", "3", "4", "5"];
const points = rows.flatMap((row) => cols.map((col) => `${row}${col}`));

const homeView = document.querySelector("#homeView");
const mailView = document.querySelector("#mailView");
const navLinks = document.querySelectorAll("[data-view-link]");
const rideForm = document.querySelector("#rideForm");
const startInput = document.querySelector("#startInput");
const endInput = document.querySelector("#endInput");
const datalist = document.querySelector("#gridPoints");
const callButton = document.querySelector("#callButton");
const resetButton = document.querySelector("#resetButton");
const startField = document.querySelector("#startField");
const endField = document.querySelector("#endField");
const waypointList = document.querySelector("#waypointList");
const addWaypointButton = document.querySelector("#addWaypointButton");
const carPositionText = document.querySelector("#carPositionText");
const carMetric = document.querySelector("#carMetric");
const messageType = document.querySelector("#messageType");
const messageText = document.querySelector("#messageText");
const messageList = document.querySelector("#messageList");
const routeTitle = document.querySelector("#routeTitle");
const etaText = document.querySelector("#etaText");
const gridLines = document.querySelector("#gridLines");
const gridPointsLayer = document.querySelector("#gridPointsLayer");
const carMarker = document.querySelector("#carMarker");
const routePolyline = document.querySelector("#routePolyline");
const progressPolyline = document.querySelector("#progressPolyline");
const simulateMailButton = document.querySelector("#simulateMailButton");
const mailSubject = document.querySelector("#mailSubject");
const mailBody = document.querySelector("#mailBody");

let timers = [];
let running = false;
let carPoint = "C3";
let activeTarget = "start";
let waypointCounter = 0;
let waypoints = [];

function pointToCoord(point) {
  const normalized = point.trim().toUpperCase();
  const row = rows.indexOf(normalized[0]);
  const col = cols.indexOf(normalized.slice(1));
  if (row < 0 || col < 0) {
    return null;
  }
  return { point: normalized, row, col };
}

function coordToPoint(row, col) {
  return `${rows[row]}${cols[col]}`;
}

function pointToPercent(point) {
  const coord = pointToCoord(point);
  const left = 10 + coord.col * 20;
  const top = 10 + coord.row * 20;
  return { left, top };
}

function buildPath(from, to) {
  const start = pointToCoord(from);
  const end = pointToCoord(to);
  const path = [start.point];
  let row = start.row;
  let col = start.col;

  while (col !== end.col) {
    col += col < end.col ? 1 : -1;
    path.push(coordToPoint(row, col));
  }

  while (row !== end.row) {
    row += row < end.row ? 1 : -1;
    path.push(coordToPoint(row, col));
  }

  return path;
}

function buildMultiStopPath(stops) {
  return stops.slice(1).reduce((path, stop, index) => {
    const segment = buildPath(stops[index], stop);
    return [...path, ...segment.slice(index === 0 ? 0 : 1)];
  }, []);
}

function buildStraightSegments(path) {
  if (path.length < 2) {
    return [];
  }

  const segments = [];
  let segmentStart = 0;
  let currentDirection = getStepDirection(path[0], path[1]);

  for (let index = 2; index < path.length; index += 1) {
    const nextDirection = getStepDirection(path[index - 1], path[index]);
    if (nextDirection !== currentDirection) {
      segments.push({
        from: path[segmentStart],
        to: path[index - 1],
        startIndex: segmentStart,
      });
      segmentStart = index - 1;
      currentDirection = nextDirection;
    }
  }

  segments.push({
    from: path[segmentStart],
    to: path[path.length - 1],
    startIndex: segmentStart,
  });

  return segments.filter((segment) => segment.from !== segment.to);
}

function getStepDirection(from, to) {
  const start = pointToCoord(from);
  const end = pointToCoord(to);
  return start.row === end.row ? "horizontal" : "vertical";
}

function getWaypointValues() {
  return waypoints.map((waypoint) => waypoint.value.trim().toUpperCase()).filter(Boolean);
}

function getRouteStops() {
  return [startInput.value.trim().toUpperCase(), ...getWaypointValues(), endInput.value.trim().toUpperCase()];
}

function updateRouteTitle() {
  routeTitle.textContent = getRouteStops().join(" → ");
}

function speak(message) {
  if (!("speechSynthesis" in window)) {
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(message);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

function setMessage(type, text, announce = false) {
  messageType.textContent = type;
  messageText.textContent = text;
  addMessage(type, text);
  if (announce) {
    speak(text);
  }
}

function addMessage(type, text) {
  const item = document.createElement("li");
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString();
  item.append(time, document.createTextNode(`${type}：${text}`));
  messageList.prepend(item);
}

function setCarPoint(point) {
  carPoint = point;
  carPositionText.textContent = point;
  const pos = pointToPercent(point);
  carMarker.style.left = `${pos.left}%`;
  carMarker.style.top = `${pos.top}%`;
}

function setCarBusy(isBusy) {
  carMetric.classList.toggle("busy", isBusy);
  carMetric.classList.toggle("idle", !isBusy);
}

function setCallButtonLabel(label) {
  const icon = document.createElement("span");
  icon.className = "button-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "▣";
  callButton.replaceChildren(icon, document.createTextNode(label));
}

function renderWaypoints() {
  waypointList.innerHTML = "";

  waypoints.forEach((waypoint, index) => {
    const row = document.createElement("label");
    row.className = "field-row route-field waypoint-field";
    row.dataset.id = waypoint.id;
    row.draggable = true;
    row.classList.toggle("active", activeTarget === waypoint.id);

    const node = document.createElement("span");
    node.className = "route-node route-square";
    node.setAttribute("aria-hidden", "true");

    const body = document.createElement("span");
    body.className = "field-body";

    const label = document.createElement("span");
    label.className = "field-label";
    label.textContent = `途径点 ${index + 1}`;

    const input = document.createElement("input");
    input.type = "text";
    input.value = waypoint.value;
    input.setAttribute("list", "gridPoints");
    input.autocomplete = "off";

    const remove = document.createElement("button");
    remove.className = "waypoint-remove";
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `删除途径点 ${index + 1}`);

    row.addEventListener("click", () => setActiveTarget(waypoint.id));
    input.addEventListener("focus", () => setActiveTarget(waypoint.id));
    input.addEventListener("input", () => {
      waypoint.value = input.value.toUpperCase();
      input.value = waypoint.value;
      if (!running && pointToCoord(startInput.value) && pointToCoord(endInput.value)) {
        updateRouteTitle();
        paintRoute(startInput.value.toUpperCase(), endInput.value.toUpperCase(), []);
      }
    });

    row.addEventListener("dragstart", (event) => {
      row.classList.add("dragging");
      event.dataTransfer.setData("text/plain", waypoint.id);
      event.dataTransfer.effectAllowed = "move";
    });

    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });

    row.addEventListener("drop", (event) => {
      event.preventDefault();
      const draggedId = event.dataTransfer.getData("text/plain");
      reorderWaypoint(draggedId, waypoint.id);
    });

    remove.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removeWaypoint(waypoint.id);
    });

    body.append(label, input);
    row.append(node, body, remove);
    waypointList.append(row);
  });
}

function reorderWaypoint(draggedId, targetId) {
  if (!draggedId || draggedId === targetId) {
    return;
  }
  const fromIndex = waypoints.findIndex((waypoint) => waypoint.id === draggedId);
  const toIndex = waypoints.findIndex((waypoint) => waypoint.id === targetId);
  if (fromIndex < 0 || toIndex < 0) {
    return;
  }
  const [moved] = waypoints.splice(fromIndex, 1);
  waypoints.splice(toIndex, 0, moved);
  renderWaypoints();
  updateRouteTitle();
  paintRoute(startInput.value.toUpperCase(), endInput.value.toUpperCase(), []);
}

function removeWaypoint(id) {
  if (running) {
    return;
  }
  waypoints = waypoints.filter((waypoint) => waypoint.id !== id);
  if (activeTarget === id) {
    activeTarget = "end";
  }
  renderWaypoints();
  setActiveTarget(activeTarget);
  updateRouteTitle();
}

function addWaypoint() {
  if (running) {
    return;
  }
  const usedPoints = new Set(getRouteStops());
  const seedPoint = points.find((point) => !usedPoints.has(point)) || "C3";
  const waypoint = {
    id: `waypoint-${++waypointCounter}`,
    value: seedPoint,
  };
  waypoints.push(waypoint);
  renderWaypoints();
  setActiveTarget(waypoint.id);
  updateRouteTitle();
}

function syncActiveFields() {
  document.querySelectorAll(".waypoint-field").forEach((row) => {
    row.classList.toggle("active", row.dataset.id === activeTarget);
  });
}

function setActiveTarget(target) {
  activeTarget = target;
  const isStart = target === "start";
  const isEnd = target === "end";
  startField.classList.toggle("active", isStart);
  endField.classList.toggle("active", isEnd);
  document.body.classList.toggle("selecting-end", !isStart);
  syncActiveFields();
  paintRoute(startInput.value.toUpperCase(), endInput.value.toUpperCase(), []);
}

function pathToSvgPoints(path) {
  return path
    .map((point) => {
      const pos = pointToPercent(point);
      return `${pos.left},${pos.top}`;
    })
    .join(" ");
}

function paintRoute(start, end, progressPath = []) {
  if (!pointToCoord(start) || !pointToCoord(end)) {
    return;
  }
  const waypointStops = getWaypointValues().filter((point) => pointToCoord(point));
  const stops = [start, ...waypointStops, end];
  const routePath = buildMultiStopPath(stops);
  routePolyline.setAttribute("points", pathToSvgPoints(routePath));
  progressPolyline.setAttribute("points", pathToSvgPoints(progressPath));

  document.querySelectorAll(".grid-point").forEach((node) => {
    node.classList.toggle("start", node.dataset.point === start);
    node.classList.toggle("end", node.dataset.point === end);
    node.classList.toggle("waypoint", waypointStops.includes(node.dataset.point));
  });
}

function clearTimers() {
  timers.forEach((timer) => window.clearTimeout(timer));
  timers = [];
}

function schedule(delay, callback) {
  const timer = window.setTimeout(callback, delay);
  timers.push(timer);
}

function validatePoint(input, name) {
  const coord = pointToCoord(input);
  if (!coord) {
    throw new Error(`${name} 必须是 A1 到 E5 之间的点位`);
  }
  return coord.point;
}

function startRide(start, end) {
  const routeStops = [start, ...getWaypointValues(), end];
  const routeLabel = routeStops.join(" → ");
  clearTimers();
  running = true;
  callButton.disabled = true;
  setCallButtonLabel("行程进行中");
  messageList.innerHTML = "";
  routeTitle.textContent = routeLabel;
  etaText.textContent = "派单中";
  setCarBusy(true);
  setMessage("乘客", `请求路线 ${routeLabel}`, true);

  schedule(1000, () => {
    setMessage("小车", `收到叫车请求，当前上报位置 ${carPoint}`, true);
    etaText.textContent = "来车中";
  });

  const pickupPath = buildPath(carPoint, start);
  const tripPath = buildMultiStopPath(routeStops);
  const fullPath = [...pickupPath, ...tripPath.slice(1)];
  const straightSegments = buildStraightSegments(fullPath);

  paintRoute(start, end, [carPoint]);

  straightSegments.forEach((segment) => {
    schedule(1800 + segment.startIndex * 850, () => {
      etaText.textContent = `直线行驶 ${segment.from} → ${segment.to}`;
      setMessage("小车", `直线行驶 ${segment.from} → ${segment.to}`);
    });
  });

  fullPath.forEach((point, index) => {
    schedule(1800 + index * 850, () => {
      setCarPoint(point);
      progressPolyline.setAttribute("points", pathToSvgPoints(fullPath.slice(0, index + 1)));
      if (point === start) {
        etaText.textContent = "已到起点";
        setMessage("小车", `已到达起点 ${start}，请上车`, true);
      } else if (index > pickupPath.length - 1 && point !== end) {
        etaText.textContent = `当前位置 ${point}`;
      } else if (point === end) {
        etaText.textContent = `当前位置 ${point}`;
      }
    });
  });

  schedule(1800 + fullPath.length * 850, () => {
    setCarPoint(end);
    etaText.textContent = "已到达";
    setCarBusy(false);
    setMessage("小车", `已到达终点 ${end}，即将发送到达邮件`, true);
    mailSubject.textContent = `4WD 小车到达通知：${end}`;
    mailBody.textContent = `模拟邮件：小车已完成路线 ${routeLabel}，当前位置 ${end}。后期可由树莓派实际发送。`;
    callButton.disabled = false;
    setCallButtonLabel("再次叫车");
    running = false;
  });
}

function resetRide(options = {}) {
  const { reportPosition = false } = options;
  const reportedPoint = carPoint;
  clearTimers();
  running = false;
  waypoints = [];
  activeTarget = "start";
  renderWaypoints();
  callButton.disabled = false;
  setCallButtonLabel("叫车");
  updateRouteTitle();
  etaText.textContent = "待开始";
  messageList.innerHTML = "";
  setCarPoint(reportedPoint);
  setCarBusy(false);
  if (reportPosition) {
    setMessage("系统", `已重置，当前小车位置 ${reportedPoint}`);
  } else {
    setMessage("系统", "等待小车上报位置。");
  }
  setActiveTarget("start");
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

function switchView(viewName) {
  const isMail = viewName === "mail";
  homeView.classList.toggle("active", !isMail);
  mailView.classList.toggle("active", isMail);
  navLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.viewLink === viewName);
  });
}

function initGrid() {
  datalist.innerHTML = points.map((point) => `<option value="${point}"></option>`).join("");

  rows.forEach((_, rowIndex) => {
    const line = document.createElement("div");
    line.className = "grid-line horizontal";
    line.style.top = `${10 + rowIndex * 20}%`;
    gridLines.append(line);
  });

  cols.forEach((_, colIndex) => {
    const line = document.createElement("div");
    line.className = "grid-line vertical";
    line.style.left = `${10 + colIndex * 20}%`;
    gridLines.append(line);
  });

  points.forEach((point) => {
    const marker = document.createElement("button");
    const pos = pointToPercent(point);
    marker.type = "button";
    marker.className = "grid-point";
    marker.dataset.point = point;
    marker.textContent = point;
    marker.style.left = `${pos.left}%`;
    marker.style.top = `${pos.top}%`;
    marker.addEventListener("click", () => {
      if (running) {
        return;
      }
      if (activeTarget === "end") {
        endInput.value = point;
      } else if (activeTarget.startsWith("waypoint-")) {
        const waypoint = waypoints.find((item) => item.id === activeTarget);
        if (waypoint) {
          waypoint.value = point;
          renderWaypoints();
        }
      } else {
        startInput.value = point;
      }
      paintRoute(startInput.value.toUpperCase(), endInput.value.toUpperCase(), []);
      updateRouteTitle();
    });
    gridPointsLayer.append(marker);
  });
}

rideForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (running) {
    return;
  }

  try {
    const start = validatePoint(startInput.value, "起点");
    const end = validatePoint(endInput.value, "终点");
    const validatedWaypoints = waypoints.map((waypoint, index) =>
      validatePoint(waypoint.value, `途径点 ${index + 1}`)
    );
    const uniqueStops = new Set([start, ...validatedWaypoints, end]);
    if (uniqueStops.size < validatedWaypoints.length + 2) {
      throw new Error("起点、途径点和终点不能重复");
    }
    if (start === end) {
      throw new Error("起点和终点不能相同");
    }
    startInput.value = start;
    endInput.value = end;
    waypoints = waypoints.map((waypoint, index) => ({
      ...waypoint,
      value: validatedWaypoints[index],
    }));
    renderWaypoints();
    startRide(start, end);
  } catch (error) {
    setMessage("系统", error.message, true);
  }
});

resetButton.addEventListener("click", () => resetRide({ reportPosition: true }));
addWaypointButton.addEventListener("click", addWaypoint);

startField.addEventListener("click", () => setActiveTarget("start"));
endField.addEventListener("click", () => setActiveTarget("end"));
startInput.addEventListener("focus", () => setActiveTarget("start"));
endInput.addEventListener("focus", () => setActiveTarget("end"));

[startInput, endInput].forEach((input) => {
  input.addEventListener("input", () => {
    input.value = input.value.toUpperCase();
    if (!running && pointToCoord(startInput.value) && pointToCoord(endInput.value)) {
      updateRouteTitle();
      paintRoute(startInput.value, endInput.value, []);
    }
  });
});

navLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    switchView(link.dataset.viewLink);
  });
});

simulateMailButton.addEventListener("click", () => {
  const position = carPositionText.textContent;
  mailSubject.textContent = `4WD 小车到达通知：${position}`;
  mailBody.textContent = `模拟邮件：小车当前上报位置为 ${position}。真实版本会由树莓派发送邮件。`;
});

initGrid();
resetRide();
setActiveTarget("start");
