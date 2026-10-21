// The page measure of the look review (product:ui-reviewer). Call it at every state shot:
// `await page.evaluate(measure)`, or `page.evaluate(measure, '.cell')` to keep the boxes of
// whatever the selector matches. Compare two states of one screen with moved(first, second).
// Runs in the page, so it uses nothing from outside itself.
export function measure(also) {
  const root = document.documentElement;
  // An element with no box of its own (display: contents or inline) clips nothing, even with
  // overflow hidden: its box is 0 x 0.
  const boxless = (style) => style.display === 'contents' || style.display === 'inline';
  const clips = (el) => {
    const style = getComputedStyle(el);
    if (boxless(style)) return false;
    return style.overflowX !== 'visible' || style.overflowY !== 'visible';
  };
  // The part of an element a person can see: its box cut by every ancestor that clips or scrolls.
  const seen = (el) => {
    let { left, top, right, bottom } = el.getBoundingClientRect();
    for (let up = el.parentElement; up !== null; up = up.parentElement) {
      if (!clips(up)) continue;
      const box = up.getBoundingClientRect();
      left = Math.max(left, box.left);
      top = Math.max(top, box.top);
      right = Math.min(right, box.right);
      bottom = Math.min(bottom, box.bottom);
    }
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  };
  const shown = [...document.querySelectorAll('body *')].filter((el) => {
    const box = seen(el);
    return box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  });
  const words = (el) => (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 50);
  const name = (el) =>
    el.dataset.testid ?? (el.getAttribute('class') || el.tagName.toLowerCase()).split(' ')[0];
  const hides = (value) => value === 'hidden' || value === 'clip';
  const scrollable = (value) => value === 'auto' || value === 'scroll';
  const over = (el, test) => {
    const style = getComputedStyle(el);
    return (
      (test(style.overflowX) && el.scrollWidth > el.clientWidth) ||
      (test(style.overflowY) && el.scrollHeight > el.clientHeight)
    );
  };
  // Partly: something under the box starts inside it and ends outside it: a child element, or a
  // run of text at any depth (words that sit an element down and overflow from there). A text
  // in a nearer box that scrolls is not read: the person scrolls to it. What lies wholly outside
  // is left out on purpose (a line below a one-line box, as a locked look may want) and is not a
  // cut; read the shot for it. The edges: half a pixel, and a pixel more above a line, where Chromium stands a text with no ink cut.
  const partly = (el) => {
    const box = el.getBoundingClientRect();
    const crosses = (r) => {
      if (r.width <= 0) return false;
      const away =
        r.right <= box.left + 0.5 || r.left >= box.right - 0.5 || r.bottom <= box.top + 0.5 || r.top >= box.bottom - 1.5;
      const out =
        r.right > box.right + 0.5 || r.left < box.left - 0.5 || r.bottom > box.bottom + 0.5 || r.top < box.top - 1.5;
      return out && !away;
    };
    // A child by its boxes, one a line where it is inline and wraps: a line of it may be left out.
    if ([...el.children].some((child) => [...child.getClientRects()].some(crosses))) return true;
    const scrolled = (node) => {
      for (let up = node.parentElement; up !== null && up !== el; up = up.parentElement) {
        const style = getComputedStyle(up);
        if (!boxless(style) && (scrollable(style.overflowX) || scrollable(style.overflowY))) return true;
      }
      return false;
    };
    const range = document.createRange();
    const texts = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
      if (node.textContent.trim() === '' || scrolled(node)) continue;
      range.selectNodeContents(node);
      if ([...range.getClientRects()].some(crosses)) return true;
    }
    return false;
  };
  // Cut: a box that hides what does not fit and holds more than fits (an ellipsis, a clipped line).
  const cut = shown
    .filter((el) => over(el, hides) && partly(el))
    .map(
      (el) =>
        `${name(el)} "${words(el)}" needs ${el.scrollWidth}x${el.scrollHeight}, has ${el.clientWidth}x${el.clientHeight}`,
    );
  // Scrolls: a box the person has to scroll.
  const scrolls = shown.filter((el) => over(el, scrollable)).map((el) => name(el));
  // Off: anything that starts left of the window or ends right of it.
  const off = shown
    .filter((el) => {
      const box = el.getBoundingClientRect();
      return box.left < 0 || box.right > root.clientWidth;
    })
    .map((el) => `${name(el)} "${words(el)}"`);
  // Overlap: two elements with text of their own, neither inside the other, whose seen parts cross.
  const leaves = shown.filter((el) =>
    [...el.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim() !== ''),
  );
  const overlap = [];
  for (const [i, a] of leaves.entries()) {
    for (const b of leaves.slice(i + 1)) {
      if (a.contains(b) || b.contains(a)) continue;
      const p = seen(a);
      const q = seen(b);
      const w = Math.min(p.right, q.right) - Math.max(p.left, q.left);
      const h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
      if (w > 1 && h > 1) {
        overlap.push(
          `${name(a)} "${words(a)}" and ${name(b)} "${words(b)}" cross by ${Math.round(w)}x${Math.round(h)}`,
        );
      }
    }
  }
  // Boxes by name (left, top, width, height), to compare two states of one screen with moved().
  const boxes = {};
  const keep = (key, el) => {
    const { left, top, width, height } = el.getBoundingClientRect();
    boxes[key] ??= [left, top, width, height].map((n) => Math.round(n * 10) / 10);
  };
  for (const el of shown) {
    const role = el.getAttribute('role') ?? (el.tagName === 'BUTTON' ? 'button' : null);
    if (el.dataset.testid !== undefined) keep(el.dataset.testid, el);
    else if (role !== null) keep(`${role} ${el.getAttribute('aria-label') ?? words(el)}`, el);
  }
  if (also) document.querySelectorAll(also).forEach((el, i) => keep(`${also} ${i}`, el));
  return { cut, scrolls, off, overlap, sideways: root.scrollWidth > root.clientWidth, boxes };
}

// The boxes that are in both states and moved or changed size by more than half a pixel.
export function moved(before, after) {
  return Object.keys(before.boxes)
    .filter((key) => after.boxes[key]?.some((n, i) => Math.abs(n - before.boxes[key][i]) > 0.5))
    .map((key) => `${key}: ${before.boxes[key].join(' ')} -> ${after.boxes[key].join(' ')}`);
}
