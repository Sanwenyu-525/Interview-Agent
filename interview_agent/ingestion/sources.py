"""把不同输入形式准备为 Analyzer 可读取的项目目录。"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterable, Mapping, Protocol, runtime_checkable
import os
import shutil
import stat
import tempfile
import zipfile

from .security import is_link_like, path_exists, prepare_target, remove_tree, safe_relative_destination


ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024
ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024
ZIP_DESCRIPTOR_DEFAULT_MAX_FILES = 10_000


@runtime_checkable
class ProjectSource(Protocol):
    """项目输入源的统一边界。"""

    source_type: str

    def prepare(self, workspace_path: Path) -> Path:
        """将输入准备到 workspace_path，并返回准备好的项目根目录。"""


def _stage_directory(target: Path) -> Path:
    return Path(
        tempfile.mkdtemp(prefix=f".{target.name}-staging-", dir=str(target.parent))
    ).resolve()


def _replace_directory(staging: Path, target: Path) -> None:
    backup = None
    if path_exists(target):
        try:
            backup = Path(
                tempfile.mkdtemp(prefix=f".{target.name}-backup-", dir=str(target.parent))
            ).resolve()
            remove_tree(backup)
            target.replace(backup)
        except Exception as move_error:
            if backup is not None and path_exists(backup):
                try:
                    remove_tree(backup)
                except Exception as cleanup_error:
                    raise RuntimeError(
                        f"failed to prepare backup cleanup for {target}"
                    ) from cleanup_error
            raise RuntimeError(f"failed to move old target {target}") from move_error
    try:
        staging.replace(target)
    except Exception as swap_error:
        if backup is None:
            raise RuntimeError(f"atomic replacement failed for {target}") from swap_error
        try:
            backup.replace(target)
        except Exception as restore_error:
            try:
                if path_exists(backup):
                    remove_tree(backup)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"replacement failed; old target restore and backup cleanup failed for {target}"
                ) from cleanup_error
            raise RuntimeError(
                f"replacement failed and old target could not be restored: {target}"
            ) from restore_error
        raise RuntimeError(f"atomic replacement failed; old target restored: {target}") from swap_error
    if backup is not None:
        try:
            remove_tree(backup)
        except Exception as cleanup_error:
            raise RuntimeError(f"replacement succeeded but backup cleanup failed: {backup}") from cleanup_error


def _atomic_prepare(target: Path, writer) -> Path:
    staging = _stage_directory(target)
    try:
        writer(staging)
        _replace_directory(staging, target)
    except Exception:
        try:
            if path_exists(staging):
                remove_tree(staging)
        except Exception as cleanup_error:
            raise RuntimeError(f"staging cleanup failed: {staging}") from cleanup_error
        raise
    return target


def _zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _is_zip_directory(info: zipfile.ZipInfo) -> bool:
    return info.is_dir() or info.filename.endswith(("/", "\\"))


def _check_member_conflict(
    key: tuple[str, ...],
    is_directory: bool,
    seen: dict[tuple[str, ...], bool],
    *,
    source_name: str,
) -> None:
    conflict_key = tuple(part.casefold() for part in key)
    if not key:
        raise ValueError(f"{source_name} member path must name a file or directory")
    if conflict_key in seen:
        raise ValueError(f"{source_name} member path conflict or duplicate: {'/'.join(key)}")
    for index in range(1, len(key)):
        ancestor = conflict_key[:index]
        if ancestor in seen and not seen[ancestor]:
            raise ValueError(f"{source_name} member path conflict or duplicate: {'/'.join(key)}")
    if not is_directory and any(existing[: len(conflict_key)] == conflict_key for existing in seen):
        raise ValueError(f"{source_name} member path conflict or duplicate: {'/'.join(key)}")
    seen[conflict_key] = is_directory


@dataclass(frozen=True)
class ZipSource:
    """从 ZIP 归档安全准备项目文件。"""

    archive_path: Path
    max_total_size: int | None = None
    max_file_size: int | None = None
    max_files: int | None = None
    source_type: ClassVar[str] = "zip"

    def __post_init__(self) -> None:
        object.__setattr__(self, "archive_path", Path(self.archive_path))
        for name in ("max_total_size", "max_file_size", "max_files"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def prepare(self, workspace_path: Path) -> Path:
        archive = self.archive_path.resolve()
        if not archive.is_file():
            raise ValueError(f"ZIP archive does not exist: {archive}")
        target = prepare_target(workspace_path)

        with zipfile.ZipFile(archive) as zipped:
            entries: list[tuple[zipfile.ZipInfo, tuple[str, ...], bool]] = []
            seen: dict[tuple[str, ...], bool] = {}
            total_size = 0
            file_count = 0
            for info in zipped.infolist():
                destination = safe_relative_destination(target, info.filename, source_name="ZIP")
                relative = tuple(destination.relative_to(target).parts)
                is_directory = _is_zip_directory(info)
                if _zip_symlink(info):
                    raise ValueError(f"symbolic link entries are not allowed: {info.filename!r}")
                _check_member_conflict(
                    relative, is_directory, seen, source_name="ZIP"
                )
                if is_directory:
                    entries.append((info, relative, True))
                    continue

                file_count += 1
                if self.max_files is not None and file_count > self.max_files:
                    raise ValueError(
                        f"ZIP file count exceeds limit: {file_count} > {self.max_files}"
                    )
                if self.max_file_size is not None and info.file_size > self.max_file_size:
                    raise ValueError(
                        f"ZIP single file size exceeds limit: {info.file_size} > {self.max_file_size}"
                    )
                total_size += info.file_size
                if self.max_total_size is not None and total_size > self.max_total_size:
                    raise ValueError(
                        f"ZIP total size exceeds limit: {total_size} > {self.max_total_size}"
                    )
                entries.append((info, relative, False))

            def write(staging: Path) -> None:
                for info, relative, is_directory in entries:
                    destination = staging.joinpath(*relative)
                    if is_directory:
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(info, "r") as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)

            return _atomic_prepare(target, write)


@dataclass(frozen=True)
class FolderFile:
    """FolderSource 的一个相对路径文件。"""

    path: str
    content: bytes


@dataclass(frozen=True)
class FolderSource:
    """从带相对路径的内存文件集合准备项目目录。"""

    files: Iterable[FolderFile | tuple[str, bytes]] | Mapping[str, bytes]
    source_type: ClassVar[str] = "folder"

    def __post_init__(self) -> None:
        raw_entries = self.files.items() if isinstance(self.files, Mapping) else self.files
        object.__setattr__(self, "files", tuple(raw_entries))

    def _entries(self) -> list[tuple[str, bytes]]:
        entries: list[tuple[str, bytes]] = []
        for item in self.files:
            if isinstance(item, FolderFile):
                raw_path, content = item.path, item.content
            else:
                try:
                    raw_path, content = item
                except (TypeError, ValueError) as exc:
                    raise ValueError("FolderSource files must contain path/content pairs") from exc
            if not isinstance(content, (bytes, bytearray, memoryview)):
                raise TypeError("FolderSource file content must be bytes-like")
            entries.append((raw_path, bytes(content)))
        return entries

    def prepare(self, workspace_path: Path) -> Path:
        target = prepare_target(workspace_path)
        prepared: list[tuple[tuple[str, ...], bytes]] = []
        seen: dict[tuple[str, ...], bool] = {}
        for raw_path, content in self._entries():
            destination = safe_relative_destination(target, raw_path, source_name="Folder")
            if destination == target:
                raise ValueError("Folder path must name a file")
            relative = tuple(destination.relative_to(target).parts)
            _check_member_conflict(relative, False, seen, source_name="Folder")
            prepared.append((relative, content))

        def write(staging: Path) -> None:
            for relative, content in prepared:
                destination = staging.joinpath(*relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)

        return _atomic_prepare(target, write)


@dataclass(frozen=True)
class DirectorySource:
    """从本地目录路径安全准备项目文件。

    桌面端原生目录对话框只返回路径，由本类在服务端复制到隔离工作区；
    限制与 zip / folder 输入一致，拒绝符号链接与 junction。
    """

    source_path: Path
    max_total_size: int | None = None
    max_file_size: int | None = None
    max_files: int | None = None
    source_type: ClassVar[str] = "directory"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path))
        for name in ("max_total_size", "max_file_size", "max_files"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def prepare(self, workspace_path: Path) -> Path:
        source = self.source_path.resolve()
        if not source.is_dir():
            raise ValueError(f"Source directory does not exist: {source}")
        target = prepare_target(workspace_path)

        entries: list[tuple[tuple[str, ...], Path]] = []
        file_count = 0
        total_size = 0
        for root, dirs, files in os.walk(source, topdown=True, followlinks=False):
            root_path = Path(root)
            for name in dirs:
                entry = root_path / name
                if is_link_like(entry):
                    raise ValueError(f"symbolic link entries are not allowed: {entry}")
            for name in files:
                entry = root_path / name
                if is_link_like(entry):
                    raise ValueError(f"symbolic link entries are not allowed: {entry}")
                file_count += 1
                if self.max_files is not None and file_count > self.max_files:
                    raise ValueError(
                        f"directory file count exceeds limit: {file_count} > {self.max_files}"
                    )
                size = entry.stat().st_size
                if self.max_file_size is not None and size > self.max_file_size:
                    raise ValueError(
                        f"directory single file size exceeds limit: {size} > {self.max_file_size}"
                    )
                total_size += size
                if self.max_total_size is not None and total_size > self.max_total_size:
                    raise ValueError(
                        f"directory total size exceeds limit: {total_size} > {self.max_total_size}"
                    )
                entries.append((tuple(entry.relative_to(source).parts), entry))

        def write(staging: Path) -> None:
            for relative, entry in entries:
                destination = staging.joinpath(*relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with entry.open("rb") as source_file, destination.open("wb") as output:
                    shutil.copyfileobj(source_file, output)

        return _atomic_prepare(target, write)


__all__ = [
    "DirectorySource",
    "FolderFile",
    "FolderSource",
    "ProjectSource",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_FILES",
    "ZIP_DESCRIPTOR_DEFAULT_MAX_TOTAL_SIZE",
    "ZipSource",
]
