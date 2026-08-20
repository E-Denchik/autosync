from app.services.upload_helpers import compute_files_hash


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_same_content_same_hash(tmp_path):
    a = _write(tmp_path, "a.xlsx", b"hello world")
    b = _write(tmp_path, "b.xlsx", b"hello world")
    assert compute_files_hash([a]) == compute_files_hash([b])


def test_different_content_different_hash(tmp_path):
    a = _write(tmp_path, "a.xlsx", b"hello world")
    b = _write(tmp_path, "b.xlsx", b"goodbye world")
    assert compute_files_hash([a]) != compute_files_hash([b])


def test_file_order_does_not_matter(tmp_path):
    a = _write(tmp_path, "a.xlsx", b"page one")
    b = _write(tmp_path, "b.xlsx", b"page two")
    assert compute_files_hash([a, b]) == compute_files_hash([b, a])


def test_file_count_matters(tmp_path):
    a = _write(tmp_path, "a.xlsx", b"same")
    b = _write(tmp_path, "b.xlsx", b"same")
    assert compute_files_hash([a]) != compute_files_hash([a, b])
