import pytest

from btb.uihelpers import show_df


class NewSt:
    calls = []
    def dataframe(self, data, width=None, **kw):  # noqa: D401
        self.calls.append(("new", width, kw))
NewSt.dataframe.__annotations__["width"] = "int | Literal['stretch', 'content']"


class OldSt:
    def __init__(self):
        self.calls = []
    def dataframe(self, data, width=None, height=None, use_container_width=False, **kw):
        self.calls.append(("old", width, use_container_width, kw))


class OlderSt(OldSt):
    def dataframe(self, data, height=None, use_container_width=False):  # no width param at all
        self.calls.append(("older", use_container_width))


def test_new_streamlit_uses_width_stretch():
    st = NewSt(); st.calls = []
    show_df(st, [1], hide_index=True)
    assert st.calls == [("new", "stretch", {"hide_index": True})]


def test_old_signature_with_int_width_falls_back_without_recursion():
    st = OldSt()
    OldSt.dataframe.__annotations__["width"] = "int"
    show_df(st, [1])
    assert st.calls[0][1] is None and st.calls[0][2] is True


def test_no_width_param_uses_container_width():
    st = OlderSt()
    show_df(st, [1])
    assert st.calls == [("older", True)]


def test_caller_width_is_not_duplicated():
    st = NewSt(); st.calls = []
    show_df(st, [1], width=300)
    assert st.calls == [("new", 300, {})]


def test_real_streamlit_installed_runs_without_error():
    import streamlit as st
    # outside a script run, st.dataframe is a harmless no-op; it must not raise or recurse
    show_df(st, __import__("pandas").DataFrame({"a": [1]}))
