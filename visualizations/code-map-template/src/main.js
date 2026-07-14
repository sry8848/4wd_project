import Panzoom from '@panzoom/panzoom';
import {
  applyCallLineFocus,
  clearCallLines,
  drawCallLines,
} from './call-lines.js';
import { mapData } from './map-data.js';
import './styles.css';

const MIN_SCALE = 0.35;
const MAX_SCALE = 2.4;
const ZOOM_STEP = 1.2;

const app = document.querySelector('#app');
const errorPanel = document.querySelector('#error-panel');
const methodById = new Map(
  mapData.methods.map((method) => [method.id, method]),
);
const runtimeErrors = { lines: null, panzoom: null };

let panzoomInstance = null;
let redrawFrame = null;
let lineFocus = null;
const navigationStack = [];

const canvas = createElement('section', 'panzoom-content');
const callSvg = createCallSvg();
const codeTree = renderCodeTree();
canvas.append(callSvg, codeTree);
app.replaceChildren(canvas);

bindMethodInteraction();
bindCallNavigation();
bindLineFocusControls();
document.addEventListener('keydown', handleJumpBack);
requestRedraw();
initializePanzoom();

window.addEventListener('resize', requestRedraw);
document.fonts?.ready.then(requestRedraw);

function renderCodeTree() {
  const rootDirectory = mapData.directories
    .find((directory) => directory.parentId === null);
  const childDirectories = mapData.directories
    .filter((directory) => directory.parentId === rootDirectory.id);

  const root = createElement('section', 'directory directory--root');
  root.dataset.directoryId = rootDirectory.id;
  root.append(renderNodeHeader('顶层目录', rootDirectory.name, rootDirectory.description));

  const grid = createElement('div', 'directory-grid');
  childDirectories.forEach((directory) => grid.append(renderDirectory(directory)));
  root.append(grid);
  return root;
}

function renderDirectory(directory) {
  const container = createElement('section', 'directory directory--child');
  container.dataset.directoryId = directory.id;
  container.append(renderNodeHeader('子目录', directory.name, directory.description));

  mapData.files
    .filter((file) => file.directoryId === directory.id)
    .forEach((file) => container.append(renderFile(file)));
  return container;
}

function renderFile(file) {
  const container = createElement('article', 'file-node');
  container.dataset.fileId = file.id;
  container.append(renderNodeHeader('文件', file.name, file.description, file.path));

  const methods = createElement('div', 'method-list');
  mapData.methods
    .filter((method) => method.fileId === file.id)
    .sort((left, right) => left.source.startLine - right.source.startLine)
    .forEach((method) => methods.append(renderMethod(method)));
  container.append(methods);
  return container;
}

function renderMethod(method) {
  const details = createElement(
    'details',
    `method-card panzoom-exclude${method.compact ? ' method-card--compact' : ''}`,
  );
  details.dataset.methodId = method.id;
  details.open = method.defaultExpanded;

  const summary = createElement('summary', 'method-summary panzoom-exclude');
  summary.dataset.methodTarget = '';
  summary.append(
    createElement('code', 'method-signature', getMethodName(method.signature)),
    createElement('span', 'method-meaning', method.meaning),
  );

  const body = createElement('div', 'method-body');
  body.append(renderLineFocusControls(method));
  body.append(renderInputs(method));
  body.append(renderOutput(method.output));

  const logic = createElement('section', 'logic-section');
  logic.append(createElement('h4', 'detail-title', '按真实执行顺序'));
  method.steps.forEach((step) => logic.append(renderStep(method, step)));
  body.append(logic);

  const source = createElement('p', 'source-location');
  source.append(
    createElement('span', 'detail-label', '源码'),
    createElement(
      'code',
      '',
      `${method.source.path}:${method.source.startLine}-${method.source.endLine}`,
    ),
  );
  body.append(source);
  details.append(summary, body);
  return details;
}

function renderLineFocusControls(method) {
  const controls = createElement('div', 'line-focus-controls panzoom-exclude');
  for (const [direction, label] of [
    ['incoming', '查看入线'],
    ['outgoing', '查看出线'],
  ]) {
    const button = createElement('button', 'line-focus-button panzoom-exclude', label);
    button.type = 'button';
    button.dataset.focusMethodId = method.id;
    button.dataset.focusDirection = direction;
    button.setAttribute('aria-pressed', 'false');
    controls.append(button);
  }
  return controls;
}

