import pytest

from ayurnidaan.http import UnsafeURL, check_url


@pytest.mark.parametrize(
    "url",
    [
        "https://api.open-meteo.com/v1/archive?x=1",
        "http://localhost:8000/x",
        "http://127.0.0.1:8501/h",
    ],
)
def test_allowed(url):
    assert check_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["http://example.com/", "file:///etc/passwd", "ftp://host/f", "https:///nohost", "gopher://x"],
)
def test_refused(url):
    with pytest.raises(UnsafeURL):
        check_url(url)
