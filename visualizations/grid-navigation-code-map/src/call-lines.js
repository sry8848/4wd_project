import {
  assignIntervalLanes,
  assignTargetPorts,
} from './route-layout.js';

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const LANE_GAP = 14;
const LANE_CLEARANCE = 6;
const CORRIDOR_MARGIN = 20;
const TARGET_PORT_MARGIN = 6;
const TARGET_PORT_GAP = 6;
const DEFAULT_DIRECTORY_GAP = 180;

export function clearCallLines(svg, root = null) {
  svg.querySelectorAll('[data-call-line]').forEach((path) => path.remove());
  if (root) resetDynamicLayout(root);
}

/**
 * 只改变现有调用线的阅读焦点，不重新计算端口或通道。
 *
 * @param {SVGElement} svg 覆盖在代码树上的 SVG 图层。
 * @param {{methodId: string, direction: 'incoming'|'outgoing'} | null} focus
 *   当前聚焦的方法与方向；null 表示恢复全部线路的原始样式。
 */
export function applyCallLineFocus(svg, focus) {
  svg.querySelectorAll('[data-call-line]').forEach((path) => {
    const focused = Boolean(focus) && (
      focus.direction === 'incoming'
        ? path.dataset.targetMethodId === focus.methodId
        : path.dataset.sourceMethodId === focus.methodId
    );
    path.classList.toggle('call-line--focused', focused);
    path.classList.toggle('call-line--dimmed', Boolean(focus) && !focused);
    path.setAttribute(
      'marker-end',
      `url(#arrow-${focused ? 'focus' : path.dataset.tone})`,
    );
  });
}

/**
 * 根据当前 DOM 的真实位置自动分配走廊、通道和目标端口，再绘制调用线。
 *
 * @param {SVGElement} svg 覆盖在代码树上的 SVG 图层。
 * @param {Element} root 代码目录树根节点。
 * @param {Array<object>} calls 当前所有已展开来源方法的调用关系。
 */
export function drawCallLines(svg, root, calls) {
  clearCallLines(svg);
  if (calls.length === 0) {
    resetDynamicLayout(root);
    return;
  }

  prepareTargetHeights(root, calls);
  const preliminaryLayout = layoutRoutes(measureRoutes(svg, root, calls));
  applyCorridorSpacing(root, preliminaryLayout.corridors);

  const finalLayout = layoutRoutes(measureRoutes(svg, root, calls));
  const paths = finalLayout.routes.map((route) => buildCallPath(svg, route));
  svg.append(...paths);
}

function prepareTargetHeights(root, calls) {
  root.querySelectorAll('[data-method-target]').forEach((title) => {
    title.style.removeProperty('min-height');
  });

  const sideCounts = new Map();
  calls.forEach((call) => {
    const key = `${call.targetMethodId}:${call.targetSide}`;
    sideCounts.set(key, (sideCounts.get(key) || 0) + 1);
  });

  const requiredByMethod = new Map();
  sideCounts.forEach((count, key) => {
    const methodId = key.slice(0, key.lastIndexOf(':'));
    const requiredHeight = TARGET_PORT_MARGIN * 2 + (count - 1) * TARGET_PORT_GAP;
    requiredByMethod.set(
      methodId,
      Math.max(requiredByMethod.get(methodId) || 0, requiredHeight),
    );
  });
  requiredByMethod.forEach((height, methodId) => {
    const method = findByData(root, 'methodId', methodId);
    method?.querySelector('[data-method-target]')
      ?.style.setProperty('min-height', `${height}px`);
  });
}

