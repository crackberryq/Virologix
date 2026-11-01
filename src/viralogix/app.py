"""The approved HTML workspace, mounted as an interactive Streamlit component."""
from pathlib import Path
import streamlit as st
from streamlit.components.v2 import component
from viralogix.store import Store
from viralogix.ui_backend import handle_request, snapshot

st.set_page_config(page_title="Virologix", page_icon=str(Path(__file__).parent / 'assets/brand.png'), layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
header[data-testid="stHeader"], [data-testid="stSidebar"], #MainMenu, footer {display:none}
.stApp {background:#f5f8ff}
.block-container {padding:0!important;max-width:100%!important}
[data-testid="stMainBlockContainer"] {padding:0!important}
[data-testid="stVerticalBlock"] {gap:0}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def workspace_component():
    assets = Path(__file__).parent / "ui"
    brand = (Path(__file__).parent / 'assets/brand.svg').read_text().strip()
    return component("viralogix_workspace", html=(assets / "shell.html").read_text().replace('__BRAND_SVG__', brand),
                     css=(assets / "styles.css").read_text(), js=(assets / "workspace.js").read_text().replace('__BRAND_SVG__', brand))

store = Store()

def on_action():
    request = st.session_state["workspace-ui"].get("action")
    if request:
        handle_request(store, request, st.session_state)

workspace_component()(key="workspace-ui", data={"workspace": snapshot(store), "response": st.session_state.get("ui-response")},
                      on_action_change=on_action, width="stretch", height="content")
