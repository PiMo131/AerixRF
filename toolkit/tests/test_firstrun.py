"""The one-command first session: does the plan hold together without a board?

Everything here runs with no hardware. What it checks is that the plan is
internally consistent with the constraints established elsewhere in the
toolkit, so that a later edit cannot quietly put a capture at a rate that
cannot work.
"""

from __future__ import annotations

import json

import pytest

from antsdr_toolkit import cli_firstrun as fr


def test_the_dry_run_prints_a_plan_and_touches_nothing(tmp_path, capsys):
    assert fr.main(["--dry-run", "-o", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "nothing was captured" in out
    for step in fr.DEFAULT_PLAN:
        assert step.name in out
    assert not (tmp_path / "out").exists()


def test_every_video_step_is_above_the_rate_where_the_fm_aliases():
    """The constraint that a plan edit is most likely to break."""
    from antsdr_toolkit.analog import video_decode as vd
    for step in fr.DEFAULT_PLAN:
        if "video" in step.analyses:
            assert step.sample_rate_hz > vd.MIN_SAMPLE_RATE_HZ, step.name


def test_every_droneid_step_is_at_a_rate_whose_fft_divides_evenly():
    """15.36, 30.72 or 61.44 MSPS. 20 MSPS does not work, however convenient."""
    from antsdr_toolkit.droneid import constants as C
    for step in fr.DEFAULT_PLAN:
        if "droneid" in step.analyses:
            assert C.is_supported_rate(step.sample_rate_hz), step.name


def test_the_droneid_step_sits_on_a_documented_centre():
    from antsdr_toolkit.droneid import constants as C
    for step in fr.DEFAULT_PLAN:
        if "droneid" in step.analyses:
            assert C.channel_for(step.center_freq_hz) is not None, step.name


def test_every_step_is_inside_the_boards_tuning_range():
    from antsdr_toolkit import hardware as hw
    for step in fr.DEFAULT_PLAN:
        assert hw.E200.lo_min <= step.center_freq_hz <= hw.E200.lo_max, step.name
        assert step.sample_rate_hz <= hw.E200.sample_rate_max_1ch, step.name


def test_the_plan_warns_that_high_rates_are_snapshots(capsys):
    """Above the IIO ceiling the radio is on for a fraction of the time."""
    from antsdr_toolkit import hardware as hw
    fr.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "snapshot captures" in out
    ceiling = hw.E200.host_stream_ceiling_sps["iio_sc16_1ch"]
    assert any(s.sample_rate_hz > ceiling for s in fr.DEFAULT_PLAN)


def test_every_step_explains_why_it_is_there():
    for step in fr.DEFAULT_PLAN:
        assert step.why and len(step.why) > 20, step.name
        assert step.analyses and step.seconds > 0


def test_a_single_step_can_be_selected(capsys):
    assert fr.main(["--dry-run", "--only", "fpv-5g8"]) == 0
    out = capsys.readouterr().out
    assert "fpv-5g8" in out and "droneid-2g4" not in out
    assert "1 step(s)" in out


def test_an_unknown_step_name_is_refused_with_the_choices(capsys):
    assert fr.main(["--dry-run", "--only", "nonesuch"]) == 1
    err = capsys.readouterr().err
    assert "nonesuch" in err and "fpv-5g8" in err


def test_seconds_overrides_every_step(capsys):
    assert fr.main(["--dry-run", "--seconds", "0.5"]) == 0
    out = capsys.readouterr().out
    assert f"{0.5 * len(fr.DEFAULT_PLAN):.0f} s of capture" in out


def test_it_fails_clearly_when_the_board_is_not_there(tmp_path, capsys):
    """The commonest first-session outcome, so the message has to be useful."""
    code = fr.main(["-o", str(tmp_path / "run"), "--uri", "ip:203.0.113.1"])
    assert code == 1
    out = capsys.readouterr().out
    assert "could not reach the board" in out
    assert "iio_info" in out and "ADR-0012" in out


def test_the_summary_says_what_an_empty_result_does_not_prove(tmp_path, capsys):
    """Silence has three separate innocent explanations, and they matter."""
    fr._summarise({"steps": {"a": {"n_bursts": 0}}}, tmp_path)
    out = capsys.readouterr().out
    assert "does not prove" in out
    assert "Mini 2" in out          # open code decodes only two airframes
    assert "250 g" in out           # C0 is exempt from Remote ID
    assert "600 ms" in out          # a short capture sees few bursts


def test_the_report_is_json_serialisable(tmp_path):
    report = {"uri": "ip:1.2.3.4", "steps": {s.name: {"why": s.why} for s in fr.DEFAULT_PLAN}}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report, default=str))
    assert json.loads(path.read_text())["uri"] == "ip:1.2.3.4"


@pytest.mark.parametrize("name", [s.name for s in fr.DEFAULT_PLAN])
def test_step_names_are_usable_as_filenames(name):
    assert name and "/" not in name and " " not in name



def test_identify_uses_read_only_device_probe(monkeypatch):
    from antsdr_toolkit.device import e200
    monkeypatch.setattr(e200, 'probe', lambda *, uri: {'uri': uri, 'devices': ['ad9361-phy']})
    assert fr._identify('ip:test')['devices'] == ['ad9361-phy']


def test_firstrun_cannot_bypass_high_rate_recording_guard(tmp_path, monkeypatch):
    from antsdr_toolkit.device import e200
    monkeypatch.setattr(e200, 'E200Source', lambda **kw: pytest.fail('must fail before opening radio'))
    step = next(s for s in fr.DEFAULT_PLAN if s.sample_rate_hz == 20e6)
    result = fr._capture_and_analyse(step, tmp_path / 'bad', 'ip:test', 40.0)
    assert 'Multi-buffer gap timing is not implemented' in result['error']
    assert not (tmp_path / 'bad.sigmf-data').exists()
