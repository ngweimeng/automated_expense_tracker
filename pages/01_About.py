import streamlit as st

st.set_page_config(
    page_title="WeiMeng's Budget Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("💰 WeiMeng's Budget Tracker")

st.markdown(
    """
## *About the Project*

---

### 🎯 Motivation
Keeping track of expenses and savings has always been a challenge for me. I tried off-the-shelf budgeting apps and even Excel, but manual data entry felt too cumbersome—and I inevitably fell off the wagon. So I decided to build my own tailored solution that automates as much as possible and gives me clear, timely insights into my spending habits.

### 🔧 How It Works
1. **Automated Extraction**  
   - Connects to your Gmail via the Gmail API  
   - Scrapes transaction details from Instarem and Wise email receipts  
   - Automatically imports those records into your dashboard  

2. **Recurring Transactions**  
   - Define any regular payments (e.g., subscriptions, rent)  
   - The app will auto-add them on the schedule you choose  

3. **Manual Entry**  
   - For one-off or non-email transactions (e.g., peer-to-peer transfers)  
   - Add them quickly via a simple form  

---

*Developed by WeiMeng.* This project is **open source**—contributions welcome!  
[![GitHub](https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png)](https://github.com/ngweimeng) Connect on GitHub  
""",
    unsafe_allow_html=True
)