function measureRoutes(svg, root, calls) {
  const directories = [...root.querySelectorAll('.directory--child')]
    .map((element) => ({
      element,
      id: element.dataset.directoryId,
      rect: toSvgRect(svg, element.getBoundingClientRect()),
    }))
    .sort((left, right) => left.rect.left - right.rect.left)
    .map((directory, index) => ({ ...directory, index }));

  return calls.map((call) => {
    const sourceMethod = findByData(root, 'methodId', call.sourceMethodId);
    const targetMethod = findByData(root, 'methodId', call.targetMethodId);
    const sourceCall = findByData(sourceMethod, 'callId', call.id);
    const sourceStep = sourceCall?.closest('[data-step-id]');
    const targetTitle = targetMethod?.querySelector('[data-method-target]');
    const sourceDirectoryElement = sourceMethod?.closest('.directory--child');
    const targetDirectoryElement = targetMethod?.closest('.directory--child');
    const sourceDirectory = directories
      .find((directory) => directory.element === sourceDirectoryElement);
    const targetDirectory = directories
      .find((directory) => directory.element === targetDirectoryElement);

    if (
      !sourceCall
      || !sourceStep
      || !targetTitle
      || !sourceDirectory
      || !targetDirectory
    ) {
      throw new Error(`调用 ${call.id} 找不到来源行、目标方法或目录`);
    }

    return {
      call,
      sourceStep,
      sourceRect: toSvgRect(svg, sourceCall.getBoundingClientRect()),
      targetRect: toSvgRect(svg, targetTitle.getBoundingClientRect()),
      sourceDirectory,
      targetDirectory,
      corridor: selectCorridor(call, sourceDirectory, targetDirectory, directories),
    };
  });
}

function selectCorridor(call, sourceDirectory, targetDirectory, directories) {
  if (call.targetSide !== 'left' && call.targetSide !== 'right') {
    throw new Error(`调用 ${call.id} 的 targetSide 必须是 left 或 right`);
  }

  if (sourceDirectory === targetDirectory) {
    const direction = call.targetSide === 'left' ? -1 : 1;
    const neighbor = directories[sourceDirectory.index + direction];
    if (!neighbor) {
      return {
        key: `outer:${call.targetSide}:${sourceDirectory.id}`,
        kind: call.targetSide === 'left' ? 'outer-left' : 'outer-right',
        directory: sourceDirectory,
        sourceSide: call.targetSide,
      };
    }
    const leftDirectory = direction < 0 ? neighbor : sourceDirectory;
    const rightDirectory = direction < 0 ? sourceDirectory : neighbor;
    return {
      key: `between:${leftDirectory.id}:${rightDirectory.id}`,
      kind: 'between',
      leftDirectory,
      rightDirectory,
      sourceSide: call.targetSide,
    };
  }

  if (Math.abs(sourceDirectory.index - targetDirectory.index) !== 1) {
    throw new Error(`调用 ${call.id} 跨越非相邻目录，当前地图没有安全走廊`);
  }
  const targetIsLeft = targetDirectory.index < sourceDirectory.index;
  const expectedTargetSide = targetIsLeft ? 'right' : 'left';
  if (call.targetSide !== expectedTargetSide) {
    throw new Error(
      `调用 ${call.id} 的 targetSide=${call.targetSide} 没有面向目录间走廊`,
    );
  }
  const leftDirectory = targetIsLeft ? targetDirectory : sourceDirectory;
  const rightDirectory = targetIsLeft ? sourceDirectory : targetDirectory;
  return {
    key: `between:${leftDirectory.id}:${rightDirectory.id}`,
    kind: 'between',
    leftDirectory,
    rightDirectory,
    sourceSide: targetIsLeft ? 'left' : 'right',
  };
}

function layoutRoutes(routes) {
  const portGroups = groupBy(routes, (route) => (
    `${route.call.targetMethodId}:${route.call.targetSide}`
  ));
  portGroups.forEach((group) => {
    const targetRect = group[0].targetRect;
    const ports = assignTargetPorts(
      group.map((route) => ({
        id: route.call.id,
        sourceY: centerY(route.sourceRect),
        sortHint: route.call.lane,
      })),
      targetRect.top + TARGET_PORT_MARGIN,
      targetRect.bottom - TARGET_PORT_MARGIN,
      TARGET_PORT_GAP,
    );
    group.forEach((route) => {
      route.targetY = ports.get(route.call.id);
    });
  });

  const corridorGroups = groupBy(routes, (route) => route.corridor.key);
  const corridors = [];
  corridorGroups.forEach((group) => {
    const assignments = assignIntervalLanes(
      group.map((route) => ({
        id: route.call.id,
        startY: centerY(route.sourceRect),
        endY: route.targetY,
        sortHint: route.call.lane,
      })),
      LANE_CLEARANCE,
    );
    const laneCount = Math.max(...assignments.values()) + 1;
    group.forEach((route) => {
      route.laneIndex = assignments.get(route.call.id);
    });
    corridors.push({
      ...group[0].corridor,
      laneCount,
    });
  });

  return { routes, corridors };
}

