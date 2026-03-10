from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests
from documents.services.qdrant_service import QdrantService
from workspace.models import Workspace, WorkspaceConfig, User, WorkspaceMembership
from pipeline.services.pipeline_registry import get_pipeline

#Added by rayan to run here the questionnaire page
def questionnaire_page(request):
    """Backend logic here"""
    return render(request, "questionnaire.html")


@csrf_exempt
def questionnaire(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)  
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Extract values from JSON
    language = data.get("language")
    use_case = data.get("use_case")
    reference_value = data.get("reference")
    temperature_value = data.get("temperature")
    top_p_value = data.get("top_p")
    uptodate_value = data.get("uptodate")
    metadata_value = data.get("metadata")
    chunking_value = data.get("chunking_strategy")

    # Process logic
    embedding_config = embedding_reranker(language, use_case)
    k_value = top_k(reference_value)
    reference_flag = reference(reference_value)
    temp_value = temperature(temperature_value)
    top_p_final = top_p(top_p_value)
    uptodate_flag = up_to_date_docs(uptodate_value)
    metadata_flag = add_metadata(metadata_value)
    chunking_strategy = determine_chunking_strategy(chunking_value)
    
    # save to DB
    workspace = Workspace.objects.create()

    # 2️⃣ Create WorkspaceConfig linked via OneToOne
    WorkspaceConfig.objects.create(
        workspace=workspace,
        retrieval_type='none',  # placeholder, (what is retrieval type?)
        re_ranker=embedding_config["reranker_model"],
        embedding_model=embedding_config["embedding_model"],
        chunking_strategy=chunking_strategy,
        distance_metric="cosine", # placeholder, (is it always cosine?)
        temperature=temp_value,
        top_p=top_p_final,
        top_k=k_value
    )
    return JsonResponse({
        "status": "success",
        "config": {
            "embedding": embedding_config,
            "top_k": k_value,
            "reference": reference_flag,
            "temperature": temp_value,
            "top_p": top_p_final,
            "uptodate": uptodate_flag,
            "metadata": metadata_flag,
            "chunking_strategy": chunking_strategy
        },
        "received_payload": data, #Added by rayan to see the payload in the response
    })


"""
EXAMPLE of json(API) or (form) sent from frontend to backend (including the 9 answers) hi abdul:
{
    "reference": True,
    'temprature': 0.7,
    'top_p': 0.9,
    'upToDate': True,
    'chunking_strategy':'slide deck'
}

"""
def embedding_reranker(language, use_case):
   
    if language == 'english':
        if use_case == 'fast':
            return {
                "embedding_model": "all-MiniLM-L6-v2",
                "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2"
            }

        elif use_case == 'balanced':
            return {
                "embedding_model": "all-mpnet-base-v2",
                "reranker_model": "cross-encoder/ms-marco-MiniLM-L6-v2"
            }

        elif use_case == 'quality':
            return {
                "embedding_model": "intfloat/e5-large-v2",
                "reranker_model": "intfloat/e5-mistral-7b-instruct"
            }
    else:
        return {
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": "BAAI/bge-reranker-v2-m3"
        }


def top_k(top_k_value):  
    if top_k_value == 'main':
        k = 5
    else:
        k = 10
    return k

def temperature(temperature_value):
    temp = 0
    if temperature_value == 'precise':
        temp = 0.2
    elif temperature_value == 'balanced':
        temp = 0.5
    else: # creative
        temp = 0.8
    return temp      

def top_p(top_p_value):  
    top = 0
    if top_p_value == 'strict':
        top = 0.2
    elif top_p_value == 'balanced':
        top = 0.5
    else: # explaratory
        top = 0.9
    return top
        

def reference(reference_value):
    if reference_value == 'yes':
        return True
    else:
        return False
    
def up_to_date_docs(response):
    """
    Determines if the user wants the document up to date on not.
    """
    if response.lower().strip()== 'yes':
        uptodate = True
    else:
        uptodate = False

    return uptodate

def add_metadata(response):
    """
    Determines if the user wants the answer with metadata or not .
    """
    if response.lower().strip()== 'yes':
        metadata = True
    else:
        metadata = False

    return metadata

def determine_chunking_strategy(response):
    """
    Determines the appropriate chunking strategy based on content type response. hi 

    """
    response_lower = response.lower().strip()

    if 'slide deck' in response_lower:
        chunking_strategy = 'page-based'
 
    elif 'meeting notes' in response_lower:
        chunking_strategy = 'large-overlapping'

    elif 'article' in response_lower:
        chunking_strategy = 'paragraph-based'

    elif 'manual' in response_lower:
        chunking_strategy = 'hierarchical'

    elif 'research paper' in response_lower:
        chunking_strategy = 'semantic'

    elif 'policy' in response_lower:
        chunking_strategy = 'document-structure'

    else:
        chunking_strategy = 'fixed-length'

    return chunking_strategy


def initiate_pipeline(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    config = workspace.config

    get_pipeline(workspace_id, config)

    return JsonResponse({"status": "Pipeline initialized"})


def query_handling(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    config = workspace.config

    pipeline = get_pipeline(workspace_id, config)

    embedding_model = pipeline["embedding_model"]
    reranker = pipeline["reranker"]
    temperature = pipeline["temperature"]
    top_p = pipeline["top_p"]
    top_k = pipeline["top_k"]

    data = json.loads(request.body)
    query = data.get("query")

    embedded_query = embedding_model.encode(query)

    qdrant = QdrantService(host="qdrant", port=6333)

    chunks = qdrant.search(
        collection_name=pipeline["embedding_model"] + "document",
        workspace_id=workspace_id,
        query_vector=embedded_query,
        top_k=top_k,
    )

    pairs = [(query, chunk["text"]) for chunk in chunks]
    scores = reranker.predict(pairs)
    ranked_chunks = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    top_chunks_for_llm = [chunk["text"] for chunk, score in ranked_chunks][:top_k]

    context = "\n\n".join(top_chunks_for_llm)
    prompt = f"Answer the following question based on the context:\n\nContext:\n{context}\n\nQuestion: {query}"

    ollama_url = "http://ollama:11434/api/generate"
    payload = {
        "model": "llama3",
        "prompt": prompt,
        "temperature": temperature,
        "top_p": top_p,
        "options": {"top_k": top_k},
        "stream": False,
    }
    response = requests.post(ollama_url, json=payload)

    if response.status_code == 200:
        llm_response = response.json().get("response", "No response from LLaMA")
    else:
        llm_response = f"Error generating response: {response.status_code}"
    return JsonResponse({"response": llm_response})