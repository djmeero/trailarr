from config.settings import app_settings


def test_clips_dir_default_and_set(tmp_path):
    original = app_settings.clips_dir
    try:
        app_settings.clips_dir = str(tmp_path / "myclips")
        assert app_settings.clips_dir == str(tmp_path / "myclips")
    finally:
        app_settings.clips_dir = original


def test_clips_dir_in_as_dict():
    assert "clips_dir" in app_settings.as_dict()
