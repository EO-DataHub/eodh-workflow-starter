from eodh_workflow import fallback_render, remap_source_renders
from eodh_workflow.testing import write_synthetic_raster


def test_remap_keeps_only_renders_for_the_source_asset():
    source = {
        "tc": {"assets": ["cog"], "bidx": [3, 2, 1], "rescale": [[0, 3000]] * 3},
        "index": {"assets": ["cog"], "expression": "(cog_b7-cog_b3)/(cog_b7+cog_b3)", "rescale": [[-1, 1]]},
        "mixed": {"assets": ["cog", "thumbnail"], "rescale": [[0, 1]]},
    }
    remapped = remap_source_renders(source, "cog")

    assert set(remapped) == {"tc", "index"}
    assert remapped["tc"]["assets"] == ["data"]
    assert remapped["index"]["expression"] == "(data_b7-data_b3)/(data_b7+data_b3)"
    assert source["tc"]["assets"] == ["cog"]  # source not mutated


def test_fallback_render_is_greyscale_without_rgb_common_names(tmp_path):
    cog = write_synthetic_raster(tmp_path / "single.tif", [1000])
    render = fallback_render(cog)

    assert list(render) == ["greyscale"]
    low, high = render["greyscale"]["rescale"][0]
    # Nodata (0) is excluded, so the stretch sits within the 1000-1100 gradient.
    assert 1000 <= low < high <= 1100


def test_fallback_render_is_true_colour_with_rgb(tmp_path):
    cog = write_synthetic_raster(tmp_path / "rgb.tif", [300, 2500, 500])
    render = fallback_render(cog, ["blue", "green", "red"])
    assert render["true-colour"]["bidx"] == [3, 2, 1]
    assert len(render["true-colour"]["rescale"]) == 3
