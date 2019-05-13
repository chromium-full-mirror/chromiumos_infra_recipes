from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'easy',
    'naming',
]

PROPERTIES = {
    'skylab_server':
        Property(kind=str, default='https://chromeos-swarming.appspot.com'),
    'skylab_version':
        Property(kind=str, default='prod'),
}
