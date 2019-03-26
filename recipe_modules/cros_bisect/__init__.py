DEPS = [
    'recipe_engine/step',
]

from recipe_engine.config import Dict
from recipe_engine.recipe_api import Property

PROPERTIES = {
  # BuildRerunCompileFailureInput when invoked by FindIt for bisection build.
  'findit_bisect': Property(kind=Dict(), default={}),
}
