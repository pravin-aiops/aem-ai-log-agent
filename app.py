import streamlit as st
import boto3
import time
import pandas as pd
from datetime import datetime, timedelta
import google.generativeai as genai

# 1. Core Page Customizations
st.set_page_config(page_title="AEM AI Log Agent", layout="wide")

st.markdown("""
    <style>
    .stChatInput { position: fixed; bottom: 30px; }
    .reportview-container { background: #0e1117; }
    code { color: #f43f5e !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🤖 AEM Live Log Analyzer AI Agent")
st.caption("Partition-Optimized Historical Search & Architecture Diagnoser")

# 2. Setup Sidebar Configuration Panel
st.sidebar.header("⚙️ Log Parsing Engine Filters")

# Configurable multi-word query targets
search_keywords_input = st.sidebar.text_input(
    "Log Search Words (Comma separated for multiple)", 
    value="ERROR, NullPointerException"
)

log_level = st.sidebar.selectbox("Filter Level", ["ALL", "ERROR", "WARN", "INFO", "DEBUG"])

# Multi-Year / Multi-Day Date Window Selectors
st.sidebar.subheader("📅 Target Timeline Selection")
preset_date = st.sidebar.selectbox(
    "Quick Timeline Presets", 
    ["Custom", "Last 90 Days", "Last 1 Year", "Last 2 Years"]
)

# Date calculations based on user choice
today = datetime.now()
if preset_date == "Last 90 Days":
    start_default = today - timedelta(days=90)
    end_default = today
elif preset_date == "Last 1 Year":
    start_default = today - timedelta(days=365)
    end_default = today
elif preset_date == "Last 2 Years":
    start_default = today - timedelta(days=730)
    end_default = today
else:
    start_default = today
    end_default = today

start_date = st.sidebar.date_input("Start Date", start_default)
end_date = st.sidebar.date_input("End Date", end_default)

# AWS Environment Variable Details (Fetched through Streamlit Production secrets)
ATHENA_DATABASE = "default"
ATHENA_TABLE = "aem_logs"
ATHENA_OUTPUT_S3 = "s3://aem-athena-results-demo-2026/" # Ensure trailing slash

# 3. Helper Function to Query Athena Engine
def run_athena_query(query_string):
    try:
        client = boto3.client(
            'athena',
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
            region_name=st.secrets["AWS_DEFAULT_REGION"]
        )
        
        response = client.start_query_execution(
            QueryString=query_string,
            QueryExecutionContext={'Database': ATHENA_DATABASE},
            ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_S3}
        )
        exec_id = response['QueryExecutionId']
        
        while True:
            status = client.get_query_execution(QueryExecutionId=exec_id)['QueryExecution']['Status']['State']
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break
            time.sleep(0.5)
            
        if status == 'SUCCEEDED':
            s3_client = boto3.client(
                's3',
                aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
                region_name=st.secrets["AWS_DEFAULT_REGION"]
            )
            result_file_key = f"{exec_id}.csv"
            bucket_name = ATHENA_OUTPUT_S3.replace("s3://", "").split("/")[0]
            
            obj = s3_client.get_object(Bucket=bucket_name, Key=result_file_key)
            return pd.read_csv(obj['Body'])
        else:
            st.error(f"Athena query execution state failed with status: {status}")
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"AWS Execution Error: {str(e)}")
        return pd.DataFrame()

# 4. Trigger Query Assembly
if st.sidebar.button("🔍 Sync & Index target Logs", use_container_width=True):
    # Formulate structural partition bounds matching S3 path strings (YYYY, MM, DD)
    start_year, start_month, start_day = start_date.strftime("%Y"), start_date.strftime("%m"), start_date.strftime("%d")
    end_year, end_month, end_day = end_date.strftime("%Y"), end_date.strftime("%m"), end_date.strftime("%d")
    
    # Construct precise partition-based fast-scan SQL query
    sql_query = f"SELECT log_date, log_time, log_level, message FROM {ATHENA_TABLE} WHERE "
    conditions = []
    
    # Apply folder structure optimization boundary
    partition_condition = f"""
    (year CONCAT month CONCAT day BETWEEN '{start_year}{start_month}{start_day}' AND '{end_year}{end_month}{end_day}')
    """
    conditions.append(partition_condition)

    if log_level != "ALL":
        conditions.append(f"log_level = '{log_level}'")
        
    # Multi-word layout parser
    if search_keywords_input:
        words = [w.strip() for w in search_keywords_input.split(",") if w.strip()]
        for word in words:
            conditions.append(f"message LIKE '%{word}%'")
        
    sql_query += " AND ".join(conditions) + " LIMIT 100;"
    
    with st.spinner("Executing optimized Partition Scan across S3 history..."):
        df_results = run_athena_query(sql_query)
        st.session_state['fetched_logs'] = df_results
        st.sidebar.success(f"Successfully processed {len(df_results)} rows!")

# Show structural data table preview if populated
if 'fetched_logs' in st.session_state and not st.session_state['fetched_logs'].empty:
    with st.expander("📄 View Live Raw Filtered Logs DataFrame", expanded=True):
        st.dataframe(st.session_state['fetched_logs'], use_container_width=True)

# 5. Core Chat Logic Setup
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "assistant", "content": "Welcome! I am your AEM Expert Agent powered by Gemini. Pull logs via the sidebar, then ask me to perform an RCA, summary, or debugging script outline."}
    ]

for chat in st.session_state.chat_history:
    with st.chat_message(chat["role"]):
        st.markdown(chat["content"])

if user_input := st.chat_input("Ask about errors, request RCA, or look up keyword trends..."):
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    context_string = "No logs pulled yet. Prompt the user to use the sidebar filters if context is required."
    if 'fetched_logs' in st.session_state and not st.session_state['fetched_logs'].empty:
        context_string = st.session_state['fetched_logs'].to_string(index=False)

    system_prompt = f"""
    You are an AI DevOps Architect specializing in Adobe Experience Manager (AEM 6.5 and AEMaaCS).
    Your goal is to evaluate raw target logs to provide concrete Root Cause Analysis (RCA), contextual summaries, and steps for technical resolution.
    
    Reference Log Context extracted from Amazon S3:
    \"\"\"
    {context_string}
    \"\"\"
    
    When answering runtime exceptions, format clearly using markdown headers:
    ### 📝 Summary
    ### 🔍 Root Cause Analysis (RCA)
    ### 🛠️ Step-by-Step Fix Action Plan
    """

    with st.chat_message("assistant"):
        with st.spinner("Analyzing exceptions and trace logs via Gemini..."):
            try:
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel(
                    model_name='gemini-2.5-flash',
                    system_instruction=system_prompt
                )
                
                native_contents = []
                for msg in st.session_state.chat_history:
                    role_map = "user" if msg["role"] == "user" else "model"
                    native_contents.append({"role": role_map, "parts": [msg["content"]]})
                
                response = model.generate_content(native_contents)
                output_text = response.text
                
                st.markdown(output_text)
                st.session_state.chat_history.append({"role": "assistant", "content": output_text})
            except Exception as ex:
                st.error(f"Gemini Inference Error: {str(ex)}")
