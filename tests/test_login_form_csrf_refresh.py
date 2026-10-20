from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_login_form_refreshes_csrf_before_the_native_submission():
    template = (PROJECT_ROOT / "templates" / "login.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "login.js").read_text(encoding="utf-8")

    assert 'data-csrf-refresh-url="/login/csrf"' in template
    assert "filename='login.js'" in template
    assert 'credentials: "same-origin"' in script
    assert 'cache: "no-store"' in script
    assert "tokenInput.value = payload.csrf_token" in script
    assert "form.requestSubmit(submitter)" in script
