DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/legacy_annotation',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'depot_tools/bot_update',
    'depot_tools/gclient',
    'depot_tools/git',
    'depot_tools/gitiles',
    'depot_tools/tryserver',
    'cros_infra_config',
    'cros_source',
    'goma',
    'repo',
]

# TODO(phajdan.jr): provide coverage (http://crbug.com/693058).
DISABLE_STRICT_COVERAGE = True
