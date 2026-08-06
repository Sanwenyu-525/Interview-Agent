const DEFAULT_PROJECT_NAME = "未命名项目";

export const MAX_UPLOAD_FILES = 10000;
export const MAX_FILE_TEXT_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_TEXT_BYTES = 100 * 1024 * 1024;

const BINARY_MIME_TYPES = new Set([
  "application/java-archive",
  "application/octet-stream",
  "application/wasm",
  "application/x-7z-compressed",
  "application/x-rar-compressed",
  "application/x-zip-compressed",
  "application/zip",
]);

const BINARY_EXTENSIONS = new Set([
  ".7z",
  ".a",
  ".avi",
  ".bin",
  ".bmp",
  ".bz2",
  ".class",
  ".dll",
  ".dylib",
  ".ear",
  ".exe",
  ".gif",
  ".gz",
  ".ico",
  ".jar",
  ".jpeg",
  ".jpg",
  ".mkv",
  ".mov",
  ".mp3",
  ".mp4",
  ".o",
  ".pdf",
  ".png",
  ".rar",
  ".so",
  ".tar",
  ".tgz",
  ".ttf",
  ".wasm",
  ".wav",
  ".webp",
  ".woff",
  ".woff2",
  ".xz",
  ".zip",
]);

function rawFilePath(file) {
  return String(file?.webkitRelativePath || file?.name || "").replaceAll("\\", "/");
}

function fileName(file) {
  return file?.name || rawFilePath(file) || "未知文件";
}

function knownFileSize(file) {
  return typeof file?.size === "number"
    && Number.isFinite(file.size)
    && file.size >= 0
    ? file.size
    : null;
}

function isBinaryFile(file) {
  const mimeType = String(file?.type || "").toLowerCase().split(";", 1)[0].trim();
  if (
    mimeType.startsWith("image/")
    || mimeType.startsWith("audio/")
    || mimeType.startsWith("video/")
    || BINARY_MIME_TYPES.has(mimeType)
  ) {
    return true;
  }

  const path = rawFilePath(file).toLowerCase();
  const extension = path.slice(path.lastIndexOf("."));
  return BINARY_EXTENSIONS.has(extension);
}

function assertKnownFileSizeLimits(files) {
  let knownTotalBytes = 0;
  for (const file of files) {
    if (isBinaryFile(file)) continue;
    const size = knownFileSize(file);
    if (size === null) continue;
    if (size > MAX_FILE_TEXT_BYTES) {
      throw new Error(`文件超过单文件大小上限：${fileName(file)}`);
    }
    knownTotalBytes += size;
    if (knownTotalBytes > MAX_TOTAL_TEXT_BYTES) {
      throw new Error(`项目文件总大小超过上限：${fileName(file)}`);
    }
  }
}

function filePathParts(file) {
  const rawPath = rawFilePath(file);
  if (!rawPath.trim()) throw new Error(`路径为空：${fileName(file)}`);
  if (rawPath.startsWith("/") || /^[A-Za-z]:\//.test(rawPath)) {
    throw new Error(`路径必须是相对路径：${fileName(file)}`);
  }

  const parts = rawPath.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`路径包含非法片段：${fileName(file)}`);
  }
  return parts;
}

export function relativeUploadPath(file) {
  const parts = filePathParts(file);
  const relativePath = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
  if (!relativePath || relativePath.startsWith("/")) {
    throw new Error(`路径不是安全的相对路径：${fileName(file)}`);
  }
  return relativePath;
}

export function selectedFolderName(files) {
  const firstFile = Array.from(files || [])[0];
  const parts = rawFilePath(firstFile).split("/").filter(Boolean);
  return parts.length > 1 ? parts[0] : "";
}

export function generateProjectId() {
  return Date.now();
}

export function normalizeProjectId(value) {
  let candidate = value;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!/^\d+$/.test(trimmed)) return null;
    candidate = Number(trimmed);
  }
  if (!Number.isSafeInteger(candidate) || candidate <= 0) return null;
  return candidate;
}

function textByteLength(text) {
  return new TextEncoder().encode(text).byteLength;
}

async function readFileText(file) {
  if (typeof file?.text === "function") return String(await file.text());

  if (typeof FileReader === "undefined") {
    throw new Error("当前环境不支持读取文件文本");
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("文件读取失败"));
    reader.readAsText(file);
  });
}

export async function createFolderUploadDescriptor(files, { projectId, projectName } = {}) {
  const selectedFiles = Array.from(files || []);
  if (selectedFiles.length === 0) {
    throw new Error("请先选择包含文本文件的项目目录");
  }
  if (selectedFiles.length > MAX_UPLOAD_FILES) {
    throw new Error(`文件数超过上限：最多 ${MAX_UPLOAD_FILES} 个文件`);
  }

  const normalizedProjectId = normalizeProjectId(projectId);
  if (normalizedProjectId === null) {
    throw new Error("项目 ID 必须是正整数");
  }
  assertKnownFileSizeLimits(selectedFiles);

  const descriptorFiles = [];
  const skippedFiles = [];
  const seenPaths = new Map();
  let totalTextBytes = 0;
  for (const file of selectedFiles) {
    const name = fileName(file);
    let path;
    try {
      path = relativeUploadPath(file);
    } catch (cause) {
      throw new Error(`文件路径无效：${name}：${cause.message}`, { cause });
    }

    for (const existingPath of seenPaths.keys()) {
      if (
        path === existingPath
        || path.startsWith(`${existingPath}/`)
        || existingPath.startsWith(`${path}/`)
      ) {
        throw new Error(`路径冲突：${name} 与 ${seenPaths.get(existingPath)}`);
      }
    }

    seenPaths.set(path, name);
    if (isBinaryFile(file)) {
      skippedFiles.push(path);
      continue;
    }

    let content;
    try {
      content = await readFileText(file);
    } catch (cause) {
      throw new Error(`读取文件失败：${name}`, { cause });
    }

    const fileTextBytes = textByteLength(content);
    if (fileTextBytes > MAX_FILE_TEXT_BYTES) {
      throw new Error(`文件超过单文件文本大小上限：${name}`);
    }
    totalTextBytes += fileTextBytes;
    if (totalTextBytes > MAX_TOTAL_TEXT_BYTES) {
      throw new Error(`项目文本总大小超过上限：${name}`);
    }

    descriptorFiles.push({ path, content });
  }

  if (descriptorFiles.length === 0) {
    throw new Error("项目目录中没有可读取的文本文件，二进制文件已跳过");
  }

  const source = { type: "folder", files: descriptorFiles };
  if (skippedFiles.length > 0) source.skipped_files = skippedFiles;

  return {
    project_id: normalizedProjectId,
    project_name: String(projectName || DEFAULT_PROJECT_NAME).trim() || DEFAULT_PROJECT_NAME,
    source,
  };
}
