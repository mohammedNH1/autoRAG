from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import requests
from documents.services.qdrant_service import QdrantService
from documents.services.embedding_service import EmbeddingService
from workspace.models import Workspace, WorkspaceConfig, WorkspaceMembership
from pipeline.services.pipeline_registry import get_pipeline
from workspace.models import Message, Session
import uuid
from django.core.exceptions import ValidationError

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
    is_citation_value = data.get("is_citation", False)

    # Process logic
    embedding_config = embedding_reranker(language, use_case)
    k_value = top_k(reference_value)
    reference_flag = reference(reference_value)
    temp_value = temperature(temperature_value)
    top_p_final = top_p(top_p_value)
    uptodate_flag = up_to_date_docs(uptodate_value)
    metadata_flag = add_metadata(metadata_value)
    chunking_strategy = determine_chunking_strategy(chunking_value)
    
    # Use existing workspace if workspace_id provided, otherwise create new
    workspace_id = data.get("workspace_id")
    if workspace_id:
        try:
            workspace = Workspace.objects.get(workspace_id=workspace_id)
        except Workspace.DoesNotExist:
            workspace = Workspace.objects.create()
    else:
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
        top_k=k_value,
        is_citation=is_citation_value,
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

def chat_page(request, workspace_id):
    workspace = Workspace.objects.get(workspace_id=workspace_id)
    get_pipeline(workspace_id, workspace.config)
    return render(request, "chat.html", {"workspace_id": workspace_id})

@csrf_exempt
@login_required
def query_handling(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    embedding_model_mapping = {
        "all-MiniLM-L6-v2": "minilm",
        "all-mpnet-base-v2": "mpnet",
        "intfloat/e5-large-v2": "e5_large",
        "BAAI/bge-m3": "bge_m3",
    }

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    workspace_id = int(data.get("workspace_id"))
    session_id = data.get("session_id")
    query = (data.get("message") or "").strip()

    if not workspace_id or not query:
        return JsonResponse(
            {'error': 'workspace_id and message are required'}, status=400
        )

    try:
        workspace = Workspace.objects.get(workspace_id=workspace_id)
    except Workspace.DoesNotExist:
        return JsonResponse({'error': 'Workspace not found'}, status=404)

    is_member = (
        workspace.workspace_owner_id == request.user.id
        or WorkspaceMembership.objects.filter(
            workspace=workspace, user=request.user
        ).exists()
    )
    if not is_member:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if not hasattr(workspace, 'config'):
        return JsonResponse(
            {'error': 'Workspace is not configured yet'}, status=400
        )

    config = workspace.config
    embedding_model_name = config.embedding_model
    is_citation = config.is_citation                  # ← read citation flag
    pipeline = get_pipeline(workspace_id, config)

    embedding_model = pipeline["embedding_model"]
    reranker = pipeline["reranker"]
    temperature = pipeline["temperature"]
    top_p = pipeline["top_p"]
    top_k = pipeline["top_k"]

    # -------------------------
    # Session — must belong to this user + workspace; otherwise start a new one.
    # -------------------------
    session = None
    if session_id:
        try:
            session = Session.objects.filter(
                session_id=session_id,
                workspace=workspace,
                user=request.user,
            ).first()
        except (ValueError, ValidationError):
            session = None

    if not session:
        session = Session.objects.create(
            workspace=workspace,
            user=request.user,
            title="New Session",
        )

    # Auto-title from the first user message, ChatGPT-style.
    is_first_message = not session.messages.exists()
    if is_first_message and session.title == "New Session":
        session.title = (query[:60] + "…") if len(query) > 60 else query
        session.save(update_fields=["title"])

    # -------------------------
    # Save User Message
    # -------------------------
    Message.objects.create(
        session=session,
        sender="user",
        text=query
    )

    embedded_query = EmbeddingService.embed_text(query, embedding_model_name)

    qdrant = QdrantService(host="qdrant", port=6333)

    chunks = qdrant.search(
        collection_name=f"documents__{embedding_model_mapping[embedding_model_name]}",
        workspace_id=workspace_id,
        query_vector=embedded_query,
        top_k=top_k * 10,
    )
    print("this is the chunks before reranking:", len(chunks))
    pairs = [(query, chunk["payload"]["text"]) for chunk in chunks]
    scores = reranker.predict(pairs)

    ranked_chunks = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)

    print("\n\n========== RERANK DEBUG ==========\n")
    for i, (chunk, score) in enumerate(ranked_chunks[:5]):
        print(f"{i+1}. Score: {score:.4f}")
        print(chunk['payload']["text"][:100])
        print("-" * 50)
    print("\n========== END DEBUG ==========\n\n")

    top_ranked = ranked_chunks[:top_k]
    top_chunks_for_llm = [chunk['payload']["text"] for chunk, score in top_ranked]
    context = "\n\n".join(top_chunks_for_llm)

    # -------------------------
    # Citations (only if is_citation=True)
    # -------------------------
    sources = []
    if is_citation:
        seen = set()
        for chunk, score in top_ranked:
            payload     = chunk['payload']
            document_id = payload.get("document_id")
            page        = payload.get("page")
            source      = payload.get("source", f"Document {document_id}")
            key = (document_id, page)
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document_id": document_id,
                    "page":        page,
                    "source":      source,
                })

        source_lines = "\n".join(
            f"- {s['source']}, page {s['page']}" for s in sources
        )
        prompt = (
            f"Answer the following question based on the context below.\n"
            f"At the end of your answer, cite the sources used from this list:\n{source_lines}\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}"
        )
    else:
        prompt = f"Answer the following question based on the context:\n\nContext:\n{context}\n\nQuestion: {query}"

    ollama_url = "http://ollama:11434/api/generate"
    payload = {
        "model": "llama3:8b-instruct-q4_0",
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

    # -------------------------
    # Save Assistant Message
    # -------------------------
    Message.objects.create(
        session=session,
        sender="assistant",
        text=llm_response
    )

    return JsonResponse({
        "response": llm_response,
        "session_id": str(session.session_id),
        "session_title": session.title,
        "session_created": is_first_message,
    })