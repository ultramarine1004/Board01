
import streamlit as st
options = ["A","B"]
if "sel" not in st.session_state:
    st.session_state["sel"] = "A"
current = st.session_state["sel"]
st.write("Selected:", current)
st.selectbox("sel", options, key="sel")
