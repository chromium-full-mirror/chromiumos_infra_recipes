from PB.recipe_modules.chromeos.result_flow.result_flow import \
  ResultFlowModuleProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'easy',
]

PROPERTIES = ResultFlowModuleProperties
