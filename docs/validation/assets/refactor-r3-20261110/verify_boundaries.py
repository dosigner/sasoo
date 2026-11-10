import sys

from services import visualization_policy as policy

for name in ('models.database', 'api.settings', 'services.analysis_execution', 'services.odl_parser'):
    assert name not in sys.modules, f'Policy imports runtime module: {name}'
print('Policy imports without database, settings, parser, or execution modules.')

from services import analysis_execution as ae

names = (
    '_viz_score', '_viz_plan_shape_error', '_normalize_viz_plan', '_gate_viz_items',
    '_VIZ_CORE_PURPOSES', '_MERMAID_RENDERABLE_TYPES',
)
for name in names:
    assert getattr(ae, name) is getattr(policy, name), name
print('Four policy functions and two constants keep the same objects at both import paths.')

assert ae._visualization_cache_input.__module__ == 'services.analysis_execution'
assert ae._plan_visualizations.__module__ == 'services.analysis_execution'
assert ae._run_visualization_items.__module__ == 'services.analysis_execution'
print('Cache assembly, planning calls, and generation remain in analysis_execution.')
