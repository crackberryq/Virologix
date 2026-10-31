from pathlib import Path
import os
import psutil
import streamlit as st
from viralogix import __version__
from viralogix.store import Store
from viralogix.samples import register
from viralogix.cfasta import parse, export_consensus

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="Virologix | Human Link GenoMix", page_icon=str(ASSETS / "brand.png"), layout="wide")
st.markdown("""<style>.stApp {background:#f5f8ff} h1,h2,h3 {color:#102d56}
[data-testid="stSidebar"]{background:#eaf1fc} .stButton>button{border-radius:10px; border-color:#2563eb; color:#1d4ed8}
</style>""", unsafe_allow_html=True)
store = Store()
st.sidebar.image(str(ASSETS / "brand.png"), width=48)
st.sidebar.title("Virologix")
st.sidebar.caption("HUMAN LINK GenoMix")
st.sidebar.caption("VIROLOGY WORKSPACE • " + __version__)
page = st.sidebar.radio("Workspace", ["Overview", "Samples", "cFASTA", "Setup"])
st.sidebar.caption("Local workspace: " + str(store.home))
if page == "Overview":
    st.title("Your virology workspace")
    st.write("Organize sequencing inputs and inspect consensus-anchored population files.")
    a,b,c=st.columns(3)
    a.metric("Registered samples", len(store.all("samples")))
    b.metric("cFASTA inspection", "Ready")
    c.metric("Read-to-cFASTA builder", "Planned")
    st.subheader("cFASTA workbench")
    st.write("Validate draft files, review segment tables and download ordinary consensus FASTA.")
    st.info("This foundation does not run sequencing analysis yet. Samples are registered as local file paths.")
    st.subheader("Platform roadmap")
    st.dataframe([{"Module":"Sample registry", "Status":"Available"}, {"Module":"cFASTA inspection and consensus export", "Status":"Available"}, {"Module":"Illumina cFASTA builder", "Status":"Planned"}, {"Module":"Run queue and provenance", "Status":"Planned"}, {"Module":"Long-read/hybrid evidence", "Status":"Planned"}], hide_index=True)
elif page == "Samples":
    st.title("Samples")
    with st.form("register"):
        sample=st.text_input("Sample ID")
        r1=st.text_input("R1 FASTQ path")
        r2=st.text_input("R2 FASTQ path (optional)")
        ref=st.text_input("Segment reference FASTA path (optional)")
        if st.form_submit_button("Register sample"):
            try:
                register(store,sample,r1,r2,ref)
                st.success("Sample registered.")
            except ValueError as exc:
                st.error(str(exc))
    st.caption("Windows/WSL: use the Linux path, such as /mnt/c/data/sample_R1.fastq.gz.")
    st.dataframe(store.all("samples"), hide_index=True)
elif page == "cFASTA":
    st.title("cFASTA workbench")
    st.caption("Native cFASTA plus a separate ordinary consensus FASTA export.")
    uploaded=st.file_uploader("Open a cFASTA file", type=["cfasta"])
    if uploaded:
        try:
            entries=parse(uploaded.getvalue().decode("utf-8"))
            st.success(f"Syntax valid: {len(entries)} segments")
            st.warning("Draft semantics: consensus is not automatically an observed haplotype. Local rows may overlap and their abundances must not be pooled.")
            for entry in entries:
                with st.expander(entry.metadata["sample"]+" / "+entry.metadata["segment"]):
                    st.code(entry.consensus)
                    st.dataframe(entry.haplotypes, hide_index=True)
            st.download_button("Download consensus FASTA", export_consensus(entries), file_name=Path(uploaded.name).stem+".consensus.fasta", mime="text/plain")
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
else:
    st.title("Setup")
    st.write("CPU cores:", os.cpu_count())
    st.write("Available RAM (GiB):", round(psutil.virtual_memory().available/2**30,2))
    st.write("Workspace:", str(store.home))
    st.info("Resource profiles, GPU detection, environment repair and pipeline installation will be connected with the builder.")
