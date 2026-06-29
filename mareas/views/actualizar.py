import os

from django.http import JsonResponse

from mareas.services.admin_ops import refresh_real_data

MAREAS_UPDATE_TOKEN = os.environ.get("MAREA_JOB_TOKEN", "")


def mareas_actualizar_view(request):
    token = request.GET.get("token", "")
    if not MAREAS_UPDATE_TOKEN or token != MAREAS_UPDATE_TOKEN:
        return JsonResponse({"error": "no autorizado"}, status=403)

    try:
        result = refresh_real_data()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    return JsonResponse(result, safe=False)