function renderInputs(method) {
  const section = createElement('details', 'io-section panzoom-exclude');
  section.append(createElement('summary', 'io-summary panzoom-exclude', '输入'));
  const content = createElement('div', 'io-content');
  if (method.inputNote) {
    content.append(createElement('p', 'input-note', method.inputNote));
  }
  if (method.inputs.length > 0) {
    content.append(renderFieldList(method.inputs));
  }
  section.append(content);
  section.addEventListener('toggle', requestRedraw);
  return section;
}

function renderOutput(output) {
  const section = createElement('details', 'io-section panzoom-exclude');
  section.append(createElement('summary', 'io-summary panzoom-exclude', '输出'));
  const content = createElement('div', 'io-content');
  content.append(createElement('p', 'output-summary', output.summary));
  if (output.fields?.length) {
    content.append(renderFieldList(output.fields));
  }
  section.append(content);
  section.addEventListener('toggle', requestRedraw);
  return section;
}

function renderFieldList(fields) {
  const list = createElement('ul', 'field-list');
  fields.forEach((field) => list.append(renderField(field)));
  return list;
}

function renderField(field) {
  const item = createElement('li', 'field-row');
  const summary = createElement('div', 'field-summary');
  summary.append(
    createElement('code', 'field-name', field.name),
    createElement('span', 'field-description', field.summary),
  );

  if (field.detail) {
    const help = createElement('span', 'field-help');
    const trigger = createElement('span', 'field-help-trigger', '?');
    const popover = createElement('span', 'field-help-popover', field.detail);
    popover.setAttribute('role', 'tooltip');
    help.append(trigger, popover);
    summary.append(help);
  }

  item.append(summary);
  return item;
}

function renderStep(method, step) {
  const container = createElement(
    'article',
    `logic-step logic-step--${step.tone} panzoom-exclude`,
  );
  container.dataset.stepId = step.id;
  container.dataset.tone = step.tone;
  container.append(createElement('p', 'logic-text', step.text));

  const calls = mapData.calls.filter(
    (call) => call.sourceMethodId === method.id && call.sourceStepId === step.id,
  );
  if (calls.length > 0) {
    const callList = createElement('ul', 'step-call-list');
    calls.forEach((call) => {
      const target = methodById.get(call.targetMethodId);
      const item = createElement('li');
      item.dataset.callId = call.id;
      const targetButton = createElement(
        'button',
        'call-target panzoom-exclude',
        getMethodName(target.signature),
      );
      targetButton.type = 'button';
      targetButton.dataset.targetMethodId = target.id;
      targetButton.title = `展开并跳转到 ${getMethodName(target.signature)}`;
      item.append(
        createElement(
          'span',
          `call-kind call-kind--${call.kind}`,
          call.kind === 'certain' ? '确定调用' : '条件调用',
        ),
        targetButton,
        createElement('span', 'call-label', `：${call.label}`),
      );
      callList.append(item);
    });
    container.append(callList);
  }
  return container;
}

function renderNodeHeader(type, name, description, path = null) {
  const header = createElement('header', 'node-header');
  const title = createElement('div', 'node-title-row');
  title.append(
    createElement('span', 'node-type', type),
    createElement('code', 'node-name', name),
  );
  header.append(title, createElement('p', 'node-description', description));
  if (path) header.append(createElement('code', 'file-path', path));
  return header;
}

function bindMethodInteraction() {
  codeTree.querySelectorAll('[data-method-id]').forEach((details) => {
    details.addEventListener('toggle', () => {
      if (!details.open && lineFocus?.methodId === details.dataset.methodId) {
        lineFocus = null;
      }
      requestRedraw();
    });
  });
}

function bindLineFocusControls() {
  codeTree.querySelectorAll('[data-focus-method-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextFocus = {
        methodId: button.dataset.focusMethodId,
        direction: button.dataset.focusDirection,
      };
      lineFocus = lineFocus?.methodId === nextFocus.methodId
        && lineFocus.direction === nextFocus.direction
        ? null
        : nextFocus;
      const calls = getVisibleCalls();
      updateLineFocusControls(calls);
      applyCallLineFocus(callSvg, lineFocus);
    });
  });
}

