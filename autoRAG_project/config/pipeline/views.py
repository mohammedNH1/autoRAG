from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def questionnaire(request):
    if request.method == 'POST':
        # Read data from form POST
        
        reference = reference(request.POST.get('reference'))
        temperature = temperature(request.POST.get('creative'))
        top_p = top_p(request.POST.get('strict'))
        
        
        # later --> workspace.insert(reference, temperature, top_p, embedding)

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
def temperature(temperature_value):
    temp = 0
    if temperature_value == 'precise':
        temp = 0.2
    elif temperature_value == 'balanced':
        0.5
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
    
