from scripts.lidar_corridor_probe import corridor_aoi


def test_corridor_aoi_contains_route_endpoints() -> None:
    bbox = corridor_aoi((-98.4861, 29.4259), (-98.4853, 29.4225), 100)
    assert bbox[0] < -98.4861 < bbox[2]
    assert bbox[1] < 29.4225 < bbox[3]
    assert bbox[2] - bbox[0] > 0
    assert bbox[3] - bbox[1] > 0


def test_corridor_aoi_grows_with_buffer() -> None:
    small = corridor_aoi((-97.7415, 30.2676), (-97.7405, 30.2747), 50)
    large = corridor_aoi((-97.7415, 30.2676), (-97.7405, 30.2747), 100)
    assert large[0] < small[0]
    assert large[1] < small[1]
    assert large[2] > small[2]
    assert large[3] > small[3]
