"""Ingestion 使用的路径、链接和项目 ID 安全边界。"""

from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import re


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path) -> bool:
    """识别符号链接、junction 和 Windows reparse point；属性读取失败即拒绝。"""
    try:
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
    except OSError as exc:
        raise ValueError(f"cannot inspect link-like path: {path}") from exc

    try:
        if path.is_symlink():
            return True
    except OSError as exc:
        raise ValueError(f"cannot inspect link-like path: {path}") from exc

    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return False
    except OSError as exc:
        raise ValueError(f"cannot inspect link-like path: {path}") from exc
    return bool(attributes & 0x400)


is_link_like = _is_link_like


def _path_exists(path: Path) -> bool:
    """区分不存在与其他 lstat 错误，任何检查错误都拒绝继续。"""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError(f"cannot inspect path: {path}") from exc
    return True


path_exists = _path_exists


def _validate_target_path(path: Path) -> tuple[Path, Path]:
    target = Path(path)
    if not target.is_absolute():
        target = Path.cwd() / target
    target = Path(os.path.normpath(str(target)))
    anchor = Path(target.anchor)
    safe_root = anchor.resolve()
    current = anchor
    for part in target.parts[1:]:
        current /= part
        if not _path_exists(current):
            continue
        if _is_link_like(current):
            raise ValueError(f"target contains a link-like parent: {current}")
        resolved_current = current.resolve()
        if not is_within(resolved_current, safe_root):
            raise ValueError(f"target parent escapes allowed directory: {current}")
        safe_root = resolved_current
    return target, safe_root


def validate_target_path(path: Path, allowed_root: Path | None = None) -> tuple[Path, Path]:
    target, safe_root = _validate_target_path(path)
    resolved_target = target.resolve()
    allowed = Path(allowed_root).resolve() if allowed_root is not None else safe_root
    if not is_within(resolved_target, allowed):
        raise ValueError(f"target escapes allowed directory: {target}")
    return resolved_target, allowed


def prepare_target(path: Path) -> Path:
    """校验目标及父级并创建安全父目录，但不创建/清空目标本身。"""
    target, safe_root = validate_target_path(path)
    if _path_exists(target) and (is_link_like(target) or not target.is_dir()):
        raise ValueError("workspace path must be a real directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    if not is_within(resolved_target, safe_root):
        raise ValueError("prepared target escapes its allowed directory")
    if _path_exists(target) and is_link_like(target):
        raise ValueError("workspace path must be a real directory")
    return resolved_target


def safe_relative_destination(root: Path, raw_path: str, *, source_name: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or not raw_path.strip():
        raise ValueError(f"{source_name} path must not be empty")
    if "\x00" in raw_path:
        raise ValueError(f"invalid {source_name} path")

    posix_path = PurePosixPath(raw_path.replace("\\", "/"))
    windows_path = PureWindowsPath(raw_path)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"{source_name} path must be relative: {raw_path!r}")

    normalized = raw_path.replace("\\", "/")
    lexical_destination = root / Path(normalized)
    current = root
    for part in lexical_destination.relative_to(root).parts:
        current /= part
        if _path_exists(current) and is_link_like(current):
            raise ValueError(f"link-like path is not allowed: {current}")
    destination = lexical_destination.resolve()
    if not is_within(destination, root.resolve()):
        raise ValueError(f"{source_name} path escapes target directory: {raw_path!r}")
    return destination


def ensure_within(path: Path, root: Path, *, label: str) -> Path:
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    if not is_within(resolved_path, resolved_root):
        raise ValueError(f"{label} must be inside the allowed directory")
    return resolved_path


def normalize_project_id(project_id: int | str) -> int:
    if isinstance(project_id, bool):
        raise ValueError("project_id must be an integer or numeric string")
    if isinstance(project_id, int):
        return project_id
    if not isinstance(project_id, str):
        raise ValueError("project_id must be an integer or numeric string")
    value = project_id.strip()
    if not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError("project_id must be an integer or numeric string")
    return int(value)


def remove_tree(path: Path) -> None:
    """删除 ingestion 自己创建或替换下来的目录，不跟随链接。"""
    if is_link_like(path):
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
        return
    if not path.is_dir():
        path.unlink()
        return
    for child in path.iterdir():
        remove_tree(child)
    path.rmdir()


__all__ = [
    "_is_link_like",
    "ensure_within",
    "is_link_like",
    "is_within",
    "normalize_project_id",
    "path_exists",
    "prepare_target",
    "remove_tree",
    "safe_relative_destination",
    "validate_target_path",
]
