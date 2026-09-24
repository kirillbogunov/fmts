from app.services.localization import SUPPORTED_TIMEZONES, TIMEZONE_OPTIONS, normalize_timezone_name, timezone_label


def test_full_iana_timezone_catalog_is_available():
    # Representative regions prove this is not the old Kazakhstan/Russia shortlist.
    expected = {'Asia/Almaty', 'America/New_York', 'Europe/London', 'Pacific/Auckland', 'Africa/Cairo', 'UTC'}
    assert expected.issubset(set(SUPPORTED_TIMEZONES))
    assert len(SUPPORTED_TIMEZONES) > 400
    assert len(TIMEZONE_OPTIONS) == len(SUPPORTED_TIMEZONES)


def test_timezone_normalization_preserves_valid_and_rejects_invalid():
    assert normalize_timezone_name('Asia/Almaty') == 'Asia/Almaty'
    assert normalize_timezone_name('America/New_York') == 'America/New_York'
    assert normalize_timezone_name('not/a-real-zone') == 'Asia/Almaty'
    assert 'UTC+5' in timezone_label('Asia/Almaty')
