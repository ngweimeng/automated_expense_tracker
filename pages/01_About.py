import streamlit as st

st.set_page_config(
    page_title="WeiMeng's Budget Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("💰 WeiMeng's Budget Tracker")
st.write("A Streamlit app to upload, categorize, and visualize your personal expenses.")

st.markdown(
    """
---
## Welcome to **WeiMeng's Budget Tracker** 💰
**Track. Analyze. Budget.**

### 🔧 Get Started
1. **Settings**  
   Upload PDF statements & manage your transaction categories  
2. **Dashboard**  
   Explore summaries, trends over time, and high-spend alerts

### ✨ Key Features
- **Automatic PDF parsing**  
- **Supabase-backed** secure storage  
- **Customizable** keyword categories  
- **Interactive** charts & tables  

### 🚀 Quick Links
[GitHub Repository](https://github.com/ngweimeng)  

---
*Developed by WeiMeng*  
"""
)
