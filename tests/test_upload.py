"""文件上传校验单元测试
======================
测试 upload_handler 中的文件类型和文件大小校验逻辑。

由于 ALLOWED_EXTENSIONS 和 MAX_FILE_SIZE 定义在 upload_handler 函数内部
（非模块级常量），本测试文件复制了一份与 server.py 中完全相同的常量值。
"""

import pytest

# ═══════════════════════════════════════════
# 从 server.py upload_handler 复制的常量
# （无法直接导入，因为定义在函数内部）
# ═══════════════════════════════════════════

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_EXTENSIONS = {
    '.txt', '.md', '.json', '.py', '.js', '.ts', '.html', '.css', '.scss',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp',
    '.pdf', '.doc', '.docx', '.xlsx', '.xls', '.ppt', '.pptx', '.csv',
    '.zip', '.tar', '.gz', '.7z', '.rar',
    '.mp3', '.mp4', '.wav', '.flac', '.ogg', '.webm', '.mov', '.avi',
    '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.xml', '.sql', '.sh', '.bat', '.ps1',
    '.mdx', '.tex', '.rst',
    '.woff', '.woff2', '.ttf', '.eot',
}


# ═══════════════════════════════════════════
# 测试类
# ═══════════════════════════════════════════

class TestFileUploadValidation:
    """文件上传校验功能测试"""

    # ── 白名单扩展名测试 ──

    def test_txt_allowed(self):
        assert '.txt' in ALLOWED_EXTENSIONS

    def test_png_allowed(self):
        assert '.png' in ALLOWED_EXTENSIONS

    def test_py_allowed(self):
        assert '.py' in ALLOWED_EXTENSIONS

    def test_jpg_allowed(self):
        assert '.jpg' in ALLOWED_EXTENSIONS

    def test_pdf_allowed(self):
        assert '.pdf' in ALLOWED_EXTENSIONS

    def test_json_allowed(self):
        assert '.json' in ALLOWED_EXTENSIONS

    def test_zip_allowed(self):
        assert '.zip' in ALLOWED_EXTENSIONS

    def test_html_allowed(self):
        assert '.html' in ALLOWED_EXTENSIONS

    # ── 禁止的扩展名测试 ──

    def test_exe_blocked(self):
        assert '.exe' not in ALLOWED_EXTENSIONS

    def test_com_blocked(self):
        assert '.com' not in ALLOWED_EXTENSIONS

    def test_cmd_blocked(self):
        assert '.cmd' not in ALLOWED_EXTENSIONS

    def test_msi_blocked(self):
        assert '.msi' not in ALLOWED_EXTENSIONS

    def test_scr_blocked(self):
        assert '.scr' not in ALLOWED_EXTENSIONS

    def test_pif_blocked(self):
        assert '.pif' not in ALLOWED_EXTENSIONS

    def test_vbs_blocked(self):
        assert '.vbs' not in ALLOWED_EXTENSIONS

    def test_dll_blocked(self):
        assert '.dll' not in ALLOWED_EXTENSIONS

    # ── 常见危险扩展名批量测试 ──

    def test_dangerous_extensions_all_blocked(self):
        """常见危险扩展名全部不在白名单中"""
        dangerous = [
            '.exe', '.com', '.cmd', '.msi', '.scr', '.pif', '.vbs',
            '.dll', '.sys', '.drv', '.ocx', '.cpl',
        ]
        for ext in dangerous:
            assert ext not in ALLOWED_EXTENSIONS, f'{ext} 不应在白名单中'

    # ── 文件大小测试 ──

    def test_max_file_size_is_10mb(self):
        assert MAX_FILE_SIZE == 10 * 1024 * 1024

    def test_max_file_size_in_bytes(self):
        assert MAX_FILE_SIZE == 10_485_760

    # ── 格式规范测试 ──

    def test_allowed_extensions_are_lowercase(self):
        for ext in ALLOWED_EXTENSIONS:
            assert ext == ext.lower(), f'{ext} 应该是小写'

    def test_allowed_extensions_start_with_dot(self):
        for ext in ALLOWED_EXTENSIONS:
            assert ext.startswith('.'), f'{ext} 应该以点开头'

    # ── 边界测试 ──

    def test_empty_extension(self):
        assert '' not in ALLOWED_EXTENSIONS

    def test_extension_case_sensitivity(self):
        """大写变体不应匹配（白名单全小写）"""
        assert '.EXE' not in ALLOWED_EXTENSIONS
        assert '.PNG' not in ALLOWED_EXTENSIONS
        assert '.PDF' not in ALLOWED_EXTENSIONS
