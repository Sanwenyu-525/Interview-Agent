import assert from "node:assert/strict";
import test from "node:test";

import { insertMarkdown } from "../src/composer.js";

test("insertMarkdown wraps the selected text and keeps the cursor after the wrapper", () => {
  const result = insertMarkdown("回答采用缓存", 4, 6, "**");

  assert.deepEqual(result, { value: "回答采用**缓存**", selectionStart: 10, selectionEnd: 10 });
});

test("insertMarkdown inserts a useful placeholder when there is no selection", () => {
  const result = insertMarkdown("", 0, 0, "`", "代码");

  assert.deepEqual(result, { value: "`代码`", selectionStart: 1, selectionEnd: 3 });
});
