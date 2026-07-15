let rows = [];
let cols = [];
let points = [];

const homeView = document.querySelector("#homeView");
const obstacleView = document.querySelector("#obstacleView");
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
const refreshObstaclesButton = document.querySelector("#refreshObstaclesButton");
const obstacleList = document.querySelector("#obstacleList");

let running = false;
let carPoint = "C3";
let activeTarget = "start";
let waypointCounter = 0;
let waypoints = [];
let activeRideId = null;
let lastEventSeq = 0;
let pollTimer = null;
let obstacleRecords = new Map();
let carHeading = "north";

const terminalRideStatuses = new Set(["arrived", "failed", "canceled"]);
const eventTypeLabels = {
  system: "系统",
  passenger: "乘客",
  car: "小车",
  mail: "邮件",
  obstacle: "障碍",
};
const headingLabels = {
  north: "上",
  east: "右",
  south: "下",
  west: "左",
};

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

/**
 * 请求同源后端并统一处理 JSON 与接口错误。
 * @param {string} path API 路径。
 * @param {RequestInit} options fetch 请求参数。
 * @returns {Promise<object|null>} JSON 数据或 204 对应的 null。
 * 分步逻辑：发送请求，识别 204，再按统一错误契约解析 JSON。
 */
async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) {
    return null;
  }

  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error.message);
    error.code = payload.error.code;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function getWaypointValues() {
  return waypoints.map((waypoint) => waypoint.value.trim().toUpperCase()).filter(Boolean);
}

function getRouteStops() {
  return [startInput.value.trim().toUpperCase(), ...getWaypointValues(), endInput.value.trim().toUpperCase()];
}

function updateRouteTitle() {
  renderRouteTitle(getRouteStops());
}

function renderRouteTitle(stops, progressPath = []) {
  const currentPoint = progressPath.at(-1);
  const passedPoints = new Set(progressPath.slice(0, -1));
  let currentIndex = stops.indexOf(currentPoint);

  if (currentIndex < 0) {
    currentIndex = stops.findIndex((stop) => !passedPoints.has(stop));
  }
  if (currentIndex < 0) {
    currentIndex = stops.length - 1;
  }

  routeTitle.replaceChildren();
  stops.forEach((stop, index) => {
    const station = document.createElement("span");
    station.className = "route-stop";
    station.textContent = stop;
    station.classList.toggle("passed", passedPoints.has(stop));
    station.classList.toggle("current", index === currentIndex);
    routeTitle.append(station);

    if (index < stops.length - 1) {
      const separator = document.createElement("span");
      separator.className = "route-separator";
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "→";
      routeTitle.append(separator);
    }
  });
}

/**
 * 更新消息面板顶部的当前消息，不追加历史记录。
 * @param {string} type 中文消息类型。
 * @param {string} text 消息正文。
 * 分步逻辑：分别更新类型和正文节点。
 */
function showCurrentMessage(type, text) {
  messageType.textContent = type;
  messageText.textContent = text;
}

function setMessage(type, text) {
  showCurrentMessage(type, text);
  addMessage(type, text);
}

function addMessage(type, text, createdAt = null, obstacle = null) {
  const item = document.createElement("li");
  const time = document.createElement("time");
  time.textContent = new Date(createdAt || Date.now()).toLocaleTimeString();
  item.append(time, document.createTextNode(`${type}：${text}`));
  if (obstacle !== null) {
    item.classList.add("obstacle-message");
    const link = document.createElement("a");
    link.className = "obstacle-message-link";
    link.href = "#obstacles";
    link.textContent = "查看障碍记录";
    link.addEventListener("click", (event) => {
      event.preventDefault();
      switchView("obstacles");
      loadObstacles().catch((error) => setMessage("系统", error.message));
    });
    item.append(link);
  }
  messageList.append(item);
  messageList.scrollTop = messageList.scrollHeight;
  return item;
}

/**
 * 更新地图小车的可信点位和朝向。
 * @param {string} point 后端上报的网格点位。
 * @param {string|null} heading north/east/south/west；不传时保留最近朝向。
 * 分步逻辑：先同步有效朝向，再更新坐标、无障碍标签和可见状态。
 */
