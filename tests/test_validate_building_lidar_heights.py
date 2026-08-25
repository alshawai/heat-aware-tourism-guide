from pathlib import Path

from scripts.validate_building_lidar_heights import parse_buildings


def test_parse_buildings_keeps_closed_building_ways(tmp_path: Path) -> None:
    source = tmp_path / "map.osm"
    source.write_text(
        '<osm><node id="1" lat="29.0" lon="-98.0" />'
        '<node id="2" lat="29.0" lon="-97.9" />'
        '<node id="3" lat="29.1" lon="-97.9" />'
        '<node id="4" lat="29.1" lon="-98.0" />'
        '<way id="10"><nd ref="1" /><nd ref="2" /><nd ref="3" /><nd ref="4" /><nd ref="1" />'
        '<tag k="building" v="yes" /></way></osm>',
        encoding="utf-8",
    )
    buildings = parse_buildings(source)
    assert len(buildings) == 1
    assert buildings[0]["id"] == 10
    assert buildings[0]["tags"]["building"] == "yes"
