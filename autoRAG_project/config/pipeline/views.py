from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def questionnaire(request):
    if request.method == 'POST':
        # Read data from form POST
        
        language = request.POST.get('language')
        use_case = request.POST.get('use_case')
        embedding_reranker = embedding_reranker(language, use_case)
        
        top_k = top_k(request.POST.get('reference'))
        
        reference = reference(request.POST.get('reference'))
        temperature = temperature(request.POST.get('creative'))
        top_p = top_p(request.POST.get('strict'))
        upToDate =up_to_date_docs((request.POST.get('uptodate')))
        metadata = add_metadata((request.POST.get('metadata')))
        chunking_strategy =determine_chunking_strategy((request.POST.get('chunking_strategy')))
        
        # later --> workspace.insert(reference, temperature, top_p, embedding)

        return JsonResponse({"status": "success"})
    
    return JsonResponse({"error": "Only POST allowed"}, status=405)

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
