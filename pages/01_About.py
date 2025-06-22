import streamlit as st

st.set_page_config(
    page_title="WeiMeng's Budget Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("💰 WeiMeng's Budget Tracker")
st.write("A Streamlit app to upload, categorize, and visualize your personal expenses.")

st.markdown(
    """
    Welcome to **WeiMeng's Budget Tracker**! This app helps you take control of your spending:

    1. **Settings**: Upload your PDF statements and manage your transaction categories.  
    2. **Dashboard**: Explore interactive summaries, trends over time, and high-spend alerts.  

    **Key features**  
    - Automatic parsing of credit card PDFs  
    - Supabase backend for secure data storage  
    - Categorize transactions with keywords (or edit them manually)  
    - Visualize spend by category, time period, and more  

    **How to get started**  
    - Go to **Settings** in the sidebar to upload your first PDF.  
    - Head over to **Dashboard** to see your spending come to life!  

    ---
    Created by WeiMeng • [GitHub: ngweimeng](https://github.com/ngweimeng)
    """
)
