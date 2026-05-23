import streamlit as st
import boto3
import time
import pandas as pd
import openai
from datetime import datetime

# 1. Core Page Customizations
st.set_page_config(page_title="AEM AI Log Agent", layout="wide")

# Inject Custom CSS for dark-mode terminal visuals
st.markdown("""
    <style>
    .stChatInput { position: fixed; bottom: 30px; }
    .reportview-container { background: #0e1117; }
    code { color: #f43f5e !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🤖 AEM Live Log Analyzer AI Agent")
st.caption("Cost-Effective Serverless Search & Architecture Diagnoser")

# 2. Setup Sidebar Configuration Panel
st.sidebar.header("⚙️ Log Parsing Engine Filters")

# Configurable query targets
search_keyword = st.sidebar.text_input("Log Search Text / Match Key", value="ERROR")
log_level = st.sidebar.selectbox("Filter Level", ["ALL", "ERROR", "WARN", "INFO", "DEBUG"])

# Date Filters
start_date = st.sidebar.date_input("Start Date", datetime.now())
end_date = st.sidebar.date_input("End Date", datetime.now())

# AWS Environment Variable Details (Fetched locally or through Streamlit Production secrets)
ATHENA_DATABASE = "default"
ATHENA_TABLE = "aem_logs"
ATHENA_OUTPUT_S3 = "s3://forward-log/" # Ensure trailing slash

# 3. Helper Function to Query Athena Engine
def run_athena_query(query_string):
    try:
        # Use credentials from st.secrets
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
        
        # Keep polling until query completes
        while True:
            status = client.get_query_execution(QueryExecutionId=exec_id)['QueryExecution']['Status']['State']
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break
            time.sleep(0.5)
            
        if status == 'SUCCEEDED':
            # Retrieve the query data directly from the processed CSV in S3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
                region_name=st.secrets["AWS_DEFAULT_REGION"]
            )
            result_file_key = f"{exec_id}.csv"
            # Extract just the bucket name out of the S3 output path
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
    # Formulate Date Strings matching DD.MM.YYYY logic
    str_start = start_date.strftime("%d.%m.%Y")
    str_end = end_date.strftime("%d.%m.%Y")
    
    # Construct precise SQL query
    sql_query = f"SELECT log_date, log_time, log_level, message FROM {ATHENA_TABLE} WHERE "
    conditions = []
    
    if log_level != "ALL":
        conditions.append(f"log_level = '{log_level}'")
    if search_keyword:
        conditions.append(f"message LIKE '%{search_keyword}%'")
        
    conditions.append(f"log_date BETWEEN '{str_start}' AND '{str_end}'")
    sql_query += " AND ".join(conditions) + " LIMIT 100;"
    
    with st.spinner("Executing Athena Scan across S3 storage..."):
        df_results = run_athena_query(sql_query)
        st.session_state['fetched_logs'] = df_results
        st.sidebar.success(f"Successfully processed {len(df_results)} rows!")

# Show structural data table preview if populated
if 'fetched_logs' in st.session_state and not st.session_state['fetched_logs'].empty:
    with st.expander("📄 View Live Raw Filtered Logs DataFrame", expanded=False):
        st.dataframe(st.session_state['fetched_logs'], use_container_width=True)

# 5. Core Chat Logic Setup
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "assistant", "content": "Welcome! I am your AEM Expert Agent. Pull logs via the sidebar, then ask me to perform an RCA, summary, or debugging script outline."}
    ]

# Display older messages
for chat in st.session_state.chat_history:
    with st.chat_message(chat["role"]):
        st.markdown(chat["content"])

# User Chat Prompt Action
if user_input := st.chat_input("Ask about errors, request RCA, or look up keyword trends..."):
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Convert context dataframe into a compressed text block for the LLM
    context_string = "No logs pulled yet. Prompt the user to use the sidebar filters if context is required."
    if 'fetched_logs' in st.session_state and not st.session_state['fetched_logs'].empty:
        context_string = st.session_state['fetched_logs'].to_string(index=False)

    # AI Orchestration Prompt Engineering
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

    # Hit LLM Completion Engine
    with st.chat_message("assistant"):
    with st.spinner("Analyzing exceptions via Gemini..."):
        try:
            from openai import OpenAI
            
            # Gemini supports the OpenAI standard format natively!
            client_gemini = OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=st.secrets["GEMINI_API_KEY"]
            )
            
            api_response = client_gemini.chat.completions.create(
                model="gemini-1.5-flash", # Fast, smart, and completely free tier
                messages=[
                    {"role": "system", "content": system_prompt},
                    *st.session_state.chat_history
                ],
                temperature=0.2
            )
            output_text = api_response.choices[0].message.content
            st.markdown(output_text)
            st.session_state.chat_history.append({"role": "assistant", "content": output_text})
        except Exception as ex:
            st.error(f"Gemini Inference Error: {str(ex)}")
