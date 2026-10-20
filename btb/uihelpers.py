"""Small Streamlit compatibility helpers (kept out of app.py so they can be unit-tested)."""
from __future__ import annotations

import inspect


def _width_stretch_supported(st_module) -> bool:
    """Newer Streamlit takes width='stretch'; older versions only have use_container_width."""
    try:
        params = inspect.signature(st_module.dataframe).parameters
    except (TypeError, ValueError):
        return False
    if "width" not in params:
        return False
    # In 1.30-1.48 `width` exists but is an int (pixels); the string form needs the newer signature.
    annotation = str(params["width"].annotation)
    return "str" in annotation or "stretch" in annotation.lower() or "Width" in annotation


def show_df(st_module, data, **kwargs) -> None:
    """Render a dataframe at full width on any supported Streamlit version.

    Caller-supplied width / use_container_width are respected (never passed twice).
    The fallback is a different call (use_container_width), not a recursive one.
    """
    if "width" in kwargs or "use_container_width" in kwargs:
        st_module.dataframe(data, **kwargs)
    elif _width_stretch_supported(st_module):
        st_module.dataframe(data, width="stretch", **kwargs)
    else:
        st_module.dataframe(data, use_container_width=True, **kwargs)
