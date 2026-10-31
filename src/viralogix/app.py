"""Virologix workspace using the Bactologix presentation shell."""
from pathlib import Path
import streamlit as st
from streamlit.components.v2 import component
from viralogix.store import Store
from viralogix.ui_backend import snapshot, handle_request

ROOT = Path(__file__).parent
st.set_page_config(page_title="Virologix | Human Link GenoMix", page_icon=str(ROOT / "assets/brand.png"), layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
header[data-testid="stHeader"], [data-testid="stSidebar"], #MainMenu, footer {display:none}
.stApp{background:#f5f8ff}.block-container{padding:0!important;max-width:100%!important}
[data-testid="stMainBlockContainer"]{padding:0!important}[data-testid="stVerticalBlock"]{gap:0}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def workspace_component():
    assets = ROOT / "ui"
    return component("virologix_workspace", html=(assets / "shell.html").read_text().replace("__BRAND_SVG__", (ROOT / "assets/brand.svg").read_text()), css=(assets / "styles.css").read_text(), js=(assets / "workspace.js").read_text())

store = Store()
def on_action():
    request = st.session_state["workspace-ui"].get("action")
    if request:
        st.session_state["ui-response"] = handle_request(store, request)

workspace_component()(key="workspace-ui", data={"workspace":snapshot(store), "response":st.session_state.get("ui-response")}, on_action_change=on_action, width="stretch", height="content")
