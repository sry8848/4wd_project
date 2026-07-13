import test from 'node:test';
import assert from 'node:assert/strict';

import {
  assignIntervalLanes,
  assignTargetPorts,
} from '../src/route-layout.js';

test('相交或安全余量接触的区间不能复用通道', () => {
  const lanes = assignIntervalLanes([
    { id: 'first', startY: 10, endY: 30, sortHint: 0 },
    { id: 'touching', startY: 30, endY: 50, sortHint: 1 },
    { id: 'nearby', startY: 61, endY: 70, sortHint: 2 },
  ], 6);

  assert.notEqual(lanes.get('first'), lanes.get('touching'));
  assert.notEqual(lanes.get('touching'), lanes.get('nearby'));
});

test('分离区间复用编号最小的通道', () => {
  const lanes = assignIntervalLanes([
    { id: 'first', startY: 10, endY: 20, sortHint: 0 },
    { id: 'second', startY: 40, endY: 50, sortHint: 1 },
  ], 6);

  assert.equal(lanes.get('first'), 0);
  assert.equal(lanes.get('second'), 0);
});

test('通道结果与输入顺序无关且不修改输入', () => {
  const first = Object.freeze({ id: 'first', startY: 10, endY: 40, sortHint: 2 });
  const second = Object.freeze({ id: 'second', startY: 20, endY: 30, sortHint: 1 });
  const third = Object.freeze({ id: 'third', startY: 60, endY: 70, sortHint: 0 });
  const routes = Object.freeze([first, second, third]);
  const reversed = Object.freeze([third, second, first]);

  const forwardResult = Object.fromEntries(assignIntervalLanes(routes, 6));
  const reversedResult = Object.fromEntries(assignIntervalLanes(reversed, 6));

  assert.deepEqual(forwardResult, reversedResult);
  assert.deepEqual(routes, [first, second, third]);
});

test('区间分配拒绝无效坐标、重复 ID 和负安全余量', () => {
  assert.throws(
    () => assignIntervalLanes([{ id: 'bad', startY: Number.NaN, endY: 10, sortHint: 0 }], 0),
    TypeError,
  );
  assert.throws(
    () => assignIntervalLanes([
      { id: 'same', startY: 0, endY: 1, sortHint: 0 },
      { id: 'same', startY: 2, endY: 3, sortHint: 1 },
    ], 0),
    RangeError,
  );
  assert.throws(() => assignIntervalLanes([], -1), RangeError);
});

test('多目标端口按来源高度排序并保持最小间距', () => {
  const ports = assignTargetPorts([
    { id: 'low', sourceY: 30, sortHint: 1 },
    { id: 'high', sourceY: 10, sortHint: 0 },
    { id: 'middle', sourceY: 20, sortHint: 2 },
  ], 100, 120, 6);

  assert.ok(ports.get('high') < ports.get('middle'));
  assert.ok(ports.get('middle') < ports.get('low'));
  assert.ok(ports.get('middle') - ports.get('high') >= 6);
  assert.ok(ports.get('low') - ports.get('middle') >= 6);
  assert.ok(ports.get('high') >= 100);
  assert.ok(ports.get('low') <= 120);
});

test('目标端口结果与输入顺序无关且不修改输入', () => {
  const high = Object.freeze({ id: 'high', sourceY: 10, sortHint: 1 });
  const low = Object.freeze({ id: 'low', sourceY: 30, sortHint: 0 });
  const routes = Object.freeze([high, low]);
  const reversed = Object.freeze([low, high]);

  const forwardResult = Object.fromEntries(assignTargetPorts(routes, 100, 120, 6));
  const reversedResult = Object.fromEntries(assignTargetPorts(reversed, 100, 120, 6));

  assert.deepEqual(forwardResult, reversedResult);
  assert.deepEqual(routes, [high, low]);
});

test('单目标端口使用边界中心并拒绝无效空间', () => {
  const center = assignTargetPorts([
    { id: 'only', sourceY: 1, sortHint: 0 },
  ], 10, 20, 6);

  assert.equal(center.get('only'), 15);
  assert.throws(
    () => assignTargetPorts([
      { id: 'first', sourceY: 1, sortHint: 0 },
      { id: 'second', sourceY: 2, sortHint: 1 },
    ], 10, 14, 6),
    RangeError,
  );
  assert.throws(() => assignTargetPorts([], 20, 10, 6), RangeError);
  assert.throws(() => assignTargetPorts([], 10, 20, -1), RangeError);
});