function applyCorridorSpacing(root, corridors) {
  const grid = root.querySelector('.directory-grid');
  const betweenLaneCount = Math.max(
    0,
    ...corridors
      .filter((corridor) => corridor.kind === 'between')
      .map((corridor) => corridor.laneCount),
  );
  const requiredGap = CORRIDOR_MARGIN * 2 + betweenLaneCount * LANE_GAP;
  grid.style.setProperty(
    '--directory-gap',
    `${Math.max(DEFAULT_DIRECTORY_GAP, requiredGap)}px`,
  );

  for (const kind of ['outer-left', 'outer-right']) {
    const laneCount = Math.max(
      0,
      ...corridors
        .filter((corridor) => corridor.kind === kind)
        .map((corridor) => corridor.laneCount),
    );
    const property = kind === 'outer-left'
      ? '--route-left-gutter'
      : '--route-right-gutter';
    const gutter = laneCount === 0
      ? 0
      : CORRIDOR_MARGIN * 2 + laneCount * LANE_GAP;
    root.style.setProperty(property, `${gutter}px`);
  }
}

function buildCallPath(svg, route) {
  const sourceX = route.corridor.sourceSide === 'left'
    ? route.sourceRect.left
    : route.sourceRect.right;
  const targetX = route.call.targetSide === 'left'
    ? route.targetRect.left
    : route.targetRect.right;
  const laneX = getLaneX(route.corridor, route.laneIndex);
  const path = svg.ownerDocument.createElementNS(SVG_NAMESPACE, 'path');
  const tone = route.sourceStep.dataset.tone === 'error' ? 'error' : 'normal';
  path.setAttribute(
    'd',
    `M ${sourceX} ${centerY(route.sourceRect)} H ${laneX} V ${route.targetY} H ${targetX}`,
  );
  path.setAttribute(
    'class',
    `call-line call-line--${route.call.kind} call-line--${tone}`,
  );
  path.setAttribute('data-call-line', '');
  path.setAttribute('data-call-id', route.call.id);
  path.setAttribute('data-source-method-id', route.call.sourceMethodId);
  path.setAttribute('data-target-method-id', route.call.targetMethodId);
  path.setAttribute('data-tone', tone);
  path.setAttribute('marker-end', `url(#arrow-${tone})`);

  const title = svg.ownerDocument.createElementNS(SVG_NAMESPACE, 'title');
  title.textContent = route.call.label;
  path.append(title);
  return path;
}

function getLaneX(corridor, laneIndex) {
  if (corridor.kind === 'between') {
    return corridor.leftDirectory.rect.right
      + CORRIDOR_MARGIN
      + laneIndex * LANE_GAP;
  }
  if (corridor.kind === 'outer-left') {
    return corridor.directory.rect.left
      - CORRIDOR_MARGIN
      - laneIndex * LANE_GAP;
  }
  return corridor.directory.rect.right
    + CORRIDOR_MARGIN
    + laneIndex * LANE_GAP;
}

function resetDynamicLayout(root) {
  root.querySelector('.directory-grid')?.style.removeProperty('--directory-gap');
  root.style.removeProperty('--route-left-gutter');
  root.style.removeProperty('--route-right-gutter');
  root.querySelectorAll('[data-method-target]').forEach((title) => {
    title.style.removeProperty('min-height');
  });
}

function groupBy(values, getKey) {
  const groups = new Map();
  values.forEach((value) => {
    const key = getKey(value);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(value);
  });
  return groups;
}

function centerY(rect) {
  return rect.top + rect.height / 2;
}

function findByData(root, key, value) {
  if (!root) return null;
  return [...root.querySelectorAll(`[data-${toKebabCase(key)}]`)]
    .find((element) => element.dataset[key] === value);
}

function toKebabCase(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function toSvgRect(svg, rect) {
  const topLeft = toSvgPoint(svg, rect.left, rect.top);
  const bottomRight = toSvgPoint(svg, rect.right, rect.bottom);
  return {
    left: topLeft.x,
    top: topLeft.y,
    right: bottomRight.x,
    bottom: bottomRight.y,
    width: bottomRight.x - topLeft.x,
    height: bottomRight.y - topLeft.y,
  };
}

function toSvgPoint(svg, x, y) {
  const matrix = svg.getScreenCTM();
  if (!matrix) throw new Error('无法读取 SVG 坐标变换');
  return new DOMPoint(x, y).matrixTransform(matrix.inverse());
}