function bindCallNavigation() {
  codeTree.querySelectorAll('[data-target-method-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const source = button.closest('[data-method-id]');
      const target = findByData(codeTree, 'methodId', button.dataset.targetMethodId);
      if (!source || !target) return;
      navigationStack.push({
        returnMethodId: source.dataset.methodId,
        openedTargetMethodId: target.dataset.methodId,
        openedTargetWasOpen: target.open,
      });
      target.open = true;
      requestRedraw();
      focusMethod(target);
    });
  });

  callSvg.addEventListener('click', (event) => {
    const clickedArrow = event.target.closest('[data-call-arrow]');
    if (!clickedArrow) return;
    const arrow = [...callSvg.querySelectorAll('[data-call-arrow]')]
      .reduce((nearest, candidate) => {
        const rect = candidate.getBoundingClientRect();
        const distance = Math.hypot(
          event.clientX - (rect.left + rect.width / 2),
          event.clientY - (rect.top + rect.height / 2),
        );
        return !nearest || distance < nearest.distance
          ? { element: candidate, distance }
          : nearest;
      }, null).element;
    const source = findByData(codeTree, 'methodId', arrow.dataset.sourceMethodId);
    const target = findByData(codeTree, 'methodId', arrow.dataset.targetMethodId);
    if (!source || !target) return;
    navigationStack.push({
      returnMethodId: target.dataset.methodId,
      openedTargetMethodId: null,
      openedTargetWasOpen: null,
    });
    focusMethod(source);
  });
}

function handleJumpBack(event) {
  if (event.key !== 'Escape' || navigationStack.length === 0) return;
  event.preventDefault();
  const jump = navigationStack.pop();
  const returnMethod = findByData(codeTree, 'methodId', jump.returnMethodId);
  if (!returnMethod) return;
  if (jump.openedTargetMethodId) {
    const openedTarget = findByData(codeTree, 'methodId', jump.openedTargetMethodId);
    returnMethod.open = true;
    if (openedTarget && !jump.openedTargetWasOpen) openedTarget.open = false;
    requestRedraw();
  }
  focusMethod(returnMethod);
}

function focusMethod(method) {
  requestAnimationFrame(() => {
    centerMethod(method);
    method.querySelector('summary').focus({ preventScroll: true });
  });
}

function centerMethod(target) {
  if (!panzoomInstance) {
    target.scrollIntoView({ block: 'center', inline: 'center' });
    return;
  }
  const targetRect = target.getBoundingClientRect();
  const viewportRect = app.getBoundingClientRect();
  const scale = panzoomInstance.getScale();
  const pan = panzoomInstance.getPan();
  const deltaX = viewportRect.left + viewportRect.width / 2
    - (targetRect.left + targetRect.width / 2);
  const deltaY = viewportRect.top + viewportRect.height / 2
    - (targetRect.top + targetRect.height / 2);
  panzoomInstance.pan(
    pan.x + deltaX / scale,
    pan.y + deltaY / scale,
    { animate: true },
  );
}

function requestRedraw() {
  if (redrawFrame !== null) return;
  redrawFrame = requestAnimationFrame(() => {
    redrawFrame = null;
    const expandedMethodIds = new Set(
      [...codeTree.querySelectorAll('[data-method-id][open]')]
        .map((details) => details.dataset.methodId),
    );
    if (expandedMethodIds.size === 0) {
      clearCallLines(callSvg, codeTree);
      lineFocus = null;
      updateLineFocusControls([]);
      runtimeErrors.lines = null;
      renderErrors();
      return;
    }

    const calls = getVisibleCalls(expandedMethodIds);
    updateLineFocusControls(calls);
    try {
      drawCallLines(callSvg, codeTree, calls);
      applyCallLineFocus(callSvg, lineFocus);
      runtimeErrors.lines = null;
    } catch (error) {
      clearCallLines(callSvg, codeTree);
      runtimeErrors.lines = error instanceof Error ? error.message : String(error);
    }
    renderErrors();
  });
}

function getVisibleCalls(expandedMethodIds = null) {
  const visibleMethodIds = expandedMethodIds || new Set(
    [...codeTree.querySelectorAll('[data-method-id][open]')]
      .map((details) => details.dataset.methodId),
  );
  return mapData.calls
    .filter((call) => visibleMethodIds.has(call.sourceMethodId));
}

function updateLineFocusControls(calls) {
  if (lineFocus) {
    const focusedMethod = findByData(codeTree, 'methodId', lineFocus.methodId);
    const hasFocusedLine = focusedMethod?.open && calls.some((call) => (
      lineFocus.direction === 'incoming'
        ? call.targetMethodId === lineFocus.methodId
        : call.sourceMethodId === lineFocus.methodId
    ));
    if (!hasFocusedLine) lineFocus = null;
  }

  codeTree.querySelectorAll('[data-focus-method-id]').forEach((button) => {
    const methodId = button.dataset.focusMethodId;
    const direction = button.dataset.focusDirection;
    const available = calls.some((call) => (
      direction === 'incoming'
        ? call.targetMethodId === methodId
        : call.sourceMethodId === methodId
    ));
    button.disabled = !available;
    button.setAttribute(
      'aria-pressed',
      String(lineFocus?.methodId === methodId && lineFocus.direction === direction),
    );
  });
}

