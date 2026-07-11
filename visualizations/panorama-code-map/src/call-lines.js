const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const LANE_GAP = 12;
const INNER_LANE_INSET = 24;

export function clearCallLines(svg) {
  svg.querySelectorAll('[data-call-line]').forEach((path) => path.remove());
}

/**
 * 根据当前 DOM 的真实位置绘制一组调用线。
 * 卡片和 SVG 位于同一个 Panzoom 画布中，因此只在内容布局变化时重绘。
 */
export function drawCallLines(svg, root, calls) {
  clearCallLines(svg);
  if (calls.length === 0) return;

  const paths = calls.map((call) => buildCallPath(svg, root, call));
  svg.append(...paths);
}

function buildCallPath(svg, root, call) {
  const sourceMethod = findByData(root, 'methodId', call.sourceMethodId);
  const targetMethod = findByData(root, 'methodId', call.targetMethodId);
  const sourceStep = sourceMethod
    ? findByData(sourceMethod, 'stepId', call.sourceStepId)
    : null;
  const targetTitle = targetMethod?.querySelector('[data-method-target]');
  const sourceFile = sourceMethod?.closest('[data-file-id]');
  const targetFile = targetMethod?.closest('[data-file-id]');

  if (!sourceStep || !targetTitle || !sourceFile || !targetFile) {
    throw new Error(`调用 ${call.id} 找不到步骤或目标方法锚点`);
  }

  const sourceRect = sourceStep.getBoundingClientRect();
  const targetRect = targetTitle.getBoundingClientRect();
  const sourceFileRect = sourceFile.getBoundingClientRect();
  const targetFileRect = targetFile.getBoundingClientRect();

  const source = toSvgPoint(
    svg,
    sourceRect.right,
    sourceRect.top + sourceRect.height / 2,
  );
  const target = toSvgPoint(
    svg,
    call.targetSide === 'left' ? targetRect.left : targetRect.right,
    targetRect.top + targetRect.height / 2,
  );
  const sourceFileRight = toSvgPoint(
    svg,
    sourceFileRect.right,
    sourceFileRect.top,
  ).x;
  const targetFileLeft = toSvgPoint(
    svg,
    targetFileRect.left,
    targetFileRect.top,
  ).x;
  const laneBase = sourceFile === targetFile
    ? sourceFileRight - INNER_LANE_INSET
    : (sourceFileRight + targetFileLeft) / 2;
  const laneX = laneBase + call.lane * LANE_GAP;

  const path = svg.ownerDocument.createElementNS(SVG_NAMESPACE, 'path');
  const tone = sourceStep.dataset.tone === 'error' ? 'error' : 'normal';
  path.setAttribute(
    'd',
    `M ${source.x} ${source.y} H ${laneX} V ${target.y} H ${target.x}`,
  );
  path.setAttribute('class', `call-line call-line--${call.kind} call-line--${tone}`);
  path.setAttribute('data-call-line', '');
  path.setAttribute('data-call-id', call.id);
  path.setAttribute('marker-end', `url(#arrow-${tone})`);

  const title = svg.ownerDocument.createElementNS(SVG_NAMESPACE, 'title');
  title.textContent = call.label;
  path.append(title);
  return path;
}

function findByData(root, key, value) {
  return [...root.querySelectorAll(`[data-${toKebabCase(key)}]`)]
    .find((element) => element.dataset[key] === value);
}

function toKebabCase(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function toSvgPoint(svg, x, y) {
  const matrix = svg.getScreenCTM();
  if (!matrix) throw new Error('无法读取 SVG 坐标变换');
  return new DOMPoint(x, y).matrixTransform(matrix.inverse());
}
