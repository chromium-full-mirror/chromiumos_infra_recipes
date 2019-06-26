DEPS = [
    'recipe_engine/step', 'recipe_engine/service_account', 'recipe_engine/time',
    'recipe_engine/url', 'support'
]

from PB.recipe_modules.chromeos.cros_som.cros_som import CrosSomProperties

PROPERTIES = CrosSomProperties