function initializePanzoom() {
  const controls = ['zoom-in', 'zoom-out', 'reset-view']
    .map((id) => document.querySelector(`#${id}`));
  try {
    panzoomInstance = Panzoom(canvas, {
      maxScale: MAX_SCALE,
      minScale: MIN_SCALE,
      excludeClass: 'panzoom-exclude',
      origin: '0 0',
    });
    controls[0].addEventListener('click', () => zoomAtViewportCenter(ZOOM_STEP));
    controls[1].addEventListener('click', () => zoomAtViewportCenter(1 / ZOOM_STEP));
    controls[2].addEventListener('click', () => {
      app.scrollTo({ left: 0, top: 0 });
      panzoomInstance.reset({ animate: true });
    });
    app.addEventListener('wheel', handleCanvasWheel, { passive: false });
  } catch (error) {
    runtimeErrors.panzoom = `缩放拖动初始化失败：${error instanceof Error ? error.message : String(error)}`;
    controls.forEach((button) => { button.disabled = true; });
    renderErrors();
  }
}

function handleCanvasWheel(event) {
  if (!panzoomInstance) return;
  event.preventDefault();
  const deltaY = normalizeWheelDelta(event);
  if (event.altKey) {
    zoomAt(event.clientX, event.clientY, Math.exp(-deltaY * 0.0015));
    return;
  }

  const pan = panzoomInstance.getPan();
  const scale = panzoomInstance.getScale();
  panzoomInstance.pan(pan.x, pan.y - deltaY / scale, { animate: false });
}

function zoomAtViewportCenter(factor) {
  const viewportRect = app.getBoundingClientRect();
  zoomAt(
    viewportRect.left + viewportRect.width / 2,
    viewportRect.top + viewportRect.height / 2,
    factor,
  );
}

function zoomAt(clientX, clientY, factor) {
  const currentScale = panzoomInstance.getScale();
  const nextScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, currentScale * factor));
  if (nextScale === currentScale) return;

  const pan = panzoomInstance.getPan();
  const canvasRect = canvas.getBoundingClientRect();
  const baseLeft = canvasRect.left - currentScale * pan.x;
  const baseTop = canvasRect.top - currentScale * pan.y;
  const nextX = pan.x + (clientX - baseLeft) * (1 / nextScale - 1 / currentScale);
  const nextY = pan.y + (clientY - baseTop) * (1 / nextScale - 1 / currentScale);

  panzoomInstance.zoom(nextScale, { animate: false });
  panzoomInstance.pan(nextX, nextY, { animate: false });
}

function normalizeWheelDelta(event) {
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) return event.deltaY * 16;
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) return event.deltaY * app.clientHeight;
  return event.deltaY;
}

function createCallSvg() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'call-layer');
  svg.setAttribute('aria-hidden', 'true');
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.append(createArrowMarker('arrow-normal', 'arrow-marker--normal'));
  defs.append(createArrowMarker('arrow-error', 'arrow-marker--error'));
  defs.append(createArrowMarker('arrow-focus', 'arrow-marker--focus'));
  svg.append(defs);
  return svg;
}

function createArrowMarker(id, className) {
  const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
  marker.setAttribute('id', id);
  marker.setAttribute('viewBox', '0 0 10 10');
  marker.setAttribute('refX', '9');
  marker.setAttribute('refY', '5');
  marker.setAttribute('markerWidth', '5');
  marker.setAttribute('markerHeight', '5');
  marker.setAttribute('orient', 'auto-start-reverse');
  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
  arrow.setAttribute('class', className);
  marker.append(arrow);
  return marker;
}

function renderErrors() {
  const messages = Object.values(runtimeErrors).filter(Boolean);
  errorPanel.hidden = messages.length === 0;
  errorPanel.replaceChildren(...messages.map((message) => createElement('p', '', message)));
}

function getMethodName(signature) {
  return `${signature.slice(0, signature.indexOf('('))}()`;
}

function findByData(root, key, value) {
  return [...root.querySelectorAll(`[data-${toKebabCase(key)}]`)]
    .find((element) => element.dataset[key] === value);
}

function toKebabCase(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function createElement(tag, className = '', text = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== null) element.textContent = text;
  return element;
}
