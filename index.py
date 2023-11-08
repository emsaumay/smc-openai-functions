from flask import Flask,request,render_template
from dotenv import load_dotenv
import os
import requests
import openai
import json
from tenacity import retry, wait_random_exponential, stop_after_attempt
from termcolor import colored
GPT_MODEL = "gpt-4-0613"


app = Flask(__name__)
load_dotenv()

openai.api_key=os.environ.get('API_KEY')

import sqlite3
conn = sqlite3.connect("../smc-app/smc.db", check_same_thread=False)
def get_table_names(conn):
    table_names = []
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    for table in tables.fetchall():
        table_names.append(table[0])
    return table_names


def get_column_names(conn, table_name):
    column_names = []
    columns = conn.execute(f"PRAGMA table_info('{table_name}');").fetchall()
    for col in columns:
        column_names.append(col[1])
    return column_names


def get_database_info(conn):
    table_dicts = []
    for table_name in get_table_names(conn):
        columns_names = get_column_names(conn, table_name)
        table_dicts.append({"table_name": table_name, "column_names": columns_names})
    return table_dicts

def ask_database(conn, query):
    try:
        print(query)
        results = conn.execute(query).fetchall()
    except Exception as e:
        results = f"query failed with error: {e}"
    return results

def execute_function_call(message):
    if message["function_call"]["name"] == "ask_database":
        query = json.loads(message["function_call"]["arguments"])["query"]
        results = ask_database(conn, query)
    else:
        results = f"Error: function {message['function_call']['name']} does not exist"
    return results

@retry(wait=wait_random_exponential(multiplier=1, max=40), stop=stop_after_attempt(3))
def chat_completion_request(messages, functions=None, function_call=None, model=GPT_MODEL):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + openai.api_key,
    }
    json_data = {"model": model, "messages": messages}
    if functions is not None:
        json_data.update({"functions": functions})
    if function_call is not None:
        json_data.update({"function_call": function_call})
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=json_data,
        )
        return response
    except Exception as e:
        print("Unable to generate ChatCompletion response")
        print(f"Exception: {e}")
        return e

database_schema_dict = get_database_info(conn)
database_schema_string = "\n".join(
    [
        f"Table: {table['table_name']}\nColumns: {', '.join(table['column_names'])}"
        for table in database_schema_dict
    ]
)

functions = [
    {
        "name": "ask_database",
        "description": "Use this function to answer user questions about shop. Input should be a fully formed READ_ONLY SQL query. convert sql parameters into all capital",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": f"""
                            SQL query extracting info to answer the user's question and include relevant columns from database.
                            SQL should be written using this database schema:
                            {database_schema_string}
                            The query should be returned in plain text, not in JSON.
                            """,
                }
            },
            "required": ["query"],
        },
    }
]


@app.route('/', methods=['GET','POST'])
def form_handler():
    return render_template('index.html')
    
@app.route('/form', methods=['POST'])
def input_form():
      input_value = request.form.get('input_value')
      print(input_value)
      messages = []
      messages.append({"role": "system", "content": "Answer user questions by generating SQL queries against the sqlite Database."})
      messages.append({"role": "user", "content": f"{input_value}"})
      chat_response = chat_completion_request(messages, functions)
      assistant_message = chat_response.json()["choices"][0]["message"]
      messages.append(assistant_message)
      if assistant_message.get("function_call"):
          results = execute_function_call(assistant_message)
          messages.append({"role": "function", "name": assistant_message["function_call"]["name"], "content": results})
      output = [m['content'] for m in messages if m['role'] == 'function']
      return render_template('index.html', output=output, question=input_value)         
  
if __name__ == '__main__':
    app.run(debug=True)
