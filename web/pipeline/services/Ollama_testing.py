import requests

URL = "http://localhost:11434/api/generate"

def query_llama(prompt, temperature=0.7, top_p=0.9, top_k=40):
    payload = {
        "model": "llama3",
        "prompt": prompt,
        "temperature": temperature,
        "top_p": top_p,
        "options": {"top_k": top_k},
        "stream": False,
    }

    response = requests.post(URL, json=payload)

    if response.status_code == 200:
        return response.json()["response"]
    else:
        return f"Error: {response.status_code}, {response.text}"


# ---- Simulated RAG context ----
context = """
LLaMA is a family of large language models developed by Meta.
RAG (Retrieval-Augmented Generation) combines retrieval with generation.
Docker allows applications to run in containers.
PostgreSQL is a relational database system.
Neural networks are used in deep learning.
"""

# ---- 5 test queries ---- 
queries = [
    "What is LLaMA?",
    "Explain RAG in simple terms.",
    "Why use Docker?",
    "What is PostgreSQL?",
    "What are neural networks used for?"
]

# ---- Run tests ----
for i, q in enumerate(queries, 1):
    prompt = f"Context:\n{context}\n\nQuestion: {q}\nAnswer:"
    print(f"\n--- Query {i} ---")
    print("Q:", q)
    print("A:", query_llama(prompt))