function setCarPoint(point, heading = null) {
  if (Object.hasOwn(headingLabels, heading)) {
    carHeading = heading;
    carMarker.dataset.heading = heading;
  }
  carPoint = point;
  carPositionText.textContent = point;
  const pos = pointToPercent(point);
  carMarker.style.left = `${pos.left}%`;
  carMarker.style.top = `${pos.top}%`;
  carMarker.setAttribute(
    "aria-label",
    `小车当前位置 ${point}，朝向${headingLabels[carHeading]}`
  );
  carMarker.classList.add("is-positioned");
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

/**
 * 统一切换行程运行状态对应的表单和按钮状态。
 * @param {boolean} isRunning 是否存在正在运行的行程。
 * 分步逻辑：锁定表单，更新忙碌标识，再切换重置/取消按钮。
 */
function setRideRunning(isRunning) {
  const stateChanged = running !== isRunning;
  running = isRunning;
  callButton.disabled = isRunning;
  startInput.disabled = isRunning;
  endInput.disabled = isRunning;
  addWaypointButton.disabled = isRunning;
  resetButton.disabled = false;
  setCarBusy(isRunning);

  const icon = document.createElement("span");
  icon.className = "button-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = isRunning ? "×" : "↻";
  resetButton.replaceChildren(
    icon,
    document.createTextNode(isRunning ? "取消行程" : "重置")
  );
  if (stateChanged) {
    renderWaypoints();
  }
}

/**
 * 将取消按钮切换为等待前方节点停车的只读状态。
 * 参数说明：无。
 * 分步逻辑：禁用重复取消，再明确提示小车仍在完成当前边。
 */
function setCancelingState() {
  resetButton.disabled = true;
  const icon = document.createElement("span");
  icon.className = "button-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "…";
  resetButton.replaceChildren(
    icon,
    document.createTextNode("等待节点停车")
  );
}

function renderWaypoints() {
  waypointList.innerHTML = "";

  waypoints.forEach((waypoint, index) => {
    const row = document.createElement("label");
    row.className = "field-row route-field waypoint-field";
    row.dataset.id = waypoint.id;
    row.draggable = !running;
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
    input.disabled = running;

    const remove = document.createElement("button");
    remove.className = "waypoint-remove";
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `删除途径点 ${index + 1}`);
    remove.disabled = running;

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

function paintRoute(start, end, progressPath = [], backendRoute = null) {
  if (!pointToCoord(start) || !pointToCoord(end)) {
    return;
  }
  const waypointStops = getWaypointValues().filter((point) => pointToCoord(point));
  const stops = [start, ...waypointStops, end];
  const selectedPoint = getSelectedMapPoint(start, end);
  const routePath = backendRoute === null ? buildMultiStopPath(stops) : backendRoute;
  routePolyline.setAttribute("points", pathToSvgPoints(routePath));
  progressPolyline.setAttribute(
    "points",
    progressPath.length > 1 ? pathToSvgPoints(progressPath) : ""
  );

  document.querySelectorAll(".grid-point").forEach((node) => {
    node.classList.toggle("start", node.dataset.point === start);
    node.classList.toggle("end", node.dataset.point === end);
    node.classList.toggle("waypoint", waypointStops.includes(node.dataset.point));
    node.classList.toggle("selected", node.dataset.point === selectedPoint);
  });

}

function getSelectedMapPoint(start, end) {
  if (activeTarget === "start") {
    return start;
  }
  if (activeTarget === "end") {
    return end;
  }

  const waypoint = waypoints.find((item) => item.id === activeTarget);
  return waypoint && pointToCoord(waypoint.value) ? waypoint.value.trim().toUpperCase() : null;
}

function validatePoint(input, name) {
  const coord = pointToCoord(input);
  if (!coord) {
    throw new Error(`${name} 必须是 A1 到 E5 之间的点位`);
  }
  return coord.point;
}

/**
 * 停止下一次行程轮询。
 * 参数说明：无。
 * 分步逻辑：存在定时器时取消，并清空定时器 ID。
 */
function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

/**
 * 安排下一次非重叠行程轮询。
 * @param {number} delay 等待毫秒数。
 * 分步逻辑：先清除旧调度，再创建唯一的新定时器。
 */
function scheduleRidePoll(delay) {
  stopPolling();
  pollTimer = window.setTimeout(pollRide, delay);
}

/**
 * 使用后端行程恢复起点、终点和途径点表单。
 * @param {object} ride 后端行程状态。
 * 分步逻辑：写入起终点，重建途径点，再渲染表单。
 */
function syncRideForm(ride) {
  startInput.value = ride.start;
  endInput.value = ride.end;
  waypoints = ride.waypoints.map((value) => ({
    id: `waypoint-${++waypointCounter}`,
    value,
  }));
  activeTarget = "start";
  renderWaypoints();
}

/**
 * 将后端行程状态渲染到地图、进度和操作控件。
 * @param {object} ride 后端行程状态。
 * @param {string|null} heading 后端小车状态中的当前朝向。
 * @returns {boolean} 行程是否已经结束。
 * 分步逻辑：更新位置与路线，再根据终态锁定或解锁控件。
 */
function renderRide(ride, heading = null) {
  const routeStops = [ride.start, ...ride.waypoints, ride.end];
  const isTerminal = terminalRideStatuses.has(ride.status);
  setCarPoint(ride.current_position, heading);
  etaText.textContent = ride.eta_text;
  renderRouteTitle(routeStops, ride.progress);
  paintRoute(ride.start, ride.end, ride.progress, ride.route);
  setRideRunning(!isTerminal);
  if (ride.status === "canceling") {
    setCancelingState();
  }
  setCallButtonLabel(
    isTerminal
      ? (ride.status === "arrived" ? "再次叫车" : "重新叫车")
      : (ride.status === "canceling" ? "取消中" : "行程进行中")
  );
  return isTerminal;
}

/**
 * 按递增序号追加后端事件，避免轮询产生重复消息。
 * @param {object} eventPage 事件列表和下一游标。
 * 分步逻辑：跳过旧序号，追加新事件，最后推进游标。
 */
async function appendRideEvents(eventPage) {
  const hasNewObstacle = eventPage.events.some(
    (event) => event.seq > lastEventSeq && event.obstacle_id
  );
  if (hasNewObstacle) {
    await loadObstacles();
  }
  eventPage.events.forEach((event) => {
    if (event.seq <= lastEventSeq) {
      return;
    }
    const type = eventTypeLabels[event.type] || "系统";
    const obstacle = event.obstacle_id
      ? obstacleRecords.get(event.obstacle_id) || null
      : null;
    addMessage(type, event.text, event.created_at, obstacle);
    showCurrentMessage(type, event.text);
    lastEventSeq = event.seq;
  });
  lastEventSeq = Math.max(lastEventSeq, eventPage.next_after);
}

/**
 * 渲染后端持久化障碍记录。
 * @param {object[]} records 按时间倒序的障碍记录。
 * 分步逻辑：空列表显示说明；否则逐条展示障碍边、状态和恢复字段。
 */
function renderObstacles(records) {
  obstacleList.replaceChildren();
  if (records.length === 0) {
    const empty = document.createElement("p");
    empty.className = "obstacle-empty";
    empty.textContent = "暂无障碍记录。小车确认障碍并完成恢复后会显示在这里。";
    obstacleList.append(empty);
    return;
  }

  records.forEach((record) => {
    const card = document.createElement("article");
    card.className = "obstacle-card";

    const content = document.createElement("div");
    content.className = "obstacle-card-content";
    const top = document.createElement("div");
    top.className = "obstacle-card-top";
    const title = document.createElement("h2");
    title.textContent = `${record.from_point} → ${record.to_point}`;
    const badge = document.createElement("span");
    badge.className = `obstacle-status ${record.status}`;
    badge.textContent = record.status === "recovered" ? "已恢复并绕行" : "恢复失败";
    top.append(title, badge);

    const details = document.createElement("dl");
    [
      ["确认距离", `${record.distance_cm.toFixed(1)} cm`],
      ["恢复点位", record.recovered_point || "未恢复到可信节点"],
      ["记录时间", new Date(record.created_at).toLocaleString()],
    ].forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      details.append(term, description);
    });
    content.append(top, details);
    card.append(content);
    obstacleList.append(card);
  });
}

/**
 * 从后端刷新全部持久化障碍记录。
 * 参数说明：无。
 * 分步逻辑：读取障碍接口，更新 ID 索引和障碍记录页。
 */
async function loadObstacles() {
  const records = await requestJson("/api/obstacles");
  obstacleRecords = new Map(records.map((record) => [record.id, record]));
  renderObstacles(records);
  return records;
}

/**
 * 同步一次活动行程及其增量事件，并安排下一轮轮询。
 * 参数说明：无，使用当前 activeRideId 和 lastEventSeq。
 * 分步逻辑：并行读取行程、事件和朝向，处理终态；失败时保持锁定并重试。
 */
async function pollRide() {
  pollTimer = null;
  const rideId = activeRideId;
  if (rideId === null) {
    return;
  }

  try {
    const [ride, eventPage, carStatus] = await Promise.all([
      requestJson(`/api/rides/${rideId}`),
      requestJson(`/api/rides/${rideId}/events?after=${lastEventSeq}`),
      requestJson("/api/car/status"),
    ]);
    if (activeRideId !== rideId) {
      return;
    }

    const isTerminal = renderRide(ride, carStatus.heading);
    await appendRideEvents(eventPage);
    if (isTerminal) {
      activeRideId = null;
      return;
    }
    scheduleRidePoll(500);
  } catch (error) {
    if (activeRideId !== rideId) {
      return;
    }
    if (error.code === "ride_not_found") {
      showCurrentMessage("系统", "后端已无法找到当前行程，请确认服务状态后再操作");
      resetButton.disabled = true;
      return;
    }
    showCurrentMessage("系统", `状态同步失败：${error.message}，正在重试`);
    scheduleRidePoll(1000);
  }
}

/**
 * 进入指定后端行程的跟踪状态。
 * @param {object} ride 新建或恢复的活动行程。
 * 分步逻辑：重置轮询和事件游标，恢复表单，渲染后立即同步。
 */
function startTrackingRide(ride) {
  stopPolling();
  activeRideId = ride.id;
  lastEventSeq = 0;
  messageList.innerHTML = "";
  syncRideForm(ride);
  renderRide(ride);
  pollRide();
}

function resetRide(options = {}) {
  const { reportPosition = false } = options;
  const reportedPoint = carPoint;
  stopPolling();
  activeRideId = null;
  lastEventSeq = 0;
  waypoints = [];
  activeTarget = "start";
  setRideRunning(false);
  renderWaypoints();
  resetButton.disabled = false;
  setCallButtonLabel("叫车");
  updateRouteTitle();
  etaText.textContent = "待开始";
  messageList.innerHTML = "";
  setCarPoint(reportedPoint);
  if (reportPosition) {
    setMessage("系统", `已重置，当前小车位置 ${reportedPoint}`);
  } else {
    setMessage("系统", "等待小车上报位置。");
  }
  setActiveTarget("start");
}

function switchView(viewName) {
  const isObstacles = viewName === "obstacles";
  homeView.classList.toggle("active", !isObstacles);
  obstacleView.classList.toggle("active", isObstacles);
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

/**
 * 从后端初始化网格、小车、活动行程和障碍记录。
 * 参数说明：无。
 * 分步逻辑：先加载网格，再并行读取状态；失败时锁定叫车入口。
 */
async function initializeApp() {
  callButton.disabled = true;
  resetButton.disabled = true;
  setCallButtonLabel("连接后端中");

  try {
    const grid = await requestJson("/api/grid");
    rows = grid.rows;
    cols = grid.cols;
    points = grid.points;
    initGrid();

    const [carStatus, activeRide, obstacles] = await Promise.all([
      requestJson("/api/car/status"),
      requestJson("/api/rides/active"),
      requestJson("/api/obstacles"),
    ]);
    setCarPoint(carStatus.current_position, carStatus.heading);
    obstacleRecords = new Map(
      obstacles.map((record) => [record.id, record])
    );
    renderObstacles(obstacles);

    if (activeRide !== null) {
      startTrackingRide(activeRide);
      return;
    }

    resetRide();
    messageList.innerHTML = "";
    setMessage("系统", carStatus.last_message);
  } catch (error) {
    callButton.disabled = true;
    resetButton.disabled = true;
    setCallButtonLabel("后端不可用");
    setMessage("系统", `初始化失败：${error.message}`);
  }
}

rideForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (running) {
    return;
  }

  let requestStarted = false;
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
    callButton.disabled = true;
    setCallButtonLabel("提交中");
    requestStarted = true;
    const ride = await requestJson("/api/rides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start, waypoints: validatedWaypoints, end }),
    });
    startTrackingRide(ride);
  } catch (error) {
    if (!requestStarted || (error.status >= 400 && error.status < 500)) {
      callButton.disabled = false;
      setCallButtonLabel("叫车");
      setMessage("系统", error.message);
      return;
    }

    setRideRunning(true);
    resetButton.disabled = true;
    setCallButtonLabel("状态待确认");
    setMessage("系统", "叫车结果未知，请恢复连接后刷新页面确认行程状态");
  }
});

resetButton.addEventListener("click", async () => {
  if (!running || activeRideId === null) {
    resetRide({ reportPosition: true });
    return;
  }

  const rideId = activeRideId;
  stopPolling();
  resetButton.disabled = true;
  showCurrentMessage("系统", "取消请求发送中，小车将继续到前方下一个节点停车");
  try {
    await requestJson(`/api/rides/${rideId}/cancel`, { method: "POST" });
    await pollRide();
  } catch (error) {
    resetButton.disabled = false;
    showCurrentMessage("系统", `取消失败：${error.message}，正在重新同步`);
    scheduleRidePoll(1000);
  }
});
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
    const viewName = link.dataset.viewLink;
    switchView(viewName);
    if (viewName === "obstacles") {
      loadObstacles().catch((error) => setMessage("系统", error.message));
    }
  });
});

refreshObstaclesButton.addEventListener("click", () => {
  loadObstacles().catch((error) => setMessage("系统", error.message));
});

initializeApp();
