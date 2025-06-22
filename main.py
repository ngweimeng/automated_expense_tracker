import streamlit as st

pages = {
    "Navigate": [
        st.page("pages/01_About.py", title="About the Project", icon="💡"),
        st.page("pages/02_Dashboard.py", title="Dashboard", icon="📊"),
        st.page("pages/03_Settings.py",  title="Settings",  icon="⚙️"),
    ]
}

pg = st.navigation(pages)
pg.run()