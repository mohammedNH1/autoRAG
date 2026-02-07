from django.shortcuts import render
import json
from django.http import JsonResponse
# Create your views here.
import json
from django.http import JsonResponse
import json
from django.http import JsonResponse

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def questionnaire(request):
    if request.method == 'POST':
        # Read data from form POST
        reference = request.POST.get('reference')
        temperature = float(request.POST.get('temperature'))
        top_p = float(request.POST.get('top_p'))

        # later --> workspace.insert(reference, temperature, top_p)

        return JsonResponse({"status": "success"})
    
    return JsonResponse({"error": "Only POST allowed"}, status=405)

"""
example of json(API) sent from frontend to backend (including the 9 answers):
{
    "reference": True,
    'temprature': 0.7,
    'top_p': 0.9
}
"""
