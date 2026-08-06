import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_FILE_TEXT_BYTES,
  MAX_TOTAL_TEXT_BYTES,
  MAX_UPLOAD_FILES,
  createFolderUploadDescriptor,
  generateProjectId,
  normalizeProjectId,
  relativeUploadPath,
} from "../src/upload.js";

test("relativeUploadPath removes the selected folder root", () => {
  assert.equal(
    relativeUploadPath({ name: "Main.java", webkitRelativePath: "order-service/src/Main.java" }),
    "src/Main.java",
  );
  assert.equal(relativeUploadPath({ name: "README.md" }), "README.md");
});

test("relativeUploadPath rejects unsafe paths", () => {
  assert.throws(
    () => relativeUploadPath({ name: "absolute.java", webkitRelativePath: "/demo/absolute.java" }),
    /absolute|relative|路径/,
  );
  assert.throws(
    () => relativeUploadPath({ name: "escape.java", webkitRelativePath: "demo/../escape.java" }),
    /escape\.java|\.\.|路径/,
  );
});

test("createFolderUploadDescriptor reads text files into a folder JSON descriptor", async () => {
  const files = [
    {
      name: "pom.xml",
      webkitRelativePath: "order-service/pom.xml",
      text: async () => "<project />",
    },
    {
      name: "OrderService.java",
      webkitRelativePath: "order-service/src/OrderService.java",
      text: async () => "class OrderService {}",
    },
  ];

  const descriptor = await createFolderUploadDescriptor(files, {
    projectId: 9001,
    projectName: "order-service",
  });

  assert.deepEqual(descriptor, {
    project_id: 9001,
    project_name: "order-service",
    source: {
      type: "folder",
      files: [
        { path: "pom.xml", content: "<project />" },
        { path: "src/OrderService.java", content: "class OrderService {}" },
      ],
    },
  });
});

test("createFolderUploadDescriptor reports the file name when reading fails", async () => {
  await assert.rejects(
    () => createFolderUploadDescriptor([
      {
        name: "broken.java",
        webkitRelativePath: "demo/broken.java",
        text: async () => { throw new Error("decode failed"); },
      },
    ], { projectId: 1, projectName: "demo" }),
    /broken\.java/,
  );
});

test("createFolderUploadDescriptor rejects duplicate or conflicting paths", async () => {
  const files = [
    { name: "Main.java", webkitRelativePath: "demo/src/Main.java", text: async () => "one" },
    { name: "Main-copy.java", webkitRelativePath: "demo/src/Main.java", text: async () => "two" },
  ];

  await assert.rejects(
    () => createFolderUploadDescriptor(files, { projectId: 1, projectName: "demo" }),
    /冲突|duplicate|Main-copy\.java/,
  );
});

test("createFolderUploadDescriptor enforces file count and text size limits", async () => {
  const tooManyFiles = Array.from({ length: MAX_UPLOAD_FILES + 1 }, (_, index) => ({
    name: `file-${index}.txt`,
    webkitRelativePath: `demo/file-${index}.txt`,
    text: async () => "x",
  }));
  await assert.rejects(
    () => createFolderUploadDescriptor(tooManyFiles, { projectId: 1, projectName: "demo" }),
    /文件数|limit|上限/,
  );

  await assert.rejects(
    () => createFolderUploadDescriptor([{
      name: "large.txt",
      webkitRelativePath: "demo/large.txt",
      text: async () => "x".repeat(MAX_FILE_TEXT_BYTES + 1),
    }], { projectId: 1, projectName: "demo" }),
    /large\.txt|大小|limit|上限/,
  );

  const totalFileCount = Math.ceil(MAX_TOTAL_TEXT_BYTES / MAX_FILE_TEXT_BYTES) + 1;
  await assert.rejects(
    () => createFolderUploadDescriptor(Array.from({ length: totalFileCount }, (_, index) => ({
      name: `total-${index}.txt`,
      webkitRelativePath: `demo/total-${index}.txt`,
      text: async () => "x".repeat(MAX_FILE_TEXT_BYTES),
    })), { projectId: 1, projectName: "demo" }),
    /总|total|上限/,
  );
});

test("createFolderUploadDescriptor rejects oversized File-like objects before text()", async () => {
  let readCount = 0;
  await assert.rejects(
    () => createFolderUploadDescriptor([{
      name: "too-large.txt",
      size: MAX_FILE_TEXT_BYTES + 1,
      webkitRelativePath: "demo/too-large.txt",
      text: async () => {
        readCount += 1;
        return "should not be read";
      },
    }], { projectId: 1, projectName: "demo" }),
    /too-large\.txt|size|大小|上限/,
  );
  assert.equal(readCount, 0);

  const files = Array.from({ length: MAX_TOTAL_TEXT_BYTES / MAX_FILE_TEXT_BYTES + 1 }, (_, index) => ({
    name: `known-total-${index}.txt`,
    size: MAX_FILE_TEXT_BYTES,
    webkitRelativePath: `demo/known-total-${index}.txt`,
    text: async () => {
      readCount += 1;
      return "should not be read";
    },
  }));
  await assert.rejects(
    () => createFolderUploadDescriptor(files, { projectId: 1, projectName: "demo" }),
    /total|总|上限/,
  );
  assert.equal(readCount, 0);
});

test("createFolderUploadDescriptor skips binary files and keeps text files", async () => {
  let readCount = 0;
  const descriptor = await createFolderUploadDescriptor([
    {
      name: "screenshot.png",
      type: "image/png",
      size: MAX_FILE_TEXT_BYTES + 1,
      webkitRelativePath: "demo/screenshot.png",
      text: async () => {
        readCount += 1;
        return "should not be read";
      },
    },
    {
      name: "library.jar",
      webkitRelativePath: "demo/lib/library.jar",
      text: async () => {
        readCount += 1;
        return "should not be read";
      },
    },
    {
      name: "README.md",
      webkitRelativePath: "demo/README.md",
      text: async () => {
        readCount += 1;
        return "text content";
      },
    },
  ], { projectId: 1, projectName: "demo" });

  assert.deepEqual(descriptor.source.files, [{ path: "README.md", content: "text content" }]);
  assert.deepEqual(descriptor.source.skipped_files, ["screenshot.png", "lib/library.jar"]);
  assert.equal(readCount, 1);
});

test("createFolderUploadDescriptor rejects folders with no readable text files", async () => {
  await assert.rejects(
    () => createFolderUploadDescriptor([{
      name: "library.jar",
      webkitRelativePath: "demo/lib/library.jar",
      text: async () => "should not be read",
    }], { projectId: 1, projectName: "demo" }),
    /text|文本|可读取|二进制/,
  );
});


test("normalizeProjectId only accepts canonical positive safe integers", () => {
  assert.equal(normalizeProjectId("00042"), 42);
  assert.equal(normalizeProjectId(42), 42);
  for (const value of ["", "-1", "1.5", "1e3", "not-a-number", 0, 1.5, 9007199254740992, true]) {
    assert.equal(normalizeProjectId(value), null, `expected ${String(value)} to be rejected`);
  }
});

test("generateProjectId returns a numeric project id", () => {
  assert.equal(typeof generateProjectId(), "number");
});

test("project upload capacity supports a medium-sized repository", () => {
  assert.ok(MAX_UPLOAD_FILES >= 10000);
  assert.ok(MAX_FILE_TEXT_BYTES >= 10 * 1024 * 1024);
  assert.ok(MAX_TOTAL_TEXT_BYTES >= 100 * 1024 * 1024);
});
