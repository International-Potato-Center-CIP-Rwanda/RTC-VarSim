"""Route the Rwanda pilot, Africa demo and result-inspection APIs; computation lives in the view and screening modules."""
from django.urls import path
from . import views
from django.views.static import serve
from django.conf import settings
from . import africa_demo

urlpatterns = [path('', views.home), path('analyse/', views.analyse)]
urlpatterns += [path('api/site/', views.sample_site)]
urlpatterns += [path('api/results/<uuid:run_id>/', views.result_view)]
urlpatterns += [path('api/compute/', views.compute_api), path('runs/<uuid:run_id>/<str:filename>', views.run_file)]
urlpatterns += [path('api/setup/', views.export_setup)]
urlpatterns += [path('api/setup/validate/', views.export_setup)]
urlpatterns += [path('demo/', africa_demo.home), path('api/demo/site/', africa_demo.site)]
urlpatterns += [path('api/demo/compute/', africa_demo.compute), path('demo/runs/<uuid:run_id>/<str:filename>', africa_demo.result_file)]
urlpatterns += [path('api/demo/runs/<uuid:run_id>/score/', africa_demo.sample_result)]
urlpatterns += [path('api/demo/runs/<uuid:run_id>/temperature-range/', africa_demo.sample_temperature_range)]
urlpatterns += [path('api/demo/variety-temperature/', africa_demo.screen_variety_temperature)]
urlpatterns += [path('assets/<path:path>', serve, {'document_root': settings.BASE_DIR / 'assets'})]

urlpatterns += [path('api/demo/variety-criterion/', africa_demo.screen_variety_criterion)]
urlpatterns += [path('api/demo/runs/<uuid:run_id>/criterion-range/', africa_demo.sample_variety_criterion)]

urlpatterns += [path('api/demo/variety-summary/', africa_demo.screen_variety_summary)]
urlpatterns += [path('api/demo/runs/<uuid:run_id>/summary/', africa_demo.sample_variety_summary)]
