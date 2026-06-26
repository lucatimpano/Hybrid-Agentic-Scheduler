from langchain_core.tools import tool
from langchain.agents import create_agent

agent = create_agent(model="google_genai:gemini-3.5-flash", tools=tools)
