import ctypes
import os
import struct
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from interview_agent.ingestion.service import IngestionService
from interview_agent.ingestion.security import _is_link_like, prepare_target
from interview_agent.ingestion.sources import FolderSource, ZipSource
from interview_agent.ingestion.workspace import WorkspaceManager


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ingestion" / "sample-project"


def create_windows_junction(link: Path, target: Path) -> None:
    """Create a junction without invoking a shell command."""
    if os.name != "nt":
        raise OSError("Windows only")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    device_io_control = kernel32.DeviceIoControl
    device_io_control.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    device_io_control.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    link.mkdir()
    substitute_name = ("\\??\\" + str(target.resolve())).encode("utf-16le")
    print_name = str(target.resolve()).encode("utf-16le")
    path_buffer = substitute_name + b"\x00\x00" + print_name + b"\x00\x00"
    print_offset = len(substitute_name) + 2
    reparse_data = struct.pack(
        "<LHHHHHH",
        0xA0000003,
        len(path_buffer) + 8,
        0,
        0,
        len(substitute_name),
        print_offset,
        len(print_name),
    ) + path_buffer
    handle = create_file(
        str(link),
        0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = ctypes.c_uint32()
        buffer = ctypes.create_string_buffer(reparse_data)
        if not device_io_control(
            handle,
            0x000900A4,
            buffer,
            len(reparse_data),
            None,
            0,
            ctypes.byref(returned),
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


class IngestionTests(unittest.TestCase):
    def test_zip_source_prepares_files_under_target_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "project.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("sample-project/README.md", b"from zip")
                zipped.writestr("sample-project/src/main.py", b"print('ok')")

            project_root = ZipSource(archive).prepare(temp_root / "source")

            self.assertEqual((project_root / "sample-project" / "README.md").read_bytes(), b"from zip")
            self.assertEqual((project_root / "sample-project" / "src" / "main.py").read_bytes(), b"print('ok')")
            self.assertEqual(project_root.resolve(), (temp_root / "source").resolve())

    def test_folder_source_preserves_relative_paths(self):
        source = FolderSource(
            (
                ("README.md", b"folder project"),
                ("src/main.py", b"print('ok')"),
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = source.prepare(Path(temp_dir) / "source")

            self.assertEqual(project_root.joinpath("README.md").read_bytes(), b"folder project")
            self.assertEqual(project_root.joinpath("src", "main.py").read_bytes(), b"print('ok')")

    def test_folder_source_materializes_one_shot_iterable_for_repeated_prepare(self):
        source = FolderSource(iter((("README.md", b"stable"),)))

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "source"
            source.prepare(target)
            source.prepare(target)

            self.assertEqual((target / "README.md").read_bytes(), b"stable")

    def test_folder_source_accepts_sample_fixture_shape(self):
        source = FolderSource((("README.md", (FIXTURE_ROOT / "README.md").read_bytes()),))

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = source.prepare(Path(temp_dir) / "source")

            self.assertEqual(project_root.joinpath("README.md").read_text(encoding="utf-8"), "sample project\n")

    def test_zip_source_rejects_zip_slip_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../outside.txt", b"unsafe")

            with self.assertRaisesRegex(ValueError, "outside|安全|path"):
                ZipSource(archive).prepare(temp_root / "source")
            self.assertFalse((temp_root / "outside.txt").exists())

    def test_zip_source_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "absolute.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("/absolute.txt", b"unsafe")

            with self.assertRaisesRegex(ValueError, "absolute|绝对|path"):
                ZipSource(archive).prepare(Path(temp_dir) / "source")

    def test_zip_source_rejects_normalized_duplicate_member_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "duplicate.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("a", b"first")
                zipped.writestr("./a", b"second")

            with self.assertRaisesRegex(ValueError, "duplicate|conflict|冲突"):
                ZipSource(archive).prepare(Path(temp_dir) / "source")

    def test_zip_source_rejects_file_directory_path_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "conflict.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("a", b"file")
                zipped.writestr("a/b", b"nested")

            with self.assertRaisesRegex(ValueError, "duplicate|conflict|冲突"):
                ZipSource(archive).prepare(Path(temp_dir) / "source")

    def test_zip_source_rejects_casefold_member_path_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "casefold.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("A.txt", b"upper")
                zipped.writestr("a.txt", b"lower")

            with self.assertRaisesRegex(ValueError, "duplicate|conflict|冲突"):
                ZipSource(archive).prepare(Path(temp_dir) / "source")

    def test_folder_source_rejects_casefold_path_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "Folder.*conflict|Folder.*重复"):
                FolderSource(
                    (("A.txt", b"upper"), ("a.txt", b"lower"))
                ).prepare(Path(temp_dir) / "source")

    def test_folder_source_rejects_file_directory_path_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate|conflict|冲突"):
                FolderSource(
                    (("a", b"file"), ("a/b", b"nested"))
                ).prepare(Path(temp_dir) / "source")

    def test_link_attribute_inspection_fails_closed_on_oserror(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "interview_agent.ingestion.security.Path.lstat",
                side_effect=OSError("access denied"),
            ):
                with self.assertRaisesRegex(ValueError, "inspect|link|安全"):
                    _is_link_like(Path(temp_dir))

    def test_lstat_errors_fail_closed_in_path_existence_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "interview_agent.ingestion.security.Path.lstat",
                side_effect=PermissionError("access denied"),
            ):
                with self.assertRaisesRegex(ValueError, "inspect|stat|安全"):
                    prepare_target(Path(temp_dir) / "source")

    def test_zip_source_failure_preserves_old_target_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "write-failure.zip"
            target = temp_root / "source"
            target.mkdir()
            (target / "old.txt").write_bytes(b"keep")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("first.txt", b"first")
                zipped.writestr("second.txt", b"second")

            with patch(
                "interview_agent.ingestion.sources.shutil.copyfileobj",
                side_effect=[None, OSError("write failed")],
            ):
                with self.assertRaisesRegex(OSError, "write failed"):
                    ZipSource(archive).prepare(target)

            self.assertEqual((target / "old.txt").read_bytes(), b"keep")
            self.assertFalse((target / "first.txt").exists())
            self.assertEqual(
                [path for path in temp_root.iterdir() if path.name.startswith(".source-")],
                [],
            )

    def test_swap_failure_restores_old_target_and_cleans_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "swap-failure.zip"
            target = temp_root / "source"
            target.mkdir()
            (target / "old.txt").write_bytes(b"keep")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("new.txt", b"new")

            original_replace = Path.replace

            def fail_staging_replace(path, destination):
                if path.name.startswith(".source-staging-"):
                    raise OSError("swap failed")
                return original_replace(path, destination)

            with patch(
                "interview_agent.ingestion.sources.Path.replace",
                autospec=True,
                side_effect=fail_staging_replace,
            ):
                with self.assertRaisesRegex(RuntimeError, "replace|swap"):
                    ZipSource(archive).prepare(target)

            self.assertEqual((target / "old.txt").read_bytes(), b"keep")
            self.assertEqual(
                [path for path in temp_root.iterdir() if path.name.startswith(".source-")],
                [],
            )

    def test_restore_failure_raises_explicit_error_and_cleans_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive = temp_root / "restore-failure.zip"
            target = temp_root / "source"
            target.mkdir()
            (target / "old.txt").write_bytes(b"keep")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("new.txt", b"new")

            original_replace = Path.replace

            def fail_swap_and_restore(path, destination):
                if path.name.startswith((".source-staging-", ".source-backup-")):
                    raise OSError("replacement or restore failed")
                return original_replace(path, destination)

            with patch(
                "interview_agent.ingestion.sources.Path.replace",
                autospec=True,
                side_effect=fail_swap_and_restore,
            ):
                with self.assertRaisesRegex(RuntimeError, "restore|backup"):
                    ZipSource(archive).prepare(target)

            self.assertEqual(
                [path for path in temp_root.iterdir() if path.name.startswith(".source-")],
                [],
            )

    def test_zip_source_rejects_symlink_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "symlink.zip"
            link = zipfile.ZipInfo("link.txt")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(link, b"../../outside.txt")

            with self.assertRaisesRegex(ValueError, "symbolic|symlink|符号"):
                ZipSource(archive).prepare(Path(temp_dir) / "source")

    @unittest.skipUnless(os.name == "nt", "Windows directory reparse point test")
    def test_zip_source_rejects_windows_directory_link_without_external_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            external_root = temp_root / "external"
            source_root.mkdir()
            external_root.mkdir()
            linked_root = source_root / "linked"
            try:
                create_windows_junction(linked_root, external_root)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory links unavailable: {exc}")
            is_junction = getattr(linked_root, "is_junction", None)
            if not callable(is_junction):
                os.rmdir(linked_root)
                self.skipTest("Path.is_junction is unavailable")

            archive = temp_root / "reparse.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("linked/created.txt", b"must not escape")

            try:
                self.assertTrue(is_junction())
                with self.assertRaises(ValueError):
                    ZipSource(archive).prepare(source_root)
                self.assertFalse((external_root / "created.txt").exists())
            finally:
                os.rmdir(linked_root)

    @unittest.skipUnless(os.name == "nt", "Windows parent junction test")
    def test_zip_source_rejects_parent_junction_without_external_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            external_root = temp_root / "external"
            parent_link = temp_root / "parent-link"
            target = parent_link / "new-source"
            external_root.mkdir()
            try:
                create_windows_junction(parent_link, external_root)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory links unavailable: {exc}")

            archive = temp_root / "parent-junction.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("created.txt", b"must not escape")

            try:
                with self.assertRaises(ValueError):
                    ZipSource(archive).prepare(target)
                self.assertFalse((external_root / "new-source" / "created.txt").exists())
            finally:
                os.rmdir(parent_link)

    @unittest.skipUnless(os.name == "nt", "Windows parent junction test")
    def test_folder_source_rejects_parent_junction_without_external_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            external_root = temp_root / "external"
            parent_link = temp_root / "parent-link"
            target = parent_link / "new-source"
            external_root.mkdir()
            try:
                create_windows_junction(parent_link, external_root)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory links unavailable: {exc}")

            try:
                with self.assertRaises(ValueError):
                    FolderSource((("created.txt", b"must not escape"),)).prepare(target)
                self.assertFalse((external_root / "new-source" / "created.txt").exists())
            finally:
                os.rmdir(parent_link)

    def test_zip_source_enforces_file_size_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "large.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("large.bin", b"12345")

            with self.assertRaisesRegex(ValueError, "file size|单文件"):
                ZipSource(archive, max_file_size=4).prepare(Path(temp_dir) / "source")

    def test_zip_source_enforces_total_size_and_file_count_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "limited.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("one.txt", b"123")
                zipped.writestr("two.txt", b"456")

            with self.assertRaisesRegex(ValueError, "total size|总大小"):
                ZipSource(archive, max_total_size=5).prepare(Path(temp_dir) / "total")
            with self.assertRaisesRegex(ValueError, "file count|文件数量"):
                ZipSource(archive, max_files=1).prepare(Path(temp_dir) / "count")

    def test_folder_source_rejects_absolute_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "absolute|绝对|path"):
                FolderSource(((str((Path(temp_dir) / "absolute.txt").resolve()), b"x"),)).prepare(
                    Path(temp_dir) / "source"
                )
            with self.assertRaisesRegex(ValueError, "outside|目录外|path"):
                FolderSource((("../outside.txt", b"x"),)).prepare(Path(temp_dir) / "source")

    def test_folder_source_rejects_empty_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                FolderSource((("", b"x"),)).prepare(Path(temp_dir) / "source")

    def test_folder_source_rejects_whitespace_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                FolderSource((("   \t", b"x"),)).prepare(Path(temp_dir) / "source")

    def test_workspace_manager_creates_separate_source_and_analysis_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = WorkspaceManager(Path(temp_dir)).create_workspace(7)

            self.assertEqual(workspace.source, Path(temp_dir) / "projects" / "7" / "source")
            self.assertEqual(workspace.analysis, Path(temp_dir) / "projects" / "7" / "analysis")
            self.assertTrue(workspace.source.is_dir())
            self.assertTrue(workspace.analysis.is_dir())
            self.assertNotEqual(workspace.source.resolve(), workspace.analysis.resolve())

    def test_ingestion_service_returns_project_root_and_source_info(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = IngestionService(WorkspaceManager(Path(temp_dir))).ingest(
                11, FolderSource((("README.md", b"project"),))
            )

            self.assertEqual(result.project_root, Path(temp_dir) / "projects" / "11" / "source")
            self.assertEqual(result.source_info["source_type"], "folder")
            self.assertEqual(result.source_info["project_root"], str(result.project_root))

    def test_project_id_numeric_strings_are_normalized_to_int(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(Path(temp_dir))
            workspace = manager.create_workspace("007")
            result = IngestionService(manager).ingest(
                "008", FolderSource((("README.md", b"project"),))
            )

            self.assertEqual(workspace.project_id, 7)
            self.assertIsInstance(workspace.project_id, int)
            self.assertEqual(result.project_id, 8)
            self.assertIsInstance(result.project_id, int)
            self.assertEqual(result.workspace.project_id, 8)
            self.assertEqual(result.source_info["project_id"], 8)

    def test_project_id_rejects_bool_and_non_numeric_values(self):
        invalid_ids = (True, False, "", "project", 1.5, None)
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(Path(temp_dir))
            service = IngestionService(manager)
            for invalid_id in invalid_ids:
                with self.subTest(invalid_id=invalid_id):
                    with self.assertRaises(ValueError):
                        manager.create_workspace(invalid_id)
                    with self.assertRaises(ValueError):
                        service.ingest(invalid_id, FolderSource((("README.md", b"x"),)))

    def test_repeated_ingestion_replaces_source_and_preserves_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = IngestionService(WorkspaceManager(Path(temp_dir)))
            first = service.ingest(12, FolderSource((("old.txt", b"old"),)))
            analysis_marker = first.workspace.analysis / "result.json"
            analysis_marker.write_text("{}", encoding="utf-8")

            second = service.ingest(12, FolderSource((("new.txt", b"new"),)))

            self.assertEqual(first.project_root, second.project_root)
            self.assertFalse((second.project_root / "old.txt").exists())
            self.assertEqual((second.project_root / "new.txt").read_bytes(), b"new")
            self.assertTrue(analysis_marker.exists())


if __name__ == "__main__":
    unittest.main()
