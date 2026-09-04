import os
import json
import litellm

# Disable litellm telemetry for privacy
litellm.telemetry = False

# We use litellm.completion which natively supports OpenAI-compatible endpoints
# like Ollama/vLLM (our Primary) and commercial endpoints like Groq/Gemini (Fallback).

def _call_pm_llm(messages: list[dict], require_json: bool = False) -> str:
    """
    Calls the Project Manager LLM using a robust Primary -> Fallback strategy.
    Primary: Self-hosted local model (e.g., Ollama via Ngrok)
    Fallback: Cloud API (e.g., Groq or Gemini)
    """
    primary_url = os.environ.get("PRIMARY_PM_URL")
    primary_model = os.environ.get("PRIMARY_PM_MODEL", "openai/custom-model")
    
    fallback_key = os.environ.get("FALLBACK_PM_KEY")
    # Defaulting to Groq's GPT-OSS-20B (free tier) for the fallback
    fallback_model = os.environ.get("FALLBACK_PM_MODEL", "groq/openai/gpt-oss-20b")

    kwargs = {"messages": messages}
    if require_json:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        if not primary_url:
            raise ValueError("No PRIMARY_PM_URL configured.")
            
        print(f"PM LLM: Attempting Primary ({primary_model} at {primary_url})")
        # For OpenAI compatible endpoints, litellm uses the 'openai/' prefix
        model_name = primary_model if primary_model.startswith("openai/") else f"openai/{primary_model}"
        
        response = litellm.completion(
            model=model_name,
            api_base=primary_url,
            api_key="sk-dummy", # required by standard but ignored by local servers
            **kwargs
        )
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"PM LLM: Primary failed ({e}). Attempting Fallback...")
        
        if not fallback_key:
            raise RuntimeError(f"PM LLM: Primary failed and no FALLBACK_PM_KEY configured. Primary error: {e}")
            
        # litellm infers the provider from the model string (e.g., 'groq/...', 'gemini/...')
        # We temporarily set the env vars it expects based on common providers
        os.environ["GROQ_API_KEY"] = fallback_key
        os.environ["GEMINI_API_KEY"] = fallback_key
        
        response = litellm.completion(
            model=fallback_model,
            **kwargs
        )
        return response.choices[0].message.content

def decompose_feature(project_id: str, feature_description: str, project_context: str) -> list[dict]:
    """
    Calls the PM LLM to break a feature description into a dependency-ordered list of tasks.
    Returns a list of dicts: [{title, category, brief, acceptance_criteria, complexity_score, depends_on}]
    """
    system_prompt = """You are an elite, senior AI Project Manager. Your job is to decompose the user's feature request into a concrete, dependency-ordered list of development tasks.

Rules:
1. Maximum 10 tasks.
2. Each task MUST have:
   - "title": Short string (≤80 chars)
   - "category": One of [boilerplate, db, backend, frontend, infra, testing]
   - "brief": A 2-3 sentence technical description of what needs to be built.
   - "acceptance_criteria": A bulleted list of 2-4 strict criteria that must be met for this task to be considered complete.
   - "complexity_score": An integer from 1 (very simple, e.g. scaffolding/HTML) to 5 (very complex, e.g. core architecture/security).
   - "depends_on": The exact "title" of another task in this plan that must be completed first, or null if it has no dependencies.
3. The dependencies MUST form a valid Directed Acyclic Graph (no cycles).
4. Order matters: list the tasks from least-dependent to most-dependent (e.g. database schema first, then backend, then frontend).

Output strictly valid JSON with a root key "tasks" containing the array of task objects.
"""

    user_prompt = f"""Project ID: {project_id}

Existing Project Context:
{project_context or 'No existing context.'}

Feature to Decompose:
{feature_description}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print("PM LLM: Planning feature decomposition...")
    raw_response = _call_pm_llm(messages, require_json=True)
    
    try:
        # LLMs sometimes wrap json in markdown block
        clean_json = raw_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:-3].strip()
        elif clean_json.startswith("```"):
            clean_json = clean_json[3:-3].strip()
            
        data = json.loads(clean_json)
        return data.get("tasks", [])
    except Exception as e:
        print(f"PM LLM: Failed to parse JSON response: {e}\nRaw Response: {raw_response}")
        return []

def resolve_escalation(task_id: int, task_brief: str, current_state: str, blocker_description: str, project_context: str) -> str:
    """
    Calls the PM LLM to unblock an agent that has called escalate_to_pm.
    """
    system_prompt = """You are an elite, senior AI Project Manager supervising a team of autonomous AI coding agents. 
One of your agents has encountered a blocker and escalated the task to you.

Your job is to read the context, analyze the blocker, and provide a concrete, actionable "Strategy Pivot" to unblock the agent. 
Do not write code for them. Tell them exactly *what* they should do next, where to look, or how to rethink the problem.

Keep your response direct, technical, and under 3 paragraphs."""

    user_prompt = f"""Task #{task_id} Brief:
{task_brief}

Project Context:
{project_context}

Agent's Current State:
{current_state}

Agent's Blocker Description:
{blocker_description}

Provide the strategy pivot to unblock the agent:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"PM LLM: Resolving escalation for task {task_id}...")
    return _call_pm_llm(messages)
