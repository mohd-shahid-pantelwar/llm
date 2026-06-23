"""
title: Wazuh Agent Inventory Tool
description: Connects to the Wazuh manager API and retrieves a comprehensive list of all registered agents and their actual connected IP addresses. Use this tool when the user asks to list all agents, count agents, or check agent status.
author: Admin
requirements: requests, urllib3
"""
from pydantic import BaseModel, Field
import requests
import urllib3
import json
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Tools:
    class Valves(BaseModel):
        LOG_SOURCES: list = Field(default_factory=list)
        WAZUH_API_USER: str = Field(default=os.environ.get("WAZUH_API_USER", "wazuh"))
        WAZUH_API_PASS: str = Field(default=os.environ.get("WAZUH_API_PASS", "RNDhJ.3RqiUSERHAWzIpE?*GRV1cuLCL"))

    def __init__(self):
        self.valves = self.Valves()

    def list_agents(self) -> str:
        print("\n[rag-api] Connecting to Wazuh API to fetch agent inventory...")
        sources = self.valves.LOG_SOURCES
        
        wazuh_host = "10.0.10.101" # Default fallback
        if sources:
            wazuh_source = next((s for s in sources if s.get("name") == "Wazuh"), None)
            if wazuh_source and wazuh_source.get("host"):
                wazuh_host = wazuh_source.get("host")

        url_base = f"https://{wazuh_host}:55000"
        
        try:
            # 1. Get Token
            auth_url = f"{url_base}/security/user/authenticate?raw=true"
            auth_res = requests.post(
                auth_url, 
                auth=(self.valves.WAZUH_API_USER, self.valves.WAZUH_API_PASS), 
                verify=False,
                timeout=10
            )
            auth_res.raise_for_status()
            token = auth_res.text.strip()
            
            # 2. Get Agents
            agents_url = f"{url_base}/agents"
            headers = {"Authorization": f"Bearer {token}"}
            params = {"select": "id,name,ip,status,version,node_name", "limit": 1000}
            
            agents_res = requests.get(agents_url, headers=headers, params=params, verify=False, timeout=15)
            agents_res.raise_for_status()
            
            data = agents_res.json()
            affected_items = data.get("data", {}).get("affected_items", [])
            
            if not affected_items:
                return "Successfully connected to Wazuh API, but no agents were found."
            
            output_lines = []
            output_lines.append(f"Successfully retrieved {len(affected_items)} agents from Wazuh API:")
            output_lines.append("```")
            for agent in affected_items:
                output_lines.append(
                    f"ID: {agent.get('id', 'N/A')} | Name: {agent.get('name', 'N/A')} | "
                    f"IP: {agent.get('ip', 'N/A')} | Status: {agent.get('status', 'N/A')} | "
                    f"Version: {agent.get('version', 'N/A')}"
                )
            output_lines.append("```")
            
            return "\n".join(output_lines)

        except Exception as e:
            return f"Critical Error fetching agent inventory from API: {str(e)}"
