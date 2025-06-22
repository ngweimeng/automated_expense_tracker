import streamlit as st

st.set_page_config(
    page_title="WeiMeng's Budget Tracker",
    page_icon="💰",
    layout="centered",
    initial_sidebar_state="expanded",
)
st.title("💰 WeiMeng's Budget Tracker")
# st.write("A Streamlit app to upload, categorize, and visualize your personal expenses.")

st.markdown(
    """
## *Track. Analyze. Budget.* ##

A Streamlit app to upload, categorize, and visualize your personal expenses.

---

### 🎯 Motivation
I wanted an easy way to scan my credit card transactions without manually entering each one, since I tend to be lazy and often forget.

### 🔧 Get Started
1. **Settings**  
   Upload PDF statements & manage your transaction categories  
2. **Dashboard**  
   Explore summaries, trends over time, and high-spend alerts

---
*Developed by WeiMeng.*  
This app is open source and free to use. Contributions are welcome!

*Get in Touch:* [<img src='https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png' width='20'/> WeiMeng's GitHub](https://github.com/ngweimeng)
""",
    unsafe_allow_html=True
)
