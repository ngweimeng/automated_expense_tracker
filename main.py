import streamlit as st

pages = {
    "Navigation Page": [
        st.Page("pages/01_About.py", title="About the Project", icon="💡"),
        st.Page("pages/02_Dashboard.py", title="Dashboard", icon="📊"),
        st.Page("pages/03_Configuration.py",  title="Configuration",  icon="⚙️"),
    ]
}

pg = st.navigation(pages)
pg.run()