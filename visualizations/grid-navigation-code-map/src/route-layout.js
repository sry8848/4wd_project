/**
 * 为正交线路的竖直区间分配可复用通道。
 *
 * @param {Array<{id: string, startY: number, endY: number, sortHint: number}>} routes
 *   待分配线路；sortHint 只用于几何完全相同时保持稳定顺序。
 * @param {number} clearance 区间上下两端追加的安全距离，单位为画布像素。
 * @returns {Map<string, number>} 调用 ID 到零基通道编号的映射。
 */
export function assignIntervalLanes(routes, clearance) {
  if (!Array.isArray(routes)) {
    throw new TypeError('routes must be an array');
  }
  if (!Number.isFinite(clearance)) {
    throw new TypeError('clearance must be finite');
  }
  if (clearance < 0) {
    throw new RangeError('clearance must be >= 0');
  }

  const normalized = normalizeRoutes(routes, ['startY', 'endY']);
  normalized.sort(compareByGeometry);

  const laneEnds = [];
  const assignments = new Map();
  normalized.forEach((route) => {
    const start = Math.min(route.startY, route.endY) - clearance;
    const end = Math.max(route.startY, route.endY) + clearance;
    let laneIndex = laneEnds.findIndex((laneEnd) => laneEnd < start);
    if (laneIndex === -1) {
      laneIndex = laneEnds.length;
      laneEnds.push(end);
    } else {
      laneEnds[laneIndex] = end;
    }
    assignments.set(route.id, laneIndex);
  });
  return assignments;
}

/**
 * 在目标方法标题的一侧为多条入线分配独立端口。
 *
 * @param {Array<{id: string, sourceY: number, sortHint: number}>} routes
 *   指向同一目标同一侧的线路。
 * @param {number} top 可用目标边缘的顶部坐标。
 * @param {number} bottom 可用目标边缘的底部坐标。
 * @param {number} minimumGap 相邻端口中心的最小距离。
 * @returns {Map<string, number>} 调用 ID 到目标端口 y 坐标的映射。
 */
export function assignTargetPorts(routes, top, bottom, minimumGap) {
  if (!Array.isArray(routes)) {
    throw new TypeError('routes must be an array');
  }
  for (const [name, value] of [['top', top], ['bottom', bottom], ['minimumGap', minimumGap]]) {
    if (!Number.isFinite(value)) {
      throw new TypeError(`${name} must be finite`);
    }
  }
  if (bottom < top) {
    throw new RangeError('bottom must be >= top');
  }
  if (minimumGap < 0) {
    throw new RangeError('minimumGap must be >= 0');
  }

  const normalized = normalizeRoutes(routes, ['sourceY']);
  normalized.sort((left, right) => (
    left.sourceY - right.sourceY
    || left.sortHint - right.sortHint
    || left.id.localeCompare(right.id)
  ));
  if (normalized.length === 0) {
    return new Map();
  }
  if (normalized.length === 1) {
    return new Map([[normalized[0].id, (top + bottom) / 2]]);
  }

  const spacing = (bottom - top) / (normalized.length - 1);
  if (spacing < minimumGap) {
    throw new RangeError('target boundary cannot fit ports at minimumGap');
  }

  return new Map(normalized.map((route, index) => [
    route.id,
    top + spacing * index,
  ]));
}

function normalizeRoutes(routes, coordinateNames) {
  const ids = new Set();
  return routes.map((route) => {
    if (route === null || typeof route !== 'object') {
      throw new TypeError('each route must be an object');
    }
    if (typeof route.id !== 'string' || route.id.length === 0) {
      throw new TypeError('route id must be a non-empty string');
    }
    if (ids.has(route.id)) {
      throw new RangeError(`duplicate route id: ${route.id}`);
    }
    ids.add(route.id);
    for (const name of coordinateNames) {
      if (!Number.isFinite(route[name])) {
        throw new TypeError(`${name} must be finite for route ${route.id}`);
      }
    }
    if (!Number.isFinite(route.sortHint)) {
      throw new TypeError(`sortHint must be finite for route ${route.id}`);
    }
    return { ...route };
  });
}

function compareByGeometry(left, right) {
  const leftStart = Math.min(left.startY, left.endY);
  const rightStart = Math.min(right.startY, right.endY);
  const leftEnd = Math.max(left.startY, left.endY);
  const rightEnd = Math.max(right.startY, right.endY);
  return (
    leftStart - rightStart
    || leftEnd - rightEnd
    || left.sortHint - right.sortHint
    || left.id.localeCompare(right.id)
  );
}
