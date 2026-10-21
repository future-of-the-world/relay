import { expect, test } from 'bun:test';
import { addItem, total } from './shelf';

test('New item: the shelf holds it', () => {
  expect(addItem([], 'bolt', 3)).toEqual([{ name: 'bolt', qty: 3 }]);
});

test('Existing item: quantity increases', () => {
  expect(addItem([{ name: 'bolt', qty: 3 }], 'bolt', 2)).toEqual([{ name: 'bolt', qty: 5 }]);
});

test('Quantity not positive: rejected', () => {
  expect(() => addItem([], 'bolt', 0)).toThrow();
});

test('Sum: 3 + 4 is 7', () => {
  expect(total([{ name: 'bolt', qty: 3 }, { name: 'nut', qty: 4 }])).toBe(7);
